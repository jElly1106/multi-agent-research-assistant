# Multi-Agent Research Assistant — 文献检索、方法分析与 Critic 评价

项目目标：根据研究主题完成文献检索、结构化阅读、方法分析、Critic 审核与报告生成。
当前已交付成员1基础框架、成员2 Search Agent、成员4 Method Analyst、成员5 Critic 与系统评价；成员3、6仍待接入，尚未形成真实文献端到端系统。

| 模块 | 当前状态 |
|---|---|
| 成员1：Graph、共享 State、Coordinator、路由 | 已实现；Coordinator 支持模型调用和无配置时的模板计划 |
| 成员2：Search Agent | 已实现；OpenAlex（默认）/ arXiv / Semantic Scholar / Crossref，查询生成、筛选去重、Top-K、Critic 补搜及来源审计 |
| 成员4：Method Analyst | 已实现；支持分类、对比、技术路线归纳、引用校验与独立真实调用 |
| 成员5：Critic、系统指标、消融实验 | 已实现；包含证据审核、补充查询、独立评价标注与离线成对演示 |
| 公共模型客户端 | Coordinator、Analyst 和 Critic 共用，支持 Responses / Chat Completions |
| 成员3、6：Reader、Writer | 当前仅有 demo stub，等待正式实现接入 |
| 前端、PDF 解析、真实系统质量实验 | 尚未实现；Search 独立检索已验证，模拟流程验证不代表真实质量实验 |

**`main.py` 仍注入五个 demo 节点（包括 demo Analyst）；配置密钥不会自动替换它们。**
其中 Coordinator 可按配置调用真实模型。demo 论文和报告均不能当作科研结果。

- 运行与配置：本文。
- 跨成员数据契约：[INTERFACES.md](INTERFACES.md)。
- 已交付内容、验证记录及汇报提纲：[REPORT.md](REPORT.md)。
- 成员5完整交付、指标口径、消融复现与真实评测协议：[MEMBER5.md](MEMBER5.md)。
- 成员2接入与运行入口：[docs/MEMBER2_HANDOFF.md](docs/MEMBER2_HANDOFF.md)。
- 成员2需求对照、来源选择与历史验收：[docs/MEMBER2_SEARCH.md](docs/MEMBER2_SEARCH.md)、[docs/MEMBER2_OPENALEX.md](docs/MEMBER2_OPENALEX.md)、[docs/MEMBER2_ARXIV.md](docs/MEMBER2_ARXIV.md)、[docs/MEMBER2_RATE_LIMIT.md](docs/MEMBER2_RATE_LIMIT.md)。

## 成员2：文献检索快速运行

在下面的虚拟环境安装完成后，先规划关键词（不联网、不调用模型）：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo '多模态时间序列预测' --question '时间序列如何融合文本信息？' --plan-only
```

真实小规模检索（默认只查 OpenAlex，本次公开 API 实测无须密钥）：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --top-k 3 --max-queries 1 --results-per-query 5 --year-from 2020 --output output/search_result.json --audit-dir output/search_audit
```

省略 `--source` 时仅使用 `openalex`。其他来源可显式选择，例如 `--source arxiv`，或 `--source openalex --source crossref`；记录保留各自来源标识。2026-10-17 的替代来源实测中，OpenAlex 与 Crossref 返回 HTTP 200，Semantic Scholar 返回 HTTP 429，DBLP 连接异常；当天 arXiv 受控请求也曾返回 HTTP 429。北京时间 **2026-10-18 00:06 左右**，arXiv 官方 API 的单次新请求成功，约13.35秒取得5条记录、选入3篇，并核对原始响应和入选元数据。该次成功证明当时可用，不能保证后续持续可用，也不能确定此前429的具体原因；当前默认来源仍为 OpenAlex。OpenAlex 的本次响应提示匿名访问使用共享 IP 免费配额；本实现没有 OpenAlex 密钥支持，不保证无密钥访问始终可用。

直接选择 arXiv 的小规模真实查询：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --source arxiv --top-k 3 --max-queries 1 --results-per-query 5 --timeout 20 --max-retries 0 --output output/arxiv_result.json --audit-dir output/arxiv_audit
```

arXiv 的路由参数仍为 `--arxiv-proxy-mode auto/direct/system`，只作用于显式启用的 arXiv 请求。不会修改 Windows 全局代理，不关闭 TLS 验证。HTTP 429 会立即停止该来源本轮请求，不自动重试或切换路线，并保存服务端等待要求；缺少有效等待头时给出标为本地策略的300秒建议，不保证到时恢复。规则检索默认不请求 LLM；只有显式设置 `--use-llm` 才尝试使用已有模型配置生成查询。新论文元数据只从实际 API 响应解析，缺失字段不会由模型补造。

包内默认提供已归档的真实 OpenAlex API 响应离线重放：

```powershell
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/search_replay.json
```

重放会核对原始字节 SHA-256，并通过同一套适配器、去重筛选及排序代码，检查选入论文与录制结果完全一致。它不会发起新检索，录制时间与来源限制见 fixture 说明。人工补搜、完整参数与 Graph 接入见成员2文档。

## 项目结构

```text
multi-agent-research-assistant/
├─ main.py
├─ requirements.txt
├─ requirements-dev.txt
├─ .env.example
├─ INTERFACES.md
├─ REPORT.md
├─ examples/
│  ├─ analyst_mock_demo.py
│  ├─ analyst_live_demo.py
│  ├─ search_demo.py
│  ├─ search_replay_demo.py
│  ├─ critic_mock_demo.py
│  ├─ critic_live_demo.py
│  ├─ critic_ablation_demo.py
│  ├─ evaluate_run.py
│  └─ fixtures/
│     ├─ analyst_mock.json
│     ├─ search_recording_openalex/
│     ├─ search_recording_arxiv/
│     └─ search_recording/
├─ docs/
│  ├─ MEMBER2_HANDOFF.md
│  ├─ MEMBER2_SEARCH.md
│  ├─ MEMBER2_OPENALEX.md
│  ├─ MEMBER2_ARXIV.md
│  ├─ MEMBER2_RATE_LIMIT.md
│  └─ MEMBER2_ACCEPTANCE.md
├─ research_assistant/
│  ├─ graph.py
│  ├─ state.py
│  ├─ schemas.py
│  ├─ llm.py
│  ├─ evaluation.py
│  ├─ ablation.py
│  ├─ demo_stubs.py
│  ├─ agents/
│  │  ├─ analyst.py
│  │  ├─ critic.py
│  │  ├─ coordinator.py
│  │  └─ search.py
│  └─ search/
│     ├─ config.py
│     ├─ keywords.py
│     ├─ models.py
│     ├─ providers.py
│     ├─ openalex.py
│     ├─ crossref.py
│     ├─ ranking.py
│     └─ transport.py
└─ tests/
   ├─ test_analyst.py
   ├─ test_llm.py
   ├─ test_critic.py
   ├─ test_evaluation.py
   ├─ test_routing.py
   ├─ test_search*.py
   ├─ test_arxiv_routing.py
   └─ test_rate_limit_diagnostics.py
```

## 安装与运行入口

Python 要求为 3.10 或更新版本；本项目当前验证环境为 Python 3.12。在项目根目录运行：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

| 入口 | 用途 | 是否调用真实模型 |
|---|---|---|
| `python main.py "研究主题"` | 成员1 Graph 编排演示 | 仅 Coordinator 可能调用；其余五个节点均为 stub |
| `python -m examples.search_demo "研究主题"` | 成员2真实文献检索；默认 OpenAlex | 默认不调用模型；显式 `--use-llm` 才生成模型辅助查询 |
| `python -m examples.search_replay_demo` | 成员2真实响应离线回放 | 否；也不访问论文 API |
| `python -m examples.analyst_mock_demo` | 成员4离线样例，使用预设模型响应 | 否，即使本地已配置密钥 |
| `python -m examples.analyst_live_demo` | 成员4真实分析，默认读取模拟论文 | 有效非空输入时调用真实 Analyst |
| `python -m examples.critic_mock_demo` | 成员5审核反馈闭环，全部使用模拟材料与预设响应 | 否 |
| `python -m examples.critic_live_demo --input state.json` | 正式 Critic 独立审核 | 结构完整时调用真实模型 |
| `python -m examples.critic_ablation_demo --output output/critic_ablation.json` | 成员5模拟消融与评价公式验证 | 否 |
| `python -m examples.evaluate_run --input state.json --annotations labels.json` | 评价保存的 State，事实判断来自独立标注 | 否 |
| `python -m pytest -q` | 离线自动化测试 | 否；需先安装 `requirements-dev.txt` |

无 API 配置时，主程序中的 Coordinator 使用模板计划。若已配置密钥但希望强制离线
演示，在 macOS/Linux 中运行：

```bash
COORDINATOR_USE_LLM=0 python main.py "Multimodal Time Series Forecasting"
```

PowerShell 中先执行 `$env:COORDINATOR_USE_LLM="0"`，再运行 `python main.py "研究主题"`。
此设置只控制 Coordinator，不会关闭正式 Analyst 的模型调用。

## 其他成员如何接入

成员2已提供 `search_node` / `create_search_node`，成员4已提供 `analyst_node`，成员5已提供 `critic_node`；成员3、6仍需提供 Reader、Writer。各节点签名为：

```python
search_node(state) -> dict
reader_node(state) -> dict
analyst_node(state) -> dict
critic_node(state) -> dict
writer_node(state) -> dict
```

集成时将实际节点传给 Graph。下面是接入示意，Reader、Writer 需由对应成员导入；现有 `main.py` 仍使用 demo 节点：

```python
from research_assistant.graph import build_research_graph
from research_assistant.agents.analyst import analyst_node
from research_assistant.agents.critic import critic_node
from research_assistant.agents.search import search_node

app = build_research_graph(
    search_node=search_node,
    reader_node=reader_node,
    analyst_node=analyst_node,
    critic_node=critic_node,
    writer_node=writer_node,
)
```

详细字段约定见 `INTERFACES.md`。

## 成员4：Method Analyst Agent

已实现 `research_assistant/agents/analyst.py`，读取 Reader 的 `paper_analysis`，
结合 `research_questions`、`research_scope`、Search 的 `papers` 元数据和 Critic
反馈，生成方法分类、逐篇对比表、带论文依据的技术路线及总结。每轮重新分析全部
输入论文，只返回 `{"method_summary": ...}`，兼容现有 `ResearchLandscape`。

### 离线 mock 演示与测试

完成虚拟环境安装并激活后，在项目根目录运行：

```bash
pip install -r requirements-dev.txt
python -m examples.analyst_mock_demo
python -m pytest -q
```

mock 演示不需要 API Key，不请求真实模型。输入与预设模型响应放在
`examples/fixtures/analyst_mock.json`，包括特征拼接、跨模态注意力、对比表示对齐
三篇 `MOCK_ONLY` 论文。**论文、数据集和响应全部为人工构造，不能当作科研结果。**
该演示验证转换和校验逻辑，不证明真实模型的分类或推理质量。

测试包含输入异常、缺失信息、重复论文、虚构引用、遗漏论文、模型异常，以及
LangGraph 中 `FAIL → 补充检索 → 重新分析 → PASS` 的完整两轮流程。

### 接入真实模型与主流程

首次配置时复制 `.env.example` 为 `.env`；已有 `.env` 时直接编辑，避免覆盖本地配置。
项目导入时沿用 Coordinator 的 `.env` 加载逻辑；已有进程环境变量优先于 `.env`。

| 变量 | 含义与默认行为 |
|---|---|
| `OPENAI_API_KEY` | 模型调用必需，密钥只保存在本地 |
| `LLM_MODEL` | 模型调用必需，填写服务商提供的准确模型 ID |
| `OPENAI_BASE_URL` | 可选 API 根地址；留空使用 SDK 默认 OpenAI 服务 |
| `LLM_API` | `chat_completions`（默认）或 `responses` |
| `COORDINATOR_USE_LLM` | 设置为 `0` 时 Coordinator 使用模板计划；其他值允许按配置调用模型 |

Coordinator 缺少密钥或模型名称时使用模板；正式 Analyst 对非空输入缺少配置时会报错。
两者的真实请求失败都不会自动切换成 mock。模型及网关须支持当前 JSON Schema
结构化输出；一次服务测试成功不代表其他模型或服务也兼容。

`LLM_API=responses` 显式使用 Responses 接口；默认 `chat_completions` 使用 Chat
Completions 接口。Coordinator 与 Analyst 共用 `research_assistant/llm.py` 中的
配置。`OPENAI_BASE_URL` 只填写 API 根地址，例如 `https://api.gpt.ge/v1`，不要填写
完整的 `/responses` 路径或末尾中文标点。客户端会自动拼接请求路径。

例如连接支持 Responses 的网关时，配置如下（密钥仅保存在被 Git 忽略的 `.env`）：

```dotenv
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.gpt.ge/v1
LLM_MODEL=gpt-6-luna
LLM_API=responses
```

配置完成后，可单独用三篇模拟论文请求真实 Analyst：

```bash
python -m examples.analyst_live_demo --output output/analyst_live_result.json
```

该命令会实际调用配置的服务；输入仍为 `MOCK_ONLY`，不会使用 fixture 内的预设
模型响应。使用真实 Reader 材料时：

```bash
python -m examples.analyst_live_demo --input path/to/state.json --output output/analyst_result.json
```

输入应为包含 `paper_analysis` 的 State JSON 对象，或 `{"state": ...}` 封装；不能
直接传裸论文数组。完整字段要求见 [INTERFACES.md](INTERFACES.md)。不提供 `--output`
时打印 JSON；提供时保存到指定位置，同名文件会被覆盖。输出外层包含 `notice`、
`model`、`api`、`method_summary`；前三项是演示元数据，节点对 Graph 仍只返回
`method_summary`。结果目录 `output/` 已加入 Git 忽略列表。

Responses 请求使用 JSON Schema 结构化输出，并设置 `store=false`；不强制指定
temperature，以兼容使用默认采样参数的模型。请求失败或输出校验失败时会明确报错。

将正式 Analyst 接入主流程时，按上面的接入示意替换 `demo_analyst_node` 参数。
现有 `main.py` 不会自动启用正式 Analyst，且 demo Reader 不提供真实方法证据。
独立使用时也可直接调用 `analyst_node(state)`。
测试使用 `create_analyst_node(model)` 注入实现了 `invoke(messages)` 的结构化 mock
模型，返回 `AnalystOutput` 或符合它的字典。

### 输入与证据约定

- `paper_analysis` 每项遵循 `PaperAnalysis`，`paper_title` 去除首尾空白后作为关联键。
  完全相同的重复记录合并；同标题不同内容报错，避免静默丢失证据。
- 若提供 `papers`，每篇分析必须匹配其中的标题。可省略元数据进行方法分析，
  但技术演进引用的每篇论文必须具有已知年份；缺失时模型应返回空 `evolution`。
- 分类覆盖全部论文，每篇论文在对比表中恰好出现一次。所有结构化论文引用均检查
  是否来自输入；总结和演进中的结论会附上支持论文的标题。
- 对比表的 `dataset`、`limitation` 直接取自 Reader；未提供则标为“输入材料未提供”。
  模型仅提取 `input`、`fusion`、`backbone`，并被提示不得补造缺失内容。
- 空阅读结果返回“证据不足”，不调用模型。非空输入缺少模型配置、模型请求失败、
  格式或引用校验失败时抛出异常，不用 mock 结果冒充正式分析。
- 引用存在性校验不能证明结论确实受到论文支持；方法提取、分类合理性、文本中的
  事实性及技术演进关系仍需真实样例评估和 Critic 审核。

内部 `AnalystOutput` 使用带 `papers` 的结论对象和严格的对比行格式；输出时转换回
团队约定的 `ResearchLandscape`，不要求成员3、5、6修改接口。

## 成员5：Critic Agent 与系统评价

`research_assistant/agents/critic.py` 已提供 `critic_node(state) -> {"critic_result": ...}`。
先检查来源、引用与论文覆盖，再请求模型审核问题遗漏、证据支持和过度推断。
FAIL 包含问题、修订建议和补充检索查询；PASS 不允许遗留问题。模型异常或矛盾输出
明确报错。Graph 负责轮次上限，达到上限仍保留 FAIL，Writer 应标记“审核未完全通过”。

评价模块分别统计论文有效性、重复率、引用可追溯率、独立核验引用正确率、审核次数、
FAIL 次数和报告问题覆盖率。未核验项为 null，同时报告标注覆盖率；不会把输入中
存在论文标题直接当作真实论文或正确引用。

```bash
python -m examples.critic_mock_demo
python -m examples.critic_ablation_demo --output output/critic_ablation.json
python -m examples.critic_live_demo --input path/to/state.json --output output/critic_result.json
```

前两个入口完全离线。模拟消融验证 `FAIL → 补充检索 → PASS`；论文、模型响应和
评价标签全部为预设，不能证明真实模型质量。真实模型配置沿用上文；Critic 结构完整
输入缺少配置时会报错，结构缺口可直接 FAIL。接口、指标公式、独立标注格式、
真实消融协议与汇报材料见 [MEMBER5.md](MEMBER5.md)。
