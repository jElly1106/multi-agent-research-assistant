# 成员2 Search Agent 交接说明

整理日期：2026-10-18。本文面向小组其他成员，说明检索模块的入口、提交范围与实际验证边界。本次上传已基于包含成员5Critic的最新main（`469a40bb3245f4c3bf45f0772b0aa393a6bc57a9`）合并；保留Critic、系统评价和消融模块。

## 已实现的功能

- 根据主题、研究问题、Coordinator关键词及Critic补搜生成有预算上限的查询。
- 通过OpenAlex、arXiv、Semantic Scholar、Crossref官方API取得真实论文元数据。
- 按DOI、arXiv ID、来源ID及标题作者信息去重，执行年份、关键词、相关性筛选和每轮新论文Top-K。
- 保留符合显式条件的旧论文，返回补搜后的完整列表。
- 保存请求、原始响应SHA-256、候选来源、筛选原因和错误证据；失败时不生成替代论文。

标题、作者、年份和摘要均取自API。LLM仅可显式用于生成检索词。OpenAlex摘要从倒排索引重建；作者优先使用文献原始署名，有差异时保留警告和证据。

## 安装与运行

在克隆后的项目根目录运行。Windows PowerShell示例：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 真实arXiv检索：一次请求，最多5条候选，最终选3篇
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --source arxiv --top-k 3 --max-queries 1 --results-per-query 5 --timeout 20 --max-retries 0 --output output/arxiv_result.json --audit-dir output/arxiv_audit

# 默认来源为OpenAlex；此命令没有指定--source
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --top-k 3 --max-queries 1 --results-per-query 5 --max-retries 0 --output output/openalex_result.json --audit-dir output/openalex_audit

# 默认使用归档的真实OpenAlex响应离线回放，不联网
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/replay.json

# 离线测试
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

规则检索不需要模型密钥。Semantic Scholar可选密钥配置见 `.env.example`，真实密钥不应提交；OpenAlex当前仅实现匿名访问，受共享IP配额影响。

## 对接接口

```python
from research_assistant.agents.search import create_search_node
from research_assistant.search.config import SearchConfig

search = create_search_node(
    config=SearchConfig(sources=("arxiv",), top_k=5, max_queries=1),
    audit_dir="output/search_audit",
)
delta = search({
    "topic": "Multimodal Time Series Forecasting",
    "search_keywords": ["multimodal time series forecasting"],
})
papers = delta["papers"]
```

Graph节点签名为 `node(state) -> dict`。公共Paper保持 `title, authors, year, abstract, url, source, relevance_score` 七字段。OpenAlex公共URL为Work记录页，其实际出版页/PDF地址保存在 `search_audit.candidates[].provenance[]`，Reader应据此获取原文。

`top_k`限制本轮新选论文，上限100；补搜保留的旧论文另外计数。相关性分数为关键词覆盖分，不是学术质量或真实性概率。`--input`接收State或CLI结果JSON，不接收论文PDF；恢复旧列表应保留上轮API原文证据。

## 模块及提交内容

| 路径 | 职责 |
|---|---|
| `research_assistant/agents/search.py` | Search节点、跨轮合并、审计和Graph调用入口 |
| `research_assistant/search/` | 配置、查询规划、四个来源适配、HTTP传输、身份去重与排序 |
| `examples/search_demo.py` | 真实联网命令行入口 |
| `examples/search_replay_demo.py` | 真实API原文的哈希校验与离线回放 |
| `examples/fixtures/search_recording*` | 已归档真实响应；这些文件是回归样例，不是密钥或环境缓存 |
| `tests/test_search*.py`及路由/限流测试 | 离线可控边界和真实录制回归 |
| `README.md`、`INTERFACES.md`、`docs/MEMBER2*.md` | 安装、接口、实际验证和历史诊断 |
| `.env.example` | 可提交的空密钥配置模板 |

## 实际验证与边界

2026-10-17成员2原版本完成341项离线测试，全部通过；依赖检查无冲突。合入最新成员5版本后，2026-10-18完整回归为401项通过。OpenAlex真实调用取得5条并选入3篇，其真实录制为默认离线回放样例。

北京时间2026-10-18 00:06，arXiv官方Export API的一次请求成功：约13.35秒，direct、attempts=1、取得5条有效候选，选入3篇。标题、作者、年份和摘要与保存的Atom响应逐字段对应，SHA-256核验通过。此次成功不证明永久恢复，也不能确定此前429的具体原因。该次真实记录包含在[最新arXiv录制](../examples/fixtures/search_recording_arxiv_20261018/README.md)。

`main.py`仍注入演示节点，其他成员需显式将正式Search节点接入Graph。成员5的正式Critic和评价模块已在main实现，本次保留其内容；Reader、Writer仍待正式接入。检索模块不包含PDF下载或全文解析；额外借助网页搜索工具人工打开出版方页面的过程也不属于本地程序自动功能。

合法零结果、来源不可用和HTTP429分开处理。429会停止该来源本轮请求并给出等待证据，不换路线规避。所有联网情况只代表记录时的实际请求。

完整参数和反馈协议见[Search使用说明](MEMBER2_SEARCH.md)，来源选择和作者策略见[OpenAlex说明](MEMBER2_OPENALEX.md)，其他成员契约见[INTERFACES](../INTERFACES.md)。
