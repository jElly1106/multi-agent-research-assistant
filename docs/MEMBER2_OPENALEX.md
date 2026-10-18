# 成员2：OpenAlex 默认检索与计算机论文来源选择

2026-10-17 起，当前代码默认使用 **OpenAlex**，arXiv、Semantic Scholar、Crossref 保留为显式可选来源。调整时 arXiv 的受控 API 请求返回 HTTP 429；本地程序可以规范请求、记录失败、避免重复触发限流，但无法保证解除外部服务或其网络路径的限制。不能把“换了代理”或“延长 timeout”写成已经修复。

**2026-10-18 复测更新：** 北京时间00:06左右，arXiv 官方 API 的一次新请求首次成功，约13.35秒取得5条记录、选入3篇，原始响应哈希和入选元数据核对通过。该次成功证明当时可用，不保证后续持续可用，也不能确定此前429的具体原因；默认来源继续保留 OpenAlex。若需要搜索 arXiv，在命令中显式添加 `--source arxiv`。

这次改动解决的是当前项目如何取得有真实来源的论文元数据。所有实现与验证文件保存在本地，没有推送 GitHub。项目仍然只完成成员2的 Search 职责；`main.py` 继续注入 demo 节点，真实检索入口为 `python -m examples.search_demo`。

## 本次实际比较与选择依据

使用同一主题 `multimodal time series forecasting`，分别对独立官方接口做一次小规模直接请求，没有在遇到429后更换线路反复请求。

| 来源 | 本次实际结果 | 对本项目的意义 |
|---|---|---|
| OpenAlex Works API | HTTP 200；返回5条记录，5条均提供摘要倒排索引 | 采用为当前默认；有计算机会议论文、期刊论文和预印本元数据，适合发现候选后交给 Reader |
| Crossref Works API | HTTP 200；返回5条记录，部分记录无摘要 | 保留为可选的 DOI 元数据补充；不能依赖其一定提供可供 Reader 使用的摘要 |
| Semantic Scholar Graph API | 无密钥请求返回 HTTP 429 | 保留已有适配器与可选密钥配置；本次没有证明无密钥路径可用 |
| DBLP Search API | 连接异常 `URLError` | 本次未能取得响应；不据此宣称 DBLP 长期不可用，也没有把它接入当前版本 |
| arXiv 官方 Export API | 稍早的2026-10-17受控请求返回 HTTP 429 | 保留显式选择与历史录制；替代来源比较时没有再次请求它 |

上述结果只代表本机本次请求，不是永久可用性或检索质量排名。OpenAlex 覆盖多个学科，检索主题决定召回范围；这次5条记录的主要领域均为 Computer Science，没有通过硬编码把所有主题强行限制为计算机。结果仍需人工检查主题相关性、会议/期刊身份与论文原文。

本次 OpenAlex 原始响应中包含以下记录，可以直接核对官方 Work 页与 DOI；它们是来源比较中的真实 API 元数据示例，不是人工构造的测试论文，也不表示都一定进入某次配置的最终 Top-K：

| 标题 | 年份 | 官方记录与 DOI |
|---|---:|---|
| MulTiCast: A Multimodal Time Series Forecasting System | 2026 | [OpenAlex W7138928672](https://openalex.org/W7138928672)；[10.1609/aaai.v40i48.42371](https://doi.org/10.1609/aaai.v40i48.42371) |
| GPT4MTS: Prompt-based Large Language Model for Multimodal Time-series Forecasting | 2024 | [OpenAlex W4393145940](https://openalex.org/W4393145940)；[10.1609/aaai.v38i21.30383](https://doi.org/10.1609/aaai.v38i21.30383) |

OpenAlex 返回 `conference-paper` 与 `preprint` 等不同类型；不能把所有记录一律称为已同行评议论文。它也会收录 arXiv 论文，因此仍可能发现来自 arXiv 的研究工作；**元数据请求经过 OpenAlex，不表示 arXiv API 或 PDF 下载已经恢复**。本次没有验证 PDF 全文读取。

## 元数据真实性与跨成员接口

新增适配器为 `research_assistant/search/openalex.py`，调用官方 `https://api.openalex.org/works`，以自然语言 `search` 搜索。标题、作者、年份和 DOI 只取 API 提供的值，不由 LLM 生成。摘要按 `abstract_inverted_index` 的词位置还原；如果位置缺口、冲突或格式无效，记录警告并保留空摘要，不补造缺失文字。

实际交叉核查还发现了一处作者消歧问题：独立请求 Crossref 的确切 DOI `10.1609/aaai.v40i48.42371` 返回 HTTP 200，标题与 MulTiCast 一致；OpenAlex 同一记录的第二位作者在 `authorships[].author.display_name` 中为 `Cheon Goo Han`，但对应的 `raw_author_name` 为 `Caren Han`，Crossref 提供的作者名也是 `Caren Han`。本版据此优先使用该论文记录实际提供的 `raw_author_name`，缺失时才使用关联作者实体的 `display_name`，并在有差异时保留双方原值与警告，避免将数据库作者实体的消歧结果直接当作论文署名。这项改进不代表已核实全部论文的全部作者，也不保证原始署名字段永远正确；正式引用仍应核对出版页或论文原文。

公共 Paper 仍为七个字段：`title`、`authors`、`year`、`abstract`、`url`、`source`、`relevance_score`。OpenAlex 记录的 `source` 为 `openalex`，`url` 为 `https://openalex.org/W...`。论文实际落地页、PDF 链接、DOI 和类型等放在 `search_audit.candidates[].provenance[]`，不会破坏成员1/3/4/5/6已有接口：

| 审计字段 | 含义与用途 |
|---|---|
| `source_id` | OpenAlex Work ID，例如 `W4393145940` |
| `doi` | API 实际提供且格式有效的 DOI，用于追溯与跨来源去重 |
| `landing_page_url` | API 主记录提供的出版或仓储落地页，可能为空 |
| `pdf_url` | API 主记录实际提供的 PDF 入口，可能为空；本模块不自动下载 |
| `publication_type`、`venue`、`field` | API 提供的文献类型、来源名称、主要领域，帮助人工核查 |
| `request_url`、`retrieved_at`、`response_sha256` | 官方请求、取回时间和原始响应摘要，用于证据追溯 |

Reader 不能将公共 `url` 一律当作 PDF 下载地址。应先查对应候选的实际落地页或 PDF 链接，并继续保留原文证据；API 的存在性证据也不能证明论文结论正确。跨库合并时保留原始 provenance，不把 OpenAlex 成功改标为 arXiv 成功。

## 配额与网络边界

本次 OpenAlex 请求不需要密钥。该次响应的 `meta.notice` 提示匿名访问共享网络 IP 的免费日预算，独立免费 API Key 有自己的日预算；具体金额、政策和资格可能变化，应以服务方当前规则为准。**当前代码没有读取或发送 OpenAlex API Key**，无需在 `.env` 填写不存在的配置项；本次也没有创建账号、申请密钥或发送验证邮件。

因此，无密钥路径是已实测可用的路径，不能承诺永久免费无限使用。若小组后续长期运行遇到共享配额限制，再通过服务方正式方式申请自己的访问资格，并另行实现不泄露凭据的认证；不要把密钥放进共享输出、审计或截图。现在可用小规模请求与真实响应离线回放完成代码验收。

所有来源继续保留 HTTPS/TLS 验证、主机白名单、有限重试与本地节流。OpenAlex 至少间隔1秒；这只是本地请求策略，不是服务方配额承诺。HTTP 429 立即停止该来源本轮请求，不更换线路规避，合法 `Retry-After` 会保留；缺少该头时只提供标为本地策略的等待建议，不保证到时恢复。失败与合法零结果区分，详见 [Search 交接说明](MEMBER2_SEARCH.md) 与 [限流诊断](MEMBER2_RATE_LIMIT.md)。

## 如何运行与验收

本次最终回归实测为 **341 passed in 4.63s**，无失败，`pip check` 为 `No broken requirements found.`。北京时间11:54的默认CLI只发送一次OpenAlex请求，路线direct、尝试1次，取得5条原始记录、5条有效候选、Top-3；5篇均有摘要。修正作者字段优先级后，使用这同一份官方原文离线重新解析，未额外请求API；最终5条标题、作者原始署名、年份、摘要、DOI和原始响应SHA-256均逐项核对通过。默认离线回放为 `verified_equal=true`。

完整证据位于 `D:\chatgpt\outputs\2026-10-17-paper-sources`：`openalex-live.json` 保留初次联网运行原样结果，`openalex-result.json` 是修正作者取值后对同一原文的最终解析结果，`metadata-verification.json` 为字段核对，`crossref-doi-verification.json` 为独立DOI核对，`openalex-replay.json` 为离线复现，`test-results.txt/xml` 为实际回归日志。两份结果不代表两次联网检索；原始取回时间和哈希均保留。

在本地项目目录运行，以下命令均写入项目内被 Git 忽略的 `output` 目录：

```powershell
# 在项目根目录执行；先按 README 安装依赖
.\.venv\Scripts\python.exe -m examples.search_demo '多模态时间序列预测' --question '时间序列如何融合文本信息？' --plan-only
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/openalex_replay.json
.\.venv\Scripts\python.exe -m pytest -q
```

第一条只规划查询；第二条默认读取 `examples/fixtures/search_recording_openalex` 中的归档真实响应，核验 SHA-256 后经过正式适配器、去重、过滤、排序，成功时为 `verified_equal: true`；第三条运行离线测试。回放成功说明当前代码能够复现那次真实检索，测试通过说明相应可控边界符合契约；两者均不能证明当前联网请求成功。最终测试数量与实时验收状态应查看本次交付目录中的原始日志，不用历史235或245项代替当前统计。

确认网络可用时，执行一次小预算真实查询：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --top-k 3 --max-queries 1 --results-per-query 5 --output output/openalex_result.json --audit-dir output/openalex_audit
$result = Get-Content -LiteralPath output/openalex_result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$result.search_audit.status
$result.search_audit.counts
$result.state.papers | Format-Table title,year,source,url
```

不指定 `--source` 即仅查 OpenAlex。正常联网验收应检查：进程退出码0、审计状态 `success`、实际请求来源 `openalex`、标题和作者与保存的原始响应一致。结果数量受过滤与 Top-K 共同影响，合法零命中也可为成功状态，不能仅凭生成了 JSON 文件或固定“3篇”判断成败。摘要缺失是警告，不等同整体失败；需检查候选原因及实际响应。审计 `partial` 表示部分来源失败，`unavailable` 与退出码2表示全部实际请求失败；CLI 仍可保存失败记录供排查。

需要 Crossref 补充时显式写 `--source openalex --source crossref`。希望重新尝试 arXiv 时显式写 `--source arxiv`，先遵守上次失败记录的等待要求；不要将其网络失败触发为静默切换来源的成功。历史 arXiv 和 Crossref 响应仍保留，可分别用 `--input` 与 `--raw-dir` 指定回放，见 [arXiv 历史文档](MEMBER2_ARXIV.md)。

Critic 的补搜、旧论文完整保留、每轮新论文 Top-K 和引用成员校验继续沿用原实现。正式验收应分别保留联网结果、原始响应、离线回放与测试日志，使“代码运行正常”“本次网络可用”“论文结论有原文支持”三项结论都有各自证据。
