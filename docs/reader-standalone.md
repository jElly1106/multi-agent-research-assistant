# Reader 独立运行与本地性能选项

> 当前状态与最新测试见 [reader-status.md](reader-status.md)；本页测试数字和“未验收”记录为对应开发阶段快照。换机配置及运行风险见 [reader-operations.md](reader-operations.md)。

2026-10-18：新增独立 CLI、有界 PDF 并行解析和显式内存材料缓存。
最终交付状态及基本性能见 [reader-status.md](reader-status.md)。
这些是本地材料路径的实现，不代表跨成员联调或真实模型质量验收完成。
后续同日新增的 arXiv 全文获取见下文与下载文档。

## 职责边界

Search 负责发现、检索和去重论文，输出现有 `Paper` 元数据。Reader 分析 Search
提供的摘要，或调用者显式关联的本地 PDF。论文记录页、DOI 和 PDF 下载地址不能
混用；本轮不根据 `papers.url` 自动请求网络。不重复检索论文。
2026-10-18 用户确认沿用原有分工：Reader 获取已有论文的全文。新增显式启用的
arXiv 官方 PDF 获取，见 [下载政策与使用](reader-download.md)。其他来源暂用本地文件。

## 独立命令行

在项目根目录运行：

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_cli --input input.json --output result.json --offline
```

输入为 JSON 对象，示例中的论文完全虚构：

```json
{
  "papers": [{"title": "SYNTHETIC Paper", "authors": [], "source": "synthetic", "abstract": "Synthetic evidence only."}],
  "pdf_paths": {"SYNTHETIC Paper": "local-paper.pdf"},
  "pdf_options": {"max_workers": 2, "timeout_seconds": 60},
  "budget_options": {"max_calls": 50}
}
```

`papers` 必填；其余可省略。也接受现有 `fulltext_options`。
JSON 中的相对 PDF 路径相对于命令的当前工作目录，沿用 Python API 的路径规则。
输出包括 paper_analysis、details、preparation、budget；只有 paper_analysis 是共享输出。
`--output` 必须是新文件，已有文件会在模型调用前拒绝覆盖，父目录必须已存在。
省略时输出到标准输出。失败会清理本次创建的不完整结果文件。
控制台不能编码 PDF 特殊字符（如 Windows GBK）时，标准输出改用 JSON Unicode 转义，
解码后的内容不变；`--output` 文件始终为 UTF-8。
新增 `--no-llm` 可与 `--download-arxiv` 同用，仅获取/解析而不调用模型；
`--offline` 同时关闭模型与下载。独立真实数据验收步骤与全文节点见
[验收准备](reader-acceptance.md)。
`--offline` 禁用默认摘要与全文模型适配器，但仍解析本地 PDF，分析字段按保守策略回退。
不带此选项时按既有模型配置尝试分析，可能请求模型服务。只有显式
`--download-arxiv` 才获取 arXiv PDF；该选项与 `--offline` 互斥。

## 有界并行解析

`prepare_paper_materials(..., max_workers=1)` 默认串行；可显式设为 2–4。
统一入口通过 `pdf_options={"max_workers": 2}` 传入。
主线程池每个线程监督一个独立 spawn PDF 子进程；只有 PDF 准备并行，模型调用仍串行。
结果保持预检后论文的输入顺序，每次返回完整替换列表。未知或冲突映射在启动工作前报错。

每篇硬超时从其工作线程启动解析时计算，不包含排队等待；没有整批硬截止时间。
单篇预期失败不阻止其他论文。编程错误向调用者传播，但线程池退出前等待已派发工作
完成并清理子进程；这可能等待其他论文的逐篇截止时间。每个 worker 的大小与页数限额
仍独立生效，并行会提高瞬时内存使用量，未提供操作系统内存配额。

## 显式内存缓存

```python
from research_assistant.reader_cache import PDFMaterialCache
from research_assistant.reader_pipeline import run_reader

if __name__ == "__main__":
    cache = PDFMaterialCache(max_entries=16, max_bytes=8 * 1024 * 1024)
    first = run_reader(papers, pdf_paths, material_cache=cache)
    second = run_reader(papers, pdf_paths, material_cache=cache)
    print(cache.report())
    cache.clear()
```

缓存由调用者持有和显式复用，默认不启用；CLI 不创建跨运行缓存。
只缓存成功或部分成功的 PDF 准备材料，不缓存失败、论文分析或模型响应。
每次先读取当前 PDF 字节，再按 SHA-256 与显式解析参数匹配；修改内容或参数使旧项失效，
同内容不同路径可复用。删除文件不会命中旧项。显式传默认参数可能造成额外缓存未命中，
不影响结果。当前进程内解析器版本固定；改变代码或依赖应重建缓存。

未命中时把已哈希的字节写入临时快照，再调用隔离解析，结束或异常后清理快照。
这会产生短暂磁盘副本，但没有持久缓存文件，也不写入项目或 Git。
快照读取、哈希和写入不属于 PDF 子进程的硬超时，文件访问本身没有硬截止时间。
缓存使用 LRU 淘汰，按 JSON 编码后的材料字节数和条目数双重限制；这不是 Python
对象及正在运行工作所需总内存的上限。过大条目直接不缓存。返回值与缓存隔离，调用者
修改返回对象不污染后续结果。锁保护共享状态；并发相同未命中可能重复解析，不合并请求。
report 返回 entries/bytes/hits/misses，clear 同时清空内容和计数。

## 验证边界

新增测试使用明确标识的合成论文/PDF，覆盖真实 spawn、线程并行上限、顺序、错误后清理、
CLI 子进程、拒绝覆盖、内容与参数失效、LRU/容量、快照清理和返回值隔离。
这验证接口与可靠性，不证明真实材料的科研提取质量，也没有证明实际吞吐提升。
更多全文来源政策、真实模型与 PDF 版式质量验收仍待完成。可选的证据语义协调已实现，
使用 fulltext_options.reconcile 启用，详细决定/回退规则见 reader-fulltext.md；真实语义质量未验收。

本轮验证：完整离线回归 123 passed（40.14 秒）；随后补充临时快照权限失败的
保守降级及测试，缓存专项 7 passed（11.07 秒）。当前共 124 个测试用例，未将
专项重复通过数累加成完整回归数量。CLI --help 和 git diff --check 通过。
未安装依赖、调用真实模型、修改共享契约或进行跨成员联调。
