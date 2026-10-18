# 成员5交付：Critic Agent 与系统评价

## 职责与交付对应

| 分工要求 | 实现与验收入口 |
|---|---|
| Critic Agent、PASS/FAIL | `research_assistant/agents/critic.py`；`tests/test_critic.py` |
| Evidence Checking：证据充分性、遗漏、过度推断 | 来源与覆盖的确定性检查 + 独立模型语义审核 |
| Feedback Loop | 复用成员1 Graph；真实 Critic 节点参与两轮检索/分析的离线集成测试 |
| 系统评价指标 | `research_assistant/evaluation.py`；`examples/evaluate_run.py` |
| Without/With Critic 消融 | `research_assistant/ablation.py`；`examples/critic_ablation_demo.py` |
| 运行、联调、汇报说明 | 本文；`INTERFACES.md`；`REPORT.md` |

所有跨成员字段保持原有 JSON 契约。Critic 只返回 `critic_result`，不修改论文、分析、
报告、轮次或终止条件；轮次与分支仍由成员1 Graph 负责。

## 安装与复现

Python 3.10+，在仓库根目录运行；本次离线验证环境为 Windows / Python 3.11。

```bash
python -m venv .venv
# PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest -q
python -m examples.critic_mock_demo
python -m examples.critic_ablation_demo --output output/critic_ablation.json
```

两个 mock 入口强制本次 Coordinator 使用离线规划，不受本地密钥影响，不调用真实模型。
生成的结果位于被 Git 忽略的 `output/`。已复现的模拟指标摘要随代码保存在
`examples/results/critic_ablation_metrics.json`。PDF 解析器仅用于读取任务文档，正式
模块不依赖 pypdf，也不更改项目依赖列表。

本次最终验证：98 项测试通过（含原有 38 项），模拟闭环、消融结果复现、评价 CLI、
Python 编译与 `git diff --check` 均通过。若本机系统临时目录权限受限，可指定一个
新的项目内测试目录，例如 `python -m pytest -q --basetemp=output/pytest-local-run`。
命令行 JSON 输入兼容 UTF-8 和 PowerShell 常见的 UTF-8 BOM。

## Critic 如何审核

1. 校验 State 与论文/阅读/方法总结结构；空标题、非列表、同名冲突是输入错误，明确报错。
   完全相同的重复输入会在送入模型前合并，评价模块仍统计原始最终快照的重复率。
2. 确定性检查：研究问题、Search 来源、Reader 核心字段、分类与表格覆盖、未知引用、
   重复表格行、数据集/局限是否忠实保留 Reader。发现缺口直接 FAIL，不请求模型。
3. 结构完整时调用配置的模型，结合全部当前材料逐项检查：问题覆盖、单篇证据被
   扩大成领域结论、跨数据集/跨指标排名、技术时间顺序被写成因果、方法或结果矛盾。
   一篇论文足以支持限定范围的描述，空演进列表也不自动 FAIL。
4. 严格校验模型输出：PASS 不能仍含问题或补充查询；FAIL 必须同时包含至少一类
   问题、修订建议、可执行补充查询。字段缺失、空白项、矛盾判定均报错。
5. 当前全部证据每轮重新审核；历史判定和轮次不作为降低标准的理由。

论文、Reader、Analyst 和研究问题中的指令性文字只作为数据。模型超时、配置缺失、
格式错误直接抛出异常，不自动转为 PASS，也不以 mock 替代真实响应。
确定性 FAIL 的查询基于当前主题和问题；语义 FAIL 的查询针对模型指出的具体缺口。
Reader/Analyst 的修复建议放在 feedback，查询仍由成员2负责真实执行。

Critic 能检查现有材料的可追溯性与一致性，**不能单独证明论文真实存在，也不能证明
Reader 忠实于全文**。真实数据库核验与独立人工评价须单独完成。

## 真实模型入口与团队接入

沿用现有 `.env`：`OPENAI_API_KEY`、`LLM_MODEL`、可选 `OPENAI_BASE_URL`，以及
`LLM_API=chat_completions|responses`。不需要新的密钥或依赖。Responses 沿用
`store=false`。不要把密钥或包含私人材料的运行输出提交到 GitHub。

```bash
python -m examples.critic_live_demo --input path/to/state.json --output output/critic_result.json
```

输入是包含 `papers`、`paper_analysis`、`method_summary`、`research_questions` 的
State，或 `{"state": ...}` 封装。默认不传 `--input` 时读取模拟材料，但结构完整时
响应来自真实模型并产生服务费用。结构缺口则直接 FAIL。输出演示元数据不属于
Graph 节点契约。独立审核 CLI 不递增 `critic_round`。

```python
from research_assistant.agents.critic import critic_node
from research_assistant.graph import build_research_graph

# search_node / reader_node / analyst_node / writer_node 由相应成员提供。
app = build_research_graph(
    search_node=search_node,
    reader_node=reader_node,
    analyst_node=analyst_node,
    critic_node=critic_node,
    writer_node=writer_node,
)
```

成员2应读取 FAIL 的 `critic_result.new_search_queries`，合并并去重已有论文和新结果。
成员3和4应返回更新后的完整阅读与方法分析。成员6应在
`termination_reason == "max_critic_rounds"` 时明确标记“审核未完全通过”，保留所有
未解决问题；达到轮次上限不等于 PASS。`main.py` 的五个 demo stub 保持原有
框架演示用途；正式 Critic 的独立与闭环入口见上文，不会把其他成员 stub 伪装为正式系统。

## 评价口径

评价针对单次运行的最终 State 快照，不代表搜索 API 的全部原始候选；Search 去重
前的重复率需要另行保存原始候选集。标题匹配仅进行 Unicode NFKC、空白和大小写
标准化，不做模糊合并；同标题元数据冲突会报错，跨版本/别名需评审人预先统一。

| 指标 | 分子 / 分母或含义 |
|---|---|
| `paper_count` / `unique_paper_count` | 最终论文条目数 / 标准化标题去重数 |
| `verified_real_paper_count` | 独立标注确认真实存在的唯一论文数 |
| `invalid_paper_ratio` | 独立标注无效数 / 已评价有效性的唯一论文数 |
| `duplicate_rate` | (论文条目数 - 去重数) / 论文条目数 |
| `reference_traceability_rate` | 可匹配 Search 标题的唯一报告引用数 / 唯一报告引用数 |
| `citation_correctness_rate` | 独立核验正确的唯一引用数 / 已核验唯一引用数 |
| `critic_invocations` | 完整历史的审核次数；无历史时取 State 的轮次 |
| `critic_fail_count` | 完整历史中 FAIL 次数；无历史时为 null |
| `report_coverage_rate` | 已覆盖的唯一研究问题数 / 唯一研究问题总数 |

真实性、有效性、引用正确性与覆盖分别提供标注覆盖率和已标注数量。分母为零时为
`null`；引用可追溯并不等于论文真实或结论正确。缺少独立评价不自动计为错误或正确；
报告覆盖率只在全部问题均已评价时计算，部分评价仍报告已覆盖数量和标注覆盖率。
字符串报告不猜测 References，须由 Writer 提供结构化 `FinalReport.references`。
引用字段应沿用精确论文标题；若 Writer 改用编号/DOI，需先显式映射，不能默默匹配。

独立标注格式示例（占位内容需由评审人替换）：

```json
{
  "papers": [
    {"title": "输入论文的精确标题", "is_real": true, "is_valid": true, "note": "数据库永久链接与范围相关性核验记录"}
  ],
  "citations": [
    {"reference": "报告引用的精确标题", "correct": true, "note": "数据库记录、全文页码及该引用支持的具体结论"}
  ],
  "questions": [
    {"question": "原始研究问题", "covered": true, "evidence": "报告中的精确摘录"}
  ]
}
```

`is_real` 核验存在性；`is_valid` 核验论文真实且在当前范围内、可用。二者未核验时
可省略或填 null。所有已判断论文/引用均需核验说明，覆盖为 true 必须附报告中确实
存在的摘录；程序检查对应关系，不替代对摘录含义的人工判断。无法对应输入、重复、
“不真实但有效”的矛盾标注直接报错。

```bash
python -m examples.evaluate_run --input output/run.json --annotations path/to/annotations.json --history path/to/critic_history.json --output output/metrics.json
```

历史文件为按时间排序的 `critic_result` 对象数组，必须包含所有审核，不能仅提供
最后一次判定。输入封装若已有 `critic_history`，可省略 `--history`。

## 消融设计、已运行结果与真实评测协议

`run_ablation(initial_state, node_factory)` 每组重新创建节点并深拷贝 State。已有研究
问题时冻结规划，否则仅运行一次 Coordinator 再冻结；两组使用同一问题与范围。
Graph 新增可选 `coordinator` 注入参数，默认行为不变。Without 组只跳过实际审核，
路由适配器直接进 Writer；输出标记 `critic_bypassed=true`，移除临时 PASS 并将审核
轮次还原为零。With 组正常执行 FAIL 反馈与轮次上限，保留完整审核历史。

离线固定样例复现结果：

| 指标 | Without Critic | With Critic |
|---|---:|---:|
| 论文条目数 | 1 | 2 |
| Critic 实际调用次数 | 0 | 2 |
| FAIL 触发次数 | 0 | 1 |
| 模拟报告问题覆盖率 | 50% | 100% |
| 真实论文数 | 0 | 0 |
| 无效论文比例 | 100% | 100% |
| 真实引用正确率 | 0% | 0% |

模型响应和覆盖标注均为预设，所有论文均为人工构造；这些结果验证闭环、评价公式
和对照隔离，**不能证明真实模型会发现错误或提高报告质量**。增补模拟论文不会被
计为真实论文，也不会提高真实引用正确率。

真实评测时：

1. 事先固定研究主题集合、问题、研究范围、模型与参数、检索源、Top-K、年份过滤、
   最大审核轮次、Writer 配置和实验日期。保留初始检索快照，控制服务时间差。
2. 使用各成员正式节点创建 factory，固定同一 Coordinator 规划；With 允许按反馈
   补检索，Without 不审核。额外检索与模型预算属于实验差异，必须同时报告调用量、
   耗时与费用，避免将额外预算的收益全部归因于审核推理。
3. 导出两组完整 State、每轮检索/审核历史、最终报告。使用数据库记录核验论文，
   独立评审引用是否支持具体结论；盲评时隐藏组别，由评审人逐题判断覆盖。
4. 对每个主题重复成对运行，保存每次原始指标，再报告均值、离散程度和配对差异。
   不能用 Critic 自己的 PASS 作为引用正确率或报告覆盖率标签。
5. 不完整评测保留 null 和标注覆盖率，不将缺失值当零做差；使用 `compare_runs`
   输出双方原始指标及已测数值的 `with - without`。无效比例降低才是改善，差值为负。

当前仓库尚缺正式 Search/Writer 和真实评测标注；本交付没有声称执行了真实领域质量
实验或真实模型请求。获得这些输入后可直接复用上述入口开展真实成对实验。

## 汇报建议（3页）

1. Critic 检查什么：来源/证据、遗漏、过度推断；展示“最有效”断言缺乏对照实验的
   模拟案例，说明单篇论文描述与领域普遍结论的边界。
2. 展示 `FAIL → 新查询 → Search/Reader/Analyst → PASS`，以及连续失败达到上限后
   “审核未完全通过”的保底路径；突出 Agent 对 Agent 的独立审核。
3. 展示指标口径与 With/Without 表格，明确区分已完成的模拟流程验证和待输入真实
   数据的质量实验。不要将 50%→100% 包装成真实系统质量提升。
