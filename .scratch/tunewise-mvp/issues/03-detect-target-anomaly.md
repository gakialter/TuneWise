# 03 — TW-03 检测四角 MTF 不对称并路由保护分支

**What to build:** 让 AA 工艺工程师从已导入 Batch 启动目标异常检测，查看中心/四角指标、持续性证据和命中规则。系统稳定区分四种检测结果，只有 `TARGET_ANOMALY` 推进到 `ANOMALY_DETECTED`。

**Blocked by:** 02 — TW-02 导入预置 AA CSV 并验证版本化资产、Manifest、哈希与派生指标。

**Status:** ready-for-agent

## 规格追踪

- 规格章节：6、10、22、23.2–23.4、24.3。
- AC：AC-D1-02、AC-D3-04、AC-D5-01、AC-D5-06。
- HG：HG-07、HG-08、HG-09、HG-16。

## Acceptance criteria

- [ ] 版本化 SPC 规则只使用当前 Batch 的可观测 Measurements、派生指标和只读控制限快照。
- [ ] 中心合格/临界、四角异常条件和最小持续次数/样本比例共同决定 `TARGET_ANOMALY`；中心临界不是必要条件。
- [ ] 正确输出并展示 `TARGET_ANOMALY`、`NORMAL`、`NON_TARGET_GLOBAL_DEGRADATION`、`INSUFFICIENT_DATA`。
- [ ] NORMAL、整体退化、数据不足和单点噪声均不能进入诊断主流程。
- [ ] 检测结果包含规则版本、聚合指标、命中条件、持续性证据和输入哈希。
- [ ] 相同输入重复检测产生相同结果与证据。
- [ ] 通过依赖边界和调用计数器证明检测期间 SimulatorGateway、大模型和网络调用均为零。
- [ ] 页面显示检测结果和保护原因，状态迁移由领域逻辑控制。

## 本票不包含

根因模型、证据充足度、案例检索、参数候选和回放。

## 独立验证

用 TARGET、NORMAL、整体退化、数据不足、单点噪声和临界控制限夹具执行检测，核对路由、任务状态、规则证据、确定性和模拟器零调用。

## TDD 与边界

- 使用 `/tdd`：是。
- SimulatorGateway：调用数必须为零。
- FaultTruth / 隐藏场景：不得进入检测输入、结果、日志或 UI。
- APPROVED 案例：不涉及。

## Definition of done

- [ ] 本票新增测试及仓库原有测试全部通过。
- [ ] 不删除、跳过或弱化任何测试。
- [ ] 对应 AC/HG 具有可重复验证证据。
- [ ] 如引入新术语，已同步 `CONTEXT.md`；不得改变既有术语语义。
- [ ] 如发现规格冲突，已停止工作并上报，未修改八类冻结决策。
- [ ] 完成后仓库保持可运行和可演示。
- [ ] 本票覆盖的主流程不遗留 TODO、占位返回或假实现。
