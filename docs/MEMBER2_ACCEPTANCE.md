# 成员 2 Search Agent 本地交付验收报告

> 历史验收记录：本文件记录 2026-10-15 11:45 左右的初版。arXiv 网络路由增强与当天12:08的真实成功记录见 [arXiv 历史验收](MEMBER2_ARXIV.md)。当前默认来源已改为 OpenAlex，最新使用与验证见 [OpenAlex 更新](MEMBER2_OPENALEX.md)。

交付日期：2026-10-15（北京时间）。代码只保存在本地，没有推送、提交远程分支或创建 GitHub PR。

## 1. 交付结论与范围

已按《科研助手分工》第 3–4 页的成员 2 要求，实现 Search Agent、真实数据库 API、自动关键词生成、年份/关键词/相关性过滤、文献去重、Top-K 和统一 Paper JSON；并按仓库 `INTERFACES.md` 支持 Critic 补搜的完整列表合并。

本地完整项目：`D:\chatgpt\projects\multi-agent-research-assistant`。
仓库来源：<https://github.com/jElly1106/multi-agent-research-assistant>。
开发基线为 `main` 的 `4939019abe2a032ae63633b5d8bc8cdba3eed33f`；本地 HEAD 保持这一提交，变更未提交。

需求逐项对照、API/筛选算法、参数、数据契约与 Graph 接入见项目 `docs/MEMBER2_SEARCH.md`。
已有 Graph、共享 State、Paper Schema、Coordinator、Analyst 的实现未被替换。原 `main.py` 仍是原有 demo，真实检索使用 `examples.search_demo`。

## 2. 自动化验证

环境：Windows，Python 3.12.14，独立 `.venv` 位于 D 盘项目内；验收时 `pip check` 显示 `No broken requirements found.`。

全仓 **212 项测试通过，0 失败、0 错误、0 跳过**。其中原有路由/模型/Analyst 测试 38 项，新增 Search 相关测试 174 项。原始日志为交付目录内 `test-results.txt`、`test-results.xml`。

| 测试模块 | 通过数量 |
|---|---:|
| `tests.test_analyst` | 27 |
| `tests.test_llm` | 8 |
| `tests.test_routing` | 3 |
| `tests.test_search` | 53 |
| `tests.test_search_cli` | 5 |
| `tests.test_search_crossref` | 41 |
| `tests.test_search_providers` | 45 |
| `tests.test_search_recording` | 2 |
| `tests.test_search_transport` | 28 |

覆盖：七字段接口与 JSON、输入不变、非法参数、中英文问题生成查询、可选模型失败与伪造论文输出隔离、DOI/arXiv 版本/跨库去重、冲突标识符不误合并、年份/关键词/相关性/Top-K、已有论文保留、两轮真实 LangGraph 反馈、合法零结果与全部失败、部分来源失败、XML/JSON/JATS 解析、HTTP 限流/超时/重试/限速、响应证据/密钥隔离、CLI、真实录制重放与篡改检测。

测试中的人工记录显式为 `MOCK_ONLY`，不作为真实检索成功依据。`git diff --check` 通过。

## 3. 真实联网验收

### 首轮：三来源，2026-10-15 11:41 北京时间

研究主题：`Multimodal Time Series Forecasting`。
实际查询为 `multimodal time series forecasting` 和 `time series fusion text`。
条件：年份 2020 至当前年，每查询每来源至多 10 条，每轮新增 Top-5，默认最低覆盖分 0.12。

| 来源 | 实际结果 |
|---|---|
| arXiv | 读取超时，有限重试后失败；本轮其余查询停止 |
| Semantic Scholar | HTTP 429，有限重试后失败；本轮其余查询停止 |
| Crossref | 两次官方 HTTPS API 请求成功，返回 20 条原始记录 |

整体状态为 **partial**，不能描述为三家均已联网成功。Crossref 原始 20 条中，4 条为不支持的文献类型，解析得到 16 条；其中 3 条缺少满足接口的作者等元数据被排除，剩 13 个独立候选；年份未知 1 条、年份越界 2 条被排除；剩 10 条按覆盖分排序，选入 5 条，另外 5 条因 Top-K 未选入。本次真实记录没有重复项（去重数为 0）；重复与跨库身份场景由离线测试验证。

完整结果和逐项筛选证据在 `search_round1.json`、`audit/<run_id>.json` 以及 `audit/raw/`。首轮 5 篇中有 3 篇缺摘要，输出为真实空字符串，未调用模型补写。

### 第二轮：人工提供 Critic 查询，2026-10-15 11:42 北京时间

输入首轮完整 State，手动写入 FAIL 与查询 `time series language model text forecasting`，只请求 Crossref。真实返回 10 条原始记录，排除不支持类型后解析 8 条，再排除 2 条无效记录，得到 6 条新候选，按本轮 Top-3 选入 3 条；保留首轮全部 5 条，最终 **8 篇**。

这验证的是 Search 对 Critic 接口的补搜合并协议，**不是正式 Critic 自动判断的实测**。第二轮没有产生实际重叠论文，跨轮重复的剔除由离线 Graph 测试另行验证。完整结果在 `search_round2.json`。恢复 State 的旧条目本轮只做来源形状验证；原始首轮证据仍需一起保留。

### 最终论文清单

下列是 API 元数据清单，不是对论文结论的认可，也不是经人工精读后的质量排名。预印本、书章等类型均在 Crossref 支持范围内。

| 序号 | API 返回标题 | 年份 | 摘要 | 来源链接 |
|---:|---|---:|---|---|
| 1 | A Multimodal LLM Framework for Short-Term Footfall Time Series Forecasting | 2026 | 有 | [DOI](https://doi.org/10.2139/ssrn.6996730) |
| 2 | A universal gating framework for multi-expert fusion in heterogeneous multimodal time series forecasting | 2026 | 缺失 | [DOI](https://doi.org/10.1038/s41598-026-54540-x) |
| 3 | The Evolution of Financial Time Series Forecasting: From Classical Econometrics to Temporal Foundation Models and Multimodal LLMs | 2026 | 有 | [DOI](https://doi.org/10.20944/preprints202506.2416.v2) |
| 4 | Time-VLM: Exploring Multimodal Vision-Language Models for Augmented Time Series Forecasting | 2026 | 缺失 | [DOI](https://doi.org/10.1201/9781003616719-9) |
| 5 | Forward Growth Forecasting of Greenhouse Lettuce via Multimodal Inputs and Non-Uniform Time Series Data | 2025 | 缺失 | [DOI](https://doi.org/10.2139/ssrn.5686277) |
| 6 | CP-LLM: Conformal Calibration for Time Series Interval Forecasting with Frozen Large Language Model | 2026 | 有 | [DOI](https://doi.org/10.21203/rs.3.rs-9291769/v1) |
| 7 | Informed forecasting: Leveraging auxiliary knowledge to boost large language model performance on time series forecasting | 2026 | 有 | [DOI](https://doi.org/10.1371/journal.pone.0358970) |
| 8 | Retrieval-Augmented Large-Language-Model-Based Time-Series Forecasting for Cross-Market Equity Analysis | 2026 | 有 | [DOI](https://doi.org/10.21203/rs.3.rs-10178277/v1) |

## 4. 离线真实响应重放

`examples/fixtures/search_recording/` 保存首轮真实 Crossref 原文及公开请求收据，不含模型响应或人工生成论文。运行 `python -m examples.search_replay_demo` 会先核对 SHA-256，再将原始字节交给正式适配器与 Search 逻辑，要求重放后的完整 Paper 列表与录制完全相同。

本次重放 `verified_equal=true`，结果见 `search_replay.json`。它没有发起新网络或模型调用；取得时间是录制中的历史时间，审计开始时间是重放时间。自动化测试另验证原始字节被篡改时会拒绝重放。

## 5. 运行方式

在 PowerShell 中：

```powershell
Set-Location 'D:\chatgpt\projects\multi-agent-research-assistant'
# 已建立本地 .venv，可立即运行；重新解压的副本需先安装 requirements-dev.txt。
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/search_replay.json
.\.venv\Scripts\python.exe -m examples.search_demo '多模态时间序列预测' --question '时间序列如何融合文本信息？' --plan-only
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --source crossref --top-k 5 --max-queries 2 --results-per-query 10 --year-from 2020 --output output/search_result.json --audit-dir output/search_audit
.\.venv\Scripts\python.exe -m pytest -q
```

交给成员 1 时使用 `from research_assistant.agents.search import create_search_node`，将工厂返回的节点注入 `build_research_graph(search_node=...)`；成员 3 读取完整 `papers`；成员 5 在 FAIL 时生成 `new_search_queries`；成员 6 可使用 `validate_paper_references` 检查引用标题/URL 属于 Search 论文列表。

## 6. 保证范围与剩余条件

- 本次未调用任何真实 LLM。规则关键词与可选模型的接口/失败回退已离线测试；用户配置模型后可用 `--use-llm` 实测模型生成查询。
- 排名是透明的词覆盖启发式，不能理解为语义相关概率、真实性概率、论文质量或最优方法排序；有限中文术语表不能翻译任意领域。检索有预算，不是穷尽性文献综述。
- Search 新增论文来自数据库响应。已有 State 被视为可信历史输出，官方 URL 形状本身不能证明存在；请保留前轮真实响应证据。下游引用成员校验也不能证明论文支持某条结论。
- 缺摘要记录需要 Reader 从 DOI/论文页进一步取得合法全文，或明确表示证据不足；不得补造摘要。未下载论文全文。
- `top_k` 限制每轮新增数量，多轮后总数可以超过 K。显式年份/关键词条件变化时旧论文会重新过滤并留记录。
- 正式 Reader、Critic、Writer、前端与完整系统质量评价仍属于其他成员，当前不声称完成全系统真实端到端运行。
- Crossref 本次已真实成功；arXiv 与 Semantic Scholar 仍受本次网络/服务状态限制，其适配器与容错已通过离线测试，未来可在网络恢复或配置授权密钥后复测。

## 7. 交付目录

- `member2-source.zip`：完整源码副本，保留其他成员已有内容，排除 `.git`、虚拟环境、密钥、缓存和系统杂项。
- `member2-changes.zip`：本次新增/修改文件，路径相对于仓库根目录，方便审查与后续合并。
- `member2.patch`：相对原始基线的全部本次变更，已在相同基线的独立临时副本执行 `git apply --check`。
- `source-manifest.json`、`delivery-checksums.json`：逐源文件清单与交付文件 SHA-256。
- `test-results.txt/xml`、`requirements-tested.txt`：实际测试记录与依赖快照。
- `search_round1.json`、`search_round2.json`、`search_replay.json`、`audit/`：真实检索、人工反馈协议验证、历史响应重放及原始证据。

独立源码副本不包含 `.venv`。原始本地项目已有环境可运行；在其他路径解压后需要重新创建虚拟环境并安装依赖。后续上传 GitHub 应由用户另行决定，本次没有进行远程写入。
