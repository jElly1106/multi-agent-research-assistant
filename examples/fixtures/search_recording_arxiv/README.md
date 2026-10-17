# arXiv 官方 API 真实录制

2026-10-15 北京时间 12:08，默认仅检索 arXiv，两次官方 API 请求均通过直连成功，共 20 条记录，返回 Top-5。原始响应为 Atom XML，SHA-256 记录在 `search_round1.json` 和 `raw/*.json` 中。

`python -m examples.search_replay_demo` 默认使用本目录，先验证原始字节哈希，再通过正式适配器和筛选逻辑复现完整结果；不联网、不调用模型。原始 API metadata 和论文摘要没有由模型补写。现场时间和路由只代表录制时状态。

`search_round1.json` 中的历史绝对证据路径保留原样，重放按当前 `raw` 目录和响应哈希找文件，因此搬移后仍可使用。旧版 Crossref 录制保留在相邻 `search_recording` 目录，可显式传入 `--input` 与 `--raw-dir` 重放。
