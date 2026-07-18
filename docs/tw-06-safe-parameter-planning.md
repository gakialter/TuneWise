# TW-06 安全参数规划

TW-06 在 `DIAGNOSED` 任务上形成版本化方向证据、最多三组确定性参数候选，或保存结构化拒绝。所有候选仅供查看；本票不包含人工确认、回放、设备写参、结果报告或案例提交。

## 冻结版本

- Direction Rule：`tw-direction-rules-v1`
- Safety Rule：`tw-parameter-safety-v1`
- Planning Rule：`tw-parameter-planning-v1`
- Planning Result：`tw-parameter-planning-result-v1`
- Constraint Snapshot：继续使用 TW-02 的 `tw-parameter-constraints-v1`

离线规则资产位于 `assets/planning/tw-parameter-planning-v1/`。在仓库根目录运行 `generate-parameter-planning-assets.cmd` 可确定性重建；Manifest 固定绑定规则内容和 TW-02 参数约束快照哈希。

## 方向规则

方向证据先于案例动作读取生成。每个轴必须同时满足当前值偏离任务快照中的 `nominal_value`、对应空间特征绝对值至少为 `0.040000`，以及冻结符号关系：

| Top-1 | 参数 | 空间特征 | 符号关系 |
|---|---|---|---|
| `PLANE_TILT` | `pitch` | `top_bottom_difference` | 与当前偏差同号 |
| `PLANE_TILT` | `roll` | `left_right_difference` | 与当前偏差异号 |
| `XY_DECENTER` | `x_offset` | `left_right_difference` | 与当前偏差同号 |
| `XY_DECENTER` | `y_offset` | `top_bottom_difference` | 与当前偏差异号 |
| `Z_DEFOCUS_CONDITIONAL` | `z_offset` | 中心与四角整体观测 | 必须先通过 TW-04 Z 门控 |

满足规则后，调整方向只指向快照标称值。位于标称值、空间轴不受支持或符号冲突的参数不会进入候选。`PLATFORM_INSTABILITY` 与 `REFERENCE_DRIFT` 只返回版本化排查模板。

## 候选与案例边界

- `CONSERVATIVE`：每个可用轴向标称值移动 1 tick。
- `STANDARD`：移动 2 ticks，并截断到当前偏差和单次最大变化。
- `CASE_GUIDED`：仅从当前检索结果中的兼容 `APPROVED`、允许 TRAIN 来源案例收集同方向历史绝对 tick，取中位数并以确定性 `ROUND_HALF_UP` 落到 tick 网格后应用当前方向，再执行相同截断与安全校验。

TW-05 案例索引、标准化器、距离和排序均未改变。TW-06 只在已审核案例展示资产中增加版本化历史 delta 与中心 MTF 容差状态；案例方向不能产生或覆盖当前方向证据。规划输入哈希同时绑定案例索引和案例资产 Manifest，历史动作内容变化不能复用旧候选。相同 `proposed_values` 合并来源和支持案例，固定按总绝对 tick、支持案例数、确定性 `candidate_id` 排序。

## 唯一安全接缝

`ParameterSafetyValidator` 是范围、网格、参数族、方向、标称偏差、跨越标称值、单次最大变化、历史动作安全、版本、tick/delta 一致性以及候选哈希的唯一权威实现。运行时把版本化 JSON 解析为 typed safety/planning policy，Generator、Validator 与服务编排共享同一策略。数值边界使用 `Decimal` 和相对标称值的整数 tick；输入不会静默取整，输出固定为六位小数。

只有 `PASSED` 候选会进入 `ordered_candidates` 并将任务推进到 `PLAN_READY`。业务拒绝以 `PARAMETER_RECOMMENDATION_REFUSED` 持久化，前置状态、过期引用和非法请求另存结构化拒绝审计，任务保持原状态。`candidate_hash` 和业务 `result_hash` 排除创建时间、随机 ID 与展示顺序；相同输入重复调用会先复核当前资产、输入哈希和统一 Validator，再返回同一当前结果。

## 隔离边界

规划运行时只读取当前 Measurement、DerivedFeatureSet、诊断、只读快照、规则资产和当前检索到的已审核案例动作。运行时代码不装配或调用 SimulatorGateway，不读取 FaultTruth、隐藏场景或 `scenario_ref` 内容，不调用 LLM，也不发起外部网络请求。
