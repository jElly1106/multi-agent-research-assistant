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
