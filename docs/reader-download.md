# Reader arXiv 全文获取

2026-10-18：按原有分工，Search 提供论文元数据，Reader 获取并准备相应全文。
不重新搜索论文，不改 Search、共享 Schema、State 或默认图节点。
本轮实现范围为 arXiv 官方 PDF；其他来源仍接受显式本地 PDF 映射。

## 独立使用

```python
from research_assistant.reader_pipeline import run_reader_with_downloads

if __name__ == "__main__":
    result = run_reader_with_downloads(
        papers, pdf_paths,
        download_options={"max_requests": 5, "max_bytes": 20 * 1024 * 1024},
    )
```

`papers` 是已有 Search 输出。`pdf_paths` 可省略，已提供的本地映射优先，即使路径失效
也不擅自改用网络。返回原有 paper_analysis/details/preparation/budget，另加内部
acquisition 收据列表，不把收据写入共享 State。默认 `run_reader` 和 `reader_node`
仍不下载。模型禁用开关与下载独立：Python API 设置 READER_USE_LLM=0 仍可下载和解析。

CLI 显式启用：

```powershell
& .\.venv\Scripts\python.exe -B -m research_assistant.reader_cli --input input.json --output result.json --download-arxiv
```

输入与本地入口相同，只有该模式额外接受 download_options。
`--offline` 与 `--download-arxiv` 互斥；不带下载开关不会获取论文。
新增 `--download-arxiv --no-llm` 组合可仅获取/解析，关闭默认模型适配器。
输出必须是新文件；无模型禁用配置时仍可能请求模型服务。

## 来源与连接政策

只接受已有论文的官方 arXiv abs/pdf URL，包括 www/export 主机、HTTP/HTTPS、
新版编号和旧版分类编号、显式版本号；统一到 `https://arxiv.org/pdf/<id>`。
不访问原始 HTTP 地址。拒绝账号密码、端口、query、fragment、非官方主机及任意路径；
不解析 DOI，不爬取 HTML，不猜测 OpenAlex 等记录的全文链接。
版本号保留；无版本 URL 指向服务当时提供的版本，SHA-256 记录实际取得的字节。
合法 URL 不能证明元数据标题与全文一致，该关联仍依赖上游，未做语义身份核验。

默认 TLS 校验，沿用 urllib 的系统/环境代理配置，不修改系统代理。
自动重定向及重试均禁用；服务器改用重定向时返回 redirect_refused，而不放宽目标主机。
仅请求 PDF，不发送模型密钥或下载凭据。响应必须 HTTP 200、无内容编码，正文包含
PDF 文件头；最终仍由既有解析器验证，只有文件头不意味着 PDF 一定可解析。

下载在模块内使用进程级共享锁，单连接串行，相邻请求启动间隔默认至少 3 秒。
各进程/不同机器或 Search 的流量并不共享此锁，调用者需要统筹总流量。
429 立即结束当前请求、无重试，同一进程后续请求进入冷却；Retry-After 支持秒数
或 HTTP 日期，冷却至少 300 秒。无有效等待头时的 300 秒只是本地策略，不保证恢复。
收据只包含规范化 URL、状态、问题码以及成功时字节数/SHA-256，不包含原始错误页。

依据：[arXiv 访问与 PDF 地址说明](https://info.arxiv.org/help/ir.html)、
[官方 API 使用条款](https://info.arxiv.org/help/api/tou.html)，2026-10-18 查阅。
API 条款对传统 API 的限速不能直接理解成所有 PDF 访问的服务保证；本实现对 PDF
也采用保守串行间隔。只用于个人/研究分析，不提供全文再分发服务。

## 限额、清理与降级

download_options 默认：max_requests=5（允许 1–20）、max_bytes=20 MiB、
max_total_bytes=50 MiB、timeout_seconds=20、interval_seconds=3。
字节限额为正整数；timeout 为有限正数且至多 60 秒，interval 为 3–60 秒。
max_total_bytes 是整批下载字节的**准入预留预算**：每次尝试消耗本次允许的文件额度，
包括失败尝试，不是实际服务流量计量。默认情况下最多准入 20+20+10 MiB 三次尝试。
读取时额外读取至多 1 字节以识别越界；HTTP 头及底层缓冲不计入此预算。
超过请求或预留总额后，剩余论文记录 download_budget_exceeded，仍进行摘要分析。

timeout 是连接/套接字操作超时；正文读取另有同长度的协作截止检查。阻塞读取可在
下一次返回后才被截止检查发现，因此不承诺单篇或整批的硬墙钟上限。
解析继续使用原有独立进程硬超时。文件大小限制在 Content-Length 和流式读取两处检查；
缺少长度允许有界流式下载，声明长度与实收不一致则失败。失败正文删除。

下载文件存放在本次调用的临时目录，解析与分析结束或出现编程错误后清理。
没有持久论文缓存；可选 PDFMaterialCache 仍只保存内存中的解析材料。
不以论文标题构造文件路径，不覆盖已有文件，也不把论文加入 Git。
来源不支持、网络失败、限流、超限、下载或解析失败均保留论文并走摘要/空字段回退；
acquisition 保留下载失败码，preparation/details 继续记录既有本地准备与全文诊断。
配置错误和编程错误不冒充下载失败或分析成功。

## 验证

合成 HTTP 测试覆盖 URL 限制、流式限额、长度不一致、HTML/编码拒绝、超时与中途
失败清理、限流冷却、重定向拒绝、请求间隔、整批预留、本地优先、预检，以及
合成 PDF 下载→真实解析→注入合成提取器→全文合并、异常后目录清理。

真实小规模验证：2026-10-18，仅请求一次官方
[Attention Is All You Need v7](https://arxiv.org/abs/1706.03762v7) PDF，
取得 2,215,244 字节，SHA-256 为
`bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`。
解析 status=ok、15 页、23 块、issues=[]；模型调用数为 0，论文临时副本已清理。
该记录验证一次真实获取/解析，不代表持续可用、全文身份校验或真实模型分析质量。

最终完整离线回归：163 passed（43.00 秒），其中本轮新增39项下载/CLI测试；
git diff --check 与 CLI --help 通过。测试没有调用真实模型；唯一真实 PDF 请求为
上面的单篇冒烟验证。共享 INTERFACES/Schema/State/Graph 无改动；没有跨成员联调。
