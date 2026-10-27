# 成员6：Writer、前端和系统展示

更新：2026-10-27。开发分支 `codex/member6-writer-ui`；基于已同步的 `origin/main` (`ad9ec0b`)。

## 已实现

- `research_assistant/agents/writer.py`：`writer_node(state) -> {"final_report": ...}`，只更新该字段。
  对外沿用现有 FinalReport：title、markdown、references；不改变共享接口、Schema、State 或 Graph。
- 默认 Writer 使用公共模型客户端，读取 OPENAI_API_KEY、LLM_MODEL、可选 OPENAI_BASE_URL 和 LLM_API。
  模型只生成有支持论文的背景、逐问题回答和研究建议；报告结构、方法表、审核警告和参考文献由程序生成。
  模型异常、引用未知论文、引用无实质阅读证据的论文、遗漏问题均报错，不静默改用模拟响应。
- `create_writer_node(use_llm=False)` 显式汇编已有材料，不调用 Writer 模型，并标注未逐题生成回答。
  无可用阅读证据时也不调用模型，输出证据不足报告。
- 参考文献保持 Search 原始标题，兼容成员5评价；编号仅用于正文，元数据缺失不补造。
  方法表的数据集和局限直接取 Reader。PASS 不代表 Writer 新文本已审核；FAIL/缺少审核/达到轮次上限均保留警告。
- `research_assistant/member6.py`：调用原 build_research_graph 注入节点，按真实 updates 事件传递进度，支持反馈循环。
- `app.py`：主题输入、模式选择、论文和审核轮次设置、节点状态、论文来源、阅读和方法表、审核反馈、报告下载。
  每次启动清除旧报告和 PDF；失败保留已完成中间状态，但不允许把旧报告当作本次结果。
- `research_assistant/report_export.py`：UTF-8 Markdown、中文 PDF；表格自动换行、重复表头、分页和页码。
  Windows 自动嵌入系统宋体；无该字体时使用 ReportLab 的标准 CJK 字体回退，目标阅读器需支持该字体。
- `research_assistant/member6_cli.py`：完整图运行或已有 State 的独立 Writer 入口。

## 环境与启动

使用项目 Python 3.12 虚拟环境；新机器另需安装测试和可选 PDF 阅读依赖。仅界面/PDF 导出使用：

```powershell
Set-Location 'C:\Users\86152\Desktop\multi-agent-research-assistant'
& .\.venv\Scripts\python.exe -m pip install -r requirements-member6.txt
& .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

浏览器打开 http://127.0.0.1:8501 。默认离线演示，完全不请求论文 API 或模型，不依赖真实密钥。
输入研究主题后点击“开始研究”；报告可下载 Markdown，点击“准备 PDF”后下载 PDF。

命令行离线演示（输出目录必须不存在，不覆盖旧运行）：

```powershell
& .\.venv\Scripts\python.exe -m research_assistant.member6_cli '多模态时间序列预测' --mode demo --pdf --output-dir output/member6-demo
```

演示使用 `examples/fixtures/analyst_mock.json` 中三篇 MOCK_ONLY 论文及阅读结果，正式 Analyst 接受预设合成模型响应；
Coordinator、Search、Reader、Critic 为明确的模拟材料/函数，Writer 显式使用无模型汇编。
它不是六个真实 Agent 的服务验收。报告、界面均保留演示标识；Critic 演示 PASS 不证明科研质量。
原 `main.py` 和 demo_stubs 未修改，旧框架演示仍可运行。

## 真实运行

在运行进程配置模型（不把密钥写进 Git）。现有 `.env` 加载不覆盖进程环境变量。
必须提供 OPENAI_API_KEY、LLM_MODEL；可选 OPENAI_BASE_URL 和 LLM_API。
如果之前为离线测试禁用了节点，应在运行终端显式开启：

```powershell
$env:COORDINATOR_USE_LLM='1'
$env:READER_USE_LLM='1'
& .\.venv\Scripts\python.exe -m research_assistant.member6_cli 'Multimodal Time Series Forecasting' --mode live --top-k 3 --rounds 2 --pdf --output-dir output/member6-live
```

也可在页面选择“真实研究”，确认允许联网/模型调用，再开始。未配置模型时按钮不可用。
配置错误、关闭节点开关或运行异常明确失败；不退回合成科研结果。不显示原始网关异常正文。
真实入口使用正式 Search、摘要 Reader、Analyst、Critic 和 Writer，沿用正式 Coordinator。
Search 每轮最多一个查询、每查询5条候选，Top-K限制新增论文数；默认 OpenAlex，可在页面选其他来源。
Search 默认按规则生成查询，不调用关键词模型；Coordinator、逐篇 Reader、Analyst、Critic、Writer 可调用模型。
最多1–5轮审核，Graph保留FAIL，不把轮次上限当作PASS。轮次/论文数限制不是费用硬上限，模型重试和服务时延仍适用。

当前入口不下载全文，OpenAlex URL 仍为记录页；全文能力由成员3独立入口负责，不能称已完成全文跨成员联调。
尚未执行本次新入口的真实模型或实时论文 API 验收，不能保证提供者兼容性、检索可用性或科学结论正确性。
后续应以小规模真实论文对照原文抽查报告，记录未解决问题，并与成员5评价协议结合。

已有完整 State 单独生成报告：

```powershell
& .\.venv\Scripts\python.exe -m research_assistant.member6_cli --input path/to/state.json --pdf --output-dir output/writer-result
```

此输入接受 State 或 `{"state": ...}`，默认调用真实 Writer；增加 `--compile-only` 可显式只汇编。
Reader 独立 CLI 输出只有 paper_analysis 时，还需由调用方与原 papers、研究问题和方法总结组合成 State。
输出 report.md、state.json，可选 report.pdf；运行失败可能保留已生成文件，退出码及错误状态才是完成判据。

## 验证与局限

新增合成测试覆盖：引用追溯、无证据弃权、逐问题覆盖、未知/未阅读引用拒绝、输入不变、每轮完整替换、
Critic补搜与到上限FAIL、无密钥和禁用开关、模拟模式不调用模型、中文PDF长表与分页、页面生成/PDF/失败清旧结果。
Streamlit/ReportLab 为可选交付依赖，基础环境未安装时相应用例明确跳过；当前本地安装后验证31项通过。
包含正式 Search、Reader、Analyst、Critic、Writer 的合成串联验证，网络和模型边界由测试替身提供。
页面已在本机浏览器验证，中文PDF三页已渲染检查，长表分页用例通过。
最终全仓离线回归：**645 passed（67.24秒）**；无真实模型或实时论文请求，依赖一致性检查通过。
受限沙箱中的页面测试曾停滞，终止该次测试后正常权限复测通过；Reader子进程与最终全仓也采用正常权限。
原 README 使用 Git 已存储的 CRLF，空白检查按 `git -c core.whitespace=cr-at-eol diff --check` 保留其换行约定；
新增文件另查行尾空白，无异常。记录位于 `.venv/test-results/member6-full.log` 和同目录 XML，未加入版本控制。

引用存在性与阅读记录存在性检查不等于语义支持校验。Writer模型的背景/回答/建议仍可能误解输入，
Critic位于Writer之前，因此最终文字仍需人工核验。当前未新增Writer后审核节点，也未更改团队图契约。
报告导出仅支持本模块生成的Markdown子集，不承诺任意外部Markdown的完整排版。
PDF在本机检查通过，不代表所有阅读器/所有字体环境已验收。输出、测试日志和版本清单应保留在Git忽略目录。

## 2026-10-27 合并前复核

- 对照成员分工文档检查 Writer、页面、过程展示和 Markdown/PDF 导出，未发现阻碍成员6合并的问题。
- 成员6测试 **31项全部通过**；显式禁用模型的全仓离线回归 **645 passed（79.47秒）**。
  未设置离线开关时为644通过、1失败：既有 Reader 用例
  `test_default_resolver_respects_disabled_models` 未自行设置 `READER_USE_LLM=0`，
  导致预算断言差异。该用例及 Reader 实现均未修改；复现离线检查时需在测试进程设置
  `READER_USE_LLM=0`、`COORDINATOR_USE_LLM=0`，不必更改本地环境文件。
- `pip check` 与空白检查通过；CLI 离线演示生成 Markdown、State 和三页中文 PDF，
  PDF各页已渲染检查，标题、表格、中文和分页正常。
- 本轮记录位于被忽略的 `output/member6-review-offline-tests.xml` 和
  `output/member6-review-20261027/`，不随代码提交。测试使用正常本地权限；沙箱内页面用例停滞后已终止。
- 未执行真实模型、实时论文检索或全文联调，以上结果仅支持代码与离线功能验收。

## 团队接入

成员1可从 `research_assistant.agents.writer` 直接导入 writer_node，传给现有 build_research_graph。
当前新增入口可先供联调，是否替换原 main.py 由团队统一安排。
共享四文件（INTERFACES.md、schemas.py、state.py、graph.py）未修改。
