from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

from ..schemas import CoordinatorOutput
from ..state import ResearchState

load_dotenv()


SYSTEM_PROMPT = """你是科研调研系统中的 Coordinator Agent。
你的任务不是直接写综述，而是把用户给出的研究主题拆成后续 Agent 可以执行的计划。
必须输出：
1) research_scope：清晰定义调研范围；
2) research_questions：3~5 个可回答的研究问题；
3) search_directions：需要重点检索的方向；
4) search_keywords：适合文献检索的关键词/查询短语；
5) research_plan：从检索、阅读、分析、Critic 审核到最终报告的步骤。
要求问题具体、可检索、不要编造论文或引用。
"""


def _fallback_output(topic: str) -> CoordinatorOutput:
    """没有 API Key 时用于框架联调；不是最终科研结论。"""
    normalized = topic.strip().lower()
    if "multimodal time series forecasting" in normalized:
        return CoordinatorOutput(
            research_scope=(
                "围绕多模态时间序列预测展开，重点关注时间序列与文本、事件、图像或知识等外部模态的融合，"
                "比较主要建模路线、融合机制、代表性方法及其局限。"
            ),
            research_questions=[
                "目前 Multimodal Time Series Forecasting 有哪些主要技术路线？",
                "时间序列与文本融合主要采用哪些方法？",
                "现有方法的主要局限是什么？",
            ],
            search_directions=[
                "Multimodal Time Series Forecasting 总体方法",
                "Time Series + Text / Event 等跨模态融合",
                "Cross Attention、Contrastive Learning 与 LLM-based Fusion",
                "现有方法的实验设置、数据集、指标与局限",
            ],
            search_keywords=[
                "multimodal time series forecasting text",
                "time series language model",
                "time series text fusion",
                "multimodal temporal forecasting",
                "cross attention time series text",
                "LLM multimodal time series forecasting",
            ],
            research_plan=[
                "明确主题边界与研究问题",
                "由 Search Agent 基于研究问题生成查询并检索真实论文",
                "对检索结果去重、筛选并保留 Top-K 相关论文",
                "由 Reader Agent 结构化抽取问题、方法、数据集、结果、贡献与局限",
                "由 Method Analyst Agent 完成论文分类、方法对比和技术路线总结",
                "由 Critic Agent 审核证据、遗漏和过度推断；FAIL 时生成补充检索需求",
                "审核通过后由 Writer Agent 生成可追溯到真实论文的最终报告",
            ],
        )

    return CoordinatorOutput(
        research_scope=f"围绕“{topic}”开展聚焦型科研调研，界定核心问题、主要方法、实验评价与现有局限。",
        research_questions=[
            f"“{topic}”当前有哪些主要研究路线？",
            f"“{topic}”中不同方法的核心思想与差异是什么？",
            f"“{topic}”常用哪些数据集、评价指标或实验设置？",
            f"“{topic}”现有工作的主要局限与潜在研究方向是什么？",
        ],
        search_directions=[
            f"{topic} survey / review",
            f"{topic} representative methods",
            f"{topic} datasets metrics benchmark",
            f"{topic} limitations future directions",
        ],
        search_keywords=[
            topic,
            f"{topic} survey",
            f"{topic} review",
            f"{topic} method",
            f"{topic} benchmark",
        ],
        research_plan=[
            "明确研究范围与问题",
            "检索并筛选真实相关论文",
            "结构化阅读论文",
            "分类并比较主要方法",
            "Critic 审核证据充分性与遗漏",
            "必要时补充检索并再次审核",
            "生成最终科研调研报告",
        ],
    )


def _invoke_llm(topic: str) -> CoordinatorOutput:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 langchain-openai，请先 pip install -r requirements.txt") from exc

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model_name = os.getenv("LLM_MODEL", "").strip()
    if not api_key or not model_name:
        raise RuntimeError("使用 LLM 时必须设置 OPENAI_API_KEY 和 LLM_MODEL")

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": api_key,
        "temperature": 0.2,
    }
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url

    llm = ChatOpenAI(**kwargs)
    structured_llm = llm.with_structured_output(CoordinatorOutput)
    return structured_llm.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", f"研究主题：{topic}"),
        ]
    )


def coordinator_node(state: ResearchState) -> dict[str, Any]:
    topic = (state.get("topic") or "").strip()
    if not topic:
        raise ValueError("ResearchState.topic 不能为空")

    use_llm = os.getenv("COORDINATOR_USE_LLM", "1").strip() != "0"
    if use_llm and os.getenv("OPENAI_API_KEY", "").strip() and os.getenv("LLM_MODEL", "").strip():
        output = _invoke_llm(topic)
    else:
        output = _fallback_output(topic)

    return output.model_dump()
