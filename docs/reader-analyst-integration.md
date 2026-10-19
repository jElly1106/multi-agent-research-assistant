# Reader 与 Analyst 对接审查

审查日期：2026-10-17。

基线：Reader 分支实现提交 `99a6a1c`；成员4代码来自本地 main 的
`4939019abe2a032ae63633b5d8bc8cdba3eed33f`。通过 `git show main:<path>`
审阅，尚未把 main 合入 Reader 分支。本文记录静态审查及后续 Reader P0 实现，
不代表与正式 Analyst 联调通过。

后续独立开发更新：Reader 已支持 LLM_API 两种模式、显式严格结构化输出及客户端
参数兼容性；没有引入成员4工厂。P1 本地 PDF 准备层也已独立实现，不接共享 State。
最新 70 项离线验证和边界见 [Reader 交付记录](reader-delivery.md)。下文 29 项是此前
P0 对接准备阶段的历史验证；正式 Analyst 联调仍未完成。

## 已兼容的部分

- 两侧沿用相同的 `PaperAnalysis`，无需新增字段或改变共享 Schema、State、Graph。
- Reader 只返回 `paper_analysis`，Analyst 只返回 `method_summary`，数据可 JSON 序列化。
- Reader 校验输出并用输入标题覆盖模型生成标题，支持多论文和每轮完整替换。
- 空字符串及空列表是 Reader 的保守缺失值。Analyst 将空 datasets/limitations
  显示为“输入材料未提供”，并在总结中记录缺口。Reader 不应把该提示文字写入列表充当事实。
- 年份由 Analyst 从原始 `papers.year` 读取，不需要加到 Reader 输出。

## 接入风险及当前处理状态

| 项目 | 当前行为与风险 | 建议及责任边界 |
| --- | --- | --- |
| 空标题 | Paper 允许空白标题；Analyst 拒绝空白分析标题 | Reader 已跳过空白标题并记录日志，单元测试覆盖 |
| 重复标题 | Analyst 对标题 strip 后去重；不同分析会报冲突 | Reader 已按用户确认策略预检：同名且全部校验后字段相同只分析一次，其他情况在模型调用前抛出 ValueError。Search 仍负责完整列表去重 |
| 原始元数据 | Reader 的 Paper 校验可能接受/转换某些年份，但不改写原始 papers；Analyst 检查原始年份，只接受正整数或 null，并拒绝 bool。它还检查所有 papers 的标题和年份，即使 Reader 已跳过其中某条 | Search 保证原始元数据有效；不能认为 Reader 跳过坏记录后 Analyst 就一定能继续。Reader 不应越权返回修改后的 papers；团队确认失败策略后再处理此路径 |
| 方法信息 | Analyst 需要从阅读材料区分输入模态、融合方式和主干模型 | Reader 提示已明确三类信息仅在摘要支持时写入现有 method 字符串；未增加字段，实际提取质量仍待真实摘要验收 |
| 模型配置 | main 的 llm.py 支持 LLM_API、显式 json_schema/strict、超时及重试，且不强制 temperature；Reader 自建客户端并固定 temperature=0，不读取 LLM_API | main 合入后评估复用 create_structured_model；保留 Reader 的禁用开关、可注入分析器及保守降级。工厂的缺配置 RuntimeError、配置 ValueError 与 Reader 恢复异常需显式适配，不能笼统吞掉编程错误 |
| 联调覆盖 | Reader 现有集成测试的 Analyst 是测试函数；成员4反馈循环测试的 Reader 也是测试函数 | 增加真实 Reader 与真实 Analyst 同时参与的离线测试，使用可注入的合成模型输出，不调用网络 |

标题两侧有空格但内容非空时，Analyst 会同时规范化分析标题和元数据标题，
因此并不必然导致匹配失败；主要问题是空标题及规范化后的冲突。
Analyst 校验分析标题必须出现在 Search 元数据中，但不要求每条 Search 记录都存在分析。
这不等于允许 Reader 无提示地丢弃可用论文，完整输出规则仍适用。

## 实施记录与后续次序

本轮按用户选择不集成 main，不复制成员4模型工厂。已完成 Reader 标题预检、
重复处理、方法提示和离线测试。比较基于 Paper 校验后的字段值，仅标题去除首尾
空格，大小写不折叠，未知额外输入字段不参与比较。保留首次输入标题和顺序。
同名字段冲突不是可恢复的模型错误，不降级为一组空分析。预检完成前不创建分析器。
输入 papers 不变，包括可能被 Pydantic 转换的原始年份；这不能替代 Search 元数据治理。

后续：

1. 将已审阅 main 的改动集成到任务分支，保留 Reader 实现，并检查
   agents/__init__.py 等共同编辑文件。main 合入不是本次文档更新的一部分。
2. 保留本轮已实现的标题策略，不增加稳定 ID 或其他共享字段；未来同名论文身份问题由团队处理。
3. 对齐统一模型工厂及异常策略，补离线配置测试，尤其是 Responses 模式和不接受
   temperature 的模型；禁止在验收日志暴露凭据。
4. 增加真实 Reader → 真实 Analyst 的离线联调测试，再做经授权的真实摘要质量验收。
5. 正式启动入口切换由团队集成时安排；当前 main.py 仍使用 demo 节点。

## 验收覆盖与待办

本轮已覆盖空白标题、相同重复项、空格标题重复、大小写区分、不同摘要/年份/
作者/URL/来源/相关性分数的冲突、输入不变、方法提示和真实 Reader 的图级反馈循环。
原有无摘要、模型失败、空输入等离线测试继续通过。以下正式两节点联调用例仍待补充：

所有测试材料和模型返回值应明确标为 synthetic/mock，不得当作真实论文结论。

- 两篇有效论文：实际 Reader 输出传给 create_analyst_node(mock_model)，检查分类和
  对比表覆盖输入标题，且数据集、局限来自 Reader 而不是 Analyst 模型补造。
- 无摘要/Reader 模型失败：空字段传递成功，Analyst 对比表显示缺失值；
  不要求实际 Analyst 在无模型配置时也自动降级，它目前会抛错。
- 空论文列表：两节点均输出合法空结果，且不调用模型。
- 空白标题、规范化后重复标题、同名不同年份，以及无效年份：按团队确定的
  拒绝/跳过策略断言结果；同时检查原始 papers 保持不变。
- Critic FAIL 后补充论文：同一图内使用实际两节点，第二轮完整替换分析和方法总结，
  不保留已从输入移除的论文，也不遗漏新增论文。
- 方法三类信息的提取提示与缺失行为：mock 测试只验证接口和提示，
  真实摘要评估另行核对事实依据，不能以 Schema 校验替代质量验收。

合入并实现后，可用已安装的测试环境执行
`python -B -m pytest -p no:cacheprovider tests/test_reader.py tests/test_reader_integration.py tests/test_analyst.py tests/test_llm.py tests/test_routing.py`。
当前 Reader 分支尚无后两个 main 新增测试文件，不能把该命令记为已运行或通过。

人工验收：使用明确标为 synthetic 的两篇摘要，分别运行 Reader 与注入 mock 的
Analyst，逐项比对标题、method、datasets、limitations 和缺失提示；再增加第三篇
重跑，确认最终对比表覆盖当前完整列表。该流程待新增联调用例后执行。

## 本次验证结果与人工验收

使用现有 `.venv`、进程级禁用 LLM、注入合成分析器执行：

```powershell
$env:COORDINATOR_USE_LLM='0'
$env:READER_USE_LLM='0'
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider tests/test_reader.py tests/test_reader_integration.py tests/test_routing.py
```

结果：29 passed。未安装依赖、调用真实模型或网络，未合并 main。
本次测试不是正式 Analyst 联调，不能证明模型生成结论的事实正确性。

可复现的离线人工黑盒验收命令（不需要 API Key，不写环境文件）：

```powershell
& .\.venv\Scripts\python.exe -B -c 'import os,json; os.environ["READER_USE_LLM"]="0"; from research_assistant.agents.reader import reader_node; p={"title":"SYNTHETIC Paper","authors":["Synthetic Author"],"year":2026,"abstract":"Synthetic abstract only.","source":"synthetic"}; print(json.dumps(reader_node({"papers":[p,dict(p)]}),ensure_ascii=False,indent=2))'
```

预期：仅一个 paper_analysis 条目，标题为 SYNTHETIC Paper，其他内容为空字符串或空列表；
日志说明 LLM 禁用。把第二条改为 `dict(p, abstract="Different synthetic abstract")` 后重跑，
应抛出标题冲突 ValueError。图级完整替换场景由离线集成测试覆盖。

## 审查基线

已静态核对 main 的 analyst.py、llm.py、INTERFACES.md、schemas.py、
tests/test_analyst.py 与本分支 Reader 实现及测试；共享 schemas.py、state.py、
graph.py 在两个分支间没有差异。初次审查只更新文档；本轮继续修改 Reader 与相关测试，
验证结果见上节。P1/P2 全文能力并非当前接口兼容的前置条件。
