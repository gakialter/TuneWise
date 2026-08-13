# TuneWise

## AA 工站 AI 调机决策支持

企业：舜宇光学科技

队名：工智跃迁

参赛形式：个人参赛

成员：钟秉辰

使用的飞书 AI 能力：飞书 Aily

一句话摘要：TuneWise 是面向精密光学 Active Alignment（AA）工站的 Human-in-the-loop AI 调机决策支持原型：AI 提供异常分析、根因优先级、历史参考案例和调参候选方案，工程师审核确认后再做执行前仿真验证与本地模拟设备受控执行。

命题：如果你是智造专家，你将如何借助 AI 设计并打造「智造调机助手」，提升现场良率？

## 一、方案摘要

TuneWise 聚焦精密光学主动对准（Active Alignment，AA）单一工站。它不是让大模型自由生成参数或自动接管设备，而是把质量测量、当前参数、调机过程信息、平台状态与历史案例组织成一条可审计、可拒绝、可追溯的决策链：版本化数据导入后，系统用 SPC 识别目标异常，以固定工程特征和多分类逻辑回归排序五类根因；当前调机阶段、上一步调整和调整结果用于筛选当前适用的 APPROVED 合成开发案例；确定性方向、幅值和安全规则再生成少量调参候选。工程师确认后形成不可变 ConfirmedPlan，先做执行前仿真验证（Replay）；只有显式启用本地 OPC-UA sandbox、仿真验证为 SUCCESS 且全部门禁再次通过时，才允许演示单参数受控写入与回读。

在此基础上，已发布的飞书 Aily 应用承担生成式 AI 协作层。它检索 8 个版本化知识文件、固定 Demo 证据与 Process-aware Demo 证据，将模型、规则、安全边界和结果组织为自然语言解释。两层 AI 通过版本化知识与固定证据协作，而非通过实时控制接口连接：TuneWise Core 产生可验证的工业决策证据，Aily 负责检索、解释、追溯与问答。

项目当前是比赛原型，不代表舜宇真实内部系统。固定 Demo、Process-aware Demo、模型开发资产与案例均为规则约束的 synthetic data；仿真验证结果属于确定性模拟；OPC-UA 只连接本地 loopback sandbox。方案不声称已接入真实产线、真实设备或真实生产数据，也不填写未经验证的效率、成本与良率收益。

## 二、命题场景与核心问题

主动对准需要同时观察中心与四角 MTF 等质量指标，并调整位置、倾角、焦向等多个参数。故障现象与根因不是一一对应：相似的四角下降可能来自平面倾斜、XY 偏心、平台不稳定、参考漂移或条件式 Z 离焦；一个参数变化也可能同时影响多个质量指标。因此，现场判断不能只看单个数值，更不能把一句自然语言建议直接当作可执行参数。

本方案聚焦方法级痛点，不将行业共性误述为舜宇已确认的内部现状。质量、参数、设备状态和历史经验分散时，根因判断易依赖经验；缺少适用条件的历史动作可能被误用，缺少统一范围、步长、方向和版本约束的调参也难以安全追溯。

传统路径通常是：异常出现 → 人工查看多个指标 → 依赖工程师经验猜测根因 → 翻找历史记录或案例 → 尝试参数 → 重新测试 → 反复迭代 → 决策依据难以追溯。

TuneWise 的切入点不是替代工程师，而是把“看什么、为什么、能否调整、由谁确认、如何验证”变成一条结构化且可拒绝的链路。

【图 1｜传统调机流程 vs TuneWise 决策支持流程】

图注：TuneWise 的核心变化不是移除工程师，而是把分散经验转成可核验的证据链，并在调参候选、工程师确认、仿真验证和执行之间设置安全门禁。该对比只描述工作流能力，不代表已验证的效率或良率提升。

## 三、方案优势与创新

### 1. 从“直接生成调参值”转向证据约束型决策

TuneWise 不允许模型直接给出可执行参数。根因排序只是起点；参数候选还必须具备根因证据、方向证据、可用案例证据、确定性幅值规则与 ParameterSafetyValidator 结果。缺少支持、方向冲突、版本过期或内容被篡改时，系统拒绝继续。AI 的责任由“替人拍板”收敛为“帮助人形成可验证判断”。

### 2. 安全关键 AI 与生成式 AI 解耦

底层 TuneWise 确定性工业 AI 核心负责数值分析、结构化检索、规则约束、工程师确认、执行前仿真验证与执行门禁；上层飞书 Aily · 生成式 AI 协作层负责检索、解释、追溯与问答。Aily 能解释为什么 PLANE_TILT 排在第一、为什么最终选择 pitch 减少 1 tick、仿真验证 SUCCESS 证明什么，却不能生成或修改参数、创建 ConfirmedPlan、触发仿真验证或写 OPC-UA。

### 3. 执行前仿真验证与设备门禁

新参数不会从模型输出直接流向设备。候选先经安全校验，再由工程师确认并冻结为不可变计划；执行前仿真验证先复现导入基线，再在相同隐藏场景、扰动和 seed 下只改变确认参数。设备执行是独立边界，要求仿真验证 SUCCESS、独立人工确认和全部门禁再次通过。

### 4. 从数据到执行凭证的全链可追溯

数据、规则、模型、Scaler、案例索引、调机过程信息、方向证据、候选、ConfirmedPlan、ReplayResult 与执行凭证均绑定版本或 SHA-256。写入开始后如果结果不确定，系统进入 UNKNOWN_OUTCOME，只用同一幂等键进行只读核对，不盲目重写，也不根据当前值猜测成功。

## 四、双层 AI 总体架构

上层飞书 Aily 包含知识空间、知识检索（RAG）、大语言模型（LLM）、工程解释与评委 / 工程问答，关键词是检索、解释、追溯、问答。

下层 TuneWise Core 包含 SPC 异常检测、工程特征提取、AI 根因优先级、历史参考案例检索、安全调参候选生成、参数安全校验、工程师确认、执行前仿真验证与本地模拟设备受控执行。

当前 V1 的连接物是版本化项目知识 + 固定 Demo 证据 + Process-aware Demo 证据，不是实时控制接口。Core 产出固定证据，Aily 只读检索并解释；Aily 不生成新参数、不创建或修改 ConfirmedPlan、不触发仿真验证或 DeviceExecution，也无 OPC-UA 写权限。

【图 2｜TuneWise 双层 AI 架构】

图注：双层架构以职责隔离换取工业可信度。Core 产生确定、可审计的决策证据，Aily 只读检索并解释这些证据，不向 Core 或设备发送控制指令。

## 五、TuneWise Core 技术链路

完整链路为：版本化 CSV → 数据校验 → SPC 异常检测 → 工程特征提取 → StandardScaler → 多分类逻辑回归 → AI 根因优先级 → 调机过程信息驱动的案例资格 → 历史参考案例检索 → 安全调参候选生成 → 参数安全校验 → 工程师确认 → ConfirmedPlan → 执行前仿真验证 → 本地模拟设备受控执行。

【图 3｜TuneWise 核心决策链】

图注：TuneWise 的 AI 深度来自固定工程特征、可解释分类排序、调机过程信息驱动的案例资格、结构化案例检索与确定性安全规则。调机过程信息位于案例检索环节，不进入分类器；最终动作仍受参数安全校验与工程师确认约束。

### 1. 版本化数据与异常检测

输入是固定 schema 的 AA 批次 CSV、Dataset Manifest、规则与版本快照。导入同时校验原始文件 SHA-256 和规范化观测 SHA-256；固定 Demo 包含 24 条观测。哈希只能证明内容与版本一致，不能证明数据来自真实产线。

SPC 使用冻结控制限与持续性规则，把批次路由为 TARGET_ANOMALY、NORMAL、NON_TARGET_GLOBAL_DEGRADATION 或 INSUFFICIENT_DATA，避免单点噪声直接触发诊断。SPC 是保护路由，不是对真实故障的最终确认。

### 2. 固定工程特征与可解释机器学习

系统形成 50 个固定批次工程特征，包括中心与四角 MTF、五个参数、振动、重复定位误差、标定残差的均值、标准差与趋势，以及最差角、四角极差、四角标准差、左右差、上下差、对角差等空间特征。

固定 StandardScaler 与 multinomial logistic regression 对五类候选根因排序：PLANE_TILT、XY_DECENTER、PLATFORM_INSTABILITY、REFERENCE_DRIFT、Z_DEFOCUS_CONDITIONAL。Z 类还受额外硬门控。模型输出稳定 Top-3、raw logit、主要 logit contribution 与 normalized_score。

normalized_score 只用于当前可见候选根因的相对排序，不是经真实产线故障频率校准的概率，也不是现场发生率或真实置信度。页面中的 logit contribution 只说明标准化特征对当前类别 raw logit 的贡献，不代表因果贡献。

### 3. 历史参考案例检索与调机过程信息

案例检索对当前任务重新计算 50 维查询特征，并核对产品、工站、schema、特征定义与检索规则兼容性。可选的调机过程信息——当前调机阶段、上一步调整、上一步调整结果——先决定哪些已审核案例当前有资格参与；有资格的案例仍在独立 Scaler 下按 50 维标准化欧氏距离排序。索引中的 60 个 APPROVED 案例来自 synthetic development training partition，每类根因 12 个。APPROVED 只表示项目内版本化索引准入，不代表专家真值、企业内部案例或真实生产验证。

调机过程信息不进入 Logistic Regression classifier，不修改 StandardScaler，不改变 Root Cause Top-3 算法，也不直接计算参数值。它首先影响当前适用案例、CASE_GUIDED supporting evidence 与案例参考方案。

#### 结合调机步骤的决策演示

异常判断相同，调机过程不同，适用的参考案例也会不同。该 A/B 演示来自独立合成 fixture `tw-process-aware-demo-v1`，与 tw-demo-task-001 固定端到端 Demo 严格分离。

共同条件：测量数据相同，根因优先级相同，Top-1 均为 PLANE_TILT。

- A｜初始评估：上一步调整为“无”；当前适用案例 tw-aa-approved-011；案例参考方案 pitch -3 ticks。
- B｜调整后评估：上一步 pitch 0.250000 → 0.200000，结果为“未观察到显著改善”；当前适用案例 tw-aa-approved-003；案例参考方案 pitch -4 ticks。
- 控制项：两边保守调整方案均为 -1 tick，标准调整方案均为 -2 ticks，参数安全校验全部 PASSED。

事实边界：这是合成调机过程演示，只证明不同调机过程信息可以确定性改变历史案例资格。不代表舜宇真实 SOP，也不证明真实生产调参准确率、真实效果或因果关系。

### 4. 安全参数候选与人工确认

参数方向来自冻结工程规则，不来自 LLM，也不由案例投票决定。固定 Demo 中，PLANE_TILT 的 pitch 使用 top_bottom_difference；该特征为正，当前 pitch 高于标称值，因此安全方向为 DECREASE。roll 对应的 left_right_difference 低于最小空间支持阈值，状态为 INSUFFICIENT_SUPPORT，不生成 roll 候选。

幅值有三种策略：保守调整方案（CONSERVATIVE）固定 1 tick，标准调整方案（STANDARD）固定 2 ticks，案例参考方案（CASE_GUIDED）使用当前适用 APPROVED 案例中方向一致且历史安全通过动作的 tick 绝对值中位数。一个 tick 为 0.050000 normalized prototype unit。所有候选都要通过同一个服务端参数安全校验器 ParameterSafetyValidator，检查合法范围、tick 网格、非零变化、最大单次变化、参数数量与参数族、Top-1 允许族、方向一致、减少到标称值的偏差、不跨标称值、版本绑定与 candidate hash。

工程师只选择服务端已有且 PASSED 的候选，前端不能覆盖参数。服务端复核候选、规则与哈希后，形成状态为 VALID 的不可变 ConfirmedPlan，并绑定 actor、时间、数据、模型、规则和快照版本。上游内容变化会使其 STALE，阻断执行前仿真验证与设备执行。

【图 4｜安全调参决策流程】

图注：保守、标准与案例参考三类候选均通过统一安全校验，最终由工程师（内部身份 AA_PROCESS_ENGINEER）选择最保守的 pitch -1 tick 方案；证据不足的 roll 轴没有候选。模型负责根因排序，不直接输出参数。

## 六、执行前仿真验证与设备安全门禁

执行前仿真验证只接受服务端保存且仍为 VALID 的 ConfirmedPlan。系统先用相同 simulator、固定 seed、固定扰动和当前参数复现基线，并使用同一 canonicalizer 计算哈希；只有 simulated baseline hash 与导入时 canonical observation hash 完全一致，才运行调参方案仿真。

通过基线复现后，baseline 与 intervention 共享隐藏场景、扰动、seed、样本数、时间序列、schema 和 simulator version，唯一允许变化的是 ConfirmedPlan 中的参数。仿真验证结果（ReplayResult）包括 SUCCESS、PARTIAL_IMPROVEMENT、NO_IMPROVEMENT 与 REGRESSION。“仿真验证通过”只表示当前固定 simulator、seed、disturbance 和评价规则下，确认方案满足预设条件；不代表真实设备有效、良率提升、最优参数、生产收益或真实因果证明。

设备执行默认关闭，只能在显式 OPCUA_SANDBOX 模式下连接固定 loopback endpoint。执行前重新检查 ConfirmedPlan freshness、仿真验证绑定、基线复现、仿真验证 SUCCESS、参数安全校验、单参数限制、observed server identity、mapping、datatype、unit、access、Method capability 与设备健康。

五个参数 Variable 对普通 OPC-UA client 全生命周期只读，唯一运行期 mutation 入口是 ApplyConfirmedParameterChange。该 Method 在 sandbox 单一 execution lock 内完成 idempotency lookup、权威当前值读取、expected-before 比较、单参数写入、readback 与设备记录。OPC-UA 协议本身不天然提供 compare-and-set，这些语义只由本地 sandbox Method 实现。

若写入开始后发生超时、通信中断或本地 receipt 首次持久化失败，状态进入 UNKNOWN_OUTCOME。它不等于 FAILED，也不等于 SUCCEEDED，更不会自动重试。恢复只按同一 idempotency key 查询设备侧记录；缺少可信证据时保持 RECONCILIATION_REQUIRED，即使当前值恰好等于 target，也不能伪造成功。

【图 5｜Fixed Demo 真实运行界面】

图注：三个页面来自当前脚本实际运行 tw-demo-task-001 后的诊断 / 候选、ConfirmedPlan / 仿真验证和本地设备执行回执界面。小标签保留参数安全校验、工程师确认、基线复现、仿真通过后再检查设备执行资格与仅本地 sandbox 等门禁；完整安全语义以上述正文为准。软件实际运行不等于真实产线、真实设备或生产效果验证。

## 七、固定 Demo：一条完整而有边界的证据链

固定 Demo 身份为 Task tw-demo-task-001，预置资产 tw-aa-demo-v1，Batch tw-aa-demo-batch-001，Station AA，产品型号 TW-AA-PROTOTYPE-V1，共 24 条规则约束 synthetic AA prototype observations。本节不与前述合成调机过程 A/B 演示拼接为“真实生产案例”。

异常检测结果为 TARGET_ANOMALY，24/24 条观测持续违反当前路由信号。Top-3 根因依次为 PLANE_TILT 0.997781、XY_DECENTER 0.001454、REFERENCE_DRIFT 0.000534。其中 0.997781 是 relative ranking score，不是 99.7781% 故障概率。关键工程特征包括 top_bottom_difference 0.132913、left_right_difference 0.014371、diagonal_difference -0.051924、pitch_mean 0.250000、roll_mean -0.200000。

结构化检索返回三个兼容 PLANE_TILT 案例：tw-aa-approved-011、tw-aa-approved-001、tw-aa-approved-002。它们来自 synthetic development cases，不是企业内部案例或专家 ground truth。

同一规划结果真实生成三个 pitch 候选，且均通过安全校验：

- 保守调整方案（CONSERVATIVE）：0.250000 → 0.200000，-1 tick；
- 标准调整方案（STANDARD）：0.250000 → 0.150000，-2 ticks；
- 案例参考方案（CASE_GUIDED）：0.250000 → 0.100000，-3 ticks。

本次 ConfirmedPlan 只选择保守调整方案（CONSERVATIVE）。其幅值来自固定 1 tick 规则，不依赖案例幅值；案例参考方案（CASE_GUIDED）的 -3 ticks 才使用三个 APPROVED 案例的中位数证据。选择主体为 AA_PROCESS_ENGINEER，ConfirmedPlan 状态为 VALID 且不可变。

执行前仿真验证的基线复现为 PASSED，仿真验证状态为 SUCCESS，attempt count 为 1。固定模拟指标为：

- Center MTF mean：0.831003 → 0.832128；
- Worst corner MTF：0.567683 → 0.651478；
- Corner range：0.184837 → 0.102292；
- Corner std：0.071709 → 0.042654；
- Control limit pass：false → true；
- Target anomaly triggered：true → false。

以上变化来自固定 tw-simulator-v1、固定场景、固定扰动、固定 seed 与 tw-evaluation-v1，只证明规则约束模拟环境中的离线检查通过。浏览器人工 QA 还记录了同一方案在 LOCAL_OPCUA_SANDBOX 上执行 SUCCEEDED，pitch 写后回读 0.200000；它是本地模拟设备，不是真实设备。

【图 6｜结合调机步骤的决策演示】

图注：图中是 /process-aware-demo/ 的实际 A/B 运行界面：shared evidence 相同，A / B 的调机过程信息不同，当前适用案例与案例参考方案随之改变，保守 / 标准方案和参数安全校验保持不变。界面真实运行，但输入仍是 SYNTHETIC_TEST_FIXTURE；不代表舜宇 SOP、真实生产调参准确率或生产验证。固定 Demo 的精确数字仍以上述正文记录为准。

## 八、飞书 Aily 工程解释与问答

TuneWise Core 的输出包含模型版本、规则、哈希、候选状态、仿真验证检查与设备凭证。它们适合工程审计，却不适合所有评委或现场人员直接阅读。Aily 的价值不是替代 Core，而是把分散在项目知识、工程规则、固定 Demo 与 Process-aware Demo 证据中的事实变成可对话的解释入口。

当前已发布应用名为 TuneWise，工作流为 TuneWise Engineering Copilot，Knowledge Space 为 TuneWise Engineering Knowledge。流程是 Start → Knowledge Space Retrieval → LLM → End；Top K 为 5，Threshold Filter 关闭，发布时 LLM 为 Doubao-seed-2.0-Pro。

8 文件知识包包括 Project Overview、Architecture & AI、Diagnosis & Parameter Safety、Replay & OPC-UA Safety、Demo Evidence、Facts Boundary & FAQ、Judge Guide 与 Process-aware Demo Evidence。Aily 依据检索结果回答项目概览、根因排序、参数方向与幅值、调机过程信息影响、仿真验证语义、安全边界和评委问答；证据不足时应明确拒绝猜测。

Aily V1 已在发布应用中完成 Manual UI / conversational acceptance validation：Live Knowledge Pack 8/8、Legacy Safety Hard Gates PASS、Process-aware QA PASS、Published Environment PASS。这些是人工验收记录，不是 automated benchmark、100% model accuracy 或 real production validation。

仓库现有真实 Aily 截图仅记录固定 Demo Hero QA：“tw-demo-task-001 为什么把 PLANE_TILT 排在第一？”。它不是 Process-aware Q5 截图；图 7 只复用这份既有证据，不生成或补写 Aily 对话。

Aily 当前没有 Evidence Bridge、MCP、HTTP integration、Custom Connector 或 Runtime API，不实时读取 TuneWise 运行状态，不生成或修改参数，不创建或修改 ConfirmedPlan，不触发仿真验证、DeviceExecution 或 OPC-UA write。

【图 7｜飞书 Aily 工程解释｜Workflow + 真实问答】

图注：左侧展示 Aily Workflow 与 8 文件知识包；右侧只嵌入仓库既有真实截图，问题是“tw-demo-task-001 为什么把 PLANE_TILT 排在第一？”，属于固定 Demo Hero QA，明确不是 Process-aware Manual Acceptance 的 Q5。Process-aware QA PASS 来自人工验收记录，不伪造 Q5 截图。Aily 只负责检索与解释，不具备参数生成、仿真验证或 OPC-UA 写权限；真实 UI 也不等于模型准确率或生产验证。

## 九、方案价值

### 1. 工程效率：减少证据整理路径

TuneWise 把异常指标、根因候选、案例、参数依据、安全检查、确认与结果放在同一任务上下文中，使讨论围绕同一版本证据展开。Aily 进一步把这些证据转成可检索的自然语言解释。实际节省时间仍需在企业 Shadow Mode 中测量。

### 2. 调机安全：让“不能继续”成为系统能力

数据不足、不可调根因、方向冲突、越界、离网格、跨标称、计划过期、仿真验证不通过、设备身份或能力不匹配都会阻断后续。设备执行默认关闭，当前只验证本地 sandbox 单参数路径，不能替代真实设备的 PLC 联锁、证书、审批和现场安全制度。

### 3. 知识沉淀：保存证据，而不只保存结论

可复用知识应包含异常现象、数据版本、模型与规则、根因排序、调机过程信息、候选依据、确认主体、仿真验证结果与适用条件。当前 APPROVED 案例库与调机过程资料是固定 synthetic development assets，尚未把真实任务自动写回生产知识库；但其准入隔离和版本化结构证明了“知识必须先审核再复用”的方法。

### 4. 可复制性：场景知识与安全骨架分离

根因、特征、方向规则与约束属于具体工艺；版本、哈希、确认、执行前仿真验证、幂等、receipt 与事实边界属于可复用安全骨架。迁移时可以替换场景资产，同时保留证据链和执行门禁思路，避免把一个 Demo 生硬复制到另一设备。

### 5. 价值验证：先定义量尺，再讨论收益

进入企业 Shadow Mode 后，TuneWise 建议把价值验证拆成可审计的过程指标，而不是预先承诺收益数字。工程效率可记录从异常出现到形成完整证据包的耗时、人工检索案例的步骤数，以及工程师对 Top-3 根因和候选依据的可理解性评价；安全性可记录被 Validator 拒绝的无效候选、过期计划和门禁不满足事件；知识价值可记录证据包完整率、案例准入审核结果与相同问题的解释一致性；业务结果则由企业在获授权数据上定义质量指标、对照方式和观察周期。

这些指标在当前原型中只是一套未来验证框架，没有目标值，也没有被写成已实现收益。只有数据口径、样本范围、基线、审批人与统计方法都得到企业确认后，才进入量化比较；在此之前，项目只报告可复现的工程证据和明确的能力边界。

## 方案体验入口 & demo 展示视频【建议包含】

项目代码与工程证据：

https://github.com/gakialter/TuneWise

飞书 Aily：

TuneWise Engineering Copilot 已发布，核心 Workflow 与真实问答效果见上文截图，并已完成发布环境下的人工 UI / conversational acceptance validation。

Demo 展示：

固定 Demo 的异常检测、根因排序、安全调参候选、工程师确认、执行前仿真验证与本地 OPC-UA sandbox 结果已在上文通过完整证据链展示；独立的 Process-aware Demo 展示同一异常证据下调机过程信息如何改变当前适用案例。

本地启动后，固定端到端 Demo 位于 http://127.0.0.1:8000，Process-aware Demo 位于 http://127.0.0.1:8000/process-aware-demo/。两者都只在运行者本机有效，不是互联网体验链接。

## 十、验证证据与当前边界

当前自动化主结果：Backend full suite 454 / 454 PASS；Frontend 46 / 46 PASS。测试通过证明工程回归状态，不是模型准确率、真实设备验证或业务收益证明。

历史自动化快照绑定 commit 1fdc526：433 个 backend tests、40 个 frontend tests 与 production build 通过。该结果只作为历史 commit-bound evidence 保留，不再作为主验证数字。

浏览器人工 QA：固定 Demo PASS，本地 OPC-UA sandbox execution SUCCEEDED、readback 0.200000；Process-aware Demo PASS，桌面 / 移动端 PASS。两个 Demo 均为 synthetic，且在材料中严格分离。

图 5 / 6 的“真实运行界面”只证明当前软件按记录运行，不把 synthetic Demo、本地 sandbox 或软件截图升格为真实设备、真实数据或生产验证。

Aily V1 的 Live Knowledge Pack 8/8、Legacy Safety Hard Gates PASS、Process-aware QA PASS 与 Published Environment PASS 属于已发布应用中的 Manual UI / conversational acceptance validation，不是自动 benchmark、100% model accuracy 或真实生产验证。

【图 8｜验证与证据总结】

图注：验证摘要分开呈现工程自动化验证、固定 / Process-aware Demo 浏览器验证、Aily 人工验收与当前边界。当前主数字为 backend 454/454、frontend 46/46；历史 433/40 只绑定 1fdc526。

### 公开真实数据验证边界审查

按照 Coach 建议，我们进一步核验了 Rikkyo University 的 LOROS 公开真实光学实验数据。LOROS 提供真实采集的 slanted-edge MTF / SFR / processed ROI 数据，provenance 和 CC-BY-4.0 许可可追溯；当前 record DOI 为 10.5281/zenodo.17493261，配套论文 DOI 为 10.1186/s40645-025-00783-7。

但 LOROS 缺少 AA production identity、x/y/z/pitch/roll 设备状态、调机动作、root-cause ground truth、参数方向、before/after intervention、process stage 与 production outcome。语义映射审查结论是 NO-GO，不是“公开真实数据验证 PASS”。TuneWise 没有伪造 PLANE_TILT ground truth、把 edge angle 当 pitch、把 Pos 0..5 当空间五点、把 wavelength 当参数、复制中心 MTF 到四角或修改 frozen classifier contract。真实 AA 业务效果继续保留至授权企业数据验证阶段。

当前仍属于 SIMULATION ONLY 或 NOT YET VALIDATED 的内容包括：舜宇或其他真实光学产线接入、经授权真实设备数据的外部验证、真实 PLC 与设备联锁、生产证书和身份环境、企业 MES/QMS 集成、真实工艺控制限与单位映射审批、多参数原子执行、自动回滚，以及经真实业务数据验证的效率、成本和良率收益。

## 十一、可落地性与路线

当前已经完成可运行的本地 software prototype、版本化数据与 SPC、固定 ML 根因排序、调机过程信息驱动的当前适用案例、APPROVED-only 检索、安全候选与统一 Validator、工程师确认与不可变 ConfirmedPlan、基线复现与确定性配对执行前仿真验证、默认关闭的本地 OPC-UA sandbox 单参数受控执行、Shadow Data 只读契约、LOROS 公开数据语义边界审查（NO-GO），以及已发布并完成 8/8 与 Process-aware QA 人工验收的飞书 Aily 工程解释应用。

Phase 1｜Shadow Mode：取得授权导出数据，由设备、工艺与数据责任方确认字段语义、单位、设备型号、batch/lot、来源与授权引用。数据只进入 SHADOW_READ_ONLY，先做完整性、质量与离线输出评估，不进入训练集、案例库或设备写入。

Phase 2｜Engineer Decision Support：在真实工程师监督下，对诊断证据、候选合法性与解释质量进行盲评或回顾性验证，建立真实审核协议、拒绝标准和版本管理。系统仍只提供决策支持，由工程师在企业既有流程中执行。

Phase 3｜Supervised Controlled Execution：只有设备侧受控 Method、CAS 或 PLC/上位机联锁、身份与证书、审批、回滚、并发所有权、断线恢复和现场安全测试全部获批后，才讨论受监督的真实设备集成。当前项目没有到达该阶段，也不以无人值守自动调机为近期目标。

## 十二、推广边界

TuneWise 优先适用于同时满足以下条件的设备调优或工艺调参问题：存在多参数耦合但参数空间可明确约束；过程指标可测量并能形成版本化数据；根因候选可结构化且能区分可调与仅检查类别；历史案例具备适用条件和审核状态；高风险动作必须保留人工确认；结果可以先在离线、shadow 或仿真环境中评估。

在这些条件下，本方法可优先评估迁移到光学 AA、精密装调及部分参数型工艺优化场景。每次迁移都必须重新建立真实特征、控制限、单位、规则、模型、案例准入与设备安全协议，不能直接复用当前 synthetic 参数。

## 十三、Coach 反馈闭环

- Replay 看不懂：评委向统一改为“执行前仿真验证”；完整门禁保留在正文“六”与图 3 / 4，图 5 以运行界面小标签提示基线复现、仿真通过和设备执行资格检查，并明确 SUCCESS 只属于固定模拟条件。
- 缺少调机步骤：新增“调机过程信息 → 当前适用案例 → 案例参考方案”的合成 A/B Demo；分类器、Scaler 与 Root Cause Top-3 不变。
- 缺少真实数据：完成 LOROS 一手来源与字段语义审查，结论 NO-GO；没有为了比赛制造虚假的 AA 生产验证。

## 十四、事实边界与结论

TuneWise 是单工站、人在回路的比赛原型，不代表舜宇真实内部系统。固定 Demo、Process-aware Demo、模型开发资产和 APPROVED 案例不是企业真实生产数据；normalized_score 不是校准故障概率；“仿真验证通过”只属于当前固定 simulator、seed、disturbance 和评价规则，不证明真实良率、生产收益、真实设备效果、因果关系或最优参数；当前 OPC-UA 只连接本地 loopback sandbox；Aily 只检索和解释版本化知识与固定证据，不生成参数、不修改 ConfirmedPlan、不触发仿真验证或设备写入；LOROS 的 NO-GO 只是一项公开真实数据语义边界审查，不是 AA 生产验证 PASS。

TuneWise 的核心价值，是把工业 AI 从“给出一个答案”推进到“形成一条可验证、可拒绝、可追溯、有人授权的决策链”。它用确定性 Core 守住数据、参数和设备安全，用飞书 Aily 降低复杂证据的理解成本，为后续授权数据下的 Shadow Mode 验证提供了完整、诚实且可扩展的基础。
