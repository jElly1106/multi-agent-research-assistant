# 真实论文 API 响应录制

这套文件用于 `python -m examples.search_replay_demo`，是 **2026-10-15 的历史真实 API 响应重放**，不是实时检索，也不是人工构造论文。

- `search_round1.json`：当时 Search CLI 的完整输出，包含主题、条件、查询、入选论文和审计。
- `raw/*.response`：Crossref 官方 API 返回的原始字节，以 SHA-256 命名。
- `raw/*.json`：公开请求的 URL、响应哈希与取得时间，不包含请求头或密钥。

首轮 arXiv 与 Semantic Scholar 未成功，错误保留在 `search_round1.json`；入选论文来自成功的 Crossref 请求。Crossref 提供的记录可能为预印本或书章，且常缺摘要；数据库收录不证明经过同行评议或结论正确。

重放程序对原文重新计算 SHA-256，通过正式数据库适配器、Search 筛选去重和排序，要求选入论文与当时录制完全一致。未录制成功的请求在重放中明确失败，程序不会联网补充，也不调用模型。输出的 `recorded_started_at` 为原始检索 UTC 时间，新的 `search_audit.started_at` 是本次重放时间。

JSON 中原始 `response_file` 是当时的本地绝对路径，作为历史证据保留。重放程序从当前 `raw` 目录按哈希找文件，不依赖这些原始路径，故解压后仍可使用。

原始字节未改写。离线单元测试中的 `MOCK_ONLY` 数据位于测试文件中，与这套录制区分。
