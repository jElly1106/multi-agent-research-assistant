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

## 4. Reader -> Analyst

Analyst 读取 `paper_analysis`，写回 `method_summary`：

```json
{
  "categories": [
    {"name": "Cross Attention", "description": "...", "papers": ["Paper A"]}
  ],
  "comparison_table": [
    {"paper": "Paper A", "input": "...", "fusion": "...", "backbone": "...", "dataset": "...", "limitation": "..."}
  ],
  "evolution": ["Traditional TS", "Transformer", "Foundation Model", "Multimodal Foundation Model"],
  "summary": "..."
}
```

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
