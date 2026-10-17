# 2026-10-17：arXiv API 限流与失败诊断更新

> 本文件保留2026-10-17的 arXiv 诊断与245项测试记录；其中“当前”等表述均指当天检查时点。后续默认检索及默认离线回放切换到 OpenAlex，341项回归及真实取数见 [OpenAlex 更新](MEMBER2_OPENALEX.md)。北京时间2026-10-18 00:06左右，arXiv 官方 API 的一次新请求首次成功，约13.35秒取得5条、选入3篇，原始响应与元数据核对通过；该次成功不保证持续可用，不代表此前限流的原因已确定。当前默认仍为 OpenAlex，详见 [最新使用说明](MEMBER2_SEARCH.md)。

## 2026-10-17 检查结论

本项目调用 arXiv 官方 API，属于程序化检索接口。HTTP 429 通常是限流响应，不能据此认定 arXiv 禁止了智能体、永久封禁账号或禁止本项目。此前超时与本次429是不同现象；本次请求收到了HTTP响应，但仅凭状态无法确认是源站还是中间网络服务返回。

当天只读检查发现 Windows 系统代理 `127.0.0.1:7890` 已被 Python 识别，本地端口可达；普通 arXiv 摘要页经直连、系统代理、显式配置代理均 HTTP 200。普通页面可达不代表搜索 API 可用。代码中的 direct 仅表示不使用 urllib 显式代理，TUN 仍可能在系统网络层接管流量。

北京时间 **11:43**，在距离用户上次429数分钟后，仅发送一次与用户相同的查询，`max_retries=0`。请求约 **1.625秒**收到429：`route=direct`，`attempts=1`，没有切代理或自动重试。响应没有有效 `Retry-After`，取得论文0篇，实时检索仍未通过。

详细本地证据：`D:\chatgpt\outputs\2026-10-17-arxiv-rate-limit\single-attempt.json`。代理诊断保存在 `D:\chatgpt\work\2026-10-17-arxiv-proxy-diagnosis\proxy-diagnosis.json`。没有修改 Windows 全局代理、没有上传 GitHub、没有补造论文。

## 代码改动

- `search/models.py`：`ProviderError` 增加可选结构化 `details`，保留原有异常用法。
- `search/transport.py`：失败时记录每次尝试的路线、状态、时间、网络异常类型；只保留合法的公开 `Retry-After` 值，不记录凭据、请求头集合或任意上游异常文本。
- **429首次出现就停止该来源本轮请求，不自动重试、不换路线。**服务端等待秒数/日期完整保存；没有有效等待头时给出明确标为 `local_policy` 的300秒建议。这个建议不是服务端承诺，不能保证5分钟后恢复，也不会后台自动重试。
- 对5xx仍可按原预算重试，但服务端要求等待超过自动等待上限时，直接停止，不再将长等待截短后提前请求。
- `agents/search.py`：把失败细节写进 `search_audit.requests[].failure_evidence`。全部不可用且有429时给出明确限流提示，仍然不返回替代论文。
- `examples/search_demo.py`：失败文件提示改为“失败记录已保存”，与正常结果区分。

`failure_evidence` 主要字段：

| 字段 | 含义 |
|---|---|
| `request_url` | 实际请求的官方API地址及查询 |
| `http_status` | 最后HTTP状态；网络异常时可能为空 |
| `route` | 最后尝试路线 |
| `attempts` | 逐次尝试列表，含route、outcome、状态或网络错误类型 |
| `rate_limited` | 是否收到429 |
| `retry_after` / `retry_after_seconds` | 有效服务端等待头及解析后的完整等待秒数；缺失则null |
| `recommended_wait_seconds` | 服务端要求，或明确标为本地策略的建议 |
| `wait_source` | `server` 或 `local_policy`，区分真实要求与本地建议 |
| `retry_at` | 根据建议计算的UTC时间，不代表届时一定恢复 |

## 接下来怎样使用

1. 暂停连续重跑。不要通过换节点或换IP规避429；增大timeout也不会解决已经返回的429。
2. 有有效Retry-After时至少按要求等待。缺少等待头时先隔一段时间，再做一次小请求；本地300秒建议只是保守起点，持续429时继续停止并考虑通过arXiv官方API支持渠道反馈。
3. 需要演示和验收程序逻辑时，可运行历史真实响应重放，并明确标注原始检索时间；它不是新的联网成功。
4. 实时访问恢复后，再执行一条小查询；失败审计保留，与原始论文响应一起保存。

```powershell
# 在项目根目录执行
# 离线重放：没有新联网或模型调用
.\.venv\Scripts\python.exe -m examples.search_replay_demo --output output/replay.json
```

需要再次实时验证时，下面仅发一次请求；应在等待后手动执行，遇429就停止：

```powershell
.\.venv\Scripts\python.exe -m examples.search_demo 'Multimodal Time Series Forecasting' --source arxiv --top-k 3 --max-queries 1 --results-per-query 5 --timeout 15 --max-retries 0 --output output/single-attempt.json --audit-dir output/audit
```

没有新增跨进程的持久冷却锁；反复重启命令仍会产生新请求，需按提示停止。本次没有使用其他来源来冒充arXiv、没有关闭TLS、没有创建后台自动重试任务。

## 验证与交付

更新后全仓 **245项离线测试通过**。新增限流诊断测试覆盖429停止、无路由规避、完整等待、HTTP日期、网络异常后429的路由链、凭据隔离、5xx长等待停止、审计传递和CLI失败提示；旧版自动重试429的预期已按新策略更新。

历史真实arXiv响应重放仍 `verified_equal=true`。这证明处理逻辑回归通过；当前实时API仍429，没有声称外部服务已恢复。

源码已更新在原项目目录。本次最新源码包、测试日志和诊断结果位于 `D:\chatgpt\outputs\2026-10-17-arxiv-rate-limit`。早先压缩包是历史版本，不含本次诊断改动。
