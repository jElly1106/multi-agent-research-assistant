# 真实 OpenAlex 首轮录制

2026-10-17 在本机执行默认 Search CLI 保存的官方 API 原文，查询为 `multimodal time series forecasting`。首次请求成功，5 条原始记录、5 条有效候选、Top-3；未请求模型。修正作者取值优先级后，从这同一份原文离线重新解析生成本录制，没有额外检索。

`raw/` 保留原始响应字节，文件名为 SHA-256。`search_round1.json` 中仅将本机原文文件路径改为相对路径，论文、请求地址、时间、哈希及候选内容保留。原文含服务端当时的配额提示，其内容不是程序指令。

在项目根目录运行 `.\.venv\Scripts\python.exe -m examples.search_replay_demo`。回放仅核验历史原文，不联网，不表示 API 当前可用，也不证明数据库元数据绝无错误。原文含两篇会议论文及三篇预印本，不应将全部条目视作已经同行评审。
