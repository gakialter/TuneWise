# TuneWise｜5 分钟演示脚本

本脚本包含两个独立证据。Demo A 是 5 分钟 End-to-End Fixed Demo；如需现场展示完整 sandbox execution，必须用 `start-tunewise-opcua-demo.cmd` 显式启用本地模拟设备。Demo B 是独立的 60–90 秒 Process-aware Decision Demo，不占 Demo A 的 5 分钟主槽，也不与 Demo A 拼接成一个生产故事。Demo A 打开 `http://127.0.0.1:8000` 并选择第一个 `CONSERVATIVE` 候选，Demo B 打开 `http://127.0.0.1:8000/process-aware-demo/`。完整路径见[评委快速体验指南](judge-guide.md)。

正式产品定位：TuneWise 是面向精密光学 Active Alignment（AA）工站的 Human-in-the-loop AI 调机决策支持原型。AI 分析异常、进行根因排序、检索适用案例并形成参数候选与证据；工程师审核并选择/确认；之后才进入 Simulation Validation (Replay) / 执行前仿真验证和受控 sandbox 执行原型。

## Demo A — End-to-End Fixed Demo

`Detect → Diagnose → Recommend → Human Confirm → Simulation Validation → OPC-UA Sandbox Execution`

本 5 分钟主路径证明完整受控决策链可以运行；它不证明真实生产效果。

## 0:00–0:20｜项目定位和边界

**屏幕操作**：停留在首页首屏，指向“本地离线”、固定演示身份和任务闭环。

**建议讲稿**：

“TuneWise 是面向精密光学 AA 工站的 Human-in-the-loop AI 调机决策支持原型。底层确定性 Core 产生可验证的异常、候选与仿真证据；上层已发布的飞书 Aily 通过 RAG 检索并解释版本化知识与固定 Demo Evidence。工程师负责审核和确认，Aily 不进入参数和设备控制链。”

**必须指出**：单一 AA 工站；本地 Core 离线；人在回路；Aily 只解释固定证据，不控制。

**不应说**：AI 自动调机；已接入舜宇产线；已提升真实良率；生产级系统。

**超时缩减**：只说第一、二句，保留“没有真实设备连接”。

## 0:20–0:45｜导入 AA 演示数据

**屏幕操作**：点击“导入预置 AA 异常批次”，向下指向校验摘要。

**建议讲稿**：

“我先导入固定版本的 AA 演示批次。系统校验 schema、Manifest、原始文件哈希和规范化观测哈希，并固定规则、模型和参数约束。这里共有 24 条模拟观测。”

**必须指出**：24 条观测；raw file hash `PASSED`；canonical observation hash `PASSED`。

**不应说**：自动采集了产线数据；这是舜宇设备数据；Manifest 能证明数据真实。

**超时缩减**：只指 schema 和双哈希均 `PASSED`。

## 0:45–1:15｜异常检测和四角不对称证据

**屏幕操作**：点击“运行异常检测”，指向异常标题、指标和持续性检查。

**建议讲稿**：

“异常检测使用版本化 SPC 规则。中心 MTF 是 0.831003，最差角落 0.567683，四角极差 0.184837、标准差 0.071709；24 个样本持续越限，因此路由为 `TARGET_ANOMALY`。其他结果会被保护阻断。”

**必须指出**：`0.831003`、`0.567683`、`0.184837`、`0.071709`、24/24、`TARGET_ANOMALY`。

**不应说**：模型发现故障；中心 MTF 不合格；单个异常点就能触发。

**超时缩减**：保留中心、最差角落、极差和 `TARGET_ANOMALY` 四项。

## 1:15–1:50｜Top-3 根因、规则和 logit 贡献

**屏幕操作**：点击“运行根因诊断”，滚动到 Top-3；展开或指向第一项规则与贡献。

**建议讲稿**：

“固定逻辑回归输出的 Top-3 是 `PLANE_TILT`、`XY_DECENTER`、`REFERENCE_DRIFT`。Top-1 相对分数 0.997781，证据充分。这里展示的是特征对当前类别 logit 的贡献，不是真实故障概率；证据不足时参数候选必须为零。”

**必须指出**：Top-3 顺序；Top-1 `0.997781`；`SUFFICIENT_EVIDENCE`；logit 贡献术语。

**不应说**：99.7781% 的真实故障概率；已经确认真实根因；模型证明 Pitch/Roll 导致异常。

**超时缩减**：只读 Top-3、证据充分和“分数不是概率”。

## 1:50–2:15｜APPROVED 相似案例

**屏幕操作**：点击“检索已审核案例”，指向“仅检索 APPROVED 案例”、距离和历史动作。

**建议讲稿**：

“案例检索采用版本固定的结构化 KNN，只允许兼容的 `APPROVED` 案例进入距离计算。待审核、测试和演示来源不能进入索引；历史动作只提供参考，不会直接复制成当前参数。”

**必须指出**：返回 3 个案例；`APPROVED` only；结构化距离；历史动作仅供参考。

**不应说**：这是企业内部历史案例；最相似案例就是正确答案；系统会在线学习新案例。

**超时缩减**：保留“只用 APPROVED”和“历史动作不会直接复制”。

## 2:15–2:50｜方向证据、安全候选和 Validator

**屏幕操作**：点击“生成安全参数候选”，指向 Pitch/Roll 方向证据与候选卡；选择第一个“选择 CONSERVATIVE 候选”。

**建议讲稿**：

“这里 Pitch 有 `NO_CONFLICT` 方向证据，Roll 是 `INSUFFICIENT_SUPPORT`，所以只调整有证据的轴。唯一 Validator 检查范围、0.05 步长、最大变化、标称方向和参数族；不满足就拒绝。我选择保守候选：Pitch 从 0.250000 到 0.200000。”

**必须指出**：Pitch `NO_CONFLICT`；Roll `INSUFFICIENT_SUPPORT`；步长 `0.050000`；Pitch `0.250000 → 0.200000`；候选为 `PASSED`。

**不应说**：系统找到最优参数；案例推荐覆盖了安全规则；Roll 没问题；候选将自动写入设备。

**超时缩减**：只展示 Pitch 单轴变化和 Validator `PASSED`。

## 2:50–3:15｜人工确认和不可变 ConfirmedPlan

**屏幕操作**：点击“人工确认候选方案”，指向 `VALID`、确认身份和确认方案哈希。

**建议讲稿**：

“前端只提交候选身份，服务端复核安全规则和哈希，再生成不可变 `ConfirmedPlan`，绑定身份、时间和版本。上游变化会使方案变成 `STALE`。这只是冻结离线候选，没有设备参数下发。”

**必须指出**：`VALID`；AA 工艺工程师；确认哈希；没有设备写参。

**不应说**：参数已经生效；确认等于质量放行；前端可以修改确认方案。

**超时缩减**：说清“服务端复核、不可变、没有写参”。

## 3:15–4:10｜Simulation Validation：Baseline reproduction 和配对模拟

**屏幕操作**：点击“运行离线模拟回放”，等待 `SUCCESS`；指向 baseline reproduction、指标对比和结果哈希。

**建议讲稿**：

“确认后才进入 Simulation Validation。系统先重现导入基线，canonical hash 一致、状态 `PASSED` 才继续；前后使用同一 simulator、场景、扰动、seed 和 evaluation contract，只改变确认参数。内部结果对象仍是 `ReplayResult`。结果为 `SUCCESS`、尝试次数 1：中心 0.831003 到 0.832128，最差角落 0.567683 到 0.651478，极差 0.184837 到 0.102292，标准差 0.071709 到 0.042654；控制限通过，目标异常清除。”

**必须指出**：baseline reproduction `PASSED`；`SUCCESS`；`attempt_count = 1`；上述四组数值；control limit 与 target anomaly 变化；结果哈希可追溯。

**不应说**：真实产线反事实实验；证明 Pitch 是真实因果根因；真实良率提高；一次就能调好真实设备。

**超时缩减**：只说 baseline `PASSED`、worst corner、corner range、控制限和 `SUCCESS`。

## 4:10–4:45｜本地 OPC-UA sandbox 受控执行

**前提**：本段只有在通过 `start-tunewise-opcua-demo.cmd` 显式启用固定 loopback sandbox 时演示。默认 `start-tunewise.cmd` 不开启设备执行，不能虚构本段已运行。

**屏幕操作**：在 `SUCCESS` 后点击“检查设备执行资格”；看到“设备执行资格已通过”后，勾选“我确认当前目标是本地 OPC-UA 模拟设备，并授权执行这一次写入与回读验证”，再点击“向模拟设备执行受控下发”。

**建议讲稿**：

“设备执行默认关闭。这里连接的是固定 loopback 本地 OPC-UA sandbox。服务端重新验证 ConfirmedPlan freshness、Simulation Validation `SUCCESS`、Validator、单参数限制、server identity、mapping、datatype、unit、只读 access 和受控 Method capability。独立人工确认后，sandbox Method 对 pitch 执行 expected-before、单参数写入、readback 和幂等记录；固定证据中状态为 `SUCCEEDED`，写后回读 `0.200000`。”

**必须指出**：本地模拟设备；独立 acknowledgement；普通 Variable 只读；受控 Method；`SUCCEEDED`；readback `0.200000`；receipt hash。

**不应说**：真实设备写入；生产 PLC 原子性；OPC-UA 天然提供 CAS；真实安全联锁已经验证。

## 4:45–5:00｜结果边界和 Aily 协作层

**屏幕操作**：停留在 Simulation Validation 或本地 sandbox receipt 的免责声明；不要点击锁定的“复盘关闭”或“案例提交”。

**建议讲稿**：

“这些数字和 sandbox receipt 来自规则约束模拟环境，不代表真实产线良率改善、真实设备效果或真实因果关系。飞书 Aily 已发布，用于检索和解释版本化知识与固定证据；它没有 Runtime API、参数修改或 OPC-UA 写权限。”

**必须指出**：完整免责声明；Aily V1 是 fixed evidence RAG；没有实时 Bridge 或设备控制。

**不应说**：已经具备生产部署条件；已完成真实产线或授权企业数据验证；将直接接入设备自动执行。

**超时缩减**：只读完整免责声明并说“当前是 synthetic / sandbox 的 Human-in-the-loop 软件原型”。

## 全程超时方案

- 落后 15 秒：不展开案例卡与安全检查明细，只指向状态；
- 落后 30 秒：诊断只读 Top-3，案例只说 APPROVED-only，回放只报 worst corner、corner range 和状态；
- 页面响应慢：先讲当前段落，结果出现后只指关键状态，不重复解释；
- 剩余不足 30 秒：直接跳到回放结果截图或已完成页面，读免责声明；不要修改数据库、规则或结果赶时间。

## 30 秒极简备用介绍

“TuneWise 是面向精密光学 AA 工站的 Human-in-the-loop AI 调机决策支持原型。底层确定性 Core 把版本化数据、SPC、Top-3 根因、APPROVED 案例、安全候选、人工确认和 Simulation Validation 连成可追溯闭环；上层已发布的飞书 Aily 通过 RAG 解释版本化知识与固定证据。Aily 不生成参数或控制设备。固定演示中 baseline reproduction 通过，`ReplayResult` 状态为 SUCCESS；该结果只属于规则约束模拟环境，不代表真实产线良率改善。”

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。

## Demo B — Process-aware Decision Demo（独立证据，约 60–90 秒，不计入 5 分钟主槽）

`Same Measurement Evidence + Different Process Context → Different Eligible Historical Evidence → Different CASE_GUIDED`

**屏幕操作**：单独打开 `http://127.0.0.1:8000/process-aware-demo/`。不要把这里的 synthetic previous action 讲成 Demo A 的真实延续，也不要在本段声称执行了 Human Confirm、Simulation Validation 或 OPC-UA execution。

**建议讲稿**：

“这是独立的 synthetic process-context demonstration。A/B 两侧使用同一 measurement evidence、同一 50-D query fingerprint 和同一 Top-3：`PLANE_TILT`、`XY_DECENTER`、`REFERENCE_DRIFT`。Scenario A 处于 `INITIAL_ASSESSMENT`，没有 previous action，符合资格的案例是 `tw-aa-approved-011`，`CASE_GUIDED` 为 pitch `-3` ticks。Scenario B 处于 `POST_ADJUSTMENT_EVALUATION`，前一步 pitch `0.250000 → 0.200000`，结果抽象为 `NO_MATERIAL_IMPROVEMENT`，符合资格的案例变为 `tw-aa-approved-003`，`CASE_GUIDED` 为 pitch `-4` ticks。”

“变化发生在案例资格与解释层，不是 classifier 改变。两侧 `CONSERVATIVE -1` tick、`STANDARD -2` ticks 和 `ParameterSafetyValidator PASSED` 均保持一致。”

**必须指出**：`ProcessContext` / `CaseProcessProfile` 来自 synthetic fixtures；这些状态名称是 TuneWise abstractions，不是行业标准状态或舜宇内部 SOP；pitch `-3 / -4` ticks 是 synthetic demonstration outputs；当前 compatibility rules 未经过真实企业过程数据验证。

**不应说**：舜宇真实调机流程；真实生产 tuning history；过程上下文提高了真实推荐准确率；已经证明 sequential optimization、真实因果效果或真实良率提升。

**结论边界**：该 Demo 证明 deterministic context-sensitive evidence selection 和 legacy regression safety；后者仅指既有 classifier/Top-3、`CONSERVATIVE` / `STANDARD` candidates 与 `ParameterSafetyValidator` 结果保持不变，不表示完整生产安全或效果验证。它不证明真实 AA 推荐准确率或 production tuning effectiveness。真实生产验证仍属于后续 Shadow Data / controlled validation。
