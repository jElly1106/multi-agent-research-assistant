# Reader 独立统一入口与调用预算

## 调用

```python
from research_assistant.reader_pipeline import run_reader

if __name__ == "__main__":
    result = run_reader(
        papers,
        {"Exact Paper Title": "local-paper.pdf"},
        budget_options={"max_calls": 50, "output_tokens": 2048},
    )
```

这是 Reader 内部 opt-in 入口，不修改默认图节点或共享 State。顺序为：全量论文预检、
选项校验、本地材料准备、全批摘要分析、按篇全文提取与字段合并。优先为各篇建立摘要
回退，再消耗剩余调用预算处理全文。不访问下载来源，也不根据 URL 猜测文件路径。
没有本地映射时仍能完成摘要路径；无摘要、全文不可用或预算不足时返回保守字段。

结果含 paper_analysis、details、preparation、budget。只有 paper_analysis 符合现有
Reader 共享输出；其余是内部诊断，不直接写入图 State。preparation 保留全部P1材料及
批次问题，details 保留全文证据和字段来源。每轮独立、完整替换，不复用前次预算。
调用可能返回较多内存数据（准备层页文本及块）。新增独立 CLI JSON 导出、可选内存
材料缓存及有界 PDF 并行解析，见 [独立运行与性能选项](reader-standalone.md)；没有持久缓存。

pdf_options 接受现有P1参数、timeout_seconds 及 max_workers；material_cache 作为
独立的 run_reader 参数传入，不放在 pdf_options 中。fulltext_options 接受
max_chunks/max_chunk_chars/max_total_chars/reconcile。reconcile 默认为 False，启用时
对多个字符串候选进行可预算的证据协调，见 [全文规则](reader-fulltext.md)。
budget_options 参数见下节。未知参数或
无效配置报错，编程错误继续抛出；模型可恢复异常和预算拒绝走现有降级路径。
READER_USE_LLM=0 时默认模型适配器不创建客户端、不占调用预留；显式注入合成分析器
仍可用于离线验收。未配置模型导致初始化失败时，已作的预算预留不会退回。

## 预算语义

默认：context_tokens=16384、output_tokens=2048、overhead_tokens=512、
max_calls=50、max_reserved_tokens=200000。均为正整数，context 必须大于输出与开销预留之和。
这些是本地准入配置，不是对当前 LLM_MODEL 实际上下文长度的探测或保证。

每次分析前，对系统提示、用户材料和结构化输出 Schema 的 JSON 表示计数，再加
overhead_tokens，预留 output_tokens。超过单次上下文、整批调用次数或整批预留总额，
不创建对应分析器、不调用模型；事件分别记录 context_budget_exceeded、
call_budget_exceeded、batch_token_budget_exceeded。原有P2每篇字符/块数限制仍生效。

budget.report 返回 counter_mode、admitted_calls、reserved_tokens 和 events；每条事件
含阶段、标题、全文块号、估计输入、输出预留、准入状态和拒绝原因。准入次数不是成功次数，
也不是实际服务商账单；已准入后失败仍消耗预留，不追求失败后自动重试。

统一入口默认适配器显式传 max_tokens 限制模型输出，并设置 max_retries=0，避免客户端
重试绕过调用次数预留。自定义分析器必须自行遵守一次调用和输出限制，不应在内部重试。
直接使用原有P0/P2底层接口不会自动获得统一预算；它们保留兼容的原有行为。

## Tokenizer 与离线边界

budget_options 可以传 token_counter(text)->非负整数。应使用与模型匹配的 tokenizer；
计数内容包含序列化消息和 Schema，再额外预留消息封装开销。不同提供方的实际消息封装、
隐藏提示及推理Token不由本地计数精确复现，须根据真实模型配置余量和输出预算。

未传 counter 时，counter_mode=utf8_byte_estimate，使用 UTF-8 字节数作为保守估算。
这是无网络默认值，不是精确Token数，不能保证任意自定义模型上下文适配，也不能据此
准确计算费用。切勿把“预算已实现”等同于“模型专属精确计数已配置”。

可选 helper（依赖现有 tiktoken）只读取用户提供的本地 .tiktoken 词表，不自动下载：

```python
from research_assistant.reader_budget import local_bpe_counter

counter = local_bpe_counter(local_rank_file, pattern=model_compatible_regex)
# run_reader(..., budget_options={"token_counter": counter, ...})
```

词表和 regex 必须与目标模型匹配。普通文本中的特殊Token外观按普通文本处理。
当前不随仓库提供模型词表、不猜测网关模型的 tokenizer、不修改环境配置文件。

## 离线验收

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_pipeline_demo
```

已运行该合成示例，无网络请求。预期 paper_analysis.problem 为 Synthetic demonstration
only，preparation 显示 local_pdf_missing，details 显示摘要回退，budget 准入一次摘要分析。
实际合成PDF→准备→摘要→全文合并流程另外由测试验证。真实提供方的计数误差、输出
参数支持及质量待验收。已新增 [arXiv获取](reader-download.md) 和可选语义协调；
其他获取来源与真实材料/语义判断质量评估待做。

最终完整离线回归：106 passed（23.21秒），新增14项统一入口及预算测试；
涵盖实际合成PDF链路、摘要/全文回退、预检、消息与Schema计数、上下文/批次限额、
本地合成词表、失败预留和默认客户端参数。git diff --check通过。
