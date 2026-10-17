# 2026-10-18真实arXiv检索录制

北京时间2026-10-18 00:06，本地Search CLI向官方Export API发起一次新请求，查询`multimodal time series forecasting`。direct、attempts=1，约13.35秒取得5条有效候选、Top-3。标题、作者、年份和摘要与原始Atom响应对应，SHA-256核验通过。

`search_round1.json`保留原始论文、请求、取回时间和哈希，仅把本机响应文件路径改为`raw/`相对路径。`raw/`保存真实响应字节，`metadata-verification.json`是当次离线核对报告。本记录不证明API未来始终可用。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m examples.search_replay_demo --input examples/fixtures/search_recording_arxiv_20261018/search_round1.json --raw-dir examples/fixtures/search_recording_arxiv_20261018/raw --output output/arxiv_20261018_replay.json
```

预期`verified_equal=true`；回放只读取原文，不联网，不构成一次新的实时检索。
