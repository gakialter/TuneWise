# TuneWise｜比赛报名表可复制材料

本文件按常见报名字段整理。提交前请根据报名页面的实际字数规则复核；所有结果均对应已注明的 Core 验证基线或已发布并人工验收的飞书 Aily V1。

## 1. 项目名称

TuneWise——面向精密光学主动对准工站的 AI 调机决策支持系统

## 2. 一句话介绍（不超过 50 字）

为精密光学 AA 工站提供可追溯、人在回路的离线调机决策支持。

## 3. 100 字项目简介

TuneWise 面向精密光学主动对准单一工站，串联离线数据导入、异常检测、Top-3 根因、已审核案例、安全候选、人工确认和模拟回放。系统不直接控制设备；原型仅使用公开知识和规则化模拟数据，结果不代表真实产线良率改善。

## 4. 300 字项目简介

TuneWise 是面向精密光学主动对准（AA）单一工站的调机决策支持原型。确定性 Core 以 SPC、固定逻辑回归、APPROVED-only 检索和统一 Validator 形成诊断、荐参、确认与 Replay 证据。Process-aware 能力用 synthetic fixtures 演示“调机过程信息 → 当前适用案例 → 案例参考方案”；Process Context 不进入 classifier，也不改变 StandardScaler 或 Root Cause Top-3。飞书 Aily 通过 8-file Knowledge Pack 与 RAG 做工程解释，不生成参数或控制设备。项目未接入真实产线或真实设备；模拟结果不代表生产效果。

## 5. 500 字项目简介

TuneWise 聚焦精密光学主动对准（AA）单一工站，为工程人员提供可解释、可拒绝、可追溯的调机决策支持。确定性 Core 将版本化 CSV、SPC 异常路由、固定逻辑回归 Top-3、APPROVED-only KNN、安全候选、人工确认和配对模拟回放组织成闭环；候选统一经过 Decimal/tick Validator，证据不足、方向冲突、方案过期或篡改时拒绝继续。Process-aware 能力以 synthetic fixtures 演示“调机过程信息 → 当前适用案例 → 案例参考方案”；Process Context 不进入 classifier，不改变 StandardScaler 或 Root Cause Top-3。飞书 Aily 使用 8-file Knowledge Pack、RAG 与 LLM 解释版本化知识和固定证据，但不生成参数、不修改 ConfirmedPlan、不触发 Replay 或控制设备。Replay SUCCESS 仅表示模拟规则通过。项目未接入 MES、QMS 或真实设备；受控写参与 readback 仅在显式 LOCAL OPC-UA SANDBOX 中验证，不是生产或真实 PLC 验证。

## 6. 800～1000 字完整项目介绍

精密光学装调的异常排查需要综合质量测量、当前参数、平台状态、标定残差和历史经验；信息分散时难以形成一致、可复核的判断。TuneWise 因此定位为面向主动对准（AA）单一工站的离线调机决策支持原型，而不是 AI 自动调机系统。

系统导入版本化演示 CSV，校验文件与观测哈希、Manifest、schema、规则和模型版本，再用 SPC 识别目标异常及保护路由。固定 StandardScaler 与 multinomial logistic regression 对五类根因排序，展示 Top-3、规则、关键观测和 logit 贡献；relative score 只用于排序，不是 probability。结构化 KNN 只检索条件兼容的 APPROVED 案例。

Process-aware 能力使用 synthetic fixtures，形成“调机过程信息 → 当前适用案例 → 案例参考方案”的确定性演示。Process Context 只改变案例资格和案例参考证据，不进入 classifier，也不改变 StandardScaler 或 Root Cause Top-3。

每个参数先形成方向证据，再由 Decimal/tick 与 ParameterSafetyValidator 检查范围、网格、最大变化、标称方向和参数族。证据不足、方向冲突、版本过期或篡改时拒绝继续。工程师选择 PASSED 候选后，服务端生成绑定候选哈希、身份、时间和版本的不可变 ConfirmedPlan。

Replay 先规范化重现导入基线，再让前后方案共享 simulator、场景、扰动、seed 和因果版本，唯一变化是确认参数。固定演示中 baseline reproduction 为 PASSED，Replay 为 SUCCESS，最差角落 MTF 0.567683 → 0.651478，四角极差 0.184837 → 0.102292；这只表示固定模拟评价规则通过，不代表生产效果、真实因果或最优参数。

项目只使用公开知识和规则约束模拟数据，不包含企业内部数据，未接入 MES、QMS 或真实设备。受控单参数执行与 readback 仅在显式 LOCAL OPC-UA SANDBOX 中验证，不是生产部署、真实设备或真实 PLC 安全验证。飞书 Aily 仅通过 8-file Knowledge Pack 与 RAG 解释版本化知识和固定证据，没有 Bridge、Runtime API、参数生成或设备控制权限。

## 7. 项目背景与痛点

- 数据、参数、质量结果和经验分散，难以形成统一证据链；
- 根因排查依赖个人经验，判断过程不易复核；
- 无效试调成本高，且高风险动作不能交给模型直接执行；
- 成功处理经验缺少结构化准入与版本边界，难以安全复用；
- 比赛阶段无法使用企业真实产线数据，需要可复现且诚实标注的验证方法。

## 8. 解决方案

以单一 AA 工站为边界，构建本地离线的确定性处理链：版本化 CSV 导入与完整性校验 → SPC 异常路由 → 逻辑回归 Top-3 根因与结构化解释 → APPROVED-only 案例检索 → 参数方向证据 → 安全候选与统一 Validator → 人工确认和不可变 ConfirmedPlan → baseline reproduction → 配对模拟回放与结构化评估。任何证据、状态、版本或安全条件不满足时均拒绝继续。

## 9. 核心创新点

1. **人在回路而非模型直控设备**：模型只帮助排序和解释；参数候选必须通过服务端安全校验并由工程师确认。未接入或向真实设备写参；当前仅在显式 `LOCAL OPC-UA SANDBOX` 中验证受控单参数执行与 readback。这不是生产部署、真实设备验证或真实 PLC 安全验证。
2. **结构化模型、规则、案例与安全校验组合**：SPC、逻辑回归、APPROVED-only KNN、方向规则和统一 Validator 各自承担清晰职责，任一模块都不能绕过安全边界。
3. **过程感知但不污染分类器**：synthetic fixtures 中的调机过程信息只影响当前适用案例与案例参考方案；Process Context 不进入 classifier，不改变 StandardScaler 或 Root Cause Top-3。
4. **参数候选全链路可追溯**：从观测、诊断、方向证据、案例、约束快照到候选、确认和结果均绑定版本及哈希，STALE 或篡改内容被阻断。
5. **基线重现加配对模拟回放**：先证明模拟器能规范化重现导入基线，再固定场景、扰动和 seed 做前后对照，避免把预制结果当成验证；同时明确不外推到真实产线。
6. **双层 AI 职责隔离**：TuneWise 产生可验证的工业决策证据；飞书 Aily 通过 RAG 做 Retrieve、Explain、Trace 与 Answer，不参与参数与设备控制。

## 10. 技术方案

- 后端：Python 3.11/3.12、FastAPI、Uvicorn；
- 前端：React、TypeScript、Vite；
- 存储：本地 SQLite；
- 决策：版本化 SPC、固定 StandardScaler 与 multinomial logistic regression、结构化 KNN；
- 安全：Decimal/tick、ParameterDirectionEvidence、ParameterSafetyValidator、ConfirmedPlan、STALE 与 SHA-256；
- 回放：Replay-only SimulatorGateway、ObservableCanonicalizer、ReplayResultCanonicalizer 与冻结评价规则；
- 生成式 AI 协作：飞书 Aily Workflow Application、Knowledge Space、Knowledge Space Retrieval / RAG、LLM；V1 仅使用版本化知识与固定证据；
- 验证：pytest、Vitest、Testing Library、production build、浏览器主路径与离线检查。

## 11. 数据来源说明

项目仅使用赛事公开信息、公开的精密光学装调知识，以及由明确规则、固定版本和固定 seed 生成的模拟数据。项目没有舜宇 SOP，也未获得授权真实 AA 数据用于验证；未获得、未使用、未推断任何企业内部数据。LOROS 公开光学数据经审查为 **NO-GO / semantic mismatch**，未伪装成 AA 调机数据。模拟数据不代表真实设备参数、工艺规格或控制限。

## 12. 项目成果

- 完成原路线 TW-01～TW-08 的版本化数据导入、诊断、荐参、确认与结构化模拟回放闭环；
- 实现四类异常路由、Top-3 根因及 logit 贡献解释；
- 实现 APPROVED-only 案例检索、Process-aware 当前案例资格与案例参考方案、方向证据、安全候选和人工确认；
- 实现 baseline reproduction、确定性配对模拟回放，以及显式 `LOCAL OPC-UA SANDBOX` 中的受控单参数执行与 readback；
- 提供本地启动、真实应用截图、评委指南、五分钟脚本和应急卡。
- 发布 Feishu Aily RAG Engineering Copilot；Live Knowledge Pack **8/8**、Legacy Safety Hard Gates **PASS**、Process-aware QA **PASS**、Published Environment **PASS**，验证类型为 Manual UI / conversational acceptance validation。
- 原路线 TW-09～TW-13 尚未完整完成；本地 OPC-UA sandbox、Process-aware、飞书 Aily 与 Coach feedback competition enhancements 属于已完成的复赛工程增强，不应被表述为“当前项目只完成到 TW-08”。

## 13. 量化验证

- 当前主验证：Backend **454 / 454 PASS**；Frontend **46 / 46 PASS**；
- Fixed Demo Browser QA **PASS**；Process-aware Demo Browser QA **PASS**；
- Live Aily Knowledge Pack **8 / 8**；Legacy Safety Hard Gates **PASS**；Process-aware QA **PASS**；Published Environment **PASS**。Aily validation 为 **Manual UI / conversational acceptance validation**；
- 历史 commit-bound snapshot：commit `1fdc526cc8794965b6c591a2fa5bc399e50a4e2b` 曾记录 Backend 433 / 433、Frontend 40 / 40 与 production build 通过；这些数字不作为当前 HEAD 验证结果；
- 固定 Demo 在显式 `LOCAL OPC-UA SANDBOX` 中完成受控单参数执行与 readback；未接入或向真实设备写参，也未验证真实 PLC 安全；
- 固定回放：center MTF 0.831003 → 0.832128，worst corner 0.567683 → 0.651478，corner range 0.184837 → 0.102292，corner std 0.071709 → 0.042654，控制限 false → true，目标异常 true → false；
- baseline reproduction `PASSED`，replay `SUCCESS`，`attempt_count = 1`。

以上均为比赛原型的代码、测试或规则约束模拟结果，不是生产性能或真实良率数据。

## 14. 个人贡献（单人参赛）

本人独立完成项目的产品定位与边界定义、系统和领域架构、规则化数据与本地模拟器设计、异常检测和根因排序算法、结构化案例检索、参数安全规则、后端服务、前端交互、自动化测试、人工验收、版本化资产、文档、截图与现场演示材料。

## 15. 项目局限

- 尚未接入真实产线、MES、QMS 或真实设备；
- 仅覆盖单一 AA 工站和一个代表性异常；
- 使用公开知识与规则化模拟数据，外部有效性尚未由真实生产数据验证；
- 原路线 TW-09～TW-13 尚未完整完成；其中本地 OPC-UA sandbox 执行幂等不等同于 TW-09 全部完成，现有 shadow 协议也不等同于 TW-11 正式冻结盲测评估；
- 任务关闭、复盘报告和待审核案例提交属于 TW-10，当前界面止于 `REPLAYED`；
- 当前源码交付不是 TW-13 的完整 Windows 离线发行包。
- 未接入或向真实设备写参；当前仅在显式 `LOCAL OPC-UA SANDBOX` 中验证受控单参数执行与 readback，不是生产部署、真实设备验证或真实 PLC 安全验证；
- Process-aware 当前只使用 synthetic fixtures，不代表舜宇真实 SOP、真实生产数据或真实推荐准确率；
- Aily V1 仅解释版本化知识与固定 Demo Evidence，没有实时 Bridge、Runtime API、参数生成或设备控制权限。

## 16. 后续规划

依次完成 TW-09 回放拒绝、幂等和异常恢复，TW-10 复盘报告与待审核知识案例，TW-11 正式冻结盲测评估，TW-12 集成演示发布门，以及 TW-13 Windows 离线发行。若未来获得合规授权的数据与接口，将在不改变人在回路、安全校验和审计边界的前提下验证外部有效性；该方向目前仅是计划。

## 17. 技术关键词

精密光学；主动对准；AA 工站；SPC；逻辑回归；Top-3 根因；Logit 贡献；结构化 KNN；人在回路；ParameterSafetyValidator；ConfirmedPlan；确定性配对模拟回放；飞书 Aily；Knowledge Space；RAG；生成式 AI 工程协作；FastAPI；React；SQLite；可追溯决策支持

## 18. GitHub 仓库说明

- 仓库链接：`https://github.com/gakialter/TuneWise`
- 当前状态：**PUBLIC**；本轮复赛增强与最终文档修复位于 `feat/process-aware-retrieval` / PR #1，待 final merge review 后再决定合并。
- 仓库公开内容不包含舜宇 SOP、授权真实 AA 数据、真实设备凭据或 Aily 租户凭据；本文件不记录手机号、邮箱或本机绝对路径。

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。
