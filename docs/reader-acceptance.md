# Reader 独立真实数据验收准备

当前任务分支的交付结论见 [Reader 当前状态](reader-status.md)。本页保留验收流程与
先前准备记录；实际已运行/未运行的层次以当前状态和真实测试记录为准。
百炼Chat Completions可显式设置READER_ENABLE_THINKING=0降低默认思考开销；
仅在服务支持时使用。进程级配置和已验证输出预算见当前状态页。

2026-10-18：当前约定输入范围内的核心功能已实现，进入真实数据质量验收准备阶段。
本页是待执行的验收步骤，不是已通过的真实质量报告。按用户要求，开始真实数据测试
前先通知用户；本轮收尾仅使用合成材料，没有请求真实论文或真实模型。

本轮最终离线验证：199 passed（54.79 秒），新增14项全文节点/CLI用例；
git diff --check 与 CLI --help 通过。共享契约及默认图入口未修改，未安装依赖、
修改环境文件、提交或推送。上述通过数不代表真实模型质量验收通过。

用户随后授权开始真实测试，实际结果见 [独立真实数据测试记录](reader-real-data-test.md)。
此前的百炼403已在充值后恢复调用；之后已完成两篇真实摘要及定向全文页面检查，
具体覆盖与未通过证明的层次见当前状态页。本页后文保留验收流程，不能视为所有步骤
都已执行或所有论文质量已通过。换机配置与故障判读见 [部署与风险](reader-operations.md)。

## 功能范围（准备阶段快照，当前证据见 reader-status.md）

| 能力 | 实现状态 | 真实验证状态 |
| --- | --- | --- |
| 摘要结构化分析与保守降级 | 已实现 | 模型提取质量未验收 |
| 本地文本型 PDF 解析、分页分块、显式标题关联 | 已实现 | 合成验证完成，复杂真实版式未验收 |
| arXiv 官方 PDF 获取、限速、限额及清理 | 已实现 | 之前单篇真实获取/解析成功，持续可用性不保证 |
| 逐块全文提取、精确引句范围及字段合并 | 已实现 | 真实模型事实正确性未验收 |
| 多候选语义协调、选择/弃权/摘要回退 | 可选，已实现 | 真实判断质量未验收 |
| 独立 CLI、仅返回 paper_analysis 的全文节点 | 已实现 | 只做独立合成测试，没有跨成员联调 |
| 调用预算、解析超时、可选有界并行与内存材料缓存 | 已实现 | 不追加吞吐基准或高标准性能目标 |

支持所有来源的调用者自备本地 PDF；自动获取当前只支持官方 arXiv。
通用网站抓取、付费全文、OCR、扫描件识别、表格/多栏版式重建、章节结构推断、
模型响应缓存、持久论文存储和跨成员联调不在本次核心功能完成范围内。
不把这些未实现能力描述为已有功能；未来有明确需求再单独安排。

## 全文节点入口

```python
from research_assistant.reader_node import create_fulltext_reader_node

if __name__ == "__main__":
    reader = create_fulltext_reader_node(
        pdf_paths={"Exact Paper Title": "local-paper.pdf"},
        fulltext_options={"reconcile": True},
        budget_options={"max_calls": 30},
    )
    output = reader({"papers": papers})
```

此节点可以单独调用，不要求创建或运行整个 Graph。只返回 `{"paper_analysis": [...]}`，
诊断和引句请通过 `run_reader` 查看。`download_arxiv=True` 显式启用已有论文的获取，
其余工厂参数沿用独立入口。默认节点 `agents.reader.reader_node` 仍为摘要路径。
本地映射及选项在构造时复制并校验；调用者后续修改原配置不会影响已构造节点。
每次读取当前完整 papers，重建完整分析列表，不沿用旧分析。注入工厂与显式材料缓存
保留调用者的生命周期；不保证同一工厂实例能由多线程同时调用。

## 独立验收顺序（复测流程）

1. 用户确定1–3篇合法可用的真实论文和模型配置/调用预算。至少包含一篇摘要完整、
   一篇有文本型 PDF 的论文；避免首次就使用长篇、扫描件或复杂表格。
   论文元数据与文件标题关联先人工核对，不重新运行 Search。
2. 输入 JSON 包含 papers、可选 pdf_paths、pdf_options、fulltext_options、budget_options；
   格式见 reader-standalone.md。未配置 PDF 时走摘要，未提供的信息不得补造。
3. 先禁用模型检查准备层；确认下载状态、页码、文本顺序、分块边界、缺页、乱码等。
4. 再在确定的调用预算内启用模型，逐字段对照摘要/全文。不要仅凭 Schema 通过就验收。
5. 检查引句范围、最终 field_sources、预算拒绝/异常/降级记录；对协调器至少人工检查
   一个多候选字段。全部候选不适合时应弃权，而不是拼接出矛盾结论。
6. 在同一 Reader 实例中增删论文后重跑，检查结果完整替换；无需 Analyst、Critic 或 Writer。

## 可执行命令（复测示例）

仅准备本地真实 PDF，禁用模型与下载：

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_cli --input input.json --output preparation.json --offline
```

获取已有 arXiv 论文并解析，禁用模型：

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_cli --input input.json --output acquisition.json --download-arxiv --no-llm
```

本地 PDF 的真实模型分析（检查已有进程环境没有设置 READER_USE_LLM=0）：

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_cli --input input.json --output analysis.json
```

需下载时再添加 --download-arxiv。这些命令分别运行，output 必须是不存在的新文件。
--no-llm 不修改 .env，并在结束或异常时恢复原进程开关；其结果内容字段保守回退，
不能据此评价模型提取质量。普通分析可能产生模型服务费用，使用事先确定的预算。
真实论文、输入与结果应放在被 Git 忽略的目录或仓库外，不放入测试 fixture。

## 人工记录与通过条件

每篇记录真实论文的永久链接/版本与本地关联、模型/接口、实际分析覆盖范围、准备层问题、
预算准入与拒绝、错误与降级，以及人工核对结论。记录中不含密钥。
对 PaperAnalysis 的每个非空字段标注“支持 / 不支持 / 无法判断”，保留页码与原句；
对空字段区分“源材料没有”“提取遗漏”“预算/模型失败”。不凭自动引句匹配判定语义支持。
发现不支持的事实或错误来源时阻止质量验收，先保留失败案例再修复。
只有明确支持的内容可以通过；不要求把材料中没有的信息填满。输入变更后结果必须完整替换。
完成后再报告真实验收结果，不能把本页计划或之前单次下载冒烟测试当成分析质量证明。
