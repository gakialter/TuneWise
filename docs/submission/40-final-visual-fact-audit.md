# TuneWise 40 强最终方案视觉事实审计

审计日期：2026-08-11；最终产物复核：2026-08-13

事实基线：Git HEAD `b78eb0d75bad6670b60cecba2ce51706ff4380bc`，以及当前仓库中的 fixed Demo、Process-aware Demo、Core、OPC-UA、Aily 8/8 人工验收、454 / 46 工程验证与 LOROS 公开真实数据边界审查。

当前审计阶段：**PASS — 新版脚本、SVG / PNG、运行截图来源与最终 DOCX 渲染均已完成机械检查和逐页目视复核。**

## 逐图预审

| 图 | 新标题 | 事实规格 | 中文化要求 | 当前产物状态 |
|---|---|---|---|---|
| 1 `01_before_after` | 传统调机流程 vs TuneWise 决策支持流程 | PASS：保留工程师确认、仿真验证与本地模拟执行；无真实效率 / 良率数字 | 主流程、节点、图注中文优先 | PASS：SVG / PNG 与 DOCX 渲染目视通过 |
| 2 `02_dual_layer_ai_architecture` | TuneWise 双层 AI 架构 | PASS：Aily 只经版本化知识 + fixed / process-aware evidence 协作；8 文件；无参数 / ConfirmedPlan / 仿真 / OPC-UA 权限 | 上下层、工作流、权限红条与“非实时控制接口”中文化 | PASS：8 文件与权限红条可读 |
| 3 `03_core_pipeline` | TuneWise 核心决策链 | PASS：调机过程信息只进入案例资格支路；不进入 classifier / Scaler / Root Cause Top-3；A/B 的案例 011 / 003 与 -3 / -4 ticks 固定 | 主链中文化；技术名作小字 | PASS：支路位置与边界可读 |
| 4 `04_safe_parameter_decision` | 安全调参决策流程 | PASS：保守 / 标准 / 案例参考三类候选；固定 Demo 选 pitch -1 tick；roll `INSUFFICIENT_SUPPORT`；统一 Validator | 中文主标签，enum 作次级小字 | PASS：候选 / Validator / 确认层级清楚 |
| 5 `05_replay_opcua_safety` | Fixed Demo 真实运行界面 | PASS：当前脚本实际运行 `tw-demo-task-001` 后的诊断 / 候选、ConfirmedPlan / 仿真与设备回执页面；固定数字不变；安全门禁以小标签保留 | 页面原生 UI + 中文证据条；明确“实际软件运行 ≠ 真实产线验证” | PASS：5 个真实页面裁片与关键状态可读 |
| 6 `06_demo_evidence_card` | 结合调机步骤的决策演示 | PASS：`/process-aware-demo/` 实际页面；shared evidence、A/B comparison、invariant band 与 011 / 003、-3 / -4、-1 / -2、PASSED 一致 | 页面原生 UI；显著标注 `SYNTHETIC_TEST_FIXTURE` | PASS：8 个真实页面裁片与 A/B 主结论可读 |
| 7 `07_aily_rag_workflow` | 飞书 Aily 工程解释｜Workflow + 真实问答 | PASS：8/8 与三项人工验收状态；只嵌入仓库既有 `03_hero_qa.png`，问题为固定 Demo PLANE_TILT Top-1 Hero QA，明确非 Process-aware Q5 | Workflow 中文化；截图不改写、不补写、不伪造 | PASS：真实既有截图 + Workflow，非 Q5 标识清楚 |
| 8 `08_validation_summary` | 验证与证据总结 | PASS：454 / 454、46 / 46 为主数字；fixed / process-aware QA 分开；Aily 8/8；LOROS `NO-GO / semantic mismatch` | 四块中文化；边界状态清晰 | PASS：测试、Aily 与 NO-GO 分层可读 |

## 强制边界检查

- [x] 正式定位为“AA 工站 AI 调机决策支持”，不写 AI 自动调机、无人值守、自动接管真机或 LLM 控机。
- [x] 固定 Demo 与 Process-aware Demo 严格分离；后者标记 synthetic process context/profile。
- [x] 调机过程信息不进入 Logistic Regression classifier，不修改 StandardScaler 或 Root Cause Top-3，不直接计算参数值。
- [x] `normalized_score = 0.997781` 是 relative ranking score，不是 calibrated probability。
- [x] “仿真验证通过”不证明真实设备、良率、收益、因果或最优参数。
- [x] OPC-UA 只连接本地 loopback sandbox，不是真实设备或生产安全环境。
- [x] Aily 不指向参数、ConfirmedPlan、仿真验证、DeviceExecution 或 OPC-UA；验收类型为 Manual UI / conversational acceptance validation。
- [x] 图 5 / 6 的“真实运行界面”只表示当前软件实际页面；不写成真实产线、真实设备、真实 AA 数据或生产效果验证。
- [x] 图 7 只使用仓库既有真实 Aily 固定 Demo Hero QA；其问题不是 Process-aware Q5，Q5 PASS 只引用人工验收记录。
- [x] 最终集合固定为 8 图；Aily 截图只内嵌于图 7，不作为独立插图。
- [x] 当前主测试数字为 backend 454 / 454、frontend 46 / 46；历史 433 / 40 只属于 `1fdc526`。
- [x] LOROS 只写“公开真实数据验证边界审查 / NO-GO / semantic mismatch”，不写真实 AA 验证 PASS。
- [x] 不虚构舜宇真实 SOP、舜宇真实生产数据、真实 KPI、真实良率提升或生产收益。

## 主代理最终渲染检查清单

- [x] 新版 SVG 8/8 存在并可解析；
- [x] 新版 PNG 8/8 存在并可打开，尺寸均为 2560 × 1440；
- [x] `runtime-screenshot-evidence.json`、`runtime-screenshot-manifest.sha256` 与图 5 / 6 所用源截图存在且 15/15 hash 一致；
- [x] 中文字体正常，无乱码、明显模糊、重叠、画布截断或溢出；
- [x] 图 2 显示 8 文件与 Aily 权限红条；
- [x] 图 3 的调机过程信息支路不进入 classifier；
- [x] 图 5 标题为“Fixed Demo 真实运行界面”，页面来自当前实际软件运行，固定数字正确，门禁小标签与正文一致；
- [x] 图 6 标题为“结合调机步骤的决策演示”，页面显示 shared evidence / A/B / invariants，并醒目标注 synthetic fixture；
- [x] 图 7 显示 8/8、Legacy Safety Hard Gates、Process-aware QA、Published；内嵌截图与仓库 `03_hero_qa.png` 一致且明确非 Q5；
- [x] 图 8 以 454 / 46 为主数字，LOROS 显示 NO-GO 而非 PASS；
- [x] DOCX / 飞书共 8 张图，Aily 截图没有重复独立插入；
- [x] DOCX 严格 OOXML 校验 PASS；Microsoft Word 原生分页 / PDF 为 A4 17 页，LibreOffice 交叉渲染为 16 页；Word 的 17 页逐页检查无空白页、孤立图题 / 图注或严重表格断裂；
- [x] 缩放到 DOCX / 飞书常用展示尺寸后主要结论仍清晰可读。

## 当前结论

**PASS。** 最终视觉脚本、8 组 SVG / PNG、真实运行截图来源、截图 hash、DOCX 图位，以及 Word 17 页 / LibreOffice 16 页交叉渲染均已完成机械与目视验收。图 5 / 6 证明软件页面真实运行但不代表生产验证；图 7 使用真实固定 Demo Aily 问答并明确不是 Process-aware Q5；未伪造任何 Live Aily 或设备画面。
