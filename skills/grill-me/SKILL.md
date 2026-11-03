---
name: grill-me
description: >-
  Interview the user one question at a time about a plan or decision until
  the decision tree is resolved, giving a recommended answer with each
  question. Use when the user says "grill me", "拷问我", "帮我想清楚",
  or asks to stress-test a plan before building.
disable-model-invocation: true
---

# Grill Me

通过逐题追问，把用户还没想清的方案问到可以执行。一次只处理一个决定。

## 何时停止

同时满足才结束：

- 目标、使用者和成功标准已经说清
- 每个开放决定都已选定，或明确推迟并写明理由
- 依赖关系已按顺序排好：后面的选择不会推翻前面的

结束后给出一份决定清单：已决定、推迟、下一步。在此之前不要写实现方案，不要改代码。

## 每一轮

1. 先看已有对话和代码库。能查到的事实直接采用，不要拿去问用户。
2. 只问当前阻塞最大的那一个决定。后面的问题依赖它时，先问它。
3. 问题用用户正在使用的语言。附上你的建议答案，并用一两句说明理由。
4. 用户回答后，用一句话复述你采用的结论，再进入下一题。
5. 答案含糊、自相矛盾，或跳过了依赖项时，停在这一题上改问，直到这一支决定闭合。

## 不要做的事

- 不要一次抛出问卷。
- 不要在决定未闭合时开始实现、列文件结构或给大段教程。
- 不要重复用户已经说清的点。
