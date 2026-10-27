"""Member 6 local Streamlit UI. Run: python -m streamlit run app.py."""
from __future__ import annotations

import json
import time

import streamlit as st

from research_assistant.member6 import LABELS, model_configured, stream_research
from research_assistant.report_export import markdown_bytes, pdf_bytes

st.set_page_config(page_title="科研调研工作台", page_icon="📚", layout="wide")
st.markdown("""<style>
.stApp {background:#f6f7f9;color:#182b45}
.block-container {max-width:1220px;padding-top:2.6rem}
h1,h2,h3 {letter-spacing:-.025em;color:#182b45}
[data-testid="stSidebar"] {background:#eaf0f5}
[data-testid="stMetric"] {background:white;border:1px solid #dce4ed;border-radius:10px;padding:16px}
.desk-label {color:#447384;font-size:12px;letter-spacing:.2em;font-weight:700;margin-bottom:10px}
.desk-intro {color:#5c6c7d;font-size:17px;margin-bottom:24px}
</style>""", unsafe_allow_html=True)
st.markdown('<div class="desk-label">RESEARCH DESK / 研究工作流</div>', unsafe_allow_html=True)
st.title("科研调研工作台")
st.markdown('<div class="desk-intro">提出问题，检查证据，把研究过程整理成可追溯的报告。</div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("运行设置")
    mode_label = st.radio("运行方式", ["离线演示", "真实研究"], key="mode")
    mode = "demo" if mode_label == "离线演示" else "live"
    top_k = st.slider("每轮新增论文上限", 1, 10, 3)
    rounds = st.slider("最多审核轮次", 1, 5, 2)
    sources = st.multiselect("文献来源", ["openalex", "arxiv", "crossref", "semantic_scholar"], default=["openalex"])
    allowed = True
    if mode == "live":
        st.caption("使用本地环境中的模型配置。摘要 Reader 接入；当前入口不下载全文。")
        if not model_configured():
            st.warning("尚未配置模型密钥或模型名称。")
        allowed = st.checkbox("允许本次运行访问论文数据库并调用模型") and model_configured() and bool(sources)
    else:
        st.info("完全离线，使用三篇人工构造论文。展示效果不代表真实研究质量。")
    st.caption("真实运行每轮最多 1 个查询、每查询 5 条候选；模型可能按论文逐篇调用，轮次上限不等于费用上限。")

topic = st.text_input("研究主题", value="Multimodal Time Series Forecasting", placeholder="例如：时间序列与文本信息融合")
start = st.button("开始研究", type="primary", disabled=not allowed or not topic.strip())

if start:
    # Clear previous success immediately; failures must never expose a stale report as current.
    st.session_state.pop("result", None)
    st.session_state.pop("pdf", None)
    st.session_state["events"] = []
    st.session_state["run_mode"] = mode
    st.session_state["failed"] = False
    began = time.monotonic()
    with st.status("正在启动研究流程…", expanded=True) as status:
        try:
            for event in stream_research(topic, mode=mode, top_k=top_k, sources=tuple(sources), max_critic_rounds=rounds):
                state = event["state"]
                number = state.get("critic_round", 0)
                st.write(f"✓ {LABELS[event['node']]}完成 · 审核轮次 {number}")
                next_node = {"coordinator": "search", "search": "reader", "reader": "analyst", "analyst": "critic", "critic": "writer"}.get(event["node"])
                if event["node"] == "critic" and state["critic_result"]["decision"] != "PASS" and not state.get("termination_reason"):
                    next_node = "search"
                if next_node:
                    status.update(label="正在进行：" + LABELS[next_node])
                st.session_state["events"].append({"node": event["node"], "round": number})
                st.session_state["result"] = state
            st.session_state["elapsed"] = time.monotonic()-began
            status.update(label="报告已生成", state="complete", expanded=False)
        except Exception as exc:
            st.session_state["failed"] = True
            # No raw provider exception, key, endpoint response, or source text in public UI.
            status.update(label="运行未完成", state="error", expanded=True)
            st.error(f"运行中断（{type(exc).__name__}）。请检查模型开关、输入、网络或服务权限；已完成步骤保留在下方。")

state = st.session_state.get("result")
if state:
    actual_mode = st.session_state.get("run_mode", "demo")
    if actual_mode == "demo":
        st.warning("当前结果来自离线演示：论文、阅读材料和 Analyst 模型响应均为人工构造。")
    if st.session_state.get("failed"):
        st.error("本次运行未完成，下方为中间结果，尚无可交付报告。")
    elif state.get("critic_result", {}).get("decision") != "PASS" or state.get("termination_reason"):
        st.warning("审核未完全通过，请查看证据缺口及报告中的遗留问题。")
    elif actual_mode != "demo":
        st.success("前序材料审核通过；请继续人工核对最终报告中的结论。")
    columns = st.columns(3)
    columns[0].metric("已选文献", len(state.get("papers", [])))
    columns[1].metric("阅读结果", len(state.get("paper_analysis", [])))
    columns[2].metric("审核轮次", state.get("critic_round", 0))
    report_tab, sources_tab, analysis_tab, review_tab = st.tabs(["调研报告", "论文与来源", "阅读与方法", "审核与过程"])
    with report_tab:
        report = state.get("final_report")
        if report and not st.session_state.get("failed"):
            st.download_button("下载 Markdown", markdown_bytes(report), file_name="research-report.md", mime="text/markdown")
            if st.button("准备 PDF"):
                try:
                    st.session_state["pdf"] = pdf_bytes(report)
                except Exception as exc:
                    st.error(f"PDF 生成失败（{type(exc).__name__}），可先下载 Markdown。")
            if st.session_state.get("pdf"):
                st.download_button("下载 PDF", st.session_state["pdf"], file_name="research-report.pdf", mime="application/pdf")
            st.markdown(report["markdown"], unsafe_allow_html=False)
        else:
            st.info("报告尚未生成。")
    with sources_tab:
        st.dataframe(state.get("papers", []), hide_index=True, width="stretch")
        st.caption("来源 URL 是记录页或 DOI 链接，不一定是可下载的 PDF。")
    with analysis_tab:
        st.subheader("方法比较")
        st.dataframe(state.get("method_summary", {}).get("comparison_table", []), hide_index=True, width="stretch")
        with st.expander("逐篇阅读结果"):
            st.json(state.get("paper_analysis", []))
        with st.expander("方法分类与总结"):
            st.json(state.get("method_summary", {}))
    with review_tab:
        st.json(state.get("critic_result", {}))
        st.dataframe(st.session_state.get("events", []), hide_index=True)
        for warning in state.get("errors", []):
            # Search warnings are source diagnostics; display as text, never HTML.
            st.text(warning)
        st.download_button("保存本次状态", json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name="research-state.json", mime="application/json")
else:
    st.info("选择运行方式并输入主题，即可开始。离线演示不需要 API 密钥。")
    st.markdown("研究规划 → 文献检索 → 结构化阅读 → 方法分析 → 证据审核 → 报告生成")
