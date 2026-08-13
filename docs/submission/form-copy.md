# TuneWise｜比赛报名表可复制材料

本文件按常见报名字段整理。提交前请根据报名页面的实际字数规则复核；所有结果均对应已注明的 Core 验证基线或已发布并人工验收的飞书 Aily V1。

## 1. 项目名称

TuneWise——面向精密光学主动对准工站的 AI 调机决策支持系统

## 2. 一句话介绍（不超过 50 字）

为精密光学 AA 工站提供可追溯、人在回路的离线调机决策支持。

## 3. 100 字项目简介

TuneWise 面向精密光学主动对准单一工站，串联离线数据导入、异常检测、Top-3 根因、已审核案例、安全候选、人工确认和模拟回放。系统不直接控制设备；原型仅使用公开知识和规则化模拟数据，结果不代表真实产线良率改善。

## 4. 300 字项目简介

TuneWise 是面向精密光学主动对准（AA）单一工站的调机决策支持原型。底层确定性 Core 用 SPC、固定逻辑回归、APPROVED-only 检索和统一 Validator 产生可追溯的根因、安全候选、人工确认与 Replay 证据；本地 Core 运行期不依赖 LLM 或外部网络。上层已发布的飞书 Aily 通过 Knowledge Space、RAG 与 LLM 解释版本化知识和固定 Demo Evidence。Aily 不生成参数、不修改 ConfirmedPlan、不触发 Replay，也没有 OPC-UA 写权限。项目未接入真实设备或真实产线；模拟结果不代表真实产线效果或真实因果关系。

## 5. 500 字项目简介

TuneWise 聚焦精密光学主动对准（AA）单一工站，目标不是让 AI 自动控制设备，而是给工程人员提供可解释、可拒绝、可追溯的调机决策支持。底层确定性 Core 把版本化 CSV、SPC 异常路由、固定逻辑回归 Top-3、APPROVED-only KNN、安全候选、人工确认和配对模拟回放组织成闭环；所有候选统一经过 Decimal/tick Validator，证据不足、方向冲突、方案过期或内容篡改时拒绝继续。上层已发布的飞书 Aily Workflow Application 使用 7 文件 Knowledge Pack、Knowledge Space Retrieval / RAG 与 LLM，把项目知识、规则、安全约束和固定 Demo Evidence 组织为自然语言解释。Aily 不进入安全关键链，不生成参数、不修改 ConfirmedPlan、不触发 Replay 或 OPC-UA。固定 Replay 的 SUCCESS 仅表示模拟评价规则通过，不代表真实产线良率改善。项目不使用企业内部数据，未连接 MES、QMS 或真实设备；本地 Core 运行期不依赖 LLM 或外部网络，Aily 也没有 Bridge 或 Runtime API。

## 6. 800～1000 字完整项目介绍

精密光学装调中的异常排查需要同时理解质量测量、当前参数、平台状态、标定残差和历史经验。信息分散时难以形成一致判断，经验也不易复用。直接让模型控制设备又存在风险：证据、案例或建议可能不满足当前条件。

TuneWise 因此定位为面向主动对准（AA）单一工站的离线调机决策支持原型，而不是 AI 自动调机系统。系统导入版本化演示 CSV，校验原始文件哈希、规范化观测哈希、Manifest、schema、规则和模型版本；随后以 SPC 规则识别“中心 MTF 合格或临界合格、四角 MTF 持续不对称下降”的目标异常，并保留正常、整体退化和数据不足保护路由。

固定 StandardScaler 与 multinomial logistic regression 对五类根因稳定排序，页面展示 Top-3、显式规则、关键观测和主要正向 logit 贡献。相对分数只用于候选排序，不是真实故障概率。结构化 KNN 只从工站、产品和根因条件兼容的 APPROVED 案例中检索；待审核、测试和演示来源不能进入索引。

荐参强调“有证据才候选”。每个参数先形成方向证据，记录当前值、标称值、建议方向、支持信息与冲突状态。候选采用 Decimal 和整数 tick 计算，再由统一 ParameterSafetyValidator 检查范围、网格、最大变化、标称方向、跨标称值和参数族。证据不足、方向冲突、版本过期或内容被篡改时，系统拒绝继续。工程师选择 PASSED 候选后，服务端生成绑定候选哈希、身份、时间及版本的不可变 ConfirmedPlan；前端不能替换参数。

只有 Replay 模块能够调用 SimulatorGateway。系统先规范化重现导入基线，哈希一致后才执行配对模拟；前后使用相同隐藏场景、样本数、扰动、seed 和因果版本，唯一变化是确认参数。固定演示中，baseline reproduction 为 PASSED，回放为 SUCCESS，最差角落 MTF 从 0.567683 变为 0.651478，四角极差从 0.184837 变为 0.102292，控制限由 false 变为 true，目标异常由 true 变为 false。

项目使用公开知识和规则约束模拟数据，不包含企业内部数据；未接入 MES、QMS 或真实设备。TuneWise Core 运行时不依赖 LLM 或外部网络；独立发布的飞书 Aily 仅通过 RAG 解释版本化知识与固定 Demo Evidence，没有 Bridge、Runtime API 或控制权限。以上说明模拟环境内的可复现变化，不代表真实产线良率改善，不证明真实因果关系，也不表示获得最优参数。TW-09～TW-13 尚待完成。

## 7. 项目背景与痛点

- 数据、参数、质量结果和经验分散，难以形成统一证据链；
- 根因排查依赖个人经验，判断过程不易复核；
- 无效试调成本高，且高风险动作不能交给模型直接执行；
- 成功处理经验缺少结构化准入与版本边界，难以安全复用；
- 比赛阶段无法使用企业真实产线数据，需要可复现且诚实标注的验证方法。

## 8. 解决方案

以单一 AA 工站为边界，构建本地离线的确定性处理链：版本化 CSV 导入与完整性校验 → SPC 异常路由 → 逻辑回归 Top-3 根因与结构化解释 → APPROVED-only 案例检索 → 参数方向证据 → 安全候选与统一 Validator → 人工确认和不可变 ConfirmedPlan → baseline reproduction → 配对模拟回放与结构化评估。任何证据、状态、版本或安全条件不满足时均拒绝继续。

## 9. 核心创新点

1. **人在回路而非模型直控设备**：模型只帮助排序和解释；参数候选必须通过服务端安全校验并由工程师确认。当前仅有显式启用的本地 OPC-UA sandbox 受控执行，不是实际设备写参接口。
2. **结构化模型、规则、案例与安全校验组合**：SPC、逻辑回归、APPROVED-only KNN、方向规则和统一 Validator 各自承担清晰职责，任一模块都不能绕过安全边界。
3. **参数候选全链路可追溯**：从观测、诊断、方向证据、案例、约束快照到候选、确认和结果均绑定版本及哈希，STALE 或篡改内容被阻断。
4. **基线重现加配对模拟回放**：先证明模拟器能规范化重现导入基线，再固定场景、扰动和 seed 做前后对照，避免把预制结果当成验证；同时明确不外推到真实产线。
5. **双层 AI 职责隔离**：TuneWise 产生可验证的工业决策证据；飞书 Aily 通过 RAG 做 Retrieve、Explain、Trace 与 Answer，不参与参数与设备控制。

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

项目仅使用赛事公开信息、公开的精密光学装调知识，以及由明确规则、固定版本和固定 seed 生成的模拟数据。项目未获得、未使用、未推断任何企业内部数据；模拟数据不与舜宇或其他企业的真实产线数据混用，也不代表真实设备参数、工艺规格或控制限。

## 12. 项目成果

- 完成从版本化数据导入到结构化模拟回放评估的 TW-01～TW-08 闭环；
- 实现四类异常路由、Top-3 根因及 logit 贡献解释；
- 实现 APPROVED-only 案例检索、方向证据、安全候选和人工确认；
- 实现 baseline reproduction、确定性配对模拟回放、结果状态与 SHA-256；
- 提供本地启动、真实应用截图、评委指南、五分钟脚本和应急卡。
- 发布 Feishu Aily RAG Engineering Copilot，并完成 7/7 知识上传、安全 Hard Gates 与 Hero Demo 人工验收。

## 13. 量化验证

- Core 历史全量快照绑定 commit `1fdc526cc8794965b6c591a2fa5bc399e50a4e2b`：433 个后端测试、40 个前端测试与 production build 通过；详见 `docs/validation/engineering-validation.md`，不冒充当前 HEAD 全量结果；
- 固定输入 10 次确定性验证一致；390px 响应式检查通过；
- 该 Core 验证中的外部 HTTP 请求和真实设备调用均为 0；独立 Aily V1 的人工验收见 `docs/validation/aily-v1-validation.md`；
- 固定回放：center MTF 0.831003 → 0.832128，worst corner 0.567683 → 0.651478，corner range 0.184837 → 0.102292，corner std 0.071709 → 0.042654，控制限 false → true，目标异常 true → false；
- baseline reproduction `PASSED`，replay `SUCCESS`，`attempt_count = 1`。

以上均为比赛原型的代码、测试或规则约束模拟结果，不是生产性能或真实良率数据。

## 14. 个人贡献（单人参赛）

本人独立完成项目的产品定位与边界定义、系统和领域架构、规则化数据与本地模拟器设计、异常检测和根因排序算法、结构化案例检索、参数安全规则、后端服务、前端交互、自动化测试、人工验收、版本化资产、文档、截图与现场演示材料。

## 15. 项目局限

- 尚未接入真实产线、MES、QMS 或真实设备；
- 仅覆盖单一 AA 工站和一个代表性异常；
- 使用公开知识与规则化模拟数据，外部有效性尚未由真实生产数据验证；
- 当前完成至 TW-08；TW-09～TW-13 尚未实现；
- 任务关闭、复盘报告和待审核案例提交属于 TW-10，当前界面止于 `REPLAYED`；
- 当前源码交付不是 TW-13 的完整 Windows 离线发行包。
- Aily V1 仅解释版本化知识与固定 Demo Evidence，没有实时 Bridge、Runtime API 或设备控制权限。

## 16. 后续规划

依次完成 TW-09 回放拒绝、幂等和异常恢复，TW-10 复盘报告与待审核知识案例，TW-11 正式冻结盲测评估，TW-12 集成演示发布门，以及 TW-13 Windows 离线发行。若未来获得合规授权的数据与接口，将在不改变人在回路、安全校验和审计边界的前提下验证外部有效性；该方向目前仅是计划。

## 17. 技术关键词

精密光学；主动对准；AA 工站；SPC；逻辑回归；Top-3 根因；Logit 贡献；结构化 KNN；人在回路；ParameterSafetyValidator；ConfirmedPlan；确定性配对模拟回放；飞书 Aily；Knowledge Space；RAG；生成式 AI 工程协作；FastAPI；React；SQLite；可追溯决策支持

## 18. GitHub 仓库说明

- 仓库链接：`https://github.com/gakialter/TuneWise`
- 当前状态：**PUBLIC**；2026-08-09 已通过禁用本机凭据的匿名 `git ls-remote` 验证可读，远端 HEAD 为 `706f562502439ab2f998ae43cebf75a1f2c586e1`。
- 正式提交前仍需确认：敏感信息与本机路径扫描通过、截图无个人信息、License 与比赛公开规则已复核，并将本轮文档变更推送到默认分支。

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。
