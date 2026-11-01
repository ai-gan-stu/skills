# Skills

个人 / 团队可复用的 skill 仓库。每个 skill 是一个目录，核心文件是 `SKILL.md`。

## 布局

```
skills/                 ← 本仓库根目录
├── README.md
├── LICENSE
├── skills/             ← 所有 skill
│   └── <skill-name>/
│       ├── SKILL.md    ← 必需
│       ├── CHANGELOG.md
│       ├── scripts/	← 可执行脚本（可选）
│       ├── references/	← 较长说明（可选）
│       ├── assets/		← 图片等静态资源（可选）
│       └── evals/      ← 测试用例（可选）
├── template/           ← 新建 skill 时复制
│   └── SKILL.md
└── .gitignore
```

## 新增一个 skill

1. 复制 `template/` 到 `skills/<skill-name>/`
2. 编辑 `SKILL.md` 的 frontmatter（`name`、`description`）和正文步骤
3. 按需保留或删除 `scripts/`、`references/`、`assets/`、`evals/`，并更新 `CHANGELOG.md`
4. 提交并推送

`description` 写清**何时**使用该 skill，方便人和助手判断要不要加载它。

## 许可证

MIT，见 [LICENSE](./LICENSE)。
