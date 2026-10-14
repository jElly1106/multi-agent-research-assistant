# Multi-Agent Research Assistant — 成员1基础框架与成员4方法分析

项目目标：根据研究主题完成文献检索、结构化阅读、方法分析、Critic 审核与报告生成。
当前已交付成员1的基础框架，以及成员4的 Method Analyst；尚未形成真实文献端到端系统。

| 模块 | 当前状态 |
|---|---|
| 成员1：Graph、共享 State、Coordinator、路由 | 已实现；Coordinator 支持模型调用和无配置时的模板计划 |
| 成员4：Method Analyst | 已实现；支持分类、对比、技术路线归纳、引用校验与独立真实调用 |
| 公共模型客户端 | Coordinator 和 Analyst 共用，支持 Responses / Chat Completions |
| 成员2、3、5、6：Search、Reader、Critic、Writer | 目前仅有 demo stub，等待正式实现接入 |
| 前端、真实检索、PDF 解析、系统质量评价 | 当前仓库尚未实现 |

**`main.py` 仍注入五个 demo 节点（包括 demo Analyst）；配置密钥不会自动替换它们。**
其中 Coordinator 可按配置调用真实模型。demo 论文和报告均不能当作科研结果。

- 运行与配置：本文。
- 跨成员数据契约：[INTERFACES.md](INTERFACES.md)。
- 已交付内容、验证记录及汇报提纲：[REPORT.md](REPORT.md)。

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
│  └─ fixtures/analyst_mock.json
├─ research_assistant/
│  ├─ graph.py
│  ├─ state.py
│  ├─ schemas.py
│  ├─ llm.py
│  ├─ demo_stubs.py
│  └─ agents/
│     ├─ analyst.py
│     └─ coordinator.py
└─ tests/
   ├─ test_analyst.py
   ├─ test_llm.py
   └─ test_routing.py
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
| `python -m examples.analyst_mock_demo` | 成员4离线样例，使用预设模型响应 | 否，即使本地已配置密钥 |
| `python -m examples.analyst_live_demo` | 成员4真实分析，默认读取模拟论文 | 有效非空输入时调用真实 Analyst |
| `python -m pytest -q` | 离线自动化测试 | 否；需先安装 `requirements-dev.txt` |

无 API 配置时，主程序中的 Coordinator 使用模板计划。若已配置密钥但希望强制离线
演示，在 macOS/Linux 中运行：

```bash
COORDINATOR_USE_LLM=0 python main.py "Multimodal Time Series Forecasting"
```

PowerShell 中先执行 `$env:COORDINATOR_USE_LLM="0"`，再运行 `python main.py "研究主题"`。
此设置只控制 Coordinator，不会关闭正式 Analyst 的模型调用。

## 其他成员如何接入

成员2、3、5、6提供正式节点；成员4已提供 `analyst_node`。各节点签名为：

```python
search_node(state) -> dict
reader_node(state) -> dict
analyst_node(state) -> dict
critic_node(state) -> dict
writer_node(state) -> dict
```

集成时将实际节点传给 Graph。下面是接入示意，其他四个函数需由对应成员导入：

```python
from research_assistant.graph import build_research_graph
from research_assistant.agents.analyst import analyst_node

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
