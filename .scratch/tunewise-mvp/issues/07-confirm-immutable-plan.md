# 07 — TW-07 确认不可变方案并阻断过期与篡改

**What to build:** 让固定身份 AA 工艺工程师确认一个最新 `PASSED` 候选，形成不可修改的 ConfirmedPlan 并进入 `PLAN_CONFIRMED`；旧候选、STALE 方案、版本冲突和前端替换参数全部被服务端拒绝并审计。

**Blocked by:** 06 — TW-06 生成方向证据、安全参数候选或结构化拒绝。

**Status:** ready-for-agent

## 规格追踪

- 规格章节：6、7.1、17、20、21.4、22.2、23。
- AC：AC-D2-05、AC-D3-04、AC-D6-07。
- HG：HG-05、HG-06、HG-10。

## Acceptance criteria

- [ ] 确认接口只接受 task、candidate_id 和 candidate_hash，不接受 proposed values 或替代参数。
- [ ] 服务端读取候选、重算规范化哈希、复用 ParameterSafetyValidator，并验证候选为最新 `PASSED` 版本。
- [ ] 成功确认创建不可修改 ConfirmedPlan，绑定候选 ID/哈希、服务端参数、固定身份、时间、规则/诊断/控制限/约束快照版本。
- [ ] 确认动作形成包含身份、时间、对象哈希、版本和结果的追加式 AuditEvent。
- [ ] 重新导入、重新检测、重新诊断、当前参数、控制限、约束、规则、候选内容或哈希变化立即使相关候选和 ConfirmedPlan 成为 `STALE`。
- [ ] 非 PASSED、STALE、旧版本、哈希不匹配、前端参数替换或重放旧请求全部确认失败且任务不推进。
- [ ] 成功确认后页面显示已确认方案及 `PLAN_CONFIRMED`，但不泄漏服务端隐藏数据。

## 本票不包含

SimulatorGateway 调用、回放结果、报告、关闭任务或案例提交。

## 独立验证

正常确认一个候选；随后分别修改请求参数、candidate_hash、诊断版本、规则/快照和上游数据，确认 STALE 传播、拒绝结果、审计事件及不可变性。

## TDD 与边界

- 使用 `/tdd`：是。
- SimulatorGateway：不调用。
- FaultTruth / 隐藏场景：不得进入候选、ConfirmedPlan、审计或界面。
- APPROVED 案例：只冻结已有 supporting_case_ids，不重新检索或改变准入。

## Definition of done

- [ ] 本票新增测试及仓库原有测试全部通过。
- [ ] 不删除、跳过或弱化任何测试。
- [ ] 对应 AC/HG 具有可重复验证证据。
- [ ] 如引入新术语，已同步 `CONTEXT.md`；不得改变既有术语语义。
- [ ] 如发现规格冲突，已停止工作并上报，未修改八类冻结决策。
- [ ] 完成后仓库保持可运行和可演示。
- [ ] 本票覆盖的主流程不遗留 TODO、占位返回或假实现。
