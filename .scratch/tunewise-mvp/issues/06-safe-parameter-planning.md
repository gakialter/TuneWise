# 06 — TW-06 生成方向证据、安全参数候选或结构化拒绝

**What to build:** 让 AA 工艺工程师看到 1–3 个“通过当前证据和安全规则生成的候选方案”，包含当前值、建议值、范围、步长、方向证据、支持案例和逐项校验；不满足冻结条件时展示结构化拒绝且没有可确认参数。

**Blocked by:** 05 — TW-05 生成并检索兼容的 APPROVED-only 相似案例。

**Status:** ready-for-agent

## 规格追踪

- 规格章节：9、12、14–16、22、23、24.1。
- AC：AC-D1-04、AC-D3-04、AC-D5-04、AC-D6-01..06、AC-D6-08。
- HG：HG-01..04、HG-08、HG-09、HG-16。

## Acceptance criteria

- [ ] 候选生成仅在任务、异常、证据、最新诊断、当前参数、规则和快照全部满足冻结前置条件时运行。
- [ ] 每个可调整参数先形成版本绑定、无冲突的 ParameterDirectionEvidence；根因属于参数族不能自动放行族内全部参数。
- [ ] CONSERVATIVE、STANDARD、CASE_GUIDED 按冻结 tick/Decimal 规则确定性生成；最多 3 个，完全相同者去重，全零变化剔除并稳定排序。
- [ ] CASE_GUIDED 只使用方向一致、根因/参数族/规则兼容、历史动作安全、回放 SUCCESS 且来自允许训练分区的 APPROVED 案例。
- [ ] 唯一 ParameterSafetyValidator 校验范围、网格、最大变化、标称方向、跨标称、调整数量、参数族、方向证据、版本与 candidate_hash。
- [ ] 离网格当前值返回 `CURRENT_VALUE_OFF_GRID`，所有安全比较使用 tick 或 Decimal，禁止静默取整和二进制浮点边界比较。
- [ ] INSUFFICIENT_EVIDENCE、PLATFORM_INSTABILITY、REFERENCE_DRIFT、Z 门控失败、方向冲突、非法当前值、STALE 输入和全部候选拒绝场景产生零个可确认候选。
- [ ] 拒绝结果包含 refusal_code、message、支持证据、建议检查动作和规则版本。
- [ ] 候选生成、案例引导、排序和安全校验期间 SimulatorGateway、大模型和网络调用均为零。

## 本票不包含

人工确认、SimulatorGateway 回放、自动寻优或最优参数声明。

## 独立验证

演示正常的保守、标准和案例引导候选；运行离网格、越界、跨标称、跨参数族、不可调故障、证据不足、方向冲突、PENDING 案例和全部拒绝场景，核对候选数、拒绝原因、稳定哈希及模拟器零调用。

## TDD 与边界

- 使用 `/tdd`：是，安全规则和拒绝条件必须测试先行。
- SimulatorGateway：全票调用数必须为零。
- FaultTruth / 隐藏场景：不得作为方向、候选、排序或安全校验输入。
- APPROVED 案例：仅兼容且来源合法的案例可引导候选；PENDING 永不使用。

## Definition of done

- [ ] 本票新增测试及仓库原有测试全部通过。
- [ ] 不删除、跳过或弱化任何测试。
- [ ] 对应 AC/HG 具有可重复验证证据。
- [ ] 如引入新术语，已同步 `CONTEXT.md`；不得改变既有术语语义。
- [ ] 如发现规格冲突，已停止工作并上报，未修改八类冻结决策。
- [ ] 完成后仓库保持可运行和可演示。
- [ ] 本票覆盖的主流程不遗留 TODO、占位返回或假实现。
