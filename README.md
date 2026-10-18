# Multi-Agent Research Assistant — 成员1基础框架

本目录完成“成员1：系统架构 + Coordinator Agent”的核心交付：

- LangGraph 主程序 / 总体 Graph
- ResearchState 定义
- Coordinator Agent
- Critic 条件路由与反馈循环
- 成员2~6统一数据接口
- 可运行的 demo stub（只用于联调，绝不能当真实论文结果）
- 成员1课程汇报稿与 PPT 提纲

## 项目结构

```text
member1_research_assistant/
├─ main.py
├─ requirements.txt
├─ .env.example
├─ INTERFACES.md
├─ MEMBER1_REPORT.md
├─ research_assistant/
│  ├─ graph.py
│  ├─ state.py
│  ├─ schemas.py
│  ├─ demo_stubs.py
│  └─ agents/
│     └─ coordinator.py
└─ tests/
   └─ test_routing.py
```

## 最快运行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python main.py "Multimodal Time Series Forecasting"
```

默认可不配置 API Key：Coordinator 会使用 fallback 生成示例任务拆解，方便先验证 Graph 编排。

若要让 Coordinator 对任意主题调用 LLM：复制 `.env.example` 为 `.env`，填写 `OPENAI_API_KEY` 与 `LLM_MODEL`。若团队使用 OpenAI-compatible 网关，可同时填写 `OPENAI_BASE_URL`。

## 其他成员如何接入

成员2~6分别实现：

```python
search_node(state) -> dict
reader_node(state) -> dict
analyst_node(state) -> dict
critic_node(state) -> dict
writer_node(state) -> dict
```

然后：

```python
app = build_research_graph(
    search_node=search_node,
    reader_node=reader_node,
    analyst_node=analyst_node,
    critic_node=critic_node,
    writer_node=writer_node,
)
```

详细字段约定见 `INTERFACES.md`。

## Reader 独立实现（成员3）

交付结论、最终测试与基本性能见 [Reader 当前状态](docs/reader-status.md)。

本分支已提供摘要结构化阅读、本地文本型 PDF 准备、显式 arXiv PDF 获取、带引句的
全文提取与合并、可选语义协调，以及调用预算、解析超时、适度并行和内存材料缓存。
Reader 只负责 `paper_analysis`，不改共享 Schema/State/Graph，也不重新检索论文。
`main.py` 仍是 demo 编排，不会因配置模型密钥自动切换到正式 Reader 或其他正式节点。

- 摘要节点：`research_assistant.agents.reader.reader_node`。
- 全文节点：`research_assistant.reader_node.create_fulltext_reader_node`，默认只使用本地
  映射，`download_arxiv=True` 才获取已有 arXiv 论文。
- 独立 API：`run_reader` / `run_reader_with_downloads`，位于 reader_pipeline.py。
- 独立 CLI：`python -m research_assistant.reader_cli --input input.json --output result.json --offline`。
  `--download-arxiv --no-llm` 只获取/解析；不加模型禁用选项时可能调用真实模型。
- PDF 可选依赖：[requirements-reader-pdf.txt](requirements-reader-pdf.txt)，摘要节点不要求安装。

Reader 使用 OPENAI_API_KEY、LLM_MODEL、可选 OPENAI_BASE_URL 和 LLM_API。
READER_USE_LLM=0 明确禁用。已有 DASHSCOPE 变量不会自动映射；如何在进程中复用
百炼配置及输出预算建议见 [独立验收说明](docs/reader-acceptance.md)。不要在仓库写入密钥。

入口和边界：[独立运行](docs/reader-standalone.md)、[全文提取与协调](docs/reader-fulltext.md)、
[预算](docs/reader-pipeline.md)、[arXiv获取](docs/reader-download.md)。
验证事实与尚未覆盖的层次见 [真实数据测试记录](docs/reader-real-data-test.md)；
合成测试或一次模型成功都不代表所有论文和模型的质量保证。
