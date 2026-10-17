# 成员 2：Search Agent 交接说明

本模块完成“研究问题 → 关键词 → 官方论文 API → 去重与筛选 → 统一论文列表”，供 Reader、Analyst、Critic 和 Writer 使用。实现遵循仓库原有 `ResearchState`、`Paper` 和 `node(state) -> dict` 接口；成员 1 的 Graph 与成员 4 的 Analyst 无须更换数据格式。

真实 Search 的独立运行入口是 `python -m examples.search_demo`。原有 `main.py` 继续用于编排演示，仍然注入 demo 节点；运行它不会自动启用本模块，也不能将它输出的示例论文用于科研报告。Reader、正式 Critic、Writer 与完整系统质量评价属于其他成员的交付范围。

**2026-10-18 更新：当前默认来源仍为 OpenAlex，arXiv 可显式选择。** 10月17日 arXiv 受控 API 请求曾返回 HTTP 429；10月18日北京时间00:06左右，一次新的官方 API 请求首次成功，约13.35秒取得5条记录、选入3篇，原始响应与入选元数据核对通过。这证明该次访问可用，不能保证持续可用或认定此前限流已永久修复。[OpenAlex 使用与验收](MEMBER2_OPENALEX.md) 说明来源选择、配额限制与证据边界。

## 1. 文档要求与实现对照

需求来源为《科研助手分工》第 3–4 页、第 18–20 页，以及《多智能体 AI 科研助手》第 1–2 页。分工文档中的论文 JSON 为示例，实际 `authors` 类型严格沿用仓库已统一的 `list[str]`。

| 文档要求 | 实现位置 | 交付及验收方式 |
|---|---|---|
| 根据 Coordinator 的研究问题自动生成检索词 | `research_assistant/search/keywords.py` | 读取主题、问题、方向、关键词；支持有限中文术语转换与可选模型规划；离线测试检查问题中的文本融合信息进入查询 |
| 接入真实论文数据库 API | `research_assistant/search/providers.py`、`search/crossref.py`、`search/openalex.py` | OpenAlex Works、arXiv Atom、Semantic Scholar Graph API、Crossref Works API 四个独立适配器；解析官方响应中的标题、作者、年份、摘要和来源标识符 |
| 文献去重 | `research_assistant/search/ranking.py` | DOI、arXiv 版本、来源 ID、URL 与标准化标题/作者联合匹配；测试覆盖跨库重复及不同 DOI、年份不误合并 |
| 年份过滤 | `SearchConfig`、`filter_reason` | 年份上下界为闭区间；显式年份筛选时排除年份未知记录，并记录原因 |
| 关键词过滤 | `filter_reason` | 支持必含词 `any/all` 与排除词；在标题、摘要上执行标准化词项匹配 |
| 相关性判断 | `relevance` | 透明、可复现的主题与查询词覆盖分；审计保留分项、命中词和计算公式 |
| Top-K 筛选 | `research_assistant/agents/search.py` | 去重、过滤后排序；每轮新增最多 K 篇；Critic 补搜保留已有论文 |
| 避免 LLM 编造论文 | Search 节点、适配器、`validate_paper_references` | 模型只能生成查询；新论文来自 Provider 结果；来源/URL 校验与 API 响应审计提供追溯依据；下游可执行引用成员校验 |
| 统一 Paper JSON | `research_assistant/schemas.py`、Search 节点 | 保持原有七字段，不将内部 DOI、PDF 或审计字段塞入公共 Paper |
| Critic 反馈循环 | 查询规划、完整论文列表合并 | 优先执行 `critic_result.new_search_queries`；真实 LangGraph 离线集成测试执行两轮补搜 |
| 能与相邻成员联调 | `create_search_node`、`search_node` | 节点只返回 `papers` 与必要的 `errors`；CLI 输出合并后的完整 State；兼容原 `INTERFACES.md` |

文档规定成员 2 在 10 月 18 日前完成。交付以本地文件为准；本说明不表示已推送或发布到 GitHub。

## 2. 安装与最小运行

需要 Python 3.10 或更新版本。在项目根目录执行，Windows PowerShell 可使用已建好的环境：

```powershell
# 在项目根目录执行；尚未建立环境时先运行 python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m examples.search_demo --help
```

如果尚未建立环境，先用 `python -m venv .venv` 创建，再安装依赖。Search 的规则查询、数据库请求与排名不依赖 LLM 密钥；需要网络能够访问官方论文 API。本次 OpenAlex 无密钥请求成功，但其响应提示匿名访问使用共享 IP 免费配额，不保证始终有可用额度；本实现尚未接入 OpenAlex API Key。公共 Semantic Scholar 接口可能限流，有该平台授权密钥时可在 `.env` 或进程环境中设置 `SEMANTIC_SCHOLAR_API_KEY`，也兼容 `S2_API_KEY`。该密钥通过 HTTP 请求头发送。Crossref 官方公共检索不需要密钥，可显式选择作为独立元数据来源，但常缺摘要。

先检查离线查询规划：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo '多模态时间序列预测' --question '时间序列如何融合文本信息？' --plan-only
```

`--plan-only` 不请求数据库、不调用模型，即使同时设置 `--use-llm` 也只执行规则规划。它只能证明生成了查询，不能证明搜得论文。

执行小规模真实检索并保留证据：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --top-k 3 --max-queries 1 --results-per-query 5 --year-from 2022 --output output/search_result.json --audit-dir output/search_audit
```

省略 `--source` 时只检索 `openalex`。需切回 arXiv 时显式写 `--source arxiv`；启用多个来源可重复参数，如 `--source openalex --source crossref`，不要重复同一个来源。各来源独立标识；OpenAlex 收录的 arXiv 论文仍标为 OpenAlex，其成功不表示 arXiv API 已恢复。命令相对于项目根目录写入 `output`，该目录被 `.gitignore` 排除；运行结果与审计应另外保留用于交接。

### 完整参数

| 参数 | 默认值/用途 |
|---|---|
| `[topic]` | 可选研究主题；也可从输入 State 读取；两者都没有时用 `Multimodal Time Series Forecasting` |
| `--input PATH` | 恢复裸 State JSON，或上次 CLI 输出的 `{ "state": {...} }` |
| `--question TEXT` | 研究问题，可重复；提供后替换输入 State 的 `research_questions` |
| `--query TEXT` | Coordinator 的查询建议，可重复；提供后替换 `search_keywords` |
| `--followup TEXT` | Critic 补搜需求，可重复；写入 FAIL 与 `new_search_queries`，优先检索 |
| `--source NAME` | 可重复选择 `openalex`、`arxiv`、`semantic_scholar`、`crossref`；默认仅 `openalex` |
| `--top-k N` | 10；范围 1–100；本轮新增论文数上限 |
| `--max-queries N` | 6；范围 1–12；查询数上限 |
| `--results-per-query N` | 20；范围 1–100；每个查询、每个来源请求的候选数上限 |
| `--year-from YEAR` / `--year-to YEAR` | 不设置显式年份边界；可填 1000 至当前年份，下界不能大于上界；未来年份记录仍会排除 |
| `--required-keyword TEXT` | 可重复；要求标题/摘要命中所填关键词 |
| `--exclude-keyword TEXT` | 可重复；任一排除条件命中即剔除 |
| `--keyword-match any\|all` | `any`；控制多个必含关键词之间的组合关系 |
| `--min-relevance FLOAT` | 0.12；范围 0–1；对本轮新候选执行的最低覆盖分 |
| `--timeout SECONDS` | 20；范围 `(0,120]`；单次请求超时，并非整轮总时限 |
| `--max-retries N` | 2；范围 0–3；网络/临时服务故障的额外重试次数，HTTP 429 总是立即停止 |
| `--arxiv-proxy-mode MODE` | 默认 `auto`，也可读取 `.env` 的 `ARXIV_PROXY_MODE`；`auto/direct/system`，只影响 arXiv 请求，不改全局代理 |
| `--use-llm` | 显式启用模型生成查询；默认关闭 |
| `--plan-only` | 仅规则规划查询，不访问网络或模型 |
| `--output PATH` | 保存 UTF-8 JSON；省略时输出到终端 |
| `--audit-dir PATH` | 保存逐轮审计 JSON 及成功 API 响应原文；省略时仍可在输出中查看 `search_audit`，但不归档原始响应 |

`required_keywords` 和 `excluded_keywords` 使用有限术语转换、别名与规范化分词，但**保留 `model` 等在排名中会被删除的停用词**，避免用户显式条件被悄悄缩减。一个多词条件要求这些词项均出现，但不要求按原顺序连续出现；`any/all` 作用于多个条件之间。例如 `--required-keyword 'text fusion'` 要求出现 text 与 fusion，而非精确短语匹配。

### 可选模型查询规划

在 `.env` 或环境变量中设置 `OPENAI_API_KEY`、`LLM_MODEL`；兼容网关还需设置 `OPENAI_BASE_URL`，值为 API 根地址。`LLM_API` 采用仓库既有的 `chat_completions` 或 `responses`。随后在命令中显式加 `--use-llm`。

模型只生成结构化 `queries: list[str]`，不能产出论文。缺配置、模型超时或格式无效时，记录警告并使用规则查询，不会生成示例论文补位。模型服务可能产生调用费用；默认配置不调用它。

规则规划的优先级为 Critic 补搜、可选模型查询、Coordinator 关键词、主题、研究问题、搜索方向，经清理与去重后取前 `max_queries` 条。若前面的条目占满预算，后面的条目不会执行；需要覆盖更多问题时调整预算或提供聚焦查询。

离线中文术语表包含时间序列、文本、多模态、LLM 等常见术语，不能翻译任意研究领域。未识别的中文保留原文并提示限制。对冷门领域，应提供英文 `--query`，或显式启用模型；不能将规则转换描述为通用翻译能力。

## 3. 数据接口与节点接入

Search 读取 `topic`、`research_questions`、`search_directions`、`search_keywords`、`critic_result.new_search_queries`、已有 `papers` 与 `errors`。主题必须是非空字符串，问题/方向/关键词使用字符串列表。

节点返回：

```python
{
    "papers": [
        {
            "title": str,
            "authors": list[str],
            "year": int | None,
            "abstract": str,
            "url": str,
            "source": "openalex" | "arxiv" | "semantic_scholar" | "crossref",
            "relevance_score": float,
        }
    ],
    # 存在警告或部分失败时可有 errors: list[str]
}
```

这是类型示意，不是实际搜索结果。`year` 未知时为 `null`，摘要缺失时为 `""`，不调用模型补写。`errors` 同时承载警告，应结合审计 `status` 判断是否整体失败。Search 不更新其他成员的字段，不修改传入 State。

OpenAlex 的 `url` 是官方 Work 记录链接 `https://openalex.org/W...`，不是 PDF。API 实际提供的 `landing_page_url`、`pdf_url`、`doi`、`publication_type`、`venue`、`field` 保存在 `search_audit.candidates[].provenance[]`，不增加公共 Paper 字段。Reader 可据此选择出版页或原文入口；没有 PDF 链接时不能自行拼造。

CLI 为便于恢复，保存的 JSON 结构为 `notice`、`state`、`search_audit`；其中 `state` 为原 State 与节点返回字段的合并结果。其他字段保留的含义是便于交接，补搜后 Reader、Analyst 等仍应重新计算相应结果，不能把旧分析自动当作新论文的分析。

默认入口可以直接传入原 Graph：

```python
from research_assistant.agents.search import search_node

# build_research_graph(search_node=search_node, reader_node=..., ...)
```

需要配置与审计时，建议为每个调研会话创建一个实例并重复使用：

```python
from research_assistant.agents.search import create_search_node
from research_assistant.search.config import SearchConfig

search = create_search_node(
    config=SearchConfig(top_k=5, max_queries=3, year_from=2022),
    audit_dir="output/search_audit",
)
delta = search({
    "topic": "Multimodal Time Series Forecasting",
    "research_questions": ["时间序列如何融合文本信息？"],
})
papers = delta["papers"]
audit = search.last_audit
# 将 search 传给 build_research_graph 的 search_node 参数。
```

实例内部保留已选论文的 DOI、来源 ID 与原始证据，有利于后续补搜。`search_node(state)` 是便捷入口，每次创建新实例；需要跨轮内部身份信息和稳定证据链时使用工厂返回的同一实例。不要将同一可变实例同时用于多个并发调研会话。

### Critic 补搜与完整列表语义

`top_k` 限制每轮**新选入**的论文数。已有论文与新候选统一去重后，已有论文保留，再新增最多 K 篇，故返回总数可以超过 K。已有论文不会因本轮补搜查询造成覆盖分降低而仅依据 `min_relevance` 被删除；分数仍会按本轮查询重新计算。

显式年份或关键词条件会对已有论文再次执行。条件改变导致旧论文不合要求时，会剔除它、产生警告，并在审计记录原条目与原因。换一个完全不同的研究主题时应新建 State，避免沿用另一个调研的论文集合。

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo --input output/search_result.json --followup 'LLM multimodal time series forecasting' --top-k 3 --max-queries 2 --output output/search_result_round2.json --audit-dir output/search_audit
```

Reader 应读取返回的完整 `papers`，继续保持 `paper_analysis.paper_title` 与 `papers.title` 一致；补充论文后返回完整分析列表。Critic 填写 `new_search_queries` 后，原 Graph 会在 FAIL 时重新调用 Search。

## 4. 筛选、去重与评分依据

处理顺序为：验证输入与查询 → 请求各来源 → 验证候选 → 统一去重 → 本地覆盖评分与年份/关键词过滤 → 新论文 Top-K → 完整列表和审计。

去重优先识别相同 DOI、去掉版本号的 arXiv ID、来源 ID 或 URL。没有共同标识符时，使用 NFKC 标准化、忽略大小写与标点的标题，加至少一个相同作者进行匹配；明确不同 DOI、不同 arXiv ID，或同标题不同年份不会仅因标题相同合并。Semantic Scholar 记录还会验证 paperId 与官方 URL 中的标识符一致，OpenAlex 验证 Work ID 和 `ids.openalex` 一致。合并时保留较完整摘要、作者和未知年份的补全信息；已交付的标题保持稳定。内部 DOI、arXiv ID、多来源记录保存在审计，公共 Paper 仍为七字段。

如果不同标识符的论文恰好使用完全相同的标题，Search 会保留两篇并在 `errors` 提示使用 URL 区分。当前 Reader/Analyst 主要通过标题关联，这种情况需要人工处理或由其他成员增强关联键；不能为迁就下游而错误合并两篇论文。

相关性分数采用本地词覆盖启发式。对主题、查询、标题与摘要应用有限中文术语转换、别名并删除停用词，生成词项集合；这与保留停用词的显式关键词过滤有所区别。对某一主题/查询的每个词项，标题命中记 1，只有摘要命中记 0.7，未命中记 0，再除以该主题/查询的词项数：

```text
coverage(q) = Σ 每个词项的命中权重 / q 的有效词项数
score = 0.65 × coverage(topic) + 0.35 × max(coverage(query_i))
```

分数四舍五入到 6 位小数；新候选按分数降序、年份降序、标题和 URL 排序。这不是模型语义相似度、真实性概率、论文质量或方法性能评分，不能据此声称某论文最优。只在摘要出现的相关内容可获得分数；缺摘要候选主要依据标题计分，可能漏掉与主题语义相关但措辞不同的论文。

检索是有数量预算的候选发现流程，不声称覆盖领域全部文献。每个来源对每条查询只取配置的首批结果，不实现穷尽式分页；数据库检索排序、访问范围和限流均会影响召回。

## 5. 网络失败与审计

官方请求地址分别为 `https://api.openalex.org/works`、`https://export.arxiv.org/api/query`、`https://api.semanticscholar.org/graph/v1/paper/search` 与 `https://api.crossref.org/works`。传输层仅允许这四个 HTTPS 主机，保留证书验证，拒绝自动重定向；Semantic Scholar 可选密钥放在请求头，不写入审计，OpenAlex 当前只使用无密钥访问。默认原始响应上限为 8 MiB。

OpenAlex 使用自然语言 `search`、`per-page` 与显式 `select` 获取元数据，保留支持的学术文献类型，包括 `conference-paper`、`article` 与 `preprint`；收录类型不代表都经过同行评议。摘要来自 API 的 `abstract_inverted_index`，仅按完整、无冲突的词位置恢复文本；位置缺口、重复或无效格式会记录警告并保留空摘要，不生成缺词。DOI 和实际落地页中的 arXiv 标识符只用于来源审计与跨库去重，不改变 `source=openalex`。

arXiv 的普通检索短语会转换为受控的 `all:"word1" AND all:"word2"` 表达式，明确要求全部关键词命中，避免依赖空格的宽泛语义；不执行调用方或模型提供的任意 arXiv DSL。默认路由 `auto` 优先使用当前进程内的直连 opener。存在 HTTP/HTTPS 系统代理时，仅在连接/读取等网络异常后，在原有重试次数内尝试代理，并复用成功路线。`direct` 固定直连，`system` 固定系统/环境代理。HTTP 429 立即停止；5xx 可沿原路线有限重试，服务端等待要求超过自动等待上限时停止，不能截短等待提前请求。原始响应收据与 `response_evidence` 包含实际 `route` 和 `attempts`；失败的 `failure_evidence` 包含逐次尝试、HTTP状态、合法Retry-After和等待建议，不记录凭据或任意上游错误文本。详见 [arXiv 历史验收](MEMBER2_ARXIV.md) 和 [当前限流诊断](MEMBER2_RATE_LIMIT.md)。

Crossref 使用自然语言 `query.bibliographic`、`rows`、相关性排序获取记录，再在本地保留 `journal-article`、`proceedings-article`、`posted-content`、`book-chapter` 类型，排除其他类型。其公开论文 URL 使用 `https://doi.org/<DOI>`。年份读取发表日期，不用元数据入库日期代替。Crossref 经常不提供摘要，缺失值保留为空；已有 JATS 摘要会安全解析成文本，解析失败记录警告。空摘要论文只能提供有限的标题级检索证据，交给 Reader 后仍需获取原文，不能宣称已经读过正文。

传输层按主机共享请求间隔：arXiv 至少 3 秒，OpenAlex、Semantic Scholar 与 Crossref 至少 1 秒。这是本地节流策略，不代表数据库承诺的配额。HTTP 429 首次出现就停止，保留有效 `Retry-After` 的完整秒数或日期；没有有效值时提示本地建议等待300秒，明确不保证恢复时间。网络故障和5xx仍可有限重试；5xx要求等待超过30秒默认上限时，停止并提示，而不是截短服务端要求。其他 HTTP 错误直接报告。一个来源在本轮失败后，其剩余查询不再继续请求。总耗时可能超过单次 `timeout`。

| 情况 | 行为 |
|---|---|
| API 明确返回合法零条结果，或全部候选被筛除 | 正常返回 `papers: []` 并附说明；不会生成替代论文 |
| 部分来源失败，至少一次请求成功 | 保留成功来源的候选；审计状态 `partial`，`errors` 提示失败来源 |
| 所有实际请求均失败 | 抛出 `SearchUnavailableError`；审计状态 `unavailable`；不伪装成合法零命中 |
| API 返回 XML/JSON 错误、条目与 total 不一致或全部条目不可用 | 作为来源错误报告 |
| 个别条目缺少/违反字段或来源约束 | 排除或保留明确缺失值，并记录警告，具体见候选与来源审计 |
| 审计目录不可写或证据归档失败 | 显式失败，提示检查目录/磁盘；不能声称原始证据已保存 |

CLI 成功退出码为 0，输入错误、整体不可用或本地读写失败为 2。失败时若提供 `--output`，会保存失败说明和已产生的 `search_audit`，便于检查。

`SearchAgent.last_audit` 始终表示该实例最近一轮已经初始化的审计，包含 `run_id`、UTC 时间、主题、配置、最终查询、请求状态、计数、每个候选的筛选原因、覆盖分、身份标识符、多来源 provenance 与入选结果。成功请求的 `response_evidence` 独立保留；即使合法零结果没有候选，也能追溯响应。`api_records` 为收到的原始记录数，`api_hits` 为适配器产出的论文数，`invalid_hits` 为随后未通过公共来源/格式校验的条目数；不能将三者混为“真实入选论文数”。输入在审计初始化前即无效时，不保证产生新的审计文件。

指定 `--audit-dir` 后，目录中包含逐轮 `<run_id>.json`；`raw` 子目录保存按响应内容 SHA-256 命名的 `.response` 原文，以及按“请求 URL + 获取时间 + 响应哈希”独立计算哈希命名的 `.json` receipt 元数据。不同请求即使收到相同字节，也不会覆盖彼此的请求收据。候选的 provenance 关联请求 URL、时间、响应哈希与原始文件。需要保留整套目录，不能只保存最终 Paper 列表而丢掉来源证据。审计不记录请求头或密钥，但包含研究主题、关键词、论文元数据与响应原文，应按小组资料管理。

## 6. 真实性保证范围与恢复 State 的信任边界

新论文的标题、作者、年份与摘要来自数据库 API 解析；LLM 只规划查询。缺失摘要、未知年份、API 报错和空结果都有显式处理，不用示例论文填充。这能避免本模块把 LLM 生成的论文混入检索结果，但数据库收录也不代表论文已同行评议、结论正确或适合直接引用。

`--input` 恢复的 `papers` 被视为调用方提供的历史 Search 输出。模块检查标题/作者和官方来源 URL 形状，不会对每条旧论文重新请求 API 验证其存在。**一个形似官方的 URL 本身不是论文存在证明。** 手工伪造且格式合规的旧条目不能仅靠此检查识别；恢复时须保留并核对上轮真实 API 审计、原始响应，不能把任意 JSON 或模型生成的论文列表当成可信 State。恢复记录没有当前实例的内部证据时，会标记 `existing_state`、`api_reverified: false` 并给出提示。

对 Analyst/Writer 的引用可增加成员校验：

```python
from research_assistant.agents.search import validate_paper_references

validate_paper_references(report_references, state["papers"])
```

该函数接受论文**完整标题或 URL**的字符串列表；每项必须属于当前 `papers`，否则抛出 `ValueError`。它不解析 BibTeX/DOI 引用，不证明某篇论文支持某条科学结论。Reader 要保留原文证据，Critic 要检查结论与证据对应，Writer 要实际调用此类约束；不能因为提供了工具，就宣称所有下游节点已经杜绝编造引用。

## 7. 验证与交接验收

离线测试与联网检索分开记录。离线 Provider/模型样例均使用 `MOCK_ONLY` 标识；官方形状 URL 只用于测试格式、身份与接口，不能作为真实 API 检索成功的证据。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_search.py
.\.venv\Scripts\python.exe -m pytest -q
```

Search 入口测试覆盖接口与 JSON、输入不变、非法配置、中英文问题、查询预算、模型错误回退、各类去重、年份/关键词/相关性/Top-K、Critic 完整列表保留、来源校验、空结果、部分/整体失败、审计归档，以及真实 LangGraph 两轮反馈。适配器与传输层测试进一步检查官方响应解析和网络故障边界。离线通过说明代码在这些可控条件下满足契约，不表示当前网络可访问数据库。

初版真实检索在北京时间 **2026 年 10 月 15 日 11:41** 执行，arXiv 连接/读取超时、Semantic Scholar 返回 HTTP 429，Crossref 成功，整体状态为 `partial`，最终返回 5 篇。11:42 的第二轮使用人工填入的 Critic 补搜查询，真实请求 Crossref，保留旧 5 篇并新增 3 篇，共返回 8 篇。第二轮证明补搜协议可用，**不是正式 Critic Agent 自动运行的证明**。随后增加 arXiv 路由配置；**当天12:08 的两次 arXiv 官方 API 请求全部成功，取得 20 条、选入 5 篇**，详见 [arXiv 历史验收](MEMBER2_ARXIV.md)。10月17日受控 arXiv API 请求曾返回 HTTP 429，详见 [限流更新](MEMBER2_RATE_LIMIT.md)。**10月18日北京时间00:06左右再次只请求一次官方 API，约13.35秒取得5条有效记录、选入3篇，原始响应哈希及标题、作者、年份、摘要核对通过。** 这些结果均是各自时点的实测，不能保证未来持续可用。当前默认保持 OpenAlex；比较结果、配额说明和验收方法见 [OpenAlex 更新](MEMBER2_OPENALEX.md)。

仓库内的[初版验收记录](MEMBER2_ACCEPTANCE.md)、[Crossref 首轮真实录制](../examples/fixtures/search_recording/search_round1.json)及其[原始响应说明](../examples/fixtures/search_recording/README.md)可用于核对与离线复现；arXiv 和 OpenAlex 各有独立录制目录。完整首轮/补搜结果、测试日志与10月18日复测证据另在本地交付中留档，不依赖这些本机目录才能运行仓库。将来重新运行时可能得到不同数据库内容或网络状态；不能将历史成功解释为当前所有来源可用。

### 使用归档的真实响应离线重放

```powershell
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/search_replay.json
```

默认读取 `examples/fixtures/search_recording_openalex/search_round1.json` 和该目录下的 `raw`。arXiv 历史录制保留在相邻 `search_recording_arxiv`，Crossref 历史录制保留在 `search_recording`，可用 `--input` 和 `--raw-dir` 显式选择。重放先核验原始响应字节的 SHA-256，再使用相同请求匹配、适配器、筛选与 Search 节点重新执行，比较结果是否与录制的完整论文 JSON 相同，成功时输出 `verified_equal: true`。没有录制的请求不会联网补充；重放不会新请求 API 或模型，不应标为“又检索成功一次”。这个入口只接受没有已有论文的首轮录制；真实跨轮补搜使用 `examples.search_demo --input`。

这是历史真实 API 结果的可复现演示，与虚构 `MOCK_ONLY` 单元测试不同。二者都不等于新的联网运行。原始文件缺失、哈希不符或当前实现与历史结果不一致时会显式失败，不能以旧的预计算结果掩盖失败。

交给成员 1/3/5/6 前，建议按以下顺序验收：

1. 运行离线测试，确认原有路由、Analyst 与公共模型配置没有回归。
2. 运行 `--plan-only`，检查主题、问题与补搜优先级符合本次调研范围。
3. 执行小预算真实查询，保存结果、逐轮审计和 `raw` 响应；人工抽查入选标题、作者、链接与原始 API 返回一致。
4. 用上次结果通过 `--input` 补搜，检查旧论文保留、跨轮去重和新增计数；验证显式条件变化时的剔除说明。
5. 将工厂生成的 Search 节点接入 Graph，Reader 使用完整列表，Critic 提供补搜查询，Writer 校验引用并保留科学结论的证据边界。

建议小组汇报展示一份真实查询计划、一个可回溯论文条目、一条去重/筛选记录及一次 Critic 补搜。若现场无法联网，可展示之前已归档的真实响应并明确其检索时间；离线 MOCK_ONLY 演示需明确标识。
