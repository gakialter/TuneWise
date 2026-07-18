# 09 — TW-09 安全处理回放拒绝、异常恢复、并发与幂等

**What to build:** 在合法回放主路径之外，为工程师提供安全且可审计的保护行为：未确认、STALE、篡改和版本冲突在调用模拟器前被拒绝；模拟器异常恢复到可重试状态；并发和幂等请求不会重复运行模拟器或创建第二个有效结果；拒绝、失败和重试不增加 `attempt_count`。

**Blocked by:** 08 — TW-08 通过隔离 SimulatorGateway 完成合法确定性配对回放。

**Status:** ready-for-agent

## 规格追踪

- 规格章节：6.2、17、18.2–18.3、18.5–18.6、20、22.2、23.1、23.3。
- AC：AC-D3-05、AC-D6-07、AC-D7-02、AC-D7-03、AC-D7-06。
- HG：HG-05、HG-06、HG-10、HG-11、HG-12。

## Acceptance criteria

- [ ] 启动前验证任务状态、ConfirmedPlan 存在且未过期、候选 ID/哈希/服务端参数、诊断/控制限/约束/规则版本、Manifest 资产哈希、无并发回放及结果唯一性。
- [ ] 未确认、STALE、候选篡改、确认哈希不匹配、快照或版本冲突在 SimulatorGateway 调用前被拒绝，任务保持 `PLAN_CONFIRMED` 或原合法状态。
- [ ] 基线规范化哈希不一致返回 `BASELINE_REPRODUCTION_FAILED`，记录 expected/actual hash、canonicalizer/generator 版本、scenario_ref_hash 和时间，不修改导入数据。
- [ ] 所有回放拒绝创建 ReplayAttempt/AuditEvent，包含 refusal code/message、failed validation、request hash、固定身份和时间，但不创建 ReplayResult。
- [ ] 模拟器执行异常时 `REPLAYING → PLAN_CONFIRMED`，记录 `REPLAY_EXECUTION_FAILED`，不保存不完整结果。
- [ ] 相同 idempotency_key 与 ConfirmedPlan 重试返回已有结果，SimulatorGateway 调用次数不增加。
- [ ] 不同幂等键但相同输入哈希可以安全返回同一结果；同一 ConfirmedPlan 在并发竞争下最多一个有效 ReplayResult。
- [ ] 拒绝、执行失败、并发失败者和幂等重试均不增加 `attempt_count`。
- [ ] 页面明确区分拒绝、执行失败、重试返回和成功结果，不把保护响应呈现为有效改善结果。

## 本票不包含

合法回放算法重写、报告、任务关闭、案例提交或 Windows 打包。

## 独立验证

运行未确认、STALE、参数篡改、哈希/版本/快照冲突、基线不一致、模拟器异常、相同幂等重试和并发竞争矩阵；核对 Gateway 调用计数、状态恢复、ReplayAttempt、唯一有效结果及 attempt_count。

## TDD 与边界

- 使用 `/tdd`：是。
- SimulatorGateway：仅通过 ReplayOrchestrator 调用；所有前置拒绝必须发生在调用前。
- FaultTruth / 隐藏场景：拒绝、失败和审计信息不得包含真值、隐藏内容、系数或 scenario_ref 明文。
- APPROVED 案例：不参与回放拒绝或结果唯一性判断。

## Definition of done

- [ ] 本票新增测试及仓库原有测试全部通过。
- [ ] 不删除、跳过或弱化任何测试。
- [ ] 对应 AC/HG 具有可重复验证证据。
- [ ] 如引入新术语，已同步 `CONTEXT.md`；不得改变既有术语语义。
- [ ] 如发现规格冲突，已停止工作并上报，未修改八类冻结决策。
- [ ] 完成后仓库保持可运行和可演示。
- [ ] 本票覆盖的主流程不遗留 TODO、占位返回或假实现。
