# -*- coding: utf-8 -*-
"""从哔哩哔哩视频中取出字幕文本。"""

import argparse
import json
import re
import sys
import urllib.parse

import requests

CHINESE_LANGUAGES = ("ai-zh", "zh-CN", "zh-Hans", "zh")
PLAYER_SCRIPT_PATTERN = re.compile(r"//[^\"'\s>]+/bfs/static/player/main/core\.[a-f0-9]+\.js")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BV_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}")


class SubtitleError(Exception):
    """获取字幕失败。"""


def read_varint(buf, index):
    """读取 protobuf 变长整数。"""
    shift = 0
    value = 0
    while True:
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return value, index
        shift += 7


def read_fields(data):
    """按 protobuf wire 格式拆出字段。"""
    index = 0
    fields = []
    while index < len(data):
        key, index = read_varint(data, index)
        field_no = key >> 3
        wire_type = key & 7
        if wire_type == 0:
            value, index = read_varint(data, index)
            fields.append((field_no, value))
        elif wire_type == 2:
            length, index = read_varint(data, index)
            fields.append((field_no, data[index:index + length]))
            index += length
        elif wire_type == 1:
            index += 8
        elif wire_type == 5:
            index += 4
        else:
            break
    return fields


def parse_tracks(payload):
    """解析字幕列表接口返回的 protobuf，得到各语言轨道。"""
    if len(payload) <= 2 or payload[:1] == b"{":
        return []
    top = read_fields(payload)
    data = next(
        (value for field_no, value in top if field_no == 1 and isinstance(value, (bytes, bytearray))),
        b"",
    )
    tracks = []
    for field_no, value in read_fields(data):
        if field_no != 3 or not isinstance(value, (bytes, bytearray)):
            continue
        item = {}
        for inner_no, inner_value in read_fields(value):
            if inner_no in (2, 3, 4, 5, 8) and isinstance(inner_value, (bytes, bytearray)):
                item[inner_no] = inner_value.decode("utf-8")
        if item.get(5):
            tracks.append({
                "id": item.get(2, ""),
                "lan": item.get(3, ""),
                "lan_doc": item.get(4) or item.get(8) or item.get(3, ""),
                "url": item[5],
            })
    return tracks


def xor_text(text, key):
    """按播放器的方式对字符串逐字异或。"""
    return "".join(chr(ord(char) ^ ord(key[i % len(key)])) for i, char in enumerate(text))


def parse_js_string(text, index):
    """读取播放器脚本中的一个引号字符串。"""
    quote = text[index]
    if quote not in "'\"":
        raise SubtitleError("播放器脚本里的密钥格式无法识别")
    index += 1
    chars = []
    while index < len(text):
        char = text[index]
        if char == "\\":
            escaped = text[index + 1]
            mapping = {
                "n": "\n",
                "r": "\r",
                "t": "\t",
                "\\": "\\",
                "'": "'",
                '"': '"',
            }
            if escaped in mapping:
                chars.append(mapping[escaped])
                index += 2
                continue
            if escaped == "u" and index + 6 <= len(text):
                chars.append(chr(int(text[index + 2:index + 6], 16)))
                index += 6
                continue
            chars.append(escaped)
            index += 2
            continue
        if char == quote:
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    raise SubtitleError("播放器脚本里的密钥格式无法识别")


def skip_space(text, index):
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def parse_decode_material(script):
    """从播放器脚本中读取还原字幕地址所需的前缀、密钥和后缀。"""
    marker = script.find("aisubtitle.hdslb.com")
    suffix_at = script.rfind(",L=", 0, marker)
    array_at = script.rfind("[[", 0, suffix_at)
    if marker < 0 or suffix_at < 0 or array_at < 0:
        raise SubtitleError("播放器脚本里没有字幕密钥")
    suffix, _ = parse_js_string(script, skip_space(script, suffix_at + 3))
    index = array_at + 1
    pairs = []
    while index < suffix_at:
        index = skip_space(script, index)
        if script[index] != "[":
            break
        index = skip_space(script, index + 1)
        prefix, index = parse_js_string(script, index)
        index = skip_space(script, index)
        if script[index] != ",":
            raise SubtitleError("播放器脚本里的密钥格式无法识别")
        index = skip_space(script, index + 1)
        key, index = parse_js_string(script, index)
        index = skip_space(script, index)
        if script[index] != "]":
            raise SubtitleError("播放器脚本里的密钥格式无法识别")
        pairs.append((prefix, key))
        index = skip_space(script, index + 1)
        if index < len(script) and script[index] == ",":
            index += 1
    if not pairs or not suffix:
        raise SubtitleError("播放器脚本里没有字幕密钥")
    return pairs, suffix


def load_decode_material(session, page_html):
    """按当前视频页引用的播放器脚本，读取这一次运行要使用的密钥。"""
    matched = PLAYER_SCRIPT_PATTERN.search(page_html)
    if not matched:
        raise SubtitleError("没有找到播放器脚本")
    response = session.get("https:" + matched.group(0), timeout=30)
    response.raise_for_status()
    return parse_decode_material(response.content.decode("utf-8", "replace"))


def decode_subtitle_url(url, pairs, suffix):
    """把接口返回的混淆地址还原成可下载的字幕文件地址。"""
    full = "https:" + url if url.startswith("//") else url
    parsed = urllib.parse.urlparse(full)
    path = parsed.path.lstrip("/")
    for prefix, key in pairs:
        plain = xor_text(urllib.parse.unquote(path), key + suffix)
        if plain.startswith(prefix):
            real_path = plain.split(prefix, 1)[1]
            return "https://aisubtitle.hdslb.com" + real_path + "?" + parsed.query
    raise SubtitleError("字幕地址还原失败")


def choose_track(tracks):
    """优先使用中文轨道。"""
    for language in CHINESE_LANGUAGES:
        for track in tracks:
            if track["lan"] == language:
                return track
    for track in tracks:
        if track["lan"].startswith("zh") or track["lan"].startswith("ai-zh"):
            return track
    return tracks[0]


def parse_input(value):
    """从 BV 号或视频链接中取出稿件号和分 P。"""
    matched = BV_PATTERN.search(value)
    if not matched:
        raise SubtitleError("请输入 BV 号或哔哩哔哩视频链接")
    page = 1
    if value.startswith("http"):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
        if query.get("p"):
            page = int(query["p"][0])
    return matched.group(0), page


def new_session(bvid):
    """创建带播放页来源的会话，先访问视频页拿到访问所需的 Cookie。"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"https://www.bilibili.com/video/{bvid}/",
        "Origin": "https://www.bilibili.com",
    })
    response = session.get(f"https://www.bilibili.com/video/{bvid}/", timeout=20)
    response.raise_for_status()
    pairs, suffix = load_decode_material(session, response.text)
    return session, pairs, suffix


def get_video(session, bvid):
    """获取稿件标题、aid 和分 P 信息。"""
    response = session.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0 or not data.get("data"):
        raise SubtitleError(f"获取视频信息失败：{data.get('message') or data.get('code')}")
    video = data["data"]
    pages = video.get("pages") or [{
        "cid": video["cid"],
        "page": 1,
        "part": video.get("title") or "",
    }]
    return video, pages


def fetch_tracks(session, bvid, aid, cid):
    """先请求播放器接口，再读取该分 P 的字幕轨道。空结果时重试同一请求。"""
    last_size = 0
    for _ in range(3):
        session.get(
            "https://api.bilibili.com/x/player/wbi/v2",
            params={"bvid": bvid, "aid": aid, "cid": cid},
            timeout=20,
        )
        response = session.get(
            "https://api.bilibili.com/x/v2/subtitle/web/view",
            params={
                "oid": cid,
                "pid": aid,
                "type": 1,
                "context_ext": json.dumps({"video_type": 1}, separators=(",", ":")),
                "cur_production_type": 0,
            },
            timeout=20,
        )
        response.raise_for_status()
        last_size = len(response.content)
        tracks = parse_tracks(response.content)
        if tracks:
            return tracks
    raise SubtitleError(f"没有拿到字幕列表（接口返回 {last_size} 字节）")


def format_timestamp(seconds, duration):
    """字幕开始时间，两侧带方括号。不超过 1 小时用 [MM:SS]；视频超过 1 小时后，满 1 小时的句子再用 [HH:MM:SS]。"""
    total = int(float(seconds or 0))
    if total < 0:
        total = 0
    minutes, secs = divmod(total, 60)
    if float(duration or 0) > 3600 and total >= 3600:
        hours, minutes = divmod(minutes, 60)
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def fetch_text(session, track, pairs, suffix, duration):
    """下载字幕文件，同时得到纯文本和带时间戳的文本。"""
    url = decode_subtitle_url(track["url"], pairs, suffix)
    response = session.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json()
    lines = []
    timed_lines = []
    for item in payload.get("body") or []:
        content = (item.get("content") or "").strip()
        if content:
            lines.append(content)
            start = format_timestamp(item.get("from"), duration)
            timed_lines.append(f"{start} {content}")
    if not lines:
        raise SubtitleError("字幕文件里没有文本")
    return "\n".join(lines), "\n".join(timed_lines)


def collect(target, page_no):
    """获取指定视频的字幕文本。"""
    bvid, url_page = parse_input(target)
    if page_no is None:
        page_no = url_page
    session, pairs, suffix = new_session(bvid)
    video, pages = get_video(session, bvid)
    selected = next((item for item in pages if item.get("page") == page_no), None)
    if selected is None:
        raise SubtitleError(f"没有第 {page_no} P，这个视频共 {len(pages)} P")
    tracks = fetch_tracks(session, bvid, video["aid"], selected["cid"])
    track = choose_track(tracks)
    duration = selected.get("duration") or video.get("duration") or 0
    text, timed_text = fetch_text(session, track, pairs, suffix, duration)
    title = video.get("title") or bvid
    if len(pages) > 1:
        title = f"{title} P{selected.get('page')} {selected.get('part') or ''}".strip()
    return {
        "bvid": bvid,
        "title": title,
        "language": track["lan_doc"],
        "text": text,
        "timed_text": timed_text,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="获取哔哩哔哩视频的字幕文本")
    parser.add_argument("video", help="BV 号或视频链接，例如 BV1TDGT6vEqC")
    parser.add_argument("-p", "--page", type=int, default=None, help="分 P 序号，默认取链接中的 p，否则为第 1 P")
    parser.add_argument("-o", "--output", default=None, help="纯文本保存路径，默认保存为 BV号.txt，同时另存一份带时间戳的文本")
    return parser


def timestamp_output_path(output_path):
    """由纯文本路径得到带时间戳文件的路径。"""
    if output_path.lower().endswith(".txt"):
        return output_path[:-4] + "_时间戳.txt"
    return output_path + "_时间戳.txt"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args()
    try:
        result = collect(args.video, args.page)
    except SubtitleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    output = f"{result['title']}\n\n{result['text']}\n"
    timed_output = f"{result['title']}\n\n{result['timed_text']}\n"
    print(output, end="", flush=True)
    print(f"\n{timed_output}", end="", flush=True)
    output_path = args.output or f"{result['bvid']}.txt"
    timed_path = timestamp_output_path(output_path)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(output)
    with open(timed_path, "w", encoding="utf-8") as file:
        file.write(timed_output)
    print(f"\n已保存到 {output_path}", file=sys.stderr)
    print(f"已保存到 {timed_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
