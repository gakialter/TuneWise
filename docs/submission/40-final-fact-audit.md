# TuneWise 40 强最终方案 Fact Audit

审计日期：2026-08-11；最终产物复核：2026-08-13

被审计文本：[`40-final-plan.md`](40-final-plan.md)、[`40-final-feishu-copy.md`](40-final-feishu-copy.md)、[`40-final-form-fields.md`](40-final-form-fields.md)、[`40-final-evidence-matrix.md`](40-final-evidence-matrix.md) 与当前视觉规格 / 审计文件。

事实基线：当前工作树；Git HEAD `b78eb0d75bad6670b60cecba2ce51706ff4380bc`。

## Executive Verdict

**PASS — 正文、最终 8 图映射、Facts Boundary、运行截图来源、DOCX 生成、严格 OOXML 校验与完整渲染目视检查全部完成。**

本轮 Markdown 已按 Coach 反馈增量同步，没有重写既有成熟结构。正式定位统一为“AA 工站 AI 调机决策支持”；评委向将 Replay 统一解释为“执行前仿真验证”；新增独立的合成调机过程 A/B 证据；Aily 同步为 8/8 与 Process-aware QA；LOROS 只作为“公开真实数据验证边界审查”，结论明确为 NO-GO。

事实边界审计通过：没有把 score 写成真实故障概率，没有把仿真验证写成真实良率，没有把 Process-aware Demo 写成舜宇真实 SOP，没有把 Aily 写成控制层，也没有把 LOROS NO-GO 写成真实 AA 验证 PASS。

## Coach Feedback Closure

| Coach 反馈 | 闭环内容 | 状态 |
|---|---|---|
| 1. Replay 看不懂 | Judge-facing 统一为“执行前仿真验证”；完整安全门禁保留在正文 3.4 与图 3 / 4，图 5 以实际运行界面小标签呈现基线复现、仿真通过与设备资格检查；SUCCESS 只属于固定 simulator / seed / disturbance / 评价规则 | PASS |
| 2. 缺调机步骤 / Process Context | 新增“调机过程信息 → 当前适用案例 → 案例参考方案”链路和独立 A/B Demo；明确不进入 classifier、不修改 StandardScaler / Root Cause Top-3、不直接计算参数 | PASS |
| 3. 真实数据不足 | 核验 LOROS 一手来源、许可、DOI 与字段语义；审查结论 NO-GO；没有伪造 AA ground truth、参数或干预结果 | PASS |

## Narrative Changes

- 保留官方模板要求的信息卡、场景 / 痛点、优势 / 创新、具体方案、价值、Demo / 体验入口与自由展示区。
- AI → 工程师 → 仿真 / sandbox 的职责统一为：异常分析、根因优先级、历史参考案例、调参候选 → 工程师审核确认 → 执行前仿真验证 → 本地模拟设备受控执行。
- Judge-facing 主术语优先中文；AA、MTF、SPC、RAG、LLM、OPC-UA、pitch / roll / X / Y / Z 等精确术语保留。
- 固定 Demo `tw-demo-task-001` 的 PLANE_TILT `0.997781`、pitch `0.250000 → 0.200000`、保守方案 `-1 tick`、仿真 `SUCCESS`、sandbox `SUCCEEDED` / readback `0.200000` 未改变。
- Process-aware Demo 与固定 Demo 严格分开，不拼成真实生产故事。
- 最终视觉固定为 8 张：图 1–4 架构 / 决策，图 5 Fixed Demo 实际运行界面，图 6 Process-aware 实际 A/B，图 7 Aily Workflow + 仓库既有真实固定 Demo 问答，图 8 验证总结；Aily 截图只嵌入图 7。
- 图 7 的真实 Aily 截图问题是固定 Demo 的 PLANE_TILT Top-1 Hero QA，不是 Process-aware Q5；Q5 PASS 仍只由人工验收记录支持。
- 历史 `1fdc526` 的 433 / 40 降级为历史 commit-bound evidence；当前主数字更新为 454 / 46。

## 逐项事实检查

| 检查项 | 状态 | 审计结论 / 证据 |
|---|---|---|
| 项目定位 | PASS | “AA 工站 AI 调机决策支持”与 Human-in-the-loop 原型已统一；未写 AI 自动调机、无人值守或自动接管真机。 |
| 企业与命题 | PASS | 企业“舜宇光学科技”、命题原文、队名“工智跃迁”、成员“钟秉辰”、个人参赛均保持。 |
| 联系方式隐私 | PASS | 手机号 / 邮箱只允许出现在私有表单字段草稿，不进入公开正文或 validation。 |
| Core 算法边界 | PASS | SPC、50 特征、StandardScaler、multinomial logistic regression、五类 Root Cause、KNN、规则与 Validator 保持；本轮未声称修改 Core 算法。 |
| 调机过程信息作用域 | PASS | 只影响当前适用案例、CASE_GUIDED supporting evidence 与案例参考方案；不进入 classifier，不修改 Scaler / Top-3，不直接计算参数。 |
| Process-aware A/B | PASS | A：`tw-aa-approved-011` / pitch `-3 ticks`；B：`tw-aa-approved-003` / pitch `-4 ticks`；保守 `-1`、标准 `-2` 与 Validator `PASSED` 不变。 |
| Process-aware 来源 | PASS | 标注 `SYNTHETIC_TEST_FIXTURE`；不代表舜宇 SOP、真实生产数据、推荐准确率或因果效果。 |
| 图 5 / 6 运行界面 | PASS | “真实运行”只指当前软件实际页面与记录；源截图由 runtime evidence JSON / SHA-256 manifest 约束。固定 Demo 仍是 synthetic / deterministic simulation，Process-aware 仍是 synthetic fixture，本地设备仍是 sandbox。 |
| score 语义 | PASS | `0.997781` 是 relative ranking score / `normalized_score`，不是 99.7781% 故障概率或真实置信度。 |
| 执行前仿真验证 | PASS | “仿真验证通过”只表示固定 simulator、seed、disturbance 和评价规则下满足预设条件；不证明真机、良率、收益、因果或最优参数。 |
| 工程师确认 | PASS | 只从服务端 `PASSED` 候选选择，形成不可变 `ConfirmedPlan`；Aily 不能代替。 |
| OPC-UA 边界 | PASS | 仅 `LOCAL_OPCUA_SANDBOX`；不声称真实 PLC、真实设备、生产证书、现场联锁或自动回滚。 |
| Aily 当前状态 | PASS | Live Knowledge Pack 8/8、Legacy Safety Hard Gates、Process-aware QA、Published Environment 均为人工验收 PASS。 |
| Aily 验收类型 | PASS | 明确为 Manual UI / conversational acceptance validation，不是 automated benchmark、100% model accuracy 或 real production validation。 |
| Aily 权限 | PASS | 只检索 / 解释 / 追溯 / 问答；不生成参数、不创建 `ConfirmedPlan`、不触发仿真验证、不写 OPC-UA。 |
| Aily 截图身份 | PASS | 图 7 只复用仓库既有 `03_hero_qa.png`；内容是固定 Demo PLANE_TILT Top-1 问答，不是 Process-aware Q5，不生成或补写对话。 |
| 当前自动化验证 | PASS | Backend 454 / 454、Frontend 46 / 46 作为主结果；不解释为模型或业务准确率。 |
| 历史验证数字 | PASS | 433 backend / 40 frontend 只绑定旧 commit `1fdc526`，不作为当前主数字。 |
| LOROS 数据身份 | PASS | 只写 Rikkyo University 的真实 slanted-edge 光学实验数据；MTF / SFR / processed ROI、`CC-BY-4.0` 与 DOI 可追溯。 |
| LOROS 映射结论 | PASS | 明确 NO-GO / semantic mismatch，不写验证 PASS；缺失 AA 身份、姿态、动作、root-cause ground truth、参数方向、干预前后、process stage 与 outcome。 |
| 业务收益 | PASS | 未填写效率、成本、时长或真实良率提升数字。 |

## Public Data Audit

LOROS 当前 record DOI 为 `10.5281/zenodo.17493261`，配套论文 DOI 为 `10.1186/s40645-025-00783-7`，许可为 `CC-BY-4.0`。它支持证明公开真实光学实验数据存在、MTF / SFR 可追溯以及 provenance / license 可验证。

它不能提供 AA production identity、x/y/z/pitch/roll 设备状态、调机动作、root-cause ground truth、参数方向、before/after intervention、process stage 或 production outcome。TuneWise 没有把 edge angle 当 pitch、把 `Pos 0..5` 当空间五点、把 wavelength 当参数、复制中心 MTF 到四角，也没有修改 frozen classifier contract。

审计结论：**NO-GO。不是“公开真实数据验证 PASS”。真实 AA 业务效果继续保留至授权企业数据验证阶段。**

## 官方模板覆盖审计

| 官方必含项 | 对应位置 | 状态 |
|---|---|---|
| 参赛方案信息卡 | 首页信息卡 | PASS |
| 场景 / 问题 / 痛点 | 命题场景与核心问题 | PASS |
| 方案优势 / 创新点 | 四项创新 | PASS |
| 具体方案 | 双层 AI、核心决策链、Aily 工作流 | PASS |
| 方案价值 | 效率、安全、知识、复制与验证量尺 | PASS |
| Demo / 体验入口 | 固定 Demo、独立 Process-aware Demo、代码 / Aily 状态 | PASS |
| 自由展示区 | 安全门禁、公开数据边界、证据治理、Coach 闭环 | PASS |

## Visual Refresh Status

| 图 | 最终内容 | 审计边界 |
|---|---|---|
| 1–4 | 传统 / TuneWise、双层 AI、核心决策链、安全调参 | 架构与决策解释；无真实 KPI |
| 5 | Fixed Demo 真实运行界面 | 软件实际运行；不是产线 / 真机 / 生产验证；旧安全门禁保留在正文与图内小标签 |
| 6 | 结合调机步骤的决策演示 | 实际 A/B 页面；输入仍为 `SYNTHETIC_TEST_FIXTURE` |
| 7 | Aily Workflow + 真实问答 | 只用仓库既有固定 Demo Hero QA；非 Q5；不伪造 UI |
| 8 | 验证与证据总结 | 454 / 46、Aily 8/8、LOROS NO-GO 分层展示 |

最终材料只使用图 1–8，Aily 截图不重复独立插入。中文标题、节点术语、Process-aware / Aily / public-data 事实规格已在 [`40-final-visual-assets.md`](40-final-visual-assets.md) 与正文同步。

当前状态：**PASS**。最终 SVG 8/8 可解析，PNG 8/8 为 2560 × 1440；运行截图 manifest 15/15 复算一致。DOCX 包含 8 张图、9 个表格与 40 个标题，严格 OOXML 校验 PASS；Microsoft Word 原生分页 / PDF 为 A4 纵向 17 页，LibreOffice 交叉渲染为 16 页，均在 16–18 页目标内。Word 的 17 页逐页目视复核确认中文字体正常，无图片缺失、乱码、明显模糊、文字裁切 / 溢出、孤立图题 / 图注或严重表格断裂。图 5 / 6 的真实运行来源与合成边界、图 7 的非 Q5 身份、Aily 8/8、LOROS NO-GO、454 / 46 主数字均与图文一致。

## Remaining Evidence Gaps / Manual Steps

产物侧事实与渲染审计已完成。外部人工步骤仍为：

1. 人工检查最终 DOCX；
2. 上传 / 更新飞书最终方案；
3. 检查公开链接权限；
4. 最终提交。

如需把图 7 升级为 Process-aware Q5 证据，需由用户在已发布 Aily 登录态中人工截取真实 Q5 问答后替换图 7 右侧区域；当前版本合法使用既有固定 Demo Hero QA，并明确标注“非 Q5”，未伪造 Live Aily 对话。

不得自动提交飞书或比赛。本轮不 commit、不 push、不创建 PR。
