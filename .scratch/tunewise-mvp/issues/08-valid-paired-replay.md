# 08 — TW-08 通过隔离 SimulatorGateway 完成合法确定性配对回放

**What to build:** 为一个合法、最新且已人工确认的方案实现唯一回放主路径。ReplayOrchestrator 通过隔离 SimulatorGateway 重现导入基线、执行配对模拟干预、分类并保存不可变 ReplayResult，在页面显示前后指标、首次 `attempt_count = 1`、确定性哈希和可信免责声明。

**Blocked by:** 07 — TW-07 确认不可变方案并阻断过期与篡改。

**Status:** ready-for-agent

## 规格追踪

- 规格章节：6、8.4–8.5、9、18.1、18.3–18.7、21.2–21.3、22.3、23。
- AC：AC-D1-05、AC-D4-04、AC-D4-05、AC-D4-07、AC-D7-01、AC-D7-03..05、AC-D7-07、AC-D7-08。
- HG：HG-07、HG-08、HG-09、HG-10、HG-12、HG-14、HG-16；拒绝、异常、并发和幂等的完整证据由 TW-09 承担。

## Acceptance criteria

- [ ] 提供隔离的确定性演示隐藏场景和版本化因果模拟器资产，并把 scenario_ref、generator 版本、种子和资产哈希纳入受控绑定。
- [ ] 运行时应用资产目录与模拟器隐藏资产目录物理或权限边界明确；应用只能持有不透明 scenario_ref 及其哈希，不能枚举或读取隐藏资产内容。
- [ ] 只有 ReplayOrchestrator 的组合根能够装配 SimulatorGateway；其他业务模块不能导入其实现或持有实现引用。
- [ ] SimulatorGateway 契约只接受不透明场景引用、版本、参数、样本数和固定种子/扰动，并只返回可规范化的可观测序列。
- [ ] 契约测试证明 Gateway 永不返回 FaultTruth、primary_fault_truth、nuisance disturbance、内部系数、隐藏参数或潜在扰动明文。
- [ ] 合法回放以原始参数重现基线，并用 ObservableCanonicalizer 比较模拟基线与已导入 canonical_observation_hash；相等后才继续。
- [ ] Baseline Run 与 Intervention Run 使用同一场景、样本数、扰动序列、种子和因果版本，唯一变化是 ConfirmedPlan 参数；不得读取预制调整后结果或按 candidate_id 写死输出。
- [ ] ReplayResultCanonicalizer 固定字段、精度、指标顺序、数组排序、枚举和序列化，并生成确定性 SHA-256 result_hash。
- [ ] 结果按 REGRESSION、SUCCESS、PARTIAL_IMPROVEMENT、NO_IMPROVEMENT 固定优先级分类。
- [ ] 合法路径按 `PLAN_CONFIRMED → REPLAYING → REPLAYED` 推进并创建不可修改 ReplayResult；报告文本不得修改该结果。
- [ ] 首次成功执行不同 ConfirmedPlan 后 `attempt_count = 1`。
- [ ] 回放页面持续显示完整声明：“规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。”
- [ ] 相同合法输入重复执行隔离测试产生相同可观测序列、指标、状态和 result_hash。

## 本票不包含

未确认/STALE/篡改/版本冲突拒绝矩阵、模拟器异常恢复、并发、幂等重试和唯一结果竞争处理；这些由 TW-09 实现。也不包含真实设备、循环试算寻优、报告和案例提交。

## 独立验证

从一个合法 ConfirmedPlan 启动回放，观察基线重现、配对输入、状态推进、四类结果判定、不可变结果、首次 attempt_count 和免责声明；重复运行隔离夹具比较确定性哈希；执行 Gateway 响应白名单和应用/模拟器目录边界测试。

## TDD 与边界

- 使用 `/tdd`：是。
- SimulatorGateway：本票首次引入，但只有 ReplayOrchestrator 可调用。
- FaultTruth：可存在于隔离模拟资产内部，但 Gateway、应用、ReplayResult、日志和 UI 均不得返回或记录。
- 隐藏场景：只由外部模拟环境在受控目录解析；应用仅持不透明引用和哈希。
- APPROVED 案例：不参与回放执行和结果判定。

## Definition of done

- [ ] 本票新增测试及仓库原有测试全部通过。
- [ ] 不删除、跳过或弱化任何测试。
- [ ] 对应 AC/HG 具有可重复验证证据。
- [ ] 如引入新术语，已同步 `CONTEXT.md`；不得改变既有术语语义。
- [ ] 如发现规格冲突，已停止工作并上报，未修改八类冻结决策。
- [ ] 完成后仓库保持可运行和可演示。
- [ ] 本票覆盖的主流程不遗留 TODO、占位返回或假实现。
