# TuneWise MVP 决策基线

本文件记录 `/grill-with-docs` 访谈中已经冻结的 MVP 决策。它是后续 `/to-spec` 的输入，不是产品规格或实现设计。

## 决策 1：唯一工站和异常场景

**状态**：已冻结

### 场景

MVP 唯一场景为：相机模组主动对准（AA）工站，在首件检测中出现“中心 MTF 处于合格或临界合格范围，但四角 MTF 存在明显不对称下降”的质量异常。

该场景属于基于公开光学装调资料建立的比赛原型假设，不代表舜宇真实工站、设备或内部问题。

### 根因候选

主要根因候选限定为：

1. 传感器或镜头平面 Pitch/Roll 倾斜；
2. X/Y 方向偏心；
3. AA 平台重复定位误差、回差或振动造成的测量波动；
4. 夹具基准或设备标定漂移。

Z 向焦点偏移仅作为次级候选：只有当中心 MTF 接近下限且四角整体偏低时才参与排序，不作为“四角不对称下降”的首要根因。

### 可调整参数

MVP 可调整参数限定为：

- `x_offset`；
- `y_offset`；
- `pitch`；
- `roll`；
- `z_offset`，仅在条件满足时触发。

每个参数必须具有合法范围、单次调整步长和联动约束。系统只输出 1—3 组参数候选，不自动写入设备。

### 核心质量指标

- 中心 MTF；
- 左上、右上、左下、右下四角 MTF；
- 四角最小 MTF；
- 四角 MTF 极差或标准差；
- 调机尝试次数；
- 最终是否达到原型控制限。

### 离线回放成功判据

在中心 MTF 不恶化的前提下，提高最差角落 MTF并降低四角差异。`attempt_count` 按决策 7 定义为实际确认并执行回放的方案数量；五分钟主流程首次成功回放后为 1，不作为单次回放前后模拟改善指标。人工与系统辅助尝试次数对比只在独立离线评估实验中报告。

## 决策 2：核心用户及权限边界

**状态**：已冻结

### 用户模式与固定身份

MVP 采用单角色、无登录系统，唯一核心用户为“AA 工艺工程师”。比赛演示始终使用固定身份，不实现账号注册、登录、RBAC，也不实现调机员、质量人员、知识管理员等独立用户。

- `actor_id`：`demo-aa-engineer`
- `actor_role`：`AA_PROCESS_ENGINEER`
- `display_name`：`AA工艺工程师`

### 允许动作

AA 工艺工程师可以：

1. 导入 AA 工站离线回放数据；
2. 启动异常检测、根因排序和相似案例检索；
3. 查看异常数据、规则命中、模型结果和历史案例等证据；
4. 生成并选择一组通过安全校验的参数候选；
5. 对参数候选进行人工确认；
6. 启动模拟结果回放并查看调整前后指标；
7. 生成复盘报告；
8. 将完成的调机任务提交为候选案例。

### 禁止动作

AA 工艺工程师不可：

1. 修改原型控制限、安全规则、参数合法范围和调整步长；
2. 绕过证据充足度或安全校验；
3. 向真实设备写入参数；
4. 执行产品或异常批次的质量放行；
5. 审批自己的候选案例；
6. 将未经审核的案例直接提升为正式知识。

### 知识沉淀状态

- **调机任务记录**：任务关闭后立即保存，供审计和复盘；
- **待审核案例**：由 AA 工艺工程师提交，但不得参与后续推荐；
- **已审核案例**：作为预置知识数据存在，可以被案例检索和参数建议模块调用。

MVP 不实现真实审核角色和审批页面，只展示“待审核案例”状态及待审核列表。正式案例库使用预置的已审核案例。新增待审核案例不参与模型训练、相似案例推荐或参数生成。

### 最小审计链

所有人工确认、结果回放和案例提交动作必须记录以下内容：

- 固定演示身份；
- 时间戳；
- 动作内容。

## 决策 3：五分钟演示的唯一主流程

**状态**：已冻结

### 演示边界

五分钟现场演示采用唯一的成功主流程（happy path），不在现场切换其他批次，不演示重新调参、失败恢复、知识审核或真实设备操作。

现场不依赖外部网络、在线模型接口或真实设备。大模型解释如不可用，应由结构化模板降级生成，不能中断主流程。

### 主流程与时间预算

1. **0:00—0:25**：导入应用预置的单个 AA 异常批次 CSV，创建调机任务。
2. **0:25—1:05**：展示中心与四角 MTF、最差角落 MTF及四角差异，系统识别并标记“四角 MTF 不对称下降”。
3. **1:05—2:05**：启动诊断，展示 Top-3 根因候选、规则命中、模型特征贡献或评分依据，以及预置的已审核相似案例。
4. **2:05—3:00**：生成 1—3 组已通过安全校验的参数候选，展示当前值、建议值、合法范围、调整步长、联动约束和校验结果，由固定身份 AA 工艺工程师人工确认其中一组。
5. **3:00—4:00**：启动确定性的离线结果回放，对比调整前后的中心 MTF、最差角落 MTF、四角差异和原型控制限状态，并显示本次任务 `attempt_count = 1`。
6. **4:00—4:30**：关闭任务，生成复盘报告，将任务提交为待审核案例，并在待审核列表中看到该记录。
7. **4:30—5:00**：保留页面切换、现场讲解和性能波动缓冲。

### 任务状态

现场成功主流程的任务状态按以下顺序推进：

1. `CREATED`：任务已创建；
2. `DATA_IMPORTED`：数据已导入并通过格式校验；
3. `ANOMALY_DETECTED`：异常已识别；
4. `DIAGNOSED`：Top-3 根因与证据已生成；
5. `PLAN_READY`：参数候选已生成并通过校验；
6. `PLAN_CONFIRMED`：用户已人工确认候选；
7. `REPLAYING`：合法回放正在执行；
8. `REPLAYED`：离线结果回放完成；
9. `CLOSED`：任务已关闭并生成报告；
10. `CASE_SUBMITTED`：已提交为待审核案例。

每一步只能在前置状态完成后进入下一状态。唯一例外是决策 7 冻结的模拟器执行失败恢复：`REPLAYING → PLAN_CONFIRMED`，且不得保存不完整结果。演示页面必须明显显示当前阶段和已完成阶段，使评委能看清完整闭环，而不是在多个独立页面间跳转。

### 确定性要求

演示数据采用版本固定的预置 CSV、固定规则集、固定模型版本和确定性回放函数。相同输入必须产生相同的 Top-3 根因顺序、参数候选和回放结果，以降低现场演示风险。

输出不得写死在前端；异常检测、根因排序、案例检索、规则校验和回放必须由真实程序逻辑产生。

### 必须保留并测试的保护分支

“唯一无分支主流程”仅指现场演示脚本。系统内部必须保留并测试以下保护分支，但不在五分钟主流程中展示：

- CSV 字段缺失或格式错误；
- 未识别到目标异常；
- 诊断证据不足；
- 参数候选越界或违反联动规则；
- 所有候选均被安全规则拒绝；
- 未人工确认前尝试启动回放；
- 未完成回放前尝试关闭任务；
- 待审核案例被错误用于后续推荐。

## 决策 4：数据模型、故障模式和模拟数据因果规则

**状态**：已冻结

### 数据对象

#### `DatasetManifest`

记录：

- `dataset_version`；
- `schema_version`；
- `generator_version`；
- `rule_set_version`；
- `model_version`；
- `random_seed`；
- 数据文件与规则文件的内容哈希。

该对象用于保证演示、训练和评估可复现。

#### `Batch`

记录：

- `station_id`；
- `batch_id`；
- `product_model`；
- 原型控制限快照；
- 参数边界与规则集版本；
- 初始参数状态。

控制限与安全规则在任务创建时形成只读快照，运行过程中不可被用户修改。

#### `Measurement`

只保存原型场景中的以下可观测数据：

- `sample_index`；
- `timestamp`；
- `x_offset`；
- `y_offset`；
- `pitch`；
- `roll`；
- `z_offset`；
- `vibration_rms`；
- `repeat_position_error`；
- `calibration_residual_x`；
- `calibration_residual_y`；
- `mtf_center`；
- `mtf_lt`；
- `mtf_rt`；
- `mtf_lb`；
- `mtf_rb`。

不得使用含义模糊的“平台波动证据”字段，也不得在 `Measurement` 中保存根因标签、调整建议或调整后结果。

以下派生指标必须由程序根据 `Measurement` 计算，不进入 CSV：

- `corner_mtf_min`；
- `corner_mtf_range`；
- `corner_mtf_std`；
- 各指标相对控制限的偏差；
- 滚动均值与滚动标准差；
- 最终控制限状态。

#### `FaultTruth`

`FaultTruth` 只存在于数据生成器输出的独立测试元数据中，用于自动化评估，不进入导入 CSV、应用数据库、案例检索、诊断特征、接口响应或用户界面。

#### 业务结果对象

保留 `Task`、`DiagnosticResult`、`ParameterPlan`、`ReplayResult`、`AuditEvent`、`Case`，分别保存任务状态、诊断结果、参数候选、回放结果、审计事件和知识案例。

`Case` 必须区分 `PENDING_REVIEW` 与 `APPROVED`。只有 `APPROVED` 案例能够进入检索和参数推荐。

### 单位与坐标约定

MVP 统一采用“归一化原型单位”，不在不同字段中混用真实物理单位和归一化值：

- `x_offset`、`y_offset`、`z_offset`：Normalized Offset Unit；
- `pitch`、`roll`：Normalized Angular Unit；
- MTF：0—1 归一化指标。

四角坐标固定为：

- `LT=(-1,+1)`；
- `RT=(+1,+1)`；
- `LB=(-1,-1)`；
- `RB=(+1,-1)`。

坐标系以图像中心为原点，X 轴向右为正、Y 轴向上为正。`x_offset`、`y_offset` 的正方向分别与 X、Y 轴一致；正 `pitch` 对 Y 为正的上方角落增加局部焦平面误差，正 `roll` 对 X 为正的右侧角落增加局部焦平面误差，正 `z_offset` 对全部区域增加同向误差。

局部焦平面误差定义为：

```text
local_focus_error =
  z_offset
  + pitch_coefficient × y_coordinate
  + roll_coefficient × x_coordinate
```

以上均为比赛模拟器中的坐标与符号约定，不宣称等同于具体设备的真实轴定义。

### 故障模式

故障模式冻结为：

1. `PLANE_TILT`；
2. `XY_DECENTER`；
3. `PLATFORM_INSTABILITY`；
4. `REFERENCE_DRIFT`；
5. `Z_DEFOCUS_CONDITIONAL`。

每个异常批次只有一个 `primary_fault_truth`。Z 向偏移可以作为 nuisance disturbance 存在，但不构成第二个主要标签。MVP 不训练或评估多主要根因分类。

可以生成参数候选的故障模式：

- `PLANE_TILT`；
- `XY_DECENTER`；
- 满足条件时的 `Z_DEFOCUS_CONDITIONAL`。

只输出排查建议、不生成调机参数的故障模式：

- `PLATFORM_INSTABILITY`；
- `REFERENCE_DRIFT`。

当平台不稳定或基准漂移证据占主导时，系统必须拒绝通过 X/Y/Pitch/Roll 盲目补偿，并提示检查平台、夹具或标定状态。

### 模拟因果规则

1. MTF 由统一、非线性、有界的因果函数计算，结果限制在 0—1 范围内。
2. 局部焦平面误差绝对值增大时，对应区域 MTF 单调下降。
3. `PLANE_TILT` 主要形成稳定的空间不对称模式。
4. `XY_DECENTER` 形成与偏心方向一致的空间下降模式，但必须通过参数状态和空间特征与 `PLANE_TILT` 保持可区分。
5. `PLATFORM_INSTABILITY` 主要提高时间序列方差和重复定位误差，不形成固定的单一角落下降方向；`attempt_count` 不得由模拟器根据隐藏故障直接生成。
6. `REFERENCE_DRIFT` 必须伴随持续的 `calibration_residual` 或 reference residual 特征，否则无法与稳定平面倾斜可靠区分。
7. Z 向偏移主要导致中心和四角整体下降；只有中心 MTF 接近下限且四角整体偏低时，才能进入根因排序。
8. 没有故障注入、参数变化或固定种子噪声时，质量结果不得无原因跳变。
9. 不允许为不同故障直接写死固定 MTF 结果表。

### 模拟器与诊断系统隔离

数据生成与结果回放使用同一个受版本控制的因果模拟器，但必须将其视为外部“模拟环境”。

诊断、模型训练、案例检索和参数推荐模块：

- 不得读取 `FaultTruth`；
- 不得读取生成器内部故障类型；
- 不得读取因果函数系数；
- 不得根据演示批次 ID 返回固定结果；
- 只能使用 CSV 中的可观测字段和程序计算出的派生特征。

参数推荐可以在合法范围内生成候选，但不得直接调用模拟器搜索并反推出全局最优参数。模拟器只在用户确认方案之后用于结果回放和实验评估。

### 回放规则

确认参数后：

1. 将确认的参数变化应用到当前批次状态；
2. 重新运行同一版本的因果模拟器；
3. 使用相同的潜在扰动序列或固定回放种子进行前后对照；
4. 重新计算中心 MTF、四角 MTF 和控制限状态；
5. 禁止读取预先准备好的“调整后结果”。

相同输入、参数方案、规则版本和随机种子必须产生相同回放结果。

界面和报告必须将结果标注为：

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。

### 数据集切分与泄漏防护

训练集、验证集、测试集必须按 `Batch` 切分，禁止将同一批次的 `Measurement` 拆分到不同集合。

固定要求：

- 演示批次不得进入模型训练集；
- 测试批次不得进入案例库；
- 案例库只使用训练数据中形成的预置 `APPROVED` 案例；
- 不同集合使用不同批次 ID 和随机种子；
- 模型评估以批次级根因标签为单位，不能把同一批次的多行样本当成多个独立测试样本。

演示批次固定以可调整的 `PLANE_TILT` 为主要真值；其他故障用于案例库、盲测评估和安全拒绝测试。

## 决策 5：异常检测、根因排序和案例检索的最低可行算法

**状态**：已冻结

### 异常检测：确定性目标场景门控

异常检测不训练模型，采用版本化 SPC 规则和批次级聚合指标。

MVP 主流程只接受目标异常 `AA_CORNER_ASYMMETRY`：

- 中心 MTF 处于合格或临界合格范围，不明显低于中心控制下限；
- 同时满足以下至少一项：
  1. 最差角落 MTF 低于角落控制下限；
  2. 四角 MTF 极差超过不对称控制限；
  3. 四角 MTF 标准差超过离散控制限；
- 异常必须在批次内达到规则集定义的最小持续次数或样本比例，不能由单个噪声点触发。

不得将“中心 MTF 达到临界下限”设置为目标异常的必要条件。

检测结果分为：

- `TARGET_ANOMALY`：符合四角 MTF 不对称下降，允许进入诊断主流程；
- `NORMAL`：未超过控制限，停止主流程；
- `NON_TARGET_GLOBAL_DEGRADATION`：中心及四角整体下降，进入保护分支；
- `INSUFFICIENT_DATA`：样本数量或字段不足，进入保护分支。

`Z_DEFOCUS_CONDITIONAL` 主要用于离线评估和保护场景。中心及四角整体下降时，不得误判为主流程中的四角不对称异常。

### 根因排序算法

根因排序采用以下固定流水线：

- `StandardScaler`；
- multinomial logistic regression；
- 固定训练集、验证集和测试集；
- 按 `Batch` 切分；
- 固定随机种子；
- 固定特征顺序；
- 预处理器和模型共同版本化；
- 不在线训练、不增量学习。

输入仅来自 `Measurement` 的可观测字段及其批次级派生特征，包括：

- 均值、标准差和趋势；
- 四角方向差异；
- 中心与四角的相对变化；
- 当前参数状态；
- `vibration_rms`；
- `repeat_position_error`；
- `calibration_residual_x/y`。

禁止使用：

- `FaultTruth`；
- 生成器内部故障类型；
- 模拟器系数；
- `batch_id` 或可间接识别数据集划分的字段；
- 调整后结果；
- 案例中的已审核根因作为模型输入。

### 候选类别门控

根因候选固定为：

- `PLANE_TILT`；
- `XY_DECENTER`；
- `PLATFORM_INSTABILITY`；
- `REFERENCE_DRIFT`；
- `Z_DEFOCUS_CONDITIONAL`。

`Z_DEFOCUS_CONDITIONAL` 在分类结果展示前经过硬规则门控。只有同时满足以下条件时才允许参与排序：

- 中心 MTF 接近或低于下限；
- 四角整体同向下降；
- 四角不对称不是主导特征。

条件不成立时，将该类别从候选集合中移除，并对其余类别的模型输出重新归一化。

硬规则只负责：

- 排除不可能类别；
- 标记证据冲突；
- 触发证据不足状态。

不得在没有明确记录的情况下，使用任意人工加分改变模型排序。

### 诊断解释

每个 Top-3 候选展示：

- 模型相对概率或归一化得分；
- 命中的显式规则；
- 支持该判断的关键观测指标；
- 最主要的正向 logit 贡献；
- 与该根因冲突的证据；
- 可调整或仅排查的类别标记。

“标准化特征值 × 模型系数”必须标注为：

> 该特征对当前类别 logit 的贡献

不得称为：

- 对最终概率的直接贡献；
- 因果贡献；
- SHAP 值；
- 真实故障概率。

只展示贡献最大的 3—5 个正向特征和必要的冲突特征，不向用户直接暴露完整系数表。

### 证据充足度与拒绝机制

除输出 Top-3 外，系统必须产生：

- `SUFFICIENT_EVIDENCE`；
- `INSUFFICIENT_EVIDENCE`。

证据充足度由版本化规则判断，至少考虑：

- Top-1 模型得分；
- Top-1 与 Top-2 的差距；
- 是否命中与 Top-1 兼容的显式规则；
- 是否存在关键字段缺失；
- 是否存在模型结果与硬规则明显冲突。

具体阈值通过验证集确定并写入版本化规则集，不在界面中由用户修改。

当证据不足时：

- 可以展示 Top-3 作为排查顺序；
- 不得进入可执行参数推荐；
- 只能输出需要补充检查的项目。

### 相似案例检索

采用结构化 KNN，不使用在线 Embedding、向量数据库或大模型。

检索对象必须同时满足：

- `status = APPROVED`；
- 来自允许进入案例库的训练数据；
- 与当前任务具有相同 `station_type`；
- `product_model` 兼容；
- 不属于测试批次或演示批次。

检索特征采用与诊断一致的批次级可观测特征，但：

- 不包含 `FaultTruth`；
- 不包含已审核根因作为距离维度；
- 不包含处理动作和结果；
- 不包含 `batch_id` 或 `case_id`。

距离采用版本固定的标准化欧氏距离。标准化器只能由案例库允许使用的数据拟合。

采用两阶段检索：

1. 优先在已审核根因属于当前 Top-3 候选的案例中计算距离；
2. 如果不足 3 条，再从其余兼容 `APPROVED` 案例中按距离补足。

根因标签只用于候选池筛选和结果展示，不作为距离计算特征。

返回 3 个案例，并展示：

- `case_id`；
- 距离或相似度；
- 主要特征差异；
- 已审核根因；
- 历史调整动作；
- 历史模拟结果；
- 适用条件。

排序规则固定为：

1. 距离升序；
2. 距离相同时按 `case_id` 升序。

`PENDING_REVIEW` 案例不得进入检索索引。

### 核心决策链边界

以下模块不得进入异常检测、根因排序或案例检索的核心决策链：

- 大模型；
- 在线 Embedding；
- 向量数据库；
- Agent 自主编排；
- 网络 API 依赖。

解释文本使用结构化模板生成，保证离线可运行和结果可重复。

后续如使用大模型，只能用于：

- 对结构化诊断结果进行语言整理；
- 生成复盘报告草稿；
- 改善非关键交互文本。

大模型不可改变：

- 异常判定；
- 根因排序；
- 参数候选；
- 安全校验；
- 案例检索顺序。

大模型不可用时，模板生成必须保证完整主流程继续运行。

### 模型和检索评估

至少保留以下离线指标：

- Top-1 根因命中率；
- Top-3 根因命中率；
- macro-F1；
- 各故障类别混淆矩阵；
- 证据不足拒绝率；
- Recall@3 或 Recall@5 案例检索命中率；
- 与历史频率排序和非标准化 KNN 基线的对比。

不得只报告演示批次结果。

## 决策 6：参数候选生成、安全边界和拒绝输出条件

**状态**：已冻结

### 运行前置条件

参数候选生成仅在以下条件全部成立时运行：

- `task.status = DIAGNOSED`；
- `anomaly_result = TARGET_ANOMALY`；
- `evidence_status = SUFFICIENT_EVIDENCE`；
- `DiagnosticResult`、控制限快照、参数约束快照和规则版本完整；
- 当前参数值已通过合法范围及步长网格校验；
- 当前诊断结果仍是任务的最新版本。

候选生成只能使用：

- 当前任务的可观测参数；
- Top-1 根因及其方向证据；
- 只读参数约束快照；
- 兼容的 `APPROVED` 案例调整记录；
- 版本化规则集。

禁止使用：

- `FaultTruth`；
- 模拟器内部系数；
- 调整后结果；
- 回放模拟器试算结果；
- 测试集或演示批次的隐藏信息。

### 参数族与可调整范围

| Top-1 根因 | 允许调整 | 输出类型 |
|---|---|---|
| `PLANE_TILT` | `pitch`、`roll` 中具有明确方向证据的参数 | 参数候选 |
| `XY_DECENTER` | `x_offset`、`y_offset` 中具有明确方向证据的参数 | 参数候选 |
| `Z_DEFOCUS_CONDITIONAL` | `z_offset` | 参数候选 |
| `PLATFORM_INSTABILITY` | 无 | 平台检查建议 |
| `REFERENCE_DRIFT` | 无 | 夹具或标定检查建议 |

不得仅因根因属于某个参数族，就自动调整该族内的全部参数。

每个参数必须先得到明确的 `ParameterDirectionEvidence`：

- `parameter_name`；
- `current_value`；
- `nominal_value`；
- `recommended_direction`；
- `supporting_features`；
- `supporting_rules`；
- `conflict_status`。

如果某个参数缺少方向证据或存在方向冲突，则该参数不得进入候选。

### 参数约束快照

任务创建时保存只读的 `ParameterConstraintSnapshot`，包括：

- `product_model`；
- `parameter_name`；
- `nominal_value`；
- `minimum`；
- `maximum`；
- `step`；
- `maximum_single_plan_delta`；
- `rule_set_version`。

MVP v1 使用以下归一化原型值：

| 参数 | 标称值 | 合法范围 | 步长 | 单次最大变化 |
|---|---:|---:|---:|---:|
| `x_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 |
| `y_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 |
| `pitch` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 |
| `roll` | 0.00 | [-1.00, 1.00] | 0.05 | 0.20 |
| `z_offset` | 0.00 | [-1.00, 1.00] | 0.05 | 0.10 |

这些数值必须标注为版本化归一化原型约束，不代表真实设备参数。

代码中不得假设所有未来产品型号标称值永远为 0.00。候选算法必须读取快照中的 `nominal_value`。

### 数值表示

为避免浮点误差，参数值、步长和调整量不得使用普通二进制浮点数直接比较。

内部优先采用整数步数表示：

- X/Y/Pitch/Roll 范围：-20 至 +20 ticks；
- 每个 tick 对应 0.05 归一化单位；
- X/Y/Pitch/Roll 单次最大变化：4 ticks；
- `z_offset` 单次最大变化：2 ticks。

也可以使用固定精度 `Decimal`。所有范围、网格和跨标称值判断都基于整数 tick 或 `Decimal` 完成。

输入参数不在步长网格上时，禁止静默取整，应返回 `CURRENT_VALUE_OFF_GRID`。

### 候选生成

候选按以下确定性规则生成：

1. **保守候选**
   - 对每个具有方向证据的参数向标称值移动 1 个步长；
   - 如果参数已位于标称值，不调整该参数。
2. **标准候选**
   - 对每个具有方向证据的参数向标称值移动 2 个步长；
   - 实际变化不得超过当前偏差或单次最大变化。
3. **案例引导候选**
   - 从兼容 `APPROVED` 案例中提取同一参数族的历史调整量；
   - 对调整量取中位数；
   - 转换到当前参数方向；
   - 按步长网格取整；
   - 截断至单次最大变化；
   - 再经过完整安全校验。

最多保留 3 组不同候选。若保守、标准或案例候选最终参数完全相同，只保留一组。若某一候选的全部参数变化量均为 0，则不生成该候选。

### 兼容案例定义

案例引导候选只能使用同时满足以下条件的案例：

- `status = APPROVED`；
- `station_type = AA`；
- `product_model` 兼容；
- `reviewed_root_cause` 与当前 Top-1 根因一致；
- `parameter_family` 一致；
- 使用兼容的参数规则版本；
- 历史动作通过安全校验；
- `replay_outcome_status = SUCCESS`；
- 未发生中心 MTF 恶化或其他规则违规；
- 不属于测试集或演示批次。

案例调整量的方向必须与当前 `ParameterDirectionEvidence` 一致。

如果案例中位数方向与当前方向证据冲突，则舍弃案例引导候选，不影响保守和标准候选的生成。

没有兼容案例时，只记录 `NO_COMPATIBLE_APPROVED_CASE`，不得因此拒绝规则生成的候选。

### 联动与安全约束

每组候选必须满足：

- 最多调整两个参数；
- 只能调整一个参数族；
- X/Y、Pitch/Roll 和 Z 不得混调；
- 每个调整都必须缩小参数相对标称值的绝对偏差；
- 调整不得跨越标称值；
- 建议值必须位于合法范围；
- 建议值必须落在步长网格；
- 单次变化不得超过 `maximum_single_plan_delta`；
- 案例引导候选不得绕过任何安全规则；
- 候选不得包含没有方向证据的参数；
- 所有校验必须由统一的 `ParameterSafetyValidator` 执行。

禁止在不同模块分别实现不同版本的范围校验。

### 候选结构

每个 `ParameterPlanCandidate` 至少包含：

- `candidate_id`；
- `generation_type`：`CONSERVATIVE`、`STANDARD` 或 `CASE_GUIDED`；
- `root_cause`；
- `current_values`；
- `proposed_values`；
- `deltas`；
- `direction_evidence`；
- `supporting_case_ids`；
- `constraint_snapshot_version`；
- `rule_set_version`；
- `diagnostic_result_version`；
- `validation_checks`；
- `validation_status`；
- `rejection_reasons`；
- `candidate_hash`。

候选排序固定为：

1. 调整总绝对量升序；
2. 兼容案例支持数量降序；
3. `candidate_id` 升序。

“调整总量”按归一化 tick 绝对值之和计算。

不得使用“最优参数”“全局最优”或“预测最佳方案”等表述，只能称为：

> 通过当前证据和安全规则生成的候选方案

### 候选确认与过期机制

用户只能确认 `validation_status = PASSED` 的候选。

确认时必须记录：

- `candidate_id`；
- `candidate_hash`；
- `actor_id`；
- `actor_role`；
- `confirmed_at`；
- `rule_set_version`；
- `diagnostic_result_version`；
- 参数约束快照版本。

候选确认后形成不可修改的 `ConfirmedPlan`。

出现以下任一变化时，旧候选及旧确认立即标记为 `STALE`，不得用于回放：

- 重新导入数据；
- 重新运行异常检测；
- 重新运行诊断；
- 当前参数发生变化；
- 控制限快照变化；
- 参数规则版本变化；
- 候选内容或 `candidate_hash` 变化。

用户不得通过修改前端请求体替换已确认候选中的参数值。后端必须根据 `candidate_id` 和 `candidate_hash` 重新校验。

### 拒绝输出条件

出现以下任一情况时，不输出可执行参数候选：

- `anomaly_result` 不是 `TARGET_ANOMALY`；
- `evidence_status = INSUFFICIENT_EVIDENCE`；
- Top-1 属于不可调故障；
- `Z_DEFOCUS_CONDITIONAL` 门控未通过；
- 模型结果与方向规则冲突；
- 没有任何参数具有明确方向证据；
- 当前参数、控制限、参数快照或规则版本缺失；
- 当前参数越界或不在步长网格；
- 调整方向会扩大标称偏差；
- 调整会越界、跨过标称值或违反参数族规则；
- 所有候选均被 `ParameterSafetyValidator` 拒绝；
- `task.status` 不是 `DIAGNOSED`；
- 当前诊断结果或候选已经过期；
- 用户试图绕过校验直接确认或回放。

拒绝时返回结构化结果：

- `refusal_code`；
- `refusal_message`；
- `supporting_evidence`；
- `recommended_inspection_actions`；
- `rule_set_version`。

### 回放隔离

候选生成、排序和校验期间不得调用因果模拟器评估候选效果。

只有用户确认一组候选后，`Replay` 模块才能将确认参数应用到外部模拟环境并重新计算结果。

这保证候选系统不会通过访问模拟器反推出隐藏最优参数。

## 决策 7：离线结果回放的实现方式及可信声明

**状态**：已冻结

### 回放定位与术语

内部技术实现可以称为 `Paired Counterfactual Simulation`。

面向用户、报名材料和答辩统一表述为：

- “确定性配对模拟干预回放”；或
- “离线模拟干预对照”。

不得将其表述为真实产线反事实实验或真实因果效果证明。

回放的目的仅是验证：在版本固定的规则约束模拟环境中，将一组已确认参数应用于同一模拟批次后，质量指标会产生怎样的可复现变化。

### 模块隔离

因果模拟器作为本地独立模块运行，不依赖：

- 外部网络；
- 在线大模型；
- 在线 Embedding；
- 真实设备；
- MES 或 QMS；
- 用户可修改的前端状态。

诊断、根因排序、案例检索和候选生成模块：

- 不得导入模拟器模块；
- 不得调用模拟器 API；
- 不得读取隐藏场景；
- 不得读取模拟器系数；
- 不得利用回放结果筛选候选；
- 不得通过循环试算寻找最优参数。

只有 `Replay` 模块能够调用模拟器。

### 隐藏场景隔离

演示批次在模拟器侧具有一个不可解释、不可枚举的 `scenario_ref`。

应用侧只保存该不透明引用及其哈希，不保存或展示：

- `primary_fault_truth`；
- nuisance disturbance；
- 模拟器内部系数；
- 潜在扰动序列；
- 隐藏生成参数。

模拟器根据 `scenario_ref` 在本地受控目录中解析隐藏场景。

隐藏场景不得进入：

- 导入 CSV；
- 应用数据库中的可查询业务表；
- 诊断特征；
- 模型输入；
- 案例检索；
- 前端接口响应；
- 复盘报告；
- 用户界面。

### 回放前置条件

只有同时满足以下条件时才允许启动回放：

1. `task.status = PLAN_CONFIRMED`；
2. `ConfirmedPlan` 存在且未过期；
3. `candidate_id` 与 `candidate_hash` 匹配；
4. `ConfirmedPlan` 中的参数值与服务端保存的候选完全一致；
5. `diagnostic_result_version` 未发生变化；
6. `control_limit_snapshot_version` 未发生变化；
7. `parameter_constraint_snapshot_version` 未发生变化；
8. `rule_set_version` 未发生变化；
9. `dataset_version`、`schema_version` 和 `generator_version` 完整；
10. 原始数据、规则文件和场景引用的哈希与 `DatasetManifest` 一致；
11. 当前任务不存在正在执行的回放；
12. 当前 `ConfirmedPlan` 尚未产生有效 `ReplayResult`，或本次请求属于相同幂等请求。

前端只能提交：

- `task_id`；
- `confirmed_plan_id`；
- `confirmed_plan_hash`；
- `idempotency_key`。

前端不得提交或覆盖：

- proposed parameter values；
- random seed；
- `scenario_ref`；
- 模拟器版本；
- 规则版本；
- 原始状态；
- 评价阈值。

这些数据必须由服务端根据任务和 `ConfirmedPlan` 解析。

### 基线重现校验

不得直接比较“模拟输出哈希”和“原始 CSV 文件字节哈希”。

定义版本化的 `ObservableCanonicalizer`，对以下字段进行统一规范化：

- `sample_index`；
- `timestamp` 或规范化时间序号；
- `x_offset`；
- `y_offset`；
- `pitch`；
- `roll`；
- `z_offset`；
- `vibration_rms`；
- `repeat_position_error`；
- `calibration_residual_x`；
- `calibration_residual_y`；
- `mtf_center`；
- `mtf_lt`；
- `mtf_rt`；
- `mtf_lb`；
- `mtf_rb`。

规范化过程至少包括：

- 固定字段顺序；
- 固定记录排序；
- 固定小数精度；
- 固定空值表达；
- 固定字符编码；
- 固定序列化格式；
- 排除文件名、换行格式和无业务意义的元数据。

`DatasetManifest` 保存：

- `raw_file_hash`；
- `canonical_observation_hash`；
- `canonicalizer_version`。

运行回放前，模拟器使用原始参数状态重放基线，并将输出经过同一 `ObservableCanonicalizer` 处理。

只有以下条件成立时才允许继续：

```text
simulated_baseline_canonical_hash
=
imported_csv_canonical_observation_hash
```

否则拒绝回放并返回 `BASELINE_REPRODUCTION_FAILED`，同时记录：

- `expected_hash`；
- `actual_hash`；
- `canonicalizer_version`；
- `generator_version`；
- `scenario_ref_hash`；
- `failed_at`。

不得为了通过校验而修改、覆盖或重新生成用户已导入的数据。

### 配对模拟干预

通过基线重现校验后，模拟器执行两次配对运行。

**A. Baseline Run**

- 使用原始参数；
- 使用固定隐藏场景；
- 使用固定样本数；
- 使用固定潜在扰动序列；
- 使用固定回放种子。

**B. Intervention Run**

- 使用同一隐藏场景；
- 使用同一样本数；
- 使用同一潜在扰动序列；
- 使用同一回放种子；
- 唯一改变为 `ConfirmedPlan` 中的参数变化。

除 `ConfirmedPlan` 参数外，任何输入都不得发生变化。前后两次运行必须调用同一版本的因果函数。

不得读取预先写好的“调整后结果”，也不得按 `candidate_id` 返回固定输出。

### 数值与哈希确定性

模拟器输出使用固定精度 `Decimal` 或整数化表示。

在计算结果哈希前，必须经过版本化的 `ReplayResultCanonicalizer`，包括：

- 固定字段顺序；
- 固定小数精度；
- 固定指标计算顺序；
- 固定数组排序；
- 固定状态枚举；
- 固定序列化格式。

结果哈希采用 SHA-256。

相同的：

- `dataset_version`；
- `scenario_ref_hash`；
- `confirmed_plan_hash`；
- `generator_version`；
- `rule_set_version`；
- `evaluation_rule_version`；
- `replay_seed`；

必须产生相同的 `result_hash`。

### 回放评价规则快照

任务创建时或回放前保存只读的 `ReplayEvaluationRuleSnapshot`，至少包括：

- `center_regression_tolerance`；
- `minimum_corner_min_improvement`；
- `minimum_range_reduction`；
- `minimum_std_reduction`；
- `center_lower_limit`；
- `corner_lower_limit`；
- `asymmetry_limit`；
- `evaluation_rule_version`。

评价阈值不得由前端修改，也不得根据实际回放结果临时调整。

### 结果状态

完成模拟运行后，结果状态按以下固定优先级判定。

1. **`REGRESSION`**

   只要满足以下任一条件，即优先判定为 `REGRESSION`：

   - 中心 MTF 下降超过 `center_regression_tolerance`；
   - 最差角落 MTF 显著下降；
   - 四角极差或标准差显著恶化；
   - 调整后控制限状态比调整前更差；
   - 出现任何版本化评价规则定义的保护指标退化。

2. **`SUCCESS`**

   同时满足：

   - 不属于 `REGRESSION`；
   - 中心 MTF 未发生超容差恶化；
   - 最差角落 MTF 达到规定改善幅度；
   - 四角极差或标准差达到规定改善幅度；
   - 调整后满足目标控制限状态；
   - 所有安全保护指标均通过。

3. **`PARTIAL_IMPROVEMENT`**

   同时满足：

   - 不属于 `REGRESSION`；
   - 至少一个目标指标达到改善阈值；
   - 未满足全部 `SUCCESS` 条件或尚未达到最终控制限。

4. **`NO_IMPROVEMENT`**

   同时满足：

   - 不属于 `REGRESSION`；
   - 所有目标指标变化均未达到最小改善阈值。

拒绝回放不创建上述结果状态。

`REPLAY_REFUSED` 应记录为 `ReplayAttempt` 或 `AuditEvent`，包括：

- `refusal_code`；
- `refusal_message`；
- `failed_validation`；
- `request_hash`；
- `actor_id`；
- `occurred_at`。

### 任务状态与幂等性

启动合法回放时：

```text
PLAN_CONFIRMED → REPLAYING
```

成功生成不可变 `ReplayResult` 后：

```text
REPLAYING → REPLAYED
```

若前置检查失败：

- 任务保持 `PLAN_CONFIRMED`；
- 不创建有效 `ReplayResult`；
- 只记录拒绝审计事件。

若模拟器运行异常：

- 任务从 `REPLAYING` 恢复为 `PLAN_CONFIRMED`；
- 记录 `REPLAY_EXECUTION_FAILED`；
- 不保存不完整结果。

同一 `idempotency_key` 和同一 `ConfirmedPlan` 重复请求时：

- 不重复执行模拟器；
- 返回已有 `ReplayResult`。

不同 `idempotency_key` 但输入哈希完全相同时，可以返回相同结果，但必须保持同一 `ConfirmedPlan` 只能存在一个有效 `ReplayResult`。

### `ReplayResult`

`ReplayResult` 至少保存：

- `replay_id`；
- `task_id`；
- `confirmed_plan_id`；
- `confirmed_plan_hash`；
- `dataset_version`；
- `schema_version`；
- `generator_version`；
- `rule_set_version`；
- `model_version`；
- `evaluation_rule_version`；
- `canonicalizer_version`；
- `scenario_ref_hash`；
- `replay_seed_hash`；
- `baseline_input_hash`；
- `intervention_input_hash`；
- `baseline_output_hash`；
- `intervention_output_hash`；
- `result_hash`；
- 调整前后中心与四角 MTF；
- 调整前后最差角落 MTF；
- 调整前后四角极差；
- 调整前后四角标准差；
- 各指标变化量；
- 调整前后控制限状态；
- `result_status`；
- `evaluation_checks`；
- `created_at`；
- `disclaimer`。

`ReplayResult` 创建后不可修改。

如需补充报告文本，应创建独立 `Report` 对象引用 `ReplayResult`，不得修改原始回放结果。

### 调机尝试次数

`attempt_count` 不得由因果模拟器根据隐藏故障任意生成。

MVP 中定义为：“当前任务中已经被人工确认并实际执行回放的参数方案数量。”

五分钟主流程中，第一次成功回放后：

```text
attempt_count = 1
```

如未来允许多轮调参，则每完成一次不同 `ConfirmedPlan` 的合法回放，`attempt_count` 增加一次。

人工排障平均尝试次数、系统辅助尝试次数等对比，属于独立的离线评估实验，不作为单次 `ReplayResult` 中的模拟输出。

### 可信声明

回放页面、复盘报告和导出材料必须持续显示：

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。

允许表述：

> 在数据、规则、模拟器版本和扰动种子固定的模拟环境中，该确认方案对当前模拟批次产生了可复现的离线回放结果。

允许报告：

- 模拟环境中的中心 MTF 变化；
- 最差角落 MTF 变化；
- 四角极差和标准差变化；
- 控制限状态变化；
- 离线测试集上的指标；
- 与基线算法的模拟实验对比。

禁止表述：

- 已在舜宇真实设备或产线上验证；
- 已提升真实良率；
- 能减少舜宇实际调机时间；
- 真实设备采用该方案必然有效；
- 回放结果证明了真实世界因果关系；
- 候选是最优参数；
- 系统已经具备生产部署资格；
- 系统能够安全自动控制真实设备；
- 模拟数据等同于企业真实生产数据。

## 决策 8：验收指标、测试基线和最终交付物

**状态**：已冻结

### 验收等级

所有验收项分为两类。

#### A. 硬门槛

以下任一项失败，MVP 不得标记为可交付：

- 非法参数拦截率不是 100%；
- 通过候选合法率不是 100%；
- 证据不足时仍生成参数候选；
- `PLATFORM_INSTABILITY` 或 `REFERENCE_DRIFT` 生成了参数候选；
- `PENDING_REVIEW` 案例进入检索；
- `STALE` 方案进入回放；
- `FaultTruth` 或隐藏模拟信息泄漏到运行时系统；
- 候选生成期间调用模拟器；
- 相同输入无法产生确定性结果；
- 数据、候选、规则或版本篡改未被发现；
- 断网后无法完成演示主流程；
- 回放结果未显示可信边界声明。

#### B. 算法质量门槛

异常检测、根因分类和案例检索指标属于比赛原型质量验收线。

如果指标未达到要求：

- 不得修改盲测标签；
- 不得删除困难样本；
- 不得重新生成更容易的盲测集；
- 不得将演示批次加入训练；
- 只能根据训练集和验证集修改方法；
- 修改后产生新的模型、规则和 `Manifest` 版本；
- 对冻结盲测集重新执行完整评估；
- 若最终仍未达标，应如实报告结果和限制，不能伪造通过。

### 固定测试资产

冻结以下最低规模：

1. 根因模型训练集：不少于 200 个 `Batch`；
2. 验证集：不少于 50 个 `Batch`；
3. 冻结盲测集：不少于 100 个 `Batch`；
4. 五类主要故障在盲测集中各不少于 20 个 `Batch`；
5. 演示批次完全独立于训练、验证、盲测和案例库；
6. 预置 `APPROVED` 案例不少于 60 个，且只来自允许进入案例库的训练数据；
7. 异常检测另设独立测试集，至少覆盖：
   - `NORMAL`；
   - `TARGET_ANOMALY`；
   - `NON_TARGET_GLOBAL_DEGRADATION`；
   - `INSUFFICIENT_DATA`；
   - 单点噪声；
   - 临界控制限样本；
8. 不同集合采用不同 `batch_id` 和随机种子；
9. 同一 `Batch` 的 `Measurement` 不得跨集合；
10. 最终评估前冻结：
    - `dataset_version`；
    - `schema_version`；
    - `generator_version`；
    - `rule_set_version`；
    - `model_version`；
    - `preprocessing_version`；
    - `evaluation_rule_version`；
    - 集合清单；
    - 随机种子；
    - 文件内容哈希。

盲测集应包含接近控制限、类别特征重叠及噪声较高的边界样本，不能只生成容易区分的理想样本。

### 隐藏标签边界

`FaultTruth` 只允许存在于隔离的：

- 数据生成资产；
- 离线训练标签；
- 冻结盲测评估标签。

`FaultTruth` 不得进入：

- TuneWise 运行时数据库；
- 导入 CSV；
- 诊断特征；
- 模型推理输入；
- 案例检索输入；
- API 响应；
- 应用日志；
- 审计日志；
- 复盘报告；
- 导出材料；
- 用户界面。

运行时泄漏扫描不扫描隔离的训练与评估标签目录本身，但必须验证该目录未被运行时应用打包、导入或访问。

隐藏模拟场景可以作为本地模拟器资产随项目交付，但运行时应用只能持有不透明 `scenario_ref`，不能读取其中的故障真值和内部系数。

### 异常检测验收

在独立检测测试集上计算：

- `TARGET_ANOMALY` Precision ≥ 0.90；
- `TARGET_ANOMALY` Recall ≥ 0.90；
- `NON_TARGET_GLOBAL_DEGRADATION` 错误进入主流程数量 = 0；
- 单点噪声误触发率 ≤ 5%；
- `INSUFFICIENT_DATA` 被正确阻断率 = 100%。

单点噪声误触发率定义为：“仅包含一个孤立越限测量、但不满足持续次数或样本比例条件的测试 `Batch` 中，被错误判定为 `TARGET_ANOMALY` 的比例。”

报告必须给出：

- 每类样本数；
- 混淆矩阵；
- Precision、Recall、F1；
- 错误路由明细；
- 使用的 SPC 规则版本。

### 根因排序验收

批次级逻辑回归在冻结盲测集上达到：

- Top-1 根因命中率 ≥ 0.60；
- Top-3 根因命中率 ≥ 0.85；
- macro-F1 ≥ 0.60。

所有指标以 `Batch` 为评估单位，不能将一个 `Batch` 中的多条 `Measurement` 视作多个独立样本。

报告应同时区分：

1. **模型独立评估**：对五类故障批次直接评估逻辑回归与类别门控能力；
2. **端到端业务评估**：从异常检测、证据判断、根因排序到是否允许荐参的完整流程。

端到端报告至少增加：

- 可调故障正确进入荐参阶段的比例；
- 不可调故障产生参数候选的数量，必须为 0；
- 证据不足样本产生参数候选的数量，必须为 0；
- Z 门控错误放行数量；
- 各拒绝原因分布。

`Z_DEFOCUS_CONDITIONAL` 即使在应用主流程中被保护分支阻断，仍可在模型独立评估中统计；不得将其从盲测结果中静默删除。

### 案例检索验收

相似案例的“相关案例”定义为同时满足：

- `status = APPROVED`；
- `station_type` 兼容；
- `product_model` 兼容；
- `reviewed_root_cause` 与查询批次真实评估标签一致；
- `parameter_family` 或 `inspection_action` 兼容；
- 历史结果状态符合案例库准入规则。

在此定义下计算：

- Recall@3 ≥ 0.70；
- Recall@5 ≥ 0.85；
- 标准化结构化 KNN 的 Recall@3 至少比未标准化欧氏距离 KNN 高 5 个百分点。

如果一个查询在案例库中不存在任何相关案例，应单独标记为 `NO_RELEVANT_CASE_AVAILABLE`。该查询不进入 Recall 分母，但必须单独报告数量，不能静默忽略。

报告同时提供：

- 每个故障类别的查询数；
- 有相关案例的查询数；
- 无相关案例的查询数；
- Recall@3；
- Recall@5；
- 检索失败案例明细。

### 安全与状态验收

必须达到：

- 非法参数拦截率 = 100%；
- `validation_status = PASSED` 的候选合法率 = 100%；
- `INSUFFICIENT_EVIDENCE` 阻断荐参率 = 100%；
- 不可调故障阻断荐参率 = 100%；
- `PENDING_REVIEW` 进入检索数量 = 0；
- 测试批次或演示批次进入案例索引数量 = 0；
- `STALE` 候选被确认数量 = 0；
- `STALE ConfirmedPlan` 进入回放数量 = 0；
- 未人工确认直接回放数量 = 0；
- 前端篡改候选参数成功数量 = 0。

安全测试集应包含正常输入、边界输入、越界输入、离网格输入、跨标称值输入、跨参数族输入、过期方案和篡改哈希等测试。

### 对照基线

固定以下基线：

1. **异常检测基线**：不带持续性条件的单样本控制限判断；
2. **根因排序基线**：根据训练集中各根因出现频率进行固定排序；
3. **案例检索基线**：未标准化批次特征的欧氏距离 KNN；
4. **参数推荐风险基线**：直接复用最近兼容案例的调整量，不执行范围、步长、联动或方向校验。

参数推荐风险基线：

- 只在隔离的离线评估脚本中运行；
- 不进入应用主流程；
- 不生成可供用户确认的 `ParameterPlan`；
- 不得调用真实或模拟设备；
- 仅用于统计无安全验证时的非法建议比例。

逻辑回归的 Top-1、Top-3 和 macro-F1 必须优于历史频率基线。

如某项未显著优于基线，必须在报告中明确说明，不得只展示绝对结果。

### 确定性与完整性验收

使用固定演示输入连续运行 10 次，以下内容必须完全一致：

- `anomaly_result`；
- Top-3 根因顺序；
- 模型得分在固定精度下的值；
- Logit 贡献排序；
- 检索案例顺序；
- 候选内容；
- `candidate_hash`；
- `confirmed_plan_hash`；
- `ReplayResult` 指标；
- `result_status`；
- `result_hash`。

以下篡改必须被检测：

- CSV 内容；
- `Manifest`；
- 规则文件；
- 控制限快照；
- 参数约束快照；
- 模型文件；
- 预处理器；
- `scenario_ref`；
- `ConfirmedPlan` 内容；
- `candidate_hash`；
- 版本字段。

还必须验证：

- 相同幂等请求不会重复运行模拟器；
- 不会创建第二个有效 `ReplayResult`；
- 基线规范化哈希不一致返回 `BASELINE_REPRODUCTION_FAILED`；
- 候选生成期间模拟器调用次数为 0；
- 诊断和检索期间模拟器调用次数为 0；
- `FaultTruth` 不出现在运行时数据库、API、日志、报告或界面；
- 回放免责声明出现在页面、报告及导出材料；
- 全程断网后仍能完成演示主流程。

模拟器调用次数应通过可测试的调用计数器、依赖边界或测试替身验证，而不是仅靠代码审查推断。

### 测试范围

单元测试至少覆盖：

- MTF 派生指标；
- SPC 目标异常门控；
- 持续性与样本比例判断；
- 特征聚合与固定特征顺序；
- 类别门控；
- Logit 贡献计算；
- 证据充足度；
- KNN 过滤、标准化和稳定排序；
- tick 与 `Decimal` 运算；
- 参数方向证据；
- `ParameterSafetyValidator`；
- 候选去重与排序；
- 哈希规范化；
- 过期机制；
- `ReplayResult` 状态优先级；
- 免责声明生成。

集成测试至少覆盖：

- 完整任务状态机；
- 数据导入到诊断；
- 诊断到候选生成；
- 候选确认与过期；
- 配对回放与基线重现；
- 幂等回放；
- 案例提交；
- 案例状态隔离；
- 审计事件链。

保护分支测试覆盖已冻结的全部保护状态，包括：

- CSV 字段缺失；
- CSV 格式错误；
- `NORMAL`；
- `NON_TARGET_GLOBAL_DEGRADATION`；
- `INSUFFICIENT_DATA`；
- `INSUFFICIENT_EVIDENCE`；
- 不可调故障；
- 候选全部被拒绝；
- 未确认直接回放；
- 过期方案；
- 基线重现失败；
- 模拟器执行失败。

泄漏测试覆盖：

- Batch 级数据集切分；
- 训练、验证和测试隔离；
- 案例库与测试集隔离；
- 演示批次隔离；
- `FaultTruth` 运行时引用扫描；
- 隐藏场景运行时响应扫描。

不设置单纯追求数字的代码覆盖率门槛。测试以外部行为、风险边界和完整业务闭环为核心。

### 人工验收

在预设比赛演示 Windows 环境中：

- 关闭外部网络；
- 从干净的交付包启动应用；
- 按固定演示脚本在 4 分 30 秒内完成主流程；
- 连续成功演练至少 3 次；
- 每次都产生相同核心诊断、候选和回放结果；
- 应用启动、页面切换和回放期间不得出现阻断性错误。

五分钟总时间保留约 30 秒用于讲解和现场波动。

本地备份录像不得代替实际可运行应用，只作为设备或投影故障时的应急材料。

### 最终交付物

最终必须交付：

1. **TuneWise 离线应用包**
   - 面向预设 Windows 演示环境；
   - 提供一键启动脚本；
   - 不依赖外部网络；
   - 不连接真实设备。
2. **完整源代码**
   - 可重复构建；
   - 提供开发、启动、测试、数据生成和评估命令；
   - 不包含密钥或企业私有信息。
3. **版本化数据与模拟资产**
   - 演示 CSV；
   - 训练、验证和盲测集合清单；
   - `DatasetManifest`；
   - 规则文件；
   - 参数约束；
   - 隔离的训练与评估标签；
   - 隐藏模拟场景；
   - 内容哈希和版本记录。
4. **固定算法制品**
   - 预处理器；
   - 逻辑回归模型；
   - 特征定义；
   - `APPROVED` 案例索引；
   - 模型和索引版本信息。
5. **离线评估报告**
   - 检测指标；
   - 根因指标；
   - 检索指标；
   - 基线对比；
   - 每类支持数；
   - 混淆矩阵；
   - 拒绝分布；
   - 安全测试结果；
   - 确定性测试结果；
   - 数据和模型版本哈希；
   - 已知限制与可信声明。
6. **演示材料**
   - 五分钟演示脚本；
   - 操作步骤；
   - 本地备份演示录像；
   - 关键页面截图；
   - 故障应急步骤。
7. **最小文档集**
   - README；
   - 一键运行说明；
   - 数据字典；
   - 数据生成与切分说明；
   - 模型与规则说明；
   - 参数安全边界；
   - 模拟回放说明；
   - 可信声明；
   - 测试记录；
   - `CONTEXT.md`；
   - MVP 决策基线；
   - 后续由 `/to-spec` 生成的正式规格。

### 明确不交付

MVP 不包含：

- 真实设备连接；
- MES 或 QMS 真实集成；
- 自动设备写参；
- 真实质量放行；
- 多用户登录；
- 真实审核工作流；
- 在线模型依赖；
- 生产部署；
- 生产安全认证；
- 舜宇内部数据；
- 真实良率提升声明；
- 企业现网适用性承诺。
