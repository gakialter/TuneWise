# TuneWise MVP 实现级正式规格

| 属性 | 值 |
|---|---|
| 规格状态 | Baseline-derived / Implementation-ready |
| 适用版本 | TuneWise MVP v1 |
| 核心场景 | AA 工站首件四角 MTF 不对称下降 |
| 核心用户 | AA 工艺工程师 |
| 部署边界 | 预设 Windows 环境、本地离线、单人比赛演示 |

## 0. 规格权威性与规范用语

本规格将已冻结的 TuneWise MVP 决策转换为可实现、可测试、可验收的外部行为、领域契约和模块边界。它不重新解释或修改冻结决策。

信息冲突按以下优先级处理：

1. `docs/mvp-baseline.md`：八类冻结 MVP 决策的最高优先级事实来源；
2. `CONTEXT.md`：统一术语和语义的唯一依据；
3. `docs/competition/challenge-brief.md`、`part-1.md`、`part-2.md`：仅作为赛事背景、命题目标和早期方案说明。

本文中的“必须”“不得”表示硬性要求；“应”表示除非存在经记录且不改变冻结决策的实现约束，否则必须满足；“可以”表示允许但不构成交付要求。所有 MTF、偏移和角度均使用归一化原型单位，不得解释为舜宇或任何真实设备参数。

## 1. Problem Statement

精密光学装调中的异常诊断往往需要把质量测量、当前工艺参数、平台状态、标定残差和历史处理经验放在同一条可审计的决策链中。比赛阶段不能获得或声称使用舜宇真实产线数据，也不能验证真实设备控制效果，因此 MVP 要解决的问题不是“自动控制设备”，而是：

> 在一个限定的 AA 工站比赛原型场景中，如何仅依赖可观测离线数据，以确定、可解释、可拒绝、可审计的方式识别目标异常，排序根因，检索已审核经验，生成安全参数候选，经人工确认后完成规则约束的离线回放，并将过程沉淀为不污染正式知识库的待审核案例。

唯一目标异常是“中心 MTF 处于合格或临界合格范围，但四角 MTF 存在明显不对称下降”。MVP 不解决普通失焦、整体 MTF 下降、多工站或真实生产闭环。

## 2. Solution

TuneWise MVP 是一个面向 AA 工艺工程师的离线调机决策支持原型。系统通过 CSV 导入可观测批次数据，依次执行：

1. 版本化 SPC 规则与批次聚合指标驱动的目标异常门控；
2. 固定预处理器与 multinomial logistic regression 驱动的 Top-3 根因排序；
3. 版本化证据充足度判断；
4. 仅针对兼容 `APPROVED` 案例的结构化 KNN 检索；
5. 基于 Top-1 根因、参数方向证据、只读约束快照和兼容案例的确定性候选生成；
6. 统一 `ParameterSafetyValidator` 校验和 AA 工艺工程师人工确认；
7. 仅在确认后由 `Replay` 模块调用外部模拟环境，执行确定性配对模拟干预回放；
8. 生成复盘报告、关闭任务并提交 `PENDING_REVIEW` 案例。

异常检测、根因排序、案例检索、候选生成、安全校验和结果判定均为本地确定性程序逻辑。大模型不得进入或改变上述任一环节。MVP 不以大模型、Agent、在线 Embedding、向量数据库或网络 API 作为运行依赖；解释和报告文本由结构化模板生成。

## 3. Actors and Permissions

### 3.1 唯一角色与固定身份

MVP 为单角色、无登录系统，固定演示身份为：

| 字段 | 固定值 |
|---|---|
| `actor_id` | `demo-aa-engineer` |
| `actor_role` | `AA_PROCESS_ENGINEER` |
| `display_name` | `AA工艺工程师` |

该身份只用于演示审计，不映射舜宇真实岗位，不构成认证或授权系统。

### 3.2 允许动作

AA 工艺工程师可以导入离线数据、启动检测/诊断/检索、查看证据、请求并选择已通过校验的参数候选、人工确认候选、启动回放、查看结果、关闭任务、生成报告、提交待审核案例。

### 3.3 禁止动作

AA 工艺工程师不得修改控制限、安全规则、参数范围、步长或评价阈值；不得绕过证据和安全校验；不得向真实设备写参或执行质量放行；不得审批自己提交的案例；不得把 `PENDING_REVIEW` 案例提升为 `APPROVED`；不得读取隐藏场景、`FaultTruth` 或模拟器系数。

## 4. User Stories

| ID | 用户故事 | 完成条件 |
|---|---|---|
| US-01 | 作为 AA 工艺工程师，我要导入预置 AA 批次，以创建可追踪调机任务。 | CSV、Manifest、哈希和必需字段有效，任务进入 `DATA_IMPORTED`。 |
| US-02 | 我希望系统区分目标异常、正常、整体退化和数据不足。 | 只对 `TARGET_ANOMALY` 开放诊断主流程。 |
| US-03 | 我希望看到 Top-3 根因及可核查证据。 | 每个候选含得分、规则、观测、logit 贡献、冲突和可调标记。 |
| US-04 | 我希望知道证据是否足以荐参。 | `INSUFFICIENT_EVIDENCE` 只显示排查顺序和补充检查，不生成候选。 |
| US-05 | 我希望参考相似的已审核案例。 | 检索只使用兼容 `APPROVED` 案例并稳定排序。 |
| US-06 | 我希望获得少量、保守且安全的参数候选。 | 输出 1 至 3 个不同且全部通过统一校验的候选，或结构化拒绝。 |
| US-07 | 我希望确认的方案不可被前端替换。 | 确认绑定候选 ID、哈希、版本、快照、身份和时间。 |
| US-08 | 我希望在确认后查看同一模拟批次的前后对照。 | 回放通过基线重现、配对运行、评价和结果哈希校验。 |
| US-09 | 我希望全过程可复盘。 | 人工确认、回放、关闭和案例提交形成最小审计链。 |
| US-10 | 我希望完成任务后沉淀候选经验但不污染正式知识。 | 新案例为 `PENDING_REVIEW`，不进入检索、荐参或训练。 |
| US-11 | 作为演示者，我希望断网仍可稳定完成五分钟流程。 | 无外部服务依赖，连续运行得到一致核心输出。 |

## 5. 五分钟演示主流程

现场只使用一个预置异常批次，不切换批次，不展示失败恢复、二次调参、案例审核或真实设备操作。

| 时间 | 操作与可见结果 | 目标状态 |
|---|---|---|
| 0:00-0:25 | 导入预置 AA 异常批次 CSV，显示清单与校验通过，创建任务。 | `DATA_IMPORTED` |
| 0:25-1:05 | 显示中心/四角 MTF、最差角落、极差或标准差；标记四角 MTF 不对称下降。 | `ANOMALY_DETECTED` |
| 1:05-2:05 | 显示 Top-3 根因、规则命中、关键观测、logit 贡献/评分依据和 3 个已审核相似案例。 | `DIAGNOSED` |
| 2:05-3:00 | 显示 1-3 个通过安全校验的参数候选及当前值、建议值、范围、步长、联动、方向证据和校验结果；人工确认一组。 | `PLAN_CONFIRMED` |
| 3:00-4:00 | 执行确定性配对模拟干预回放；显示前后中心 MTF、最差角落、四角差异、控制限状态和 `attempt_count = 1`。 | `REPLAYED` |
| 4:00-4:30 | 关闭任务、生成报告、提交待审核案例并在待审核列表显示。 | `CASE_SUBMITTED` |
| 4:30-5:00 | 页面切换、讲解及性能波动缓冲。 | 不改变状态 |

所有阶段与已完成阶段必须在同一闭环导航中清晰可见。前端不得写死诊断、候选或回放结果。

## 6. 任务状态机

### 6.1 状态与进入条件

| 状态 | 进入条件 | 允许的下一状态 |
|---|---|---|
| `CREATED` | 已建立任务和只读版本/规则快照。 | `DATA_IMPORTED` |
| `DATA_IMPORTED` | CSV 格式、字段、Manifest 和完整性校验通过。 | `ANOMALY_DETECTED` |
| `ANOMALY_DETECTED` | 检测结果为 `TARGET_ANOMALY`。 | `DIAGNOSED` |
| `DIAGNOSED` | Top-3、证据和证据状态已持久化。 | `PLAN_READY` |
| `PLAN_READY` | 至少一个不同候选通过统一安全校验。 | `PLAN_CONFIRMED` |
| `PLAN_CONFIRMED` | 用户确认一个未过期 `PASSED` 候选。 | `REPLAYING` |
| `REPLAYING` | 全部回放前置条件通过且合法执行已开始。 | `REPLAYED`；执行异常时回到 `PLAN_CONFIRMED` |
| `REPLAYED` | 唯一有效、不可变 `ReplayResult` 已创建。 | `CLOSED` |
| `CLOSED` | 报告已生成，任务记录保留。 | `CASE_SUBMITTED` |
| `CASE_SUBMITTED` | 已创建 `PENDING_REVIEW` 案例。 | 无 |

### 6.2 状态规则

- 状态只能按表中路径推进；接口重试不得跳过前置状态。
- `NORMAL`、`NON_TARGET_GLOBAL_DEGRADATION`、`INSUFFICIENT_DATA` 是检测保护结果，不得进入 `ANOMALY_DETECTED`。
- `INSUFFICIENT_EVIDENCE` 可以形成 `DIAGNOSED` 结果供排查，但不得进入 `PLAN_READY`。
- 回放前置检查失败时保持 `PLAN_CONFIRMED`；不得创建有效结果。
- 模拟器执行失败时记录 `REPLAY_EXECUTION_FAILED`，从 `REPLAYING` 恢复到 `PLAN_CONFIRMED`，且不保存不完整结果。
- 未 `REPLAYED` 不得关闭；未 `CLOSED` 不得提交案例。
- 任何上游变化触发候选/确认过期时，原状态不得被用来绕过重新生成和重新确认。

## 7. 领域对象及其责任边界

| 对象 | 责任与最小数据 | 不变量/禁止内容 |
|---|---|---|
| `DatasetManifest` | 保存 dataset/schema/generator/rule/model/preprocessing/evaluation/canonicalizer 版本、随机种子、集合清单以及数据/规则/制品哈希。 | 创建后只读；哈希不匹配即拒绝使用。 |
| `Batch` | 标识工站、批次、产品型号、初始参数，并引用控制限和参数规则快照。 | 不包含隐藏真值；批次不可跨数据集合。 |
| `Measurement` | 保存 `sample_index`、时间、5 个参数、平台状态、标定残差和中心/四角 MTF。 | 不保存根因、建议、调整后结果或模糊证据字段。 |
| `DerivedFeatureSet` | 从一个 Batch 的 Measurements 计算固定顺序的批次级指标和特征。 | 可重算；不得接收标签、ID 泄漏字段或回放结果。 |
| `Task` | 聚合任务状态、当前数据版本、最新诊断、候选、确认、回放、报告和案例引用。 | 每类“当前版本”唯一；状态迁移受领域服务控制。 |
| `DiagnosticResult` | 保存异常结果、Top-3、规则、得分、logit 贡献、冲突、证据状态及相关版本。 | 不包含 `FaultTruth`、隐藏场景或模拟器输出。 |
| `ParameterDirectionEvidence` | 保存参数、当前值、标称值、建议方向、支持特征/规则和冲突状态。 | 缺失或冲突的参数不能进入候选。 |
| `ParameterConstraintSnapshot` | 保存产品型号、参数标称值、范围、步长、最大单次变化和规则版本。 | 任务创建后只读；运算基于 tick 或 Decimal。 |
| `ParameterPlanCandidate` | 保存生成类型、根因、前后值、delta、方向证据、支持案例、检查、拒绝、版本和 `candidate_hash`。 | 不可原地修改；仅 `PASSED` 可确认。 |
| `ConfirmedPlan` | 把候选 ID/哈希、参数、版本、快照、固定身份和确认时间绑定为不可修改方案。 | 前端不得提交替换参数；过期后不得回放。 |
| `ReplayEvaluationRuleSnapshot` | 保存中心退化容差、目标改善阈值、控制限和评价规则版本。 | 只读；不得按回放结果临时调整。 |
| `ReplayAttempt` | 记录每次回放启动、拒绝或执行失败及请求哈希、幂等键、身份和时间。 | 被拒绝或失败的尝试不构成有效结果。 |
| `ReplayResult` | 保存配对运行前后指标、检查、版本、输入/输出/结果哈希、状态和免责声明。 | 每个 ConfirmedPlan 最多一个有效结果；创建后不可修改。 |
| `Report` | 引用 Task、DiagnosticResult、ConfirmedPlan 和 ReplayResult 生成复盘文本。 | 不得改写或重算 ReplayResult；必须含免责声明。 |
| `Case` | 保存案例状态、兼容元数据、已审核根因或待审核内容、动作、历史模拟结果和适用条件。 | `PENDING_REVIEW` 与 `APPROVED` 严格隔离；运行时无审批提权。 |
| `AuditEvent` | 记录任务、固定身份、时间、动作、对象引用/哈希、结果或拒绝原因。 | 追加后不可通过业务接口更新或删除。 |

`FaultTruth` 与隐藏场景不是业务领域对象。它们属于隔离的数据生成、训练/评估或外部模拟环境资产，运行时业务系统不得读取其内容。

### 7.1 规范性业务结果契约

下列字段是跨模块传递和持久化的最小规范契约；实现可以增加不改变语义的技术字段，但不得省略、重命名为不同含义或加入隐藏信息。

| 契约 | 必需内容 |
|---|---|
| `DiagnosticResult` | task/batch 引用；anomaly_result；按序 Top-3（类别、得分、显式规则、关键观测、正向 logit 贡献、冲突、可调性）；evidence_status/checks；feature/preprocessing/model/rule 版本；输入哈希；结果版本/哈希。 |
| `ParameterPlanCandidate` | candidate_id；generation_type；root_cause；current_values；proposed_values；deltas；direction_evidence；supporting_case_ids；constraint_snapshot_version；rule_set_version；diagnostic_result_version；validation_checks/status；rejection_reasons；candidate_hash。 |
| `ConfirmedPlan` | confirmed_plan_id/hash；candidate_id/hash；服务端保存的不可变参数值；actor_id/role；confirmed_at；rule_set、diagnostic_result、control_limit_snapshot、parameter_constraint_snapshot 版本；状态（有效或 STALE）。 |
| `ReplayEvaluationRuleSnapshot` | center_regression_tolerance；minimum_corner_min_improvement；minimum_range_reduction；minimum_std_reduction；center_lower_limit；corner_lower_limit；asymmetry_limit；evaluation_rule_version。 |
| `ReplayAttempt` | attempt_id；task/confirmed_plan 引用；idempotency_key；request_hash；actor_id；started_at/occurred_at；执行或拒绝状态；refusal_code/message；failed_validation；失败信息（适用时）。 |
| `ReplayResult` | replay/task/confirmed_plan 引用与确认哈希；dataset/schema/generator/rule/model/evaluation/canonicalizer 版本；scenario/replay_seed/baseline_input/intervention_input/baseline_output/intervention_output/result 哈希；前后中心与四角 MTF、最差角、极差、标准差及变化量；前后控制限状态；result_status；evaluation_checks；created_at；disclaimer。 |
| `Case` | case_id；status；source_task/batch/partition；station_type；product_model；reviewed_root_cause（仅 APPROVED 权威）；parameter_family 或 inspection_action；历史调整动作/模拟结果；适用条件；来源版本和哈希；submitted/review metadata。 |

`ReplayEvaluationRuleSnapshot` 在任务创建时或回放前形成只读版本；一旦被 ConfirmedPlan/ReplayResult 引用即不可替换。`submitted/review metadata` 对 `PENDING_REVIEW` 仅表示提交信息，不授予审核资格。

## 8. 数据模型和数据隔离

### 8.1 Measurement 数据契约

导入 CSV 仅允许以下可观测列：

- 标识/顺序：`sample_index`、`timestamp`；
- 参数：`x_offset`、`y_offset`、`pitch`、`roll`、`z_offset`；
- 平台/标定：`vibration_rms`、`repeat_position_error`、`calibration_residual_x`、`calibration_residual_y`；
- 质量：`mtf_center`、`mtf_lt`、`mtf_rt`、`mtf_lb`、`mtf_rb`。

`corner_mtf_min`、`corner_mtf_range`、`corner_mtf_std`、相对控制限偏差、滚动均值/标准差和最终控制限状态必须由程序计算，不得作为 CSV 权威输入。

### 8.2 单位、坐标和数值

- X/Y/Z 使用 Normalized Offset Unit；Pitch/Roll 使用 Normalized Angular Unit；MTF 范围为 0-1。
- 坐标固定为 `LT=(-1,+1)`、`RT=(+1,+1)`、`LB=(-1,-1)`、`RB=(+1,-1)`；X 向右为正，Y 向上为正。
- 正 pitch 增加上方角落局部焦平面误差；正 roll 增加右侧角落误差；正 z 对全部区域增加同向误差。
- 局部焦平面误差语义为 `z_offset + pitch_coefficient × y_coordinate + roll_coefficient × x_coordinate`，仅属于模拟器内部因果定义。
- 安全运算使用整数 tick 或固定精度 Decimal；MVP v1 每 tick 为 0.05 归一化原型单位。不得用二进制浮点直接做安全边界比较，不得静默取整。

### 8.3 数据分区

| 分区 | 用途 | 可进入训练 | 可进入案例库 | 可用于演示 | 可读取 FaultTruth |
|---|---|---:|---:|---:|---:|
| 训练集 | 拟合预处理器和模型 | 是 | 仅由其形成预置 `APPROVED` 案例 | 否 | 仅隔离训练流程 |
| 验证集 | 冻结阈值和方法选择 | 否 | 否 | 否 | 仅隔离评估流程 |
| 冻结盲测集 | 最终算法评估 | 否 | 否 | 否 | 仅隔离评估流程 |
| 演示批次 | 五分钟现场流程 | 否 | 否 | 是 | 仅模拟器侧隐藏资产 |
| 案例库 | 结构化检索与案例引导 | 否 | 仅预置 `APPROVED` | 间接展示 | 否 |
| 独立检测测试集 | 检测门控评估 | 否 | 否 | 否 | 仅测试元数据（如需要） |

所有训练、验证、盲测、演示和案例来源使用不同 `batch_id` 与随机种子；同一 Batch 的 Measurements 不得跨集合。演示批次主要真值固定为可调 `PLANE_TILT`，但该真值只存在于隔离元数据/隐藏场景，不得进入应用。

### 8.4 FaultTruth 与隐藏场景隔离

- 每个异常 Batch 只有一个 `primary_fault_truth`；Z 向偏移可作为 nuisance disturbance，但不是第二主要标签。
- `FaultTruth` 只允许存在于数据生成资产、离线训练标签和冻结盲测评估标签。
- `FaultTruth` 不得进入导入 CSV、运行时数据库、诊断/检索/荐参输入、API、应用/审计日志、报告、导出或 UI。
- 应用侧仅保存不可解释、不可枚举 `scenario_ref` 及其哈希；隐藏场景内容只能由外部模拟环境在受控目录解析。
- 隐藏场景、内部系数、潜在扰动、生成参数和真值不得进入业务表、特征、接口响应、报告或 UI。

### 8.5 数据完整性

原始文件、规范化观测、规则、快照、模型、预处理器、场景引用、候选、确认方案和回放结果均必须具有版本或 SHA-256 内容哈希。规范化器必须固定字段、顺序、精度、空值、编码和序列化格式。发现版本或哈希不一致时拒绝后续动作并记录审计事件，不得自动修复或覆盖已导入数据。

## 9. 故障模式和责任边界

| 故障模式 | 语义 | 参数行为 |
|---|---|---|
| `PLANE_TILT` | Pitch/Roll 形成稳定空间不对称模式。 | 仅对有方向证据的 pitch/roll 生成候选。 |
| `XY_DECENTER` | X/Y 偏心形成与方向一致且可与倾斜区分的空间下降。 | 仅对有方向证据的 x/y 生成候选。 |
| `PLATFORM_INSTABILITY` | 时间序列方差与重复定位误差增加，不形成固定单角方向。 | 只给平台检查建议，不荐参。 |
| `REFERENCE_DRIFT` | 持续 calibration/reference residual 支持的基准或标定漂移。 | 只给夹具/标定检查建议，不荐参。 |
| `Z_DEFOCUS_CONDITIONAL` | 中心接近下限且四角整体偏低时的条件性 Z 偏移。 | 硬门控通过后仅允许 z_offset。 |

模拟器应使用统一、非线性、有界因果函数，MTF 限于 0-1；局部误差绝对值增大时对应 MTF 单调下降；无故障注入、参数变化或固定种子噪声时不得无原因跳变；不得按故障写死 MTF 结果表。`attempt_count` 不属于隐藏故障生成结果。

## 10. 异常检测

### 10.1 输入和算法

异常检测仅接收当前 Batch 的可观测 Measurements、派生指标和只读原型控制限快照。它不训练模型，使用版本化 SPC 规则和批次级聚合。

### 10.2 `AA_CORNER_ASYMMETRY` 判定

必须同时满足：

1. 中心 MTF 合格或临界合格，且不明显低于中心控制下限；
2. 下列至少一项成立：最差角落低于角落下限、四角极差超过不对称限、四角标准差超过离散限；
3. 异常达到规则定义的最小持续次数或样本比例，不能由单个噪声点触发。

中心 MTF 达到临界下限不得成为目标异常的必要条件。

### 10.3 输出

| 结果 | 行为 |
|---|---|
| `TARGET_ANOMALY` | 进入诊断主流程。 |
| `NORMAL` | 停止主流程并显示未超过原型控制限。 |
| `NON_TARGET_GLOBAL_DEGRADATION` | 进入保护分支，不冒充四角不对称。 |
| `INSUFFICIENT_DATA` | 进入保护分支并指出缺失字段/样本条件。 |

输出同时包含规则版本、聚合指标、命中条件、持续性证据和输入哈希。

## 11. 根因排序

### 11.1 固定流水线

根因排序使用版本固定的 `StandardScaler`、multinomial logistic regression、固定特征顺序和固定随机种子。预处理器与模型共同版本化；不在线训练、不增量学习。

输入仅包含批次级可观测特征：均值、标准差、趋势、四角方向差异、中心与四角相对变化、当前参数、`vibration_rms`、`repeat_position_error` 和 `calibration_residual_x/y`。禁止使用 FaultTruth、隐藏类型/系数、batch_id、集合识别字段、回放结果或案例已审核根因作为模型输入。

### 11.2 类别门控

候选集合固定为五类故障。`Z_DEFOCUS_CONDITIONAL` 仅在中心接近或低于下限、四角整体同向下降且不对称不是主导特征时保留；否则移除并对其余输出重新归一化。硬规则只排除不可能类别、标记冲突或触发证据不足，不得暗中人工加分改变模型排序。

### 11.3 输出与解释

输出稳定排序的 Top-3。每项包含归一化得分/相对概率、显式规则、关键观测、3-5 个主要正向 logit 贡献、必要冲突证据以及“可调整/仅排查”标记。标准化特征值与模型系数乘积必须称为“该特征对当前类别 logit 的贡献”，不得称为概率贡献、因果贡献、SHAP 或真实故障概率。

## 12. 证据充足度

`EvidenceSufficiencyEvaluator` 对最新 DiagnosticResult 产生 `SUFFICIENT_EVIDENCE` 或 `INSUFFICIENT_EVIDENCE`。规则至少考虑 Top-1 得分、Top-1/Top-2 间距、兼容显式规则、关键字段完整性和模型/硬规则冲突；具体阈值由验证集确定并进入版本化规则，用户不可修改。

- `SUFFICIENT_EVIDENCE`：可继续判断根因是否可调并生成方向证据。
- `INSUFFICIENT_EVIDENCE`：仍展示 Top-3 排查顺序与需补充检查项，但参数候选数量必须为 0。

结果必须绑定诊断版本、规则版本和输入特征哈希。

## 13. 结构化案例检索

### 13.1 索引准入

索引只包含来自允许训练数据、`status = APPROVED`、`station_type = AA`、产品兼容且不属于演示或测试批次的案例。`PENDING_REVIEW` 永不进入索引。

### 13.2 特征与排序

检索使用与诊断一致的批次级可观测特征及由允许案例数据拟合的标准化器，采用版本固定的标准化欧氏距离。距离维度不得包含 FaultTruth、已审核根因、动作、结果、batch_id 或 case_id。

两阶段候选池：先检索已审核根因属于当前 Top-3 的兼容案例；不足 3 条时从其余兼容 `APPROVED` 案例补足。根因只用于池筛选和展示，不参与距离计算。排序依次为距离升序、`case_id` 升序，目标返回 3 条。

每条结果展示 case_id、距离/相似度、主要特征差异、已审核根因、历史调整动作、历史模拟结果和适用条件。无相关案例时返回 `NO_RELEVANT_CASE_AVAILABLE`，不得以待审核、测试或演示案例补足。

## 14. 参数方向证据

每个可进入候选的参数必须先形成 `ParameterDirectionEvidence`：

- `parameter_name`、`current_value`、`nominal_value`；
- `recommended_direction`；
- `supporting_features`、`supporting_rules`；
- `conflict_status`；
- 诊断、特征和规则版本引用。

方向证据必须来自当前任务可观测数据和显式规则，不得来自 FaultTruth、模拟器系数、回放试算或案例结果反推。参数缺失方向证据或方向冲突时，该参数不得进入任何候选。根因属于某参数族不等于该族全部参数都可调整。

## 15. 参数候选生成

### 15.1 前置条件

仅当任务为 `DIAGNOSED`、异常为 `TARGET_ANOMALY`、证据为 `SUFFICIENT_EVIDENCE`、最新诊断/控制限/参数快照/规则版本完整且当前参数范围与网格有效时运行。

允许输入仅为当前可观测参数、Top-1 及方向证据、只读约束快照、兼容 `APPROVED` 案例动作和版本化规则。候选生成、排序与安全校验期间模拟器调用次数必须为 0。

### 15.2 参数约束快照

| 参数 | 标称值 | 合法范围 | 步长 | 单次最大变化 | tick 表示 |
|---|---:|---:|---:|---:|---:|
| `x_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 | -20..20，最大 4 |
| `y_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 | -20..20，最大 4 |
| `pitch` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 | -20..20，最大 4 |
| `roll` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 | -20..20，最大 4 |
| `z_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.10 | -20..20，最大 2 |

这些值是 MVP v1 版本化归一化原型约束。实现必须读取快照中的 `nominal_value`，不得假设未来型号标称值恒为零。

### 15.3 确定性生成规则

1. `CONSERVATIVE`：每个有方向证据的参数向标称值移动 1 tick；已在标称值则不调整。
2. `STANDARD`：向标称值移动 2 ticks，不超过当前偏差或单次最大变化。
3. `CASE_GUIDED`：从兼容 APPROVED 案例取同参数族历史调整量中位数，转换到当前方向，按网格取整，截断至单次最大变化，再统一校验。

案例引导仅使用根因一致、参数族一致、规则兼容、历史动作安全、回放 `SUCCESS`、中心未恶化且非测试/演示来源的案例。案例方向与当前方向证据冲突时舍弃案例候选；无兼容案例记录 `NO_COMPATIBLE_APPROVED_CASE`，不影响规则候选。

最多保留 3 个不同候选；完全相同者去重；全零变化不生成。排序固定为总绝对 tick 数升序、支持案例数降序、candidate_id 升序。界面统一称“通过当前证据和安全规则生成的候选方案”，不得称最优或预测最佳。

## 16. ParameterSafetyValidator

`ParameterSafetyValidator` 是候选合法性的唯一权威实现，候选生成、案例引导、确认和回放前复核必须复用同一规则版本，不得在其他模块复制弱化版校验。

每个候选必须验证：

- 当前值与建议值均在范围且位于网格；离网格当前值返回 `CURRENT_VALUE_OFF_GRID`，不得取整；
- 最多调整两个参数且只属于一个参数族；X/Y、Pitch/Roll、Z 不混调；
- 每个变化均有无冲突方向证据且属于 Top-1 允许参数族；
- 建议值缩小相对标称值的绝对偏差，不跨越标称值；
- 单次变化不超过快照上限；
- 候选、诊断、规则和快照均是当前版本；
- candidate_hash 与规范化候选内容一致。

输出包含 `validation_status`、逐项 `validation_checks`、`rejection_reasons`、规则/快照版本和输入哈希。只允许 `PASSED` 进入可确认列表。所有被拒候选只供审计/测试，不得呈现为可确认参数。

拒绝生成时返回 `refusal_code`、`refusal_message`、`supporting_evidence`、`recommended_inspection_actions` 和 `rule_set_version`。非法、过期、证据不足、不可调故障、Z 门控失败、方向缺失/冲突、快照缺失、当前值非法、全部候选被拒、任务状态错误或绕过请求均不得产生可确认参数。

## 17. 候选确认和过期机制

确认接口只接收候选身份，不接收替代参数值。服务端按 candidate_id 读取候选，重算规范化哈希，复用安全校验并验证其为最新 `PASSED` 候选。成功后形成不可修改 ConfirmedPlan，绑定 candidate_id/hash、actor、confirmed_at、rule_set_version、diagnostic_result_version 和约束快照版本。

以下任一变化使相关候选和 ConfirmedPlan 立即成为 `STALE`：重新导入数据、重新检测、重新诊断、当前参数变化、控制限快照变化、参数规则版本变化、候选内容或 candidate_hash 变化。`STALE` 候选不可确认，`STALE` ConfirmedPlan 不可回放。

前端修改请求体、重放旧版本或替换参数时，服务端必须拒绝并记录对象哈希、预期版本、实际版本和固定身份。

## 18. 确定性配对模拟干预回放

### 18.1 隔离边界

因果模拟器是本地外部模拟环境。只有 `Replay` 模块可依赖 `SimulatorGateway`；异常检测、诊断、模型训练、证据判断、案例检索、方向证据、候选生成和安全校验不得导入模拟器、调用其 API、读取 scenario_ref 内容/系数/隐藏状态、利用回放筛选候选或循环试算寻优。

因此在候选生成、诊断和案例检索期间，模拟器调用次数分别必须为 0。大模型不得参与回放结果判定。

### 18.2 回放请求与前置条件

前端只提交 task_id、confirmed_plan_id、confirmed_plan_hash 和 idempotency_key。服务端解析参数、种子、scenario_ref、模拟器/规则版本、原始状态和评价阈值。

启动前必须验证：任务为 PLAN_CONFIRMED；ConfirmedPlan 存在且未过期；ID/哈希/服务端候选内容一致；诊断、控制限、参数约束和规则版本未变化；dataset/schema/generator 版本完整；原始数据、规则和 scenario_ref 哈希与 Manifest 一致；无正在执行回放；当前 ConfirmedPlan 尚无有效 ReplayResult，或请求为相同幂等请求。

### 18.3 基线重现

`ObservableCanonicalizer` 固定可观测字段、记录排序、小数精度、空值、编码和序列化，排除文件名、换行及无业务元数据。Manifest 保存 raw_file_hash、canonical_observation_hash 和 canonicalizer_version。不得把模拟输出哈希与原始 CSV 文件字节哈希直接比较。

回放前以原始参数重放基线，用同一规范化器计算 `simulated_baseline_canonical_hash`。只有它与导入 CSV 的 canonical_observation_hash 相等才继续；否则返回 `BASELINE_REPRODUCTION_FAILED`，记录 expected_hash、actual_hash、canonicalizer/generator 版本、scenario_ref_hash 和 failed_at，不修改导入数据。

### 18.4 配对运行

基线运行和干预运行使用同一隐藏场景、样本数、潜在扰动序列、回放种子和因果函数版本，唯一变化是 ConfirmedPlan 参数。不得读取预制“调整后结果”，不得按 candidate_id 返回固定结果。

`ReplayResultCanonicalizer` 固定结果字段、精度、指标顺序、数组排序、状态枚举和序列化；结果哈希为 SHA-256。相同 dataset_version、scenario_ref_hash、confirmed_plan_hash、generator_version、rule_set_version、evaluation_rule_version 和 replay_seed 必须产生相同 result_hash。

### 18.5 结果判定

按固定优先级判定：

1. `REGRESSION`：中心超容差下降、最差角显著下降、四角差异恶化、控制限状态更差或保护指标退化任一成立；
2. `SUCCESS`：非退化、中心不超容差、最差角和四角差异达到改善阈值、达到目标控制限、保护指标全通过；
3. `PARTIAL_IMPROVEMENT`：非退化且至少一个目标改善达标，但未满足全部成功条件；
4. `NO_IMPROVEMENT`：非退化且所有目标变化均未达到最小改善阈值。

拒绝不创建结果状态，只创建 ReplayAttempt/AuditEvent。合法启动为 PLAN_CONFIRMED -> REPLAYING；成功为 REPLAYING -> REPLAYED；执行异常恢复 PLAN_CONFIRMED。

### 18.6 幂等、结果和尝试次数

同一 idempotency_key 与 ConfirmedPlan 重试不得重复调用模拟器，返回既有结果。不同幂等键但输入哈希相同可返回相同结果；同一 ConfirmedPlan 最多一个有效 ReplayResult。

ReplayResult 必须保存任务/确认引用、全部相关版本、canonicalizer/scenario/seed 哈希、基线与干预输入/输出哈希、result_hash、前后中心/四角/最差角/极差/标准差、变化量、控制限状态、result_status、evaluation_checks、created_at 和免责声明。

`attempt_count` 仅表示当前任务中已人工确认并实际执行回放的不同方案数量。首次有效回放后为 1；拒绝、失败或幂等重试不得增加。

人工排障平均尝试次数与系统辅助尝试次数的比较只允许出现在独立离线评估实验中，不得伪装为单次 ReplayResult 的模拟输出。

### 18.7 强制可信声明

回放页、复盘报告和导出材料持续显示：

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。

## 19. 知识案例状态

### 19.1 状态与行为

| 状态 | 来源 | 可检索 | 可用于荐参 | 可用于模型训练 | MVP 中可发生的迁移 |
|---|---|---:|---:|---:|---|
| `PENDING_REVIEW` | 已关闭任务由 AA 工艺工程师提交 | 否 | 否 | 否 | 无 |
| `APPROVED` | 随交付资产预置、来自允许进入案例库的训练数据 | 是 | 是（还须满足兼容规则） | 不作为在线训练输入 | 无 |

MVP 不实现审核角色、审批页面或 `PENDING_REVIEW -> APPROVED` 迁移。待审核列表只证明候选案例已提交，不表示知识已生效。

### 19.2 案例提交

仅 `CLOSED` 任务可提交。提交内容引用任务的异常现象、可观测证据、诊断、确认动作、ReplayResult、适用条件和所有相关版本/哈希。重复提交同一任务应幂等返回既有 `PENDING_REVIEW` 案例，不创建重复知识条目。

案例索引构建和每次查询都必须应用 `status = APPROVED` 过滤，形成双重防护。任何 `PENDING_REVIEW` 命中都属于硬门槛失败。

## 20. 审计链

最小审计链覆盖：人工确认、回放启动/拒绝/失败/完成、任务关闭、报告生成和案例提交。每个 AuditEvent 至少包含：

- `event_id`、`task_id`、动作类型；
- 固定 `actor_id`、`actor_role` 和 `display_name`；
- `occurred_at`；
- 目标对象 ID、内容哈希和相关版本；
- 动作结果、拒绝码或失败码；
- 幂等请求标识或请求哈希（适用时）。

事件以追加方式持久化，业务接口不得更新或删除。审计链不得记录 FaultTruth、scenario_ref 明文、隐藏场景、模拟器系数或敏感环境信息。报告可引用审计事件，但不得改写事件内容。

## 21. Implementation Decisions

### 21.1 运行形态

- 交付形态是预设 Windows 环境中的本地离线应用；完整主流程不依赖网络、云服务、在线模型、真实设备、MES 或 QMS。
- 采用模块化单体或等价的本地模块组织；本规格约束模块依赖方向和接口，不约束具体框架或文件布局。
- 核心决策链为同步、确定性应用服务；耗时回放可以有明确的 `REPLAYING` 状态，但同一任务不得并发执行两个回放。
- 所有用户可见解释和报告内容使用结构化模板。MVP 不需要大模型；未来引入也不得改变核心输出。

### 21.2 确定性与版本

- 固定特征顺序、模型/预处理器/规则/索引/模拟器/规范化器/评价规则版本和随机种子。
- 所有安全数值使用 tick 或固定精度 Decimal；所有内容哈希基于版本化规范化表示并使用 SHA-256。
- 确定性 ID 若包含随机成分，不得参与业务排序；所有稳定排序必须显式给出 tie-breaker。
- 时间戳和身份参与审计但不得改变检测、诊断、检索、候选或回放指标。

### 21.3 数据与信任边界

- CSV 和 Manifest 是外部输入边界，先校验后持久化；前端只提交标识与意图，不提交服务端权威参数、种子、版本或阈值。
- 业务运行时只能读取可观测数据、派生特征和允许的 APPROVED 案例视图。
- 训练/评估标签目录与隐藏模拟场景目录属于隔离资产；必须证明未被业务包导入、扫描或响应序列化。
- 只有 ReplayOrchestrator 可持有 SimulatorGateway；通过依赖规则和测试调用计数共同验证隔离。

### 21.4 不可变性与过期

DiagnosticResult、ParameterPlanCandidate、ConfirmedPlan、ReplayEvaluationRuleSnapshot、ReplayResult 和 AuditEvent 以新建版本表达变化，不进行原地业务修改。上游版本变化通过显式 `STALE` 标记或等价不可用判定传播到下游。

## 22. 接口和模块边界

### 22.1 模块依赖

| 模块 | 允许输入/依赖 | 主要输出 | 明确禁止 |
|---|---|---|---|
| `ImportAndIntegrity` | CSV、Manifest、规则/资产读取、规范化器、哈希器 | Batch、Measurements、快照、校验结果 | FaultTruth、模拟器隐藏场景内容 |
| `FeatureEngineering` | Measurements、控制限快照、固定特征定义 | DerivedFeatureSet | 标签、案例动作、回放结果 |
| `AnomalyDetection` | DerivedFeatureSet、SPC 规则快照 | 检测结果与规则证据 | 模型、LLM、模拟器 |
| `RootCauseDiagnosis` | DerivedFeatureSet、固定预处理器/模型、类别门控 | DiagnosticResult | FaultTruth、ID 泄漏、案例标签输入、模拟器 |
| `EvidenceSufficiency` | DiagnosticResult、字段完整性、证据规则 | 证据状态与检查 | 用户阈值、LLM |
| `CaseRetrieval` | 查询特征、APPROVED-only 索引、Top-3 筛选信息 | 稳定排序案例结果 | PENDING_REVIEW、FaultTruth、模拟器、在线 Embedding |
| `DirectionEvidence` | 最新诊断、观测特征、显式方向规则、快照 | ParameterDirectionEvidence | 模拟器系数/试算、隐藏真值 |
| `ParameterPlanning` | Top-1、方向证据、约束快照、兼容 APPROVED 动作 | 0-3 个候选或结构化拒绝 | 回放结果、模拟器调用、不可调根因荐参 |
| `ParameterSafetyValidator` | 候选、方向证据、快照、版本 | PASSED/REJECTED 与逐项检查 | 静默取整、分散弱校验 |
| `PlanConfirmation` | candidate_id/hash、当前任务/版本、固定身份 | ConfirmedPlan | 前端参数覆盖、STALE 确认 |
| `ReplayOrchestrator` | ConfirmedPlan、Manifest、评价快照、SimulatorGateway、幂等存储 | ReplayAttempt/ReplayResult | 未确认/过期回放、用户覆盖种子或阈值 |
| `ExternalSimulator` | scenario_ref、参数、固定种子/扰动、版本 | 可规范化观测序列 | 业务诊断、案例检索、用户界面 |
| `KnowledgeCase` | Closed Task、报告/结果引用、APPROVED 索引 | PENDING_REVIEW Case、检索视图 | MVP 内审核提权、待审核索引 |
| `AuditAndReport` | 不可变领域结果、模板、固定身份/时钟 | AuditEvent、Report/导出 | 改写回放结果、泄漏隐藏信息 |

### 22.2 领域接口契约

下列接口名称是稳定职责名；实现语言签名可按技术栈表达，但不得合并信任边界或改变输入输出语义。

| 接口 | 请求 | 成功响应 | 保护响应 |
|---|---|---|---|
| `importBatch` | CSV 内容/引用、Manifest 引用 | Task、Batch、校验摘要、`DATA_IMPORTED` | 字段/格式/哈希/版本错误；任务不推进 |
| `detectAnomaly` | task_id、当前数据版本 | 检测结果、指标、规则证据、版本 | 状态错误、数据过期；非目标结果阻断主流程 |
| `diagnoseRootCause` | task_id、最新检测引用 | Top-3、解释、证据状态、版本 | 状态/版本错误；不得调用模拟器 |
| `retrieveApprovedCases` | task_id、诊断引用、Top-K | 3 条稳定排序结果或无相关案例状态 | 索引版本错误；PENDING 永不返回 |
| `generateParameterPlans` | task_id、最新诊断引用 | 1-3 个 PASSED 候选，或结构化拒绝 | 任一拒绝条件；模拟器调用为 0 |
| `confirmParameterPlan` | task_id、candidate_id、candidate_hash | 不可变 ConfirmedPlan、审计事件 | 非 PASSED、STALE、篡改或版本冲突 |
| `startReplay` | task_id、confirmed_plan_id/hash、idempotency_key | ReplayResult 或同幂等结果 | 前置失败/基线失败/执行失败及 ReplayAttempt |
| `closeTask` | task_id | Report 引用、`CLOSED` | 未 REPLAYED 或结果不完整 |
| `submitCase` | task_id | PENDING_REVIEW Case、`CASE_SUBMITTED` | 未 CLOSED；重复请求幂等返回 |

### 22.3 外部模拟环境端口

SimulatorGateway 只暴露“按不透明场景引用、版本、参数、样本数和固定种子运行并返回可观测序列”的能力。它不得向调用方返回故障类型、nuisance disturbance、系数或隐藏参数。业务模块不得持有其实现引用；只有 ReplayOrchestrator 的组合根可以装配该端口。

## 23. Testing Decisions

### 23.1 最小测试接缝

为验证冻结要求而不扩大产品范围，必须提供以下可替换或可观测接缝：

| 接缝 | 用途 |
|---|---|
| `Clock` | 固定审计/确认时间；证明时间不影响核心决策。 |
| `IdGenerator` | 生成可预测测试 ID；排序不得依赖随机 ID。 |
| `AssetReader` + `ContentHasher` | 注入正常/篡改资产并验证拒绝。 |
| `ModelArtifactProvider` | 锁定预处理器、模型、特征顺序和版本。 |
| `ApprovedCaseIndexProvider` | 注入 APPROVED/PENDING/跨集合案例，验证过滤与稳定排序。 |
| `SimulatorGateway` 测试替身与调用计数器 | 证明诊断、检索、荐参调用数为 0，回放配对调用受控且幂等。 |
| `IdempotencyStore` | 验证重复回放/案例提交不重复执行。 |
| `ObservableCanonicalizer` / `ReplayResultCanonicalizer` 固定夹具 | 验证跨换行/顺序等规范化与哈希确定性。 |

这些接缝只服务测试和模块隔离，不形成用户可配置项，不允许前端注入种子、阈值、模型或模拟器。

### 23.2 单元测试

至少覆盖：MTF 派生指标；SPC 门控；持续性/比例；固定特征聚合；类别门控；logit 贡献；证据充足度；KNN 过滤、标准化、两阶段池和稳定排序；tick/Decimal；方向证据；ParameterSafetyValidator 全部规则；候选生成/去重/排序；规范化与哈希；STALE 传播；回放状态优先级；免责声明。

### 23.3 集成与保护分支测试

集成测试覆盖完整状态机、导入到诊断、诊断到候选、确认与过期、基线重现与配对回放、幂等回放、案例提交/状态隔离和审计链。

保护分支覆盖 CSV 字段缺失/格式错误、NORMAL、NON_TARGET_GLOBAL_DEGRADATION、INSUFFICIENT_DATA、INSUFFICIENT_EVIDENCE、不可调故障、所有候选被拒、未确认回放、过期方案、基线重现失败和模拟器执行失败。

### 23.4 泄漏与隔离测试

- 验证 Batch 级切分以及训练、验证、盲测、案例库和演示批次集合互斥；
- 扫描业务包、运行时数据库、API、日志、审计、报告、导出和 UI，不得出现 FaultTruth 或隐藏场景内容；
- 隔离标签目录本身不做“内容不得含 FaultTruth”扫描，但必须验证运行时未打包、导入或访问该目录；
- 用调用计数器证明异常检测、诊断、检索、方向证据、候选生成与安全校验的模拟器调用均为 0；
- 验证只有 ReplayOrchestrator 能触发 SimulatorGateway。

### 23.5 人工验收

在预设 Windows 环境中断网，从干净交付包一键启动，按脚本在 4 分 30 秒内完成主流程，连续成功至少 3 次，每次核心诊断、案例顺序、候选和回放结果一致，且启动、页面切换和回放无阻断错误。备份录像只作为投影/设备故障应急，不能替代可运行应用。

不设置单纯代码覆盖率门槛；测试以外部行为、风险边界和完整闭环为准。

## 24. 硬门槛与算法质量指标

### 24.1 硬门槛

任一项失败，MVP 不得标记为可交付：

| ID | 门槛 |
|---|---|
| HG-01 | 非法参数拦截率 = 100%；PASSED 候选合法率 = 100%。 |
| HG-02 | INSUFFICIENT_EVIDENCE 产生可确认候选数量 = 0。 |
| HG-03 | PLATFORM_INSTABILITY/REFERENCE_DRIFT 产生候选数量 = 0。 |
| HG-04 | PENDING_REVIEW 进入检索/荐参数量 = 0。 |
| HG-05 | STALE 候选确认数和 STALE ConfirmedPlan 回放数均为 0。 |
| HG-06 | 未人工确认直接回放数 = 0；前端篡改候选成功数 = 0。 |
| HG-07 | FaultTruth 或隐藏模拟信息进入业务运行时数量 = 0。 |
| HG-08 | 诊断、案例检索、候选生成期间模拟器调用次数分别 = 0。 |
| HG-09 | 固定输入 10 次核心输出完全一致。 |
| HG-10 | 数据、Manifest、规则、快照、模型、预处理器、scenario_ref、候选/确认内容、哈希或版本篡改全部被检测。 |
| HG-11 | 相同幂等请求不重复运行模拟器；同一 ConfirmedPlan 不创建第二有效 ReplayResult。 |
| HG-12 | 基线规范化哈希不一致必须返回 BASELINE_REPRODUCTION_FAILED。 |
| HG-13 | 断网可完成完整演示主流程。 |
| HG-14 | 回放页、报告和导出均包含完整免责声明。 |
| HG-15 | 演示、训练、验证、盲测与案例库满足冻结隔离规则。 |
| HG-16 | 大模型参与异常检测、根因排序、案例检索、参数生成、安全校验或结果判定的调用/影响数量 = 0。 |

### 24.2 固定测试资产

- 训练集不少于 200 Batch；验证集不少于 50 Batch；冻结盲测集不少于 100 Batch；
- 盲测集中五类主要故障各不少于 20 Batch，并包含临界、重叠和高噪声边界样本；
- 预置 APPROVED 案例不少于 60，且只来自允许的训练数据；
- 独立检测集覆盖 NORMAL、TARGET_ANOMALY、NON_TARGET_GLOBAL_DEGRADATION、INSUFFICIENT_DATA、单点噪声和临界控制限；
- 演示批次完全独立；同一 Batch 不跨集合；各集合使用不同 batch_id 和种子；
- 最终评估前冻结全部版本、集合清单、种子和文件内容哈希。

### 24.3 异常检测指标

- TARGET_ANOMALY Precision >= 0.90；
- TARGET_ANOMALY Recall >= 0.90；
- NON_TARGET_GLOBAL_DEGRADATION 错误进入主流程 = 0；
- 单点噪声误触发率 <= 5%；
- INSUFFICIENT_DATA 正确阻断率 = 100%。

报告给出每类样本数、混淆矩阵、Precision/Recall/F1、错误路由明细和 SPC 规则版本。

### 24.4 根因排序指标

冻结盲测集按 Batch 计算：Top-1 >= 0.60、Top-3 >= 0.85、macro-F1 >= 0.60，且三项均优于历史频率固定排序基线。

报告区分模型独立评估和端到端业务评估；端到端还报告可调故障正确进入荐参比例、不可调故障候选数（必须 0）、证据不足候选数（必须 0）、Z 门控错误放行数和拒绝原因分布。`Z_DEFOCUS_CONDITIONAL` 不得从模型独立盲测结果静默删除。

### 24.5 案例检索指标

相关案例要求 APPROVED、工站/产品兼容、reviewed_root_cause 与查询真实评估标签一致、参数族或排查动作兼容且历史结果符合准入。Recall@3 >= 0.70、Recall@5 >= 0.85；标准化结构化 KNN 的 Recall@3 至少比未标准化 KNN 高 5 个百分点。

`NO_RELEVANT_CASE_AVAILABLE` 不进入 Recall 分母，但必须报告数量。报告按类别给出总查询、有/无相关案例、Recall@3/5 和失败明细。

## 25. 对照基线

| 能力 | 固定基线 | TuneWise 对比要求 |
|---|---|---|
| 异常检测 | 无持续条件的单样本控制限判断 | 报告目标检测与单点噪声表现。 |
| 根因排序 | 训练集根因频率固定排序 | Top-1、Top-3、macro-F1 均应优于基线。 |
| 案例检索 | 未标准化批次特征欧氏距离 KNN | Recall@3 至少高 5 个百分点。 |
| 参数风险 | 直接复用最近兼容案例调整量，不做范围/步长/联动/方向校验 | 仅离线统计非法建议比例，不进入应用、不生成可确认计划、不调用设备或模拟器。 |

未优于基线的结果必须如实报告，不得只展示绝对指标。

## 26. 验收标准

以下条件采用“给定/当/则”语义执行，并与八类冻结决策一一关联。

### 26.1 决策 1：唯一工站和异常场景

- **AC-D1-01**：给定任意导入数据，当创建任务时，则仅接受 AA 工站场景；系统和材料不得声称为舜宇真实工站事实。
- **AC-D1-02**：给定中心合格/临界且四角不对称持续越限 Batch，当检测时，则结果为 TARGET_ANOMALY；普通整体失焦不得进入该主流程。
- **AC-D1-03**：给定诊断候选集合，则只包含五类冻结故障，Z 类仅在条件门控通过时出现。
- **AC-D1-04**：给定 Top-1 为 PLANE_TILT、XY_DECENTER 或门控通过的 Z 类，则只允许对应参数族；平台不稳定与基准漂移候选数为 0。
- **AC-D1-05**：给定有效回放，则成功判据使用中心不超容差、最差角改善、四角差异降低和控制限状态；首次回放 attempt_count 为 1。

### 26.2 决策 2：核心用户及权限边界

- **AC-D2-01**：应用无需注册/登录/RBAC，所有需审计动作使用固定 AA 工艺工程师身份。
- **AC-D2-02**：任何用户请求都不能修改控制限、参数约束、步长、安全或评价规则快照。
- **AC-D2-03**：应用不存在真实写参、质量放行或知识审批能力。
- **AC-D2-04**：任务提交只创建 PENDING_REVIEW；MVP 中无接口可将其提升为 APPROVED。
- **AC-D2-05**：人工确认、回放和案例提交均有身份、时间、动作及对象哈希审计记录。

### 26.3 决策 3：五分钟主流程和状态机

- **AC-D3-01**：断网环境中，预置单批次按状态顺序完成至 CASE_SUBMITTED，不跳步。
- **AC-D3-02**：主流程人工操作在 4 分 30 秒内完成，保留约 30 秒缓冲，并连续成功演练至少 3 次。
- **AC-D3-03**：页面清晰显示当前和已完成阶段；核心结果由程序逻辑生成而非前端写死。
- **AC-D3-04**：字段/格式错误、非目标、证据不足、非法/全拒候选、未确认回放、未回放关闭和待审核污染均被保护分支阻断。
- **AC-D3-05**：模拟器异常时 REPLAYING 回到 PLAN_CONFIRMED，记录失败且无不完整 ReplayResult。
- **AC-D3-06**：相同演示输入连续 10 次的检测、Top-3/得分/贡献、案例顺序、候选/哈希、确认哈希、回放指标/状态/哈希完全一致。

### 26.4 决策 4：数据、故障和模拟因果规则

- **AC-D4-01**：Measurement 只含冻结可观测字段；派生指标由程序计算；运行时无 FaultTruth。
- **AC-D4-02**：训练、验证、盲测、演示和案例来源按 Batch 隔离，集合、ID、种子和哈希检查全部通过。
- **AC-D4-03**：运行时包、数据库、接口、日志、审计、报告、导出与 UI 的 FaultTruth/隐藏信息扫描结果为 0。
- **AC-D4-04**：应用只保存 scenario_ref 及哈希，不能枚举或读取隐藏场景；业务系统不读取模拟器系数。
- **AC-D4-05**：因果模拟器满足有界、单调、可区分、固定种子无无因跳变和非结果表写死要求。
- **AC-D4-06**：CSV、Manifest、规则、快照、模型、预处理器、scenario_ref 和版本任一篡改均被检测并阻断。
- **AC-D4-07**：基线与干预仅改变 ConfirmedPlan 参数，同场景/样本/扰动/种子/因果版本保持一致。

### 26.5 决策 5：检测、排序、证据和检索

- **AC-D5-01**：独立检测集达到 Precision/Recall、整体退化误路由、噪声误触发和数据不足阻断指标。
- **AC-D5-02**：逻辑回归只使用允许可观测特征，固定预处理/特征顺序/种子/版本，盲测按 Batch 达到 Top-1/Top-3/macro-F1 门槛。
- **AC-D5-03**：Top-3 解释严格使用 logit 贡献术语并展示规则、观测、冲突和可调性。
- **AC-D5-04**：证据不足仍可显示排查顺序，但可确认参数数量为 0。
- **AC-D5-05**：案例索引与查询只返回 APPROVED，采用冻结标准化 KNN、两阶段池和稳定 tie-breaker，达到 Recall 门槛。
- **AC-D5-06**：异常检测、根因排序和案例检索期间模拟器调用次数均为 0；大模型在三项决策中的调用或影响数量为 0，网络依赖为 0。

### 26.6 决策 6：候选、安全和拒绝

- **AC-D6-01**：只有状态、异常、证据、快照、当前值和最新版本全部有效时才运行候选生成。
- **AC-D6-02**：每个候选参数均有无冲突 ParameterDirectionEvidence，且只属于 Top-1 允许族。
- **AC-D6-03**：保守、标准、案例引导规则确定执行，最多 3 个、去重、零变化剔除并按固定顺序返回。
- **AC-D6-04**：ParameterSafetyValidator 对范围、网格、最大变化、标称方向、跨标称、参数数目/族和证据统一校验；非法拦截率与 PASSED 合法率均 100%。
- **AC-D6-05**：离网格当前值返回 CURRENT_VALUE_OFF_GRID 且不静默取整；所有比较使用 tick 或 Decimal。
- **AC-D6-06**：PENDING、测试或演示案例不参与案例引导；无兼容 APPROVED 案例不阻断规则候选。
- **AC-D6-07**：确认绑定候选哈希和版本；前端替换参数、旧候选、STALE 候选均确认失败。
- **AC-D6-08**：候选生成、排序和校验期间模拟器调用次数为 0；大模型在参数生成和 ParameterSafetyValidator 中的调用或影响数量为 0；不得试算寻优。

### 26.7 决策 7：配对回放和可信声明

- **AC-D7-01**：只有 ReplayOrchestrator 可调用 SimulatorGateway；其他核心模块在构建依赖和运行调用计数上均为 0。
- **AC-D7-02**：未确认、STALE、哈希/版本/快照不匹配、并发或篡改请求不启动模拟器且不创建结果。
- **AC-D7-03**：基线规范化哈希不一致返回 BASELINE_REPRODUCTION_FAILED 并记录预期/实际哈希与版本。
- **AC-D7-04**：配对运行固定除 ConfirmedPlan 外全部输入，不读取预制调整后结果，固定输入产生固定 result_hash。
- **AC-D7-05**：结果按 REGRESSION、SUCCESS、PARTIAL_IMPROVEMENT、NO_IMPROVEMENT 固定优先级判定且不可修改。
- **AC-D7-06**：相同幂等请求不重复调用模拟器；同一 ConfirmedPlan 只有一个有效 ReplayResult；失败/拒绝/重试不增加 attempt_count。
- **AC-D7-07**：回放页、报告、导出持续显示完整免责声明，且无真实产线或真实良率因果声明。
- **AC-D7-08**：回放结果状态只由冻结 ReplayEvaluationRuleSnapshot 与确定性规则判定，大模型调用或影响数量为 0。

### 26.8 决策 8：测试、指标和交付

- **AC-D8-01**：所有 HG-01 至 HG-16 通过后才可标记可交付。
- **AC-D8-02**：测试资产规模、五类支持数、边界难例、集合清单、版本、种子和哈希按冻结要求形成 Manifest。
- **AC-D8-03**：算法报告包含检测、根因、检索、端到端安全、拒绝分布、支持数、混淆矩阵和基线对比；未达门槛如实报告。
- **AC-D8-04**：盲测未达标时不得改标签、删难例、重生成简单集合或加入演示批次；方法变化必须生成新版本并完整重评。
- **AC-D8-05**：交付包在预设 Windows 环境断网、一键启动、连续演练满足人工验收。
- **AC-D8-06**：最终交付物清单完整，且不包含任何“明确不交付”项或企业私有信息。

## 27. 最终交付物

1. TuneWise Windows 离线应用包：一键启动、无网络依赖、不连接真实设备；
2. 完整源代码：可重复构建，含开发、启动、测试、数据生成和评估命令，无密钥/企业私有信息；
3. 版本化数据与模拟资产：演示 CSV、集合清单、Manifest、规则、约束、隔离标签、隐藏场景、版本和哈希；
4. 固定算法制品：预处理器、逻辑回归模型、特征定义、APPROVED 案例索引及版本；
5. 离线评估报告：检测/根因/检索/基线/支持数/混淆矩阵/拒绝/安全/确定性结果、版本哈希、限制和可信声明；
6. 演示材料：五分钟脚本、操作步骤、备份录像、关键截图和故障应急步骤；
7. 最小文档集：README、一键运行、数据字典、生成与切分、模型与规则、参数安全、模拟回放、可信声明、测试记录、CONTEXT、MVP 基线和本正式规格。

## 28. Out of Scope

- 真实设备连接、设备日志在线采集或自动写参；
- MES/QMS 或任何企业系统真实集成；
- 真实质量放行、生产控制、生产部署或生产安全认证；
- 多工站、多工厂、多租户、账号登录、RBAC 或多角色协作；
- 真实知识审核角色/页面和在线知识晋级；
- 在线大模型、在线 Embedding、向量数据库、Agent 自主决策或网络 API 依赖；
- 在线训练、增量学习、模型训练平台或自动重训；
- 多主要根因标签、真实设备参数单位或企业控制限；
- 自动寻优、循环调用模拟器筛选候选或宣称全局最优；
- 舜宇内部数据、设备参数、产线事实、真实良率提升或企业现网适用性承诺。

## 29. 可信声明和已知限制

### 29.1 允许声明

- TuneWise 是使用公开资料、规则约束模拟数据、CSV 导入和离线回放构建的比赛原型。
- 在数据、规则、模拟器版本和扰动种子固定的模拟环境中，确认方案对当前模拟批次产生可复现结果。
- 可以报告模拟环境中的 MTF/四角差异/控制限变化、冻结测试集算法指标和基线对比。
- 系统提供决策支持和人工确认，不控制真实设备，不替代工程判断或质量放行。

### 29.2 禁止声明

不得声称已接入或验证舜宇真实设备/产线、提升真实良率、减少舜宇真实调机时间、证明真实世界因果关系、参数为最优、具备生产部署资格、可安全自动控制真实设备或模拟数据等同企业真实生产数据。

### 29.3 已知限制

- 场景仅覆盖 AA 首件四角 MTF 不对称下降；原型控制限、参数和单位不代表真实设备。
- 模型在规则生成数据和冻结资产上评估，其外部有效性未经真实生产数据验证。
- 配对回放只证明版本固定模拟器内的可复现变化，不提供真实世界因果或良率证据。
- MVP 单角色、无登录、无真实审核；新提交案例不会实时成为正式知识。
- 算法质量若未达到冻结门槛必须如实披露；硬门槛失败则不可交付。

## 30. 冻结决策追踪矩阵

| 冻结决策 | 主要规格章节 | 对应验收 |
|---|---|---|
| D1 唯一工站和异常 | 1、2、8、9、10 | AC-D1-01..05；HG-02、03 |
| D2 核心用户与权限 | 3、19、20 | AC-D2-01..05；HG-04、06 |
| D3 五分钟主流程 | 5、6 | AC-D3-01..06；HG-09、13 |
| D4 数据/故障/模拟规则 | 7、8、9、18.1-18.4 | AC-D4-01..07；HG-07、10、12、15 |
| D5 检测/排序/检索 | 10、11、12、13 | AC-D5-01..06；HG-02、04、08、16 |
| D6 候选/安全/拒绝 | 14、15、16、17 | AC-D6-01..08；HG-01..06、08、16 |
| D7 离线回放 | 18、20 | AC-D7-01..08；HG-05..14、16 |
| D8 验收/测试/交付 | 23、24、25、27 | AC-D8-01..06；HG-01..16 |

本矩阵用于从冻结决策追踪到规范性章节和可执行验收；任何实现变更若无法映射到上述 D1-D8、用户故事或验收条件，默认不属于 TuneWise MVP 范围。
