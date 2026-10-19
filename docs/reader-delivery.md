# Reader 独立开发交付记录

最新交付结论与性能依据见 [当前状态](reader-status.md)。以下日期记录属于开发历史，
其中“未提交/未推送/待开发”不自动代表最新任务分支状态。

最终交付候选完成216项离线回归、两篇真实PDF准备及定向模型检查；有限样本与
基本性能达到独立任务分支提交要求。限制和配置见当前状态页；提交不等于全系统
联调或所有论文质量保证。

2026-10-17：P0 独立开发完成；P1 本地 PDF 准备层完成。
“完成”仅指本页所列代码、配置及合成材料离线验收，真实模型质量和跨成员联调待验收。

2026-10-18 功能收尾：新增 `create_fulltext_reader_node`，只读 papers 并只写
paper_analysis，保留默认摘要节点；CLI 增加 --no-llm，可与显式 arXiv 获取独立组合。
当前约定输入范围的核心功能已实现，后续重点是 [Reader 独立真实数据验收](reader-acceptance.md)。
按用户要求只保留适度性能措施，不继续扩展性能目标；真实测试开始前先通知用户。

## P0 摘要分析

沿用 `reader_node(state) -> {"paper_analysis": [...]}`，只依据摘要。
保留全量预检、空白标题跳过、同名冲突报错、相同记录去重、完整替换及保守空字段策略。

Reader 本地客户端读取 OPENAI_API_KEY、LLM_MODEL、OPENAI_BASE_URL 和 LLM_API。
LLM_API 默认 chat_completions，另支持 responses；配置错误抛出 ValueError，
禁用或缺配置/客户端依赖使用空字段降级。READER_USE_LLM=0 明确禁用。
Base URL 为 HTTP(S) 根地址，不能带端点、query 或 fragment。
显式 json_schema/strict 输出，120 秒请求超时、2 次重试，不传 temperature；
Responses 设置 store=False。超时不是整批执行时限。真实提供方支持程度尚未验证。

审查修复：P0 与 P2 现在明确将 OpenAIRefusalError、ContentFilterFinishReasonError、
LengthFinishReasonError 转换为可恢复分析错误。P0 保守空字段、P2 保留摘要字段，
并继续处理后续论文/块；不扩大为捕获全部异常，编程错误仍抛出。
拒绝异常类型懒加载，保留可选模型客户端依赖缺失时的降级行为。
修复后完整离线回归：92 passed（19.19秒），其中新增6项覆盖实际P0/P2适配器的
三类提供方异常及后续论文处理。git diff --check通过；未调用真实模型。

## P1 内部接口

安装可选依赖：`& .\.venv\Scripts\python.exe -m pip install -r requirements-reader-pdf.txt`。
本次安装 pypdf 6.21.1。P0 不导入 pypdf，缺少它不会阻止 P0 运行。

```python
from research_assistant.reader_pdf import prepare_local_pdf
material = prepare_local_pdf("local-paper.pdf")
```

参数：max_bytes 默认 20 MiB，max_pages 默认 300，chunk_chars 默认 3000，
overlap_chars 默认 200，max_text_chars 默认 1,000,000，max_chunks 默认 5000。
计数参数为正整数，重叠为非负且小于块长；错误抛出 ValueError。
私有 _parser_factory 仅用于注入合成解析器测试，不是共享接口。

返回普通字典，含 status、pages、chunks、issues：

- status 为 ok、partial、failed。部分页可提取且存在问题为 partial；无可用文本为 failed。
- pages 每项包含从 1 开始的 page 和清洗后 text；失败/空白页不进入该列表。
- chunks 含全局从 1 开始的 index、page、start、end、text；范围是清洗后页文本的
  Python 字符索引，end 不包含在内。块不跨页。
- issues 每项含 code 和 page，文档级问题 page 为 null。

问题码：local_file_required、regular_file_required、pdf_required、size_limit、
dependency_unavailable、invalid_pdf_header、encrypted_pdf、page_limit、
page_extraction_failed、no_text、pdf_parse_failed、file_access_failed。
输出规模超限新增 text_limit、chunk_limit，整篇 failed，清空此前累积的页和块，不截断。
预计的文件及 pypdf 错误转换为问题码，编程错误继续抛出。

只接受本地普通 .pdf 文件（拒绝符号链接），检查 PDF 文件头。超过限制整篇拒绝，
不静默截断；加密文件不尝试密码。逐页保留可用内容，无 OCR，不恢复表格或多栏版式，
不推断章节。统一换行、清除 NUL、整理行内空白并保留段落；不承诺扫描件可提取。
大小/页数限制不构成解析时间或内存上限，复杂 PDF 仍可能耗时。

不修改输入、不建立缓存或持久副本、不访问网络；只在内存准备材料，
不调用 LLM、不写共享 State、不覆盖 paper_analysis。Search 仍仅按现有 Paper 接口提供
完整列表；本地映射由下节的 Reader 内部批量接口显式提供，不假设 Search 提供路径。
全文结构化提取属于 P2。

## 本地批量关联与解析隔离

```python
from research_assistant.reader_materials import prepare_paper_materials

# Windows 脚本必须保护主入口；不要在模块顶层启动子进程。
if __name__ == "__main__":
    batch = prepare_paper_materials(
        papers, {"Exact Paper Title": "local-paper.pdf"}, timeout_seconds=60
    )
```

papers 沿用现有完整列表。独立映射键去除首尾空格后区分大小写，值为字符串或 Path；
不按文件名猜测论文。相同校验后论文只处理一次，保留首次标题与顺序；同名字段冲突、
非法映射或同名不同路径在解析前报 ValueError。路径只作词法规范化，不解析为绝对路径；
相对路径相对于当前工作目录。标题键不修改原始论文，原始输入和映射均保持不变。

结果为 `{"materials": [...], "issues": [...]}`。每项材料在原 PDF 结果上增加
paper_title。未映射返回 failed/local_pdf_missing；无用映射记录批次问题
unused_pdf_mapping（含 paper_title），不访问该文件。空批次返回空材料，每轮完整替换。

也可使用 `prepare_pdf_isolated(path, timeout_seconds=60, **pdf_options)` 单篇隔离解析。
底层 prepare_local_pdf 仍是同步接口，没有硬超时。批量接口逐篇启动 spawn 子进程，
默认每篇60秒，覆盖启动、解析及管道传输。超时终止并回收当前进程，返回 parse_timeout，
之后继续下一篇。异常退出返回 worker_failed；通过管道报告的编程异常向父进程抛出
RuntimeError，停止当前调用。管道关闭、子进程和接收线程在返回前回收。
子进程启动的可预期 OSError 也返回 worker_failed；其他调用错误继续传播。

父进程用专用接收线程排空单向管道，同时监督截止时间，避免大结果阻塞
监督线程。没有线程池、PDF 并行解析或缓存。正常返回不留后台进程；终止和清理有少量
额外开销，截止时间不等于函数严格在同一毫秒返回。文本、块数与硬超时不是操作系统
内存配额，单页 extract_text 的瞬时内存仍可能较大。

PDF 参数沿用上一节，未知参数、非法参数及非有限/非正的 timeout_seconds 明确报错，
即使批次为空也校验。私有 _worker 仅用于进程边界测试，不是共享接口。

## 离线验证

```powershell
$env:COORDINATOR_USE_LLM='0'
$env:READER_USE_LLM='0'
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_pdf_demo
```

首轮本地准备层测试结果：52 passed。覆盖 P0 配置/异常边界、既有摘要行为、实际合成 PDF 解析、
页码及分块、Unicode 清洗、空白/损坏/加密/超限文件、部分页失败和可选依赖缺失。
首次测试因系统临时目录权限导致 12 个 fixture 错误；获准重跑后全部通过。
安装依赖也曾遇到临时目录权限问题，获准重试后成功。
合成 PDF 仅在临时目录生成，不下载论文。

人工黑盒命令已扩展为两篇合成论文的批量映射：第一篇 ok、1页、1块、无问题；第二篇
failed/local_pdf_missing。输出 synthetic=true；临时 PDF 随命令结束自动清理。
该命令不验证科研提取质量。

P1 续开发最终回归：70 passed（18.66秒），git diff --check 通过。
新增18项用例覆盖显式映射、批量完整替换、输入不变、预检冲突、参数边界、
真实 spawn 解析、超时和崩溃后进程回收、编程错误传播、2 MB 管道结果及输出限额。
超时续处理测试分别配置短截止时间的阻塞工作进程与较长截止时间的后续正常进程，
避免把 Windows 启动成本误当作后续解析故障。
开发中修复了超时清理等待管道接收线程的问题：接收线程使用可停止轮询，清理时关闭
管道并回收线程。最终回归无该阻塞。另移除了依赖非 Windows 私有管道方法的故障模拟，
不将该模拟记为有效覆盖。扩展批量演示已运行，输出符合上一段预期。

## 后续工作

新增独立 [统一入口与预算](reader-pipeline.md)：已串起本地准备、摘要分析、全文合并及回退，
加入单次上下文、输出预留、整批调用和预留总额控制。支持注入 tokenizer 或读取本地词表；
未配置时明确使用字节估算，模型专属计数和真实上下文适配仍待配置验收。

真实模型摘要质量验收、正式 Analyst 联调、统一模型工厂整合，以及实际 PDF 版式质量
评估均待完成；不阻塞本阶段独立开发。P1 网络获取及来源政策后续另定，本地文件映射已实现。
P2 已新增独立、可注入分析器的全文提取与合并层，详见 [P2 使用与边界](reader-fulltext.md)。
默认图节点仍只读摘要；独立统一入口已有预算机制，真实质量验收未完成。
2026-10-18 续开发：新增可选的全文语义协调，仅选择已有证据候选或明确弃权，包含
调用预算和失败摘要回退；另增加精确引句字符范围。真实语义判断质量仍待人工验收。
2026-10-18 续开发：新增显式有界内存材料缓存、有界 PDF 并行解析和独立 CLI。
使用方式、失效语义、快照与内存边界见 [独立运行与性能选项](reader-standalone.md)。
用户随后确认沿用原分工：Reader 获取已有论文全文。现已新增独立 opt-in arXiv 官方
PDF 下载及临时材料关联，含有界流式下载、串行限速、429冷却、失败回退与自动清理，
见 [下载使用与验收](reader-download.md)。模型响应缓存、自动重试退避与吞吐基准未实现。
本轮未合入 main、改共享契约或默认入口、提交或推送。
