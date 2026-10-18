# arXiv 优先检索与超时处理：2026-10-15 历史验收

> 本文件记录 2026-10-15 的实现与实测，包含当时的默认配置与测试数量。2026-10-17 观察到 API 返回429，限流处理与失败诊断见 [后续更新](MEMBER2_RATE_LIMIT.md)；不能将历史成功当作当前实时可用证明。**当前默认来源和离线回放均已改为 OpenAlex**，见 [当前使用说明](MEMBER2_OPENALEX.md)。下方运行命令已补上显式来源与录制路径，可用于选择 arXiv。

日期：2026-10-15。当前代码位置：`D:\chatgpt\projects\multi-agent-research-assistant`。本次只修改本地项目，没有上传 GitHub，也没有修改 Windows 全局代理。

## 当时实现的调整

1. 默认新检索来源改为 **仅 arXiv**；CLI 与 `SearchConfig` 使用同一默认值。Semantic Scholar / Crossref 保留，需要通过 `--source` 显式开启。恢复 State 时仍保留已有论文的真实来源，不把其他数据库记录改标成 arXiv。
2. arXiv 支持 `auto`、`direct`、`system` 三种进程内路由。默认 `auto` 先直连；配置了 HTTP/HTTPS 系统代理且发生连接、读取等网络异常时，在已有 `max_retries` 预算内切换；后续查询复用成功路线。可通过 `--arxiv-proxy-mode`、`.env` 的 `ARXIV_PROXY_MODE` 或 Python `SearchConfig.arxiv_proxy_mode` 配置。
3. 当时 HTTP 429 和 5xx 沿当前路线有限退避，不通过换路线规避限流。**2026-10-17 起，HTTP 429 已改为立即停止本轮，不自动重试；5xx 的服务端等待要求超过自动上限时也停止，详见限流更新。** 所有路线保留 HTTPS/TLS 验证，arXiv 请求间隔仍至少 3 秒。审计新增实际 `route` 与 `attempts`，不保存代理或 API 凭据。
4. 普通关键词转换为受控的 `all:"word" AND all:"word"`，明确要求词项同时匹配。初版隐式空格查询返回了多篇只与时序预测有关的论文；本次不再依赖这种宽泛语义。模型或调用方给出的文本不会作为任意 arXiv DSL 执行。
5. 默认离线重放切换为本次真实 arXiv Atom 录制；原 Crossref 录制保留，可显式指定路径回放。

## 诊断事实与因果边界

发现 Python `urllib` 会读取当前 Windows 系统代理，而命令行 curl 的此次请求走直连。只读检查发现系统代理启用；没有变更这一设置。curl 对官方摘要页、API、搜索页均收到 HTTP 200，TLS 证书验证成功。

随后对**完全相同**的官方 API 查询做 A/B：直连约 1.047 秒、系统代理约 0.703 秒，两者均 HTTP 200，返回字节哈希相同。因此本次证据不能证明“之前超时唯一由代理导致”；网络或 arXiv 后端的瞬时状态已经恢复。此次增加路由配置与有限切换，目的在于减少单一路径故障的影响，并保留可核查状态。详见 `proxy_ab.json` 与 `connection_diagnostics.json`。不将“更长 timeout”或未实测的镜像作为修复成功证据。

## 真实联网验收

北京时间 **2026-10-15 12:08:12–12:08:16**，直接运行更新后的默认入口，没有指定 `--source`。查询为：

- `multimodal time series forecasting`
- `time series fusion text`

两次请求均到 `https://export.arxiv.org/api/query`，实际路线均为 **direct**，均在首次尝试成功。状态 **success**；取得 20 条真实 Atom 记录，20 条均解析/校验通过；统一排序后返回 Top-5，5 篇都为 `source=arxiv`，且都有摘要。此次候选没有重复记录（去重数 0），重复身份场景由离线测试覆盖。

| 标题（来自官方 API） | 年份 | 官方链接 |
|---|---:|---|
| Multimodal Forecasting for Commodity Prices Using Spectrogram-Based and Time Series Representations | 2026 | [arXiv](https://arxiv.org/abs/2603.27321v1) |
| Rethinking Multimodal Time-Series Forecasting Evaluation | 2026 | [arXiv](https://arxiv.org/abs/2607.06973v1) |
| SCENARIODIFF: A Scenario-level Guidance Framework for Multimodal Time Series Forecasting--Extended Version | 2026 | [arXiv](https://arxiv.org/abs/2608.17164v1) |
| Spectral Text Fusion: A Frequency-Aware Approach to Multimodal Time-Series Forecasting | 2026 | [arXiv](https://arxiv.org/abs/2602.01588v3) |
| When Does Text Inform? Benchmarking Information-Theoretic Metrics for Multimodal Time-Series Forecasting | 2026 | [arXiv](https://arxiv.org/abs/2609.11282v1) |

已将 5 篇的标题、作者、摘要、arXiv ID 与原始 Atom 内容逐项对照，全部一致；响应 SHA-256 也已核验。见 `arxiv_verification.json`、`arxiv_round1.json` 及 `audit/raw/`。没有调用模型生成或补写论文。

另外抽查其中 2 篇官方摘要页，均 HTTP 200；页面 `citation_title` 与 API 返回标题一致，见 `paper_page_checks.json`。本次没有下载 PDF 全文，不能将摘要页成功描述为全文解析通过。

## 回归与离线验证

全仓 **235 项测试通过，0 失败、0 错误、0 跳过**，原始结果见 `test-results.txt/xml`。本次重点检查默认来源、路由配置、有限重试、网络失败切换、成功路线复用、HTTP 429/5xx 不换路、TLS 不降级、证据落盘，以及真实 arXiv 录制的离线复现。

`arxiv_replay.json` 的 `verified_equal=true`。回放先核验原始响应 SHA-256，再经过正式适配器、去重筛选及排序，完整论文 JSON 与录制相同；这次重放没有发起新网络或模型调用。旧 Crossref 录制的回归测试同样通过。

## 运行方法

当前 D 盘项目已有虚拟环境。只有希望显式查询 arXiv 时才运行下列联网命令；当前默认 OpenAlex 不受此命令说明影响。若上轮返回 HTTP 429，应先遵循失败审计中的等待要求，不反复重试：

```powershell
Set-Location 'D:\chatgpt\projects\multi-agent-research-assistant'
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --source arxiv --top-k 5 --max-queries 2 --results-per-query 10 --output output/arxiv_result.json --audit-dir output/arxiv_audit
```

固定直连时加 `--arxiv-proxy-mode direct`；固定使用系统代理时加 `--arxiv-proxy-mode system`。不传这一参数则默认 `auto`，也可以在 `.env` 设置 `ARXIV_PROXY_MODE`。这些设置仅作用于本项目请求。

显式回放历史 arXiv 录制（不会请求 API）：

```powershell
.\.venv\Scripts\python.exe -m examples.search_replay_demo --input examples/fixtures/search_recording_arxiv/search_round1.json --raw-dir examples/fixtures/search_recording_arxiv/raw --output output/arxiv_replay.json
```

arXiv 公开检索不需要 API Key。本次未使用收费模型或第三方检索服务。外部服务仍可能出现瞬时故障；完全失败时程序会明确报错，不生成论文补数。当前实现未增加缓存兜底，也不会把历史缓存伪装成实时成功。

## 交付文件

- `member2-arxiv-source.zip`：最新完整项目源码，包含成员2全部实现和本次改进；不含 `.git`、虚拟环境、真实密钥和缓存。
- `member2-arxiv-changes.zip`、`member2-arxiv.patch`：相对于原仓库 `4939019abe2a032ae63633b5d8bc8cdba3eed33f` 的累计成员2变更，包含初版与本次调整；补丁通过同基线独立副本的 `git apply --check`。
- `source-manifest.json`、`delivery-checksums.json`：源码与交付文件 SHA-256。
- `arxiv_round1.json`、`arxiv_verification.json`、`paper_page_checks.json`、`audit/`：实际请求与元数据对照证据。
- `arxiv_replay.json`、`test-results.txt/xml`、`requirements-tested.txt`：离线复现与测试环境证据。

初版 11:41 的 arXiv 超时/Crossref 成功记录保留在历史验收报告中。本文件的12:08证据仅描述2026-10-15当天；最新限流事实见 [2026-10-17 更新](MEMBER2_RATE_LIMIT.md)，当前默认配置见 [OpenAlex 使用说明](MEMBER2_OPENALEX.md)。前轮其他成员接口与责任范围继续沿用，未将 Search 成功表述为正式六 Agent 系统全部完成。
