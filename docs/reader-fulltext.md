# P2 独立全文提取层

> 当前状态与最新测试见 [reader-status.md](reader-status.md)；本页测试数字和“未验收”记录为对应开发阶段快照。换机配置及运行风险见 [reader-operations.md](reader-operations.md)。

2026-10-17：已实现 opt-in 内部接口，默认 reader_node 仍只分析摘要。
本阶段不下载论文、不合入 main、不与其他成员联调。共享 Schema、State、Graph 不变。

## 数据流与调用

```python
from research_assistant.reader_materials import prepare_paper_materials
from research_assistant.reader_fulltext import analyze_fulltext_materials

if __name__ == "__main__":
    batch = prepare_paper_materials(papers, title_to_local_path)
    result = analyze_fulltext_materials(
        papers, batch["materials"], abstract_analyses=existing_abstract_analyses,
    )
```

返回 `paper_analysis` 和 `details`。前者为原有 PaperAnalysis 字典列表，覆盖当前有效
论文；后者为 Reader 内部明细，不直接返回到共享图节点。调用方需自行保留 P1 批次级
issues；P2 接收并保留每篇材料的 issues。缺少材料仍返回一条分析，不自行触发摘要调用。

默认 LLMChunkAnalyzer 使用 Reader 的配置和禁用开关，结构化输出为本地
ChunkExtraction（claims 列表）；测试可用 analyzer_factory 注入 analyze(chunk) 分析器。
每条 claim 包含 field、value、quote：字段限于现有八个内容字段；最多32条，value 和
quote 各不超过2000字符。标题由代码回填，不交给模型决定。

每轮在任何模型调用前检查全部材料的标题对应、重复项、页码和块范围。块文本必须等于
对应清洗后页文本的 `[start:end]`。未知或重复材料标题报 ValueError；论文去重及冲突
沿用 P0。未声明的论文和摘要结果不得混入当前批次。

## 证据与合并规则

- 按页码、块起始位置和块序号顺序处理，传给模型的用户材料仅为当前块文本。
- quote 必须非空，先匹配精确子串；失败时仅折叠连续空白后匹配，保持词/数字边界。
  不删除全部空白，不改标点、数字、大小写、连字或连字符。仍不匹配则丢弃并记录
  invalid_evidence。evidence.quote保存原文片段，quote_match为exact或whitespace_normalized。
- 每条候选事实记录页码、块序号、块范围 start/end，以及 quote_start/quote_end：
  后两者是原句在清洗后页文本中的字符范围，end 不包含在内。重复原句取块内首次出现。
  重叠块中的相同值去重，证据记录可以保留多个出处。
- 每个字段有全文结果时使用全文结果；字符串字段将不同值以中文分号按来源顺序串联，
  列表字段按来源顺序去重。不同描述不自动判断谁正确，不生成额外的 LLM 综合结论。
- 没有全文值时使用调用方提供的对应摘要字段，否则为空。field_sources 明确区分
  fulltext、abstract、empty；不要将摘要回退字段说成来自 PDF。
- details.status：有接受的全文事实且无问题为 ok；有全文事实且存在问题为 partial；
  没有接受事实为 fallback。ok 也不表示所有字段完整、整篇内容完整或结论已审查。
- 原始 partial 材料保留 partial_material 标记；失败或无块记录 no_fulltext_chunks。
  模型不可用、可恢复异常或无效结构输出记录 chunk_analysis_failed 后继续；编程错误
  继续抛出。没有可用事实时完整保留所提供的摘要分析。
  预期的结构化输出拒绝、内容过滤及长度截断异常也明确纳入此降级路径。

引句存在是文本对应检查，不能证明 value 语义正确、引句足够支持概括、材料确实属于
所映射论文或论文内容真实。真实文献质量和 Critic 审核仍待验收。相互冲突的全文描述
默认仍并列保留；现可显式启用下节的受证据约束的语义协调，真实语义质量仍待验收。

## 可选语义协调（2026-10-18）

独立调用设 `analyze_fulltext_materials(..., reconcile=True)`，或统一入口传
`fulltext_options={"reconcile": true}`（JSON）/ `{"reconcile": True}`（Python）。
默认 False，保持原有合并行为，不额外调用模型。CLI 沿用同一 fulltext_options。
下载入口也支持这些选项，不改变 Search 或任何共享契约。

仅在同一论文的字符串字段拥有多个不同全文候选值时触发，每篇最多一次协调调用。
列表字段继续按来源顺序去重，不由协调器删改。不同候选不一定矛盾，也可能是互补细节。
模型收到字段候选值及已通过引句匹配的证据；只允许返回字段、决定和候选编号：

- compatible：必须引用该字段全部候选，代码按原来源顺序保留。
- select：必须引用一个已有候选，仅在证据明确适用性时选择。
- abstain：编号为空，无法协调时使用该字段的摘要回退，没有摘要则为空。

代码要求每个待协调字段恰好一个决定，拒绝未知/重复字段、越界/重复编号、布尔或字符串
编号，以及额外的新事实字段。所有决定验证完成后才应用；无效输出或可恢复调用失败
对本篇全部待协调字段回退，记录 reconciliation_failed，不退回到潜在冲突的简单拼接。
明确弃权记录 reconciliation_abstained。其他字段的已提取事实不受影响，编程错误仍抛出。

details.reconciliation 保留状态与决定；候选 evidence 全部保留便于审计，其中可能有
未被最终选择的候选。决定中的编号是对应字段去重后候选的来源顺序，从0开始。
field_sources 标明最终字段来自全文、摘要或空值。所有全文候选都被弃权或拒绝时，
status=fallback，不把仅保留审计候选说成成功的全文合并。

直接 P2 接口可传 reconciler_factory 注入提供 analyze(candidates) 的测试分析器。
统一入口的同名工厂参数也可注入；默认采用 Reader 本地结构化模型适配器，遵守
READER_USE_LLM。统一入口对 reconciliation 阶段计入消息/Schema、上下文、输出及
整批调用预算，禁用客户端自动重试；预算不足会在构造协调器前拒绝并保守回退。
直接 P2 接口没有这层整批预算；需费用约束时使用 run_reader 或 run_reader_with_downloads。
协调请求包含候选证据，可能超过上下文预算；不会静默截断证据以强行调用。

此机制约束来源和输出，不保证模型能正确判断矛盾、引句能支持候选概括或候选代表
论文最终结论。真实模型的判断质量仍需人工标注验收；没有执行真实协调模型请求。

## 输入预算与限制

默认每篇最多100块、单块6000字符、块文本累计100,000字符（重叠也计数）。超任一预算
整篇不调用模型，记录 input_budget_exceeded，并保留摘要，不悄悄截断或只读前几块。
参数须为正整数。预算按篇计算，没有批次总调用费用限制；最多每篇100次顺序调用，
不含客户端重试；启用 reconcile 时每篇可能再调用一次协调器。
单块不再递归切分，由调用方在 P1 调整分块尺寸。

字符预算不是精确 Token 计数或模型上下文保证，未加入模型专用 tokenizer、完整消息
Token 计数或输出 Token 预算。真实模型上下文上限和成本控制仍需后续完善。
上句描述P2直接接口；现在可使用 [统一 Reader 入口](reader-pipeline.md) 对两阶段添加
提示/Schema计数、输出预留与整批调用预算，支持显式Tokenizer。未配置Tokenizer时仍是估算。
生成内容仅由输出 Schema 约束规模，尚未验证真实提供方对该 Schema 的兼容性。

## 离线验收

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_fulltext_demo
```

预期：SYNTHETIC Paper 的 method 为 Synthetic method A，明细保留第1页原句，
其他字段为空；命令显式注入合成分析器，不需要凭据，不调用真实模型。
该命令已运行符合预期，不代表真实科研提取质量。

测试覆盖全文字段合并、摘要保留、重复值、无效引句、单块失败、部分材料、预算预检、
无效材料预检、禁用模型、编程错误、当前列表替换和实际合成 PDF 的 P1→P2 流转。
最终完整离线回归为86 passed（18.95秒），其中P2新增16项；git diff --check通过。
真实模型、真实 PDF 版式质量、网络来源和跨成员联调仍待完成。

2026-10-18 语义协调增量验证：完整离线回归 185 passed（51.61 秒），比上一轮
新增22项，覆盖已有候选选择/兼容/弃权、非法编号与字段、可恢复失败与编程错误、
精确引句位置、预算/上下文拒绝、禁用开关及统一入口。没有真实协调模型请求。
此前网络来源待办已部分完成为 arXiv 官方 PDF 获取，其他来源仍待扩展。
