# 成员1统一数据接口

> 原则：所有 Agent 的函数签名统一为 `node(state: ResearchState) -> dict`，只返回自己更新的字段。
> 所有跨 Agent 数据必须可 JSON 序列化；不要出现某成员给 List、下一成员私自改成 DataFrame 的情况。

## 1. 总体 State

```python
ResearchState = {
    "topic": str,
    "research_scope": str,
    "research_questions": list[str],
    "search_directions": list[str],
    "search_keywords": list[str],
    "research_plan": list[str],
    "papers": list[Paper],
    "paper_analysis": list[PaperAnalysis],
    "method_summary": ResearchLandscape,
    "critic_result": CriticResult,
    "critic_round": int,
    "max_critic_rounds": int,
    "termination_reason": str,
    "final_report": FinalReport | str,
}
```

## 2. Coordinator -> Search

Search Agent 读取：

- `topic`
- `research_questions`
- `search_directions`
- `search_keywords`
- 如果是 Critic FAIL 后的再次检索，还应读取 `critic_result.new_search_queries`

Search Agent 写回 `papers`，每篇格式：

```json
{
  "title": "...",
  "authors": ["..."],
  "year": 2025,
  "abstract": "...",
  "url": "...",
  "source": "arxiv",
  "relevance_score": 0.91
}
```

**重要：重新检索时，Search Agent 应将“已有 papers + 新结果”统一去重后再写回完整列表，而不是只写增量。**

## 3. Search -> Reader

Reader 读取 `papers`，写回 `paper_analysis`：

```json
{
  "paper_title": "...",
  "problem": "...",
  "motivation": "...",
  "method": "...",
  "datasets": ["..."],
  "metrics": ["..."],
  "main_results": "...",
  "contributions": ["..."],
  "limitations": ["..."]
}
```

## 4. Reader -> Analyst（成员4）

成员4已实现 `research_assistant/agents/analyst.py` 中的 `analyst_node(state) -> dict`，
负责论文分类、方法对比和技术路线总结，只返回 `{"method_summary": ...}`。

**给成员3：输入约定**

- 返回 `{"paper_analysis": [...]}`，每篇沿用第3节的格式。
- `paper_title`、`problem`、`motivation`、`method` 为必填字符串；论文标题与
  `papers.title` 保持一致。`method` 尽量说明输入模态、融合方式和主干模型。
- `datasets`、`metrics`、`contributions`、`limitations` 使用字符串列表，缺失填 `[]`，
  不要编造内容。
- 补充论文后返回完整分析列表。Analyst 会结合研究问题重新分析；需要总结时间演进时，
  从 `papers.year` 读取已知年份。

**给成员5：输出约定**

读取 `state["method_summary"]`，仍使用原有 `ResearchLandscape` 格式。以下是格式
示例，`Paper A` 仅为占位标题：

```json
{
  "categories": [
    {"name": "Cross Attention", "description": "按融合机制分类", "papers": ["Paper A"]}
  ],
  "comparison_table": [
    {"paper": "Paper A", "input": "时间序列与文本", "fusion": "Cross Attention", "backbone": "Transformer", "dataset": "输入材料未提供", "limitation": "输入材料未提供"}
  ],
  "evolution": [],
  "summary": "该方法通过跨模态注意力实现交互。（依据：Paper A）\n证据缺口：缺少数据集、局限和技术演进证据。"
}
```

- `categories` 给出分类及对应论文；`comparison_table` 每篇论文一行。
- 对比表中的数据集和局限直接取自 Reader，缺失时标为“输入材料未提供”。
- `evolution` 为字符串列表，`summary` 为总结文本，结论附支持论文标题；证据不足
  时演进列表可以为空，证据缺口写在 `summary` 中。
- Analyst 已检查引用标题和论文覆盖情况，结论是否确有证据仍交给 Critic 审核。

没有阅读材料时返回空分类、空对比表、空演进列表和“证据不足”的总结。

## 5. Analyst -> Critic

Critic 读取：

- `papers`
- `paper_analysis`
- `method_summary`
- `research_questions`

写回 `critic_result`：

```json
{
  "decision": "PASS",
  "feedback": [],
  "evidence_gaps": [],
  "missing_topics": [],
  "unsupported_claims": [],
  "new_search_queries": []
}
```

若 `decision = "FAIL"`，Graph 自动回到 Search；Search 应优先使用 `new_search_queries` 做补充检索。

成员5已实现 `research_assistant.agents.critic.critic_node`，仅写回 `critic_result`；
`create_critic_node(model)` 可注入结构化模型。确定性来源/覆盖缺口直接 FAIL，不调用
模型；结构完整时调用共享客户端。无阅读证据时返回带建议和查询的 FAIL。格式错误、
冲突输入、模型异常和矛盾输出会明确报错，调用方不能把异常当作 PASS。

- PASS：`evidence_gaps`、`missing_topics`、`unsupported_claims`、`new_search_queries` 均为空。
- FAIL：至少一类问题非空，同时必须有 `feedback` 与 `new_search_queries`。
- Critic 检查全部当前输入；分类和对比表必须覆盖全部阅读论文，引用可追溯到 Search。
- 对比表的 `dataset` / `limitation` 沿用成员4从 Reader 拼接的原文，缺失使用“输入材料未提供”。
- Graph 单独递增轮次；达到上限不修改审核结论。Search、Reader、Analyst 需用新材料
  返回完整结果。正式 Search/Writer 未接入前，可用 `examples.critic_mock_demo` 验证闭环。

成员5的评价标注和运行历史保存在外部 JSON，不改变共享 State。格式、真实引用核验
与 With/Without 消融协议见 [MEMBER5.md](MEMBER5.md)。

## 6. Critic -> Writer

当 `decision = "PASS"` 时进入 Writer。Writer 读取前面所有结果并写回：

```json
{
  "title": "...",
  "markdown": "# Research Report ...",
  "references": ["真实论文1", "真实论文2"]
}
```

如果 Critic 连续失败达到 `max_critic_rounds`，系统为避免死循环仍进入 Writer，同时 State 中会有：

```json
{"termination_reason": "max_critic_rounds"}
```

Writer 应在报告中明确标注“审核未完全通过”，不能把未证实结论写成确定事实。
