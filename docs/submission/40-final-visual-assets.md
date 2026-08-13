# TuneWise 40 强最终方案视觉资产计划

更新日期：2026-08-11；最终产物复核：2026-08-13

目标：保留 8 张图的总量，用评委 30 秒可理解的中文业务语言同步 Coach 反馈后的工程状态。图 1–4 解释架构与决策链，图 5–7 展示当前软件 / Aily 的实际运行证据，图 8 汇总验证边界。英文只作为行业缩写、技术精确名称、内部 enum 或次级小字。

当前状态：**PASS**。最终 SVG / PNG 已生成，图 5 / 6 使用本轮真实运行截图，图 7 只使用仓库既有真实 Aily 固定 Demo 问答；中文字体、裁切 / 溢出、事实一致性，以及 Word 17 页 / LibreOffice 16 页交叉渲染均已完成目视复核。

## 图 1–8 最终规格

| # | 最终标题 | 稳定资产文件 | 内容与证据边界 | 当前状态 |
|---:|---|---|---|---|
| 1 | 传统调机流程 vs TuneWise 决策支持流程 | `01_before_after` | 中文工作流；保留工程师确认；不写停线时长、收益比例或真实良率 | PASS |
| 2 | TuneWise 双层 AI 架构 | `02_dual_layer_ai_architecture` | 双层职责、8 文件知识包与 Aily 权限红条；无实时控制接口 | PASS |
| 3 | TuneWise 核心决策链 | `03_core_pipeline` | 中文主链；“调机过程信息 → 当前适用案例”只位于案例支路；保留仿真验证 / 执行门禁位置 | PASS |
| 4 | 安全调参决策流程 | `04_safe_parameter_decision` | 保守 / 标准 / 案例参考方案与工程师确认中文优先；统一 Validator；保留执行前安全门禁 | PASS |
| 5 | Fixed Demo 真实运行界面 | `05_replay_opcua_safety` | 当前脚本实际运行 `tw-demo-task-001` 后的诊断、候选、ConfirmedPlan、仿真与本地设备回执页面；用小标签保留基线复现、Validator、独立确认与 local sandbox 门禁 | PASS |
| 6 | 结合调机步骤的决策演示 | `06_demo_evidence_card` | `/process-aware-demo/` 实际运行界面的 shared evidence、A/B comparison 与 invariant band；数据仍是 `SYNTHETIC_TEST_FIXTURE` | PASS |
| 7 | 飞书 Aily 工程解释｜Workflow + 真实问答 | `07_aily_rag_workflow` | 工作流 + 仓库既有真实 Aily 截图 `aily-screenshots/03_hero_qa.png`；问题是固定 Demo 的 PLANE_TILT Top-1 Hero QA，明确不是 Process-aware Q5 | PASS |
| 8 | 验证与证据总结 | `08_validation_summary` | 454/454、46/46；fixed / process-aware browser QA；Aily 8/8；LOROS `NO-GO / semantic mismatch` | PASS |

最终文档只使用这 8 张图；Aily 截图只嵌入图 7，不作为独立插图。稳定文件名用于兼容既有 DOCX 引用；图 5 / 6 的文件名保留历史命名，但标题与内容以上表为准。

> **“真实运行界面”边界：**“真实”只表示当前仓库软件或已发布 Aily 的实际界面 / 实际运行截图，不表示真实产线、真实设备、真实 AA 数据、推荐准确率或生产效果验证。

## 图 2 中文节点规范

上层：

`飞书 Aily · 生成式 AI 协作层`

`知识空间 / 8 文件知识包 → 知识检索（RAG）/ Top K = 5 → 大语言模型（LLM）→ 工程解释 → 评委 / 工程问答`

权限边界红条：

`Aily 只负责知识检索与解释；不生成新参数 / 不创建 ConfirmedPlan / 不触发仿真验证 / 无 OPC-UA 写权限`

中间连接：

`版本化项目知识 + 固定 Demo 证据 + Process-aware Demo 证据`；小字 `非实时控制接口`。

下层：

`TuneWise 确定性工业 AI 核心`

`SPC 异常检测 → 工程特征提取 → AI 根因优先级 → 历史参考案例检索 → 安全调参候选生成 → 参数安全校验 → 工程师确认 → 执行前仿真验证 → 本地模拟设备受控执行`

右下角：`仅本地模拟环境`。

## 图 5｜Fixed Demo 真实运行界面规范

- 证据源：由视觉生成流程启动当前本地应用，实际运行 `tw-demo-task-001`，再截取诊断 / 候选、ConfirmedPlan / 仿真验证、设备执行回执三个软件界面。
- 必须保留：`PLANE_TILT 0.997781`、pitch `0.250000 → 0.200000`、保守方案 `-1 tick`、仿真 `SUCCESS`、`LOCAL_OPCUA_SANDBOX`、`SUCCEEDED`、readback `0.200000`。
- 小标签保留旧安全门禁的核心语义：参数安全校验、工程师确认、基线复现、仿真验证通过后才有设备执行资格、仅本地模拟环境。
- 精确完整证据仍以正文固定 Demo 表为准；本图不替代正文 3.4 对 `UNKNOWN_OUTCOME`、幂等、readback 与 reconciliation 的说明。
- 图内固定标注：`实际软件运行界面 ≠ 真实产线验证`。

## 图 6｜Process-aware 实际 A/B 界面规范

标题：`结合调机步骤的决策演示`

副标题：`异常判断相同，调机过程不同，适用的参考案例也会不同`

共同条件：`测量数据相同`、`根因优先级相同`、Top-1 `PLANE_TILT`。

| A｜初始评估 | B｜调整后评估 |
|---|---|
| 上一步调整：无 | pitch `0.250000 → 0.200000` |
| 当前适用案例：`tw-aa-approved-011` | 调整结果：未观察到显著改善 |
| 案例参考方案：pitch `-3 ticks` | 当前适用案例：`tw-aa-approved-003`；pitch `-4 ticks` |

底部控制项：两边保守调整方案均 `-1 tick`，标准调整方案均 `-2 ticks`，参数安全校验全部 `PASSED`。

界面证据：实际访问 `/process-aware-demo/` 后截取 shared evidence、A/B comparison 与 invariant band，不重新绘制伪 UI。

面板固定徽标：`tw-process-aware-demo-v1 · 独立合成 fixture`。

事实边界：`这是合成调机过程演示。用于证明不同调机过程信息可以确定性地改变历史案例资格。不代表舜宇真实 SOP，也不证明真实生产调参准确率。`

## 图 7｜Aily Workflow + 真实问答规范

- 左侧：实际 Aily Workflow 节点与知识检索 / LLM / 工程解释关系；状态为 Knowledge Pack `8/8`、Legacy Safety Hard Gates PASS、Process-aware QA PASS、Published Environment PASS。
- 右侧：只嵌入仓库既有 [`03_hero_qa.png`](assets/40-final/aily-screenshots/03_hero_qa.png)，不生成、补写或改造 Aily 对话内容。
- 截图中的真实问题是“`tw-demo-task-001` 为什么把 `PLANE_TILT` 排在第一？”，属于固定 Demo Hero QA。
- 该截图**不是** Process-aware Manual Acceptance 的 Q5；Process-aware QA PASS 只来自人工验收记录，不能暗示仓库存在 Q5 截图。
- 真实 Aily UI 证明工作流与该次问答确实存在，不证明回答准确率 100%、真实生产验证或设备控制能力。

## 图 8 四块固定内容

1. **工程自动化验证**：Backend `454 / 454 PASS`；Frontend `46 / 46 PASS`。
2. **Demo 浏览器验证**：固定 Demo PASS；Process-aware Demo PASS；桌面 / 移动端 PASS。
3. **Aily 人工验收**：Knowledge Pack `8 / 8`；Legacy Safety Hard Gates PASS；Process-aware QA PASS；Published Environment PASS。
4. **当前验证边界**：Fixed Demo `SYNTHETIC`；Process-aware `SYNTHETIC`；Device `LOCAL SANDBOX`；Real production data `NOT VALIDATED`；Public real-data audit `NO-GO / semantic mismatch`。

历史 `1fdc526` 的 433 / 40 如保留，只能放次级小字并标明 historical commit-bound evidence，不能与当前主数字并列竞争视觉层级。

## 统一图注与事实规则

- 模型分数：`relative ranking score / normalized_score`，不得写故障概率或置信度。
- 执行前仿真验证：固定写明“只属于当前固定 simulator、seed、disturbance 和评价规则；不代表真实设备、良率、收益、因果或最优参数”。
- OPC-UA：固定写明“本地 loopback sandbox，不是真实设备或生产安全环境”。
- Process-aware：固定写明“synthetic process context/profile；不代表舜宇 SOP 或真实生产调参准确率”。
- 软件界面：实际运行截图只能证明当前软件表面行为与记录，不等于真实设备、真实数据或生产验证。
- Aily：箭头只指向检索、解释、追溯与问答，不指向参数、ConfirmedPlan、仿真验证或设备；图 7 的真实问答是固定 Demo Hero QA，不是 Process-aware Q5。
- LOROS：只允许 `公开真实数据验证边界审查 / NO-GO / semantic mismatch`，禁止 `真实数据验证 PASS`。
- 测试：454 / 46 是当前主数字；433 / 40 只属于历史 `1fdc526`。

## 资产位置与后续检查

- SVG source of truth：`docs/submission/assets/40-final/*.svg`；
- 飞书 / DOCX PNG：`docs/submission/assets/40-final/*.png`；
- 实际运行源截图与 provenance：`docs/submission/assets/40-final/runtime-screenshots/` 下的 `runtime-screenshot-evidence.json`、`runtime-screenshot-manifest.sha256` 与 fixed / process 截图；
- 运行截图入口：`docs/submission/capture_40_final_runtime_screenshots.mjs`；
- 视觉生成入口：`docs/submission/generate_40_final_visuals.py`；
- PNG 导出入口：`docs/submission/render_40_final_visuals.cjs`。

最终检查已完成：8/8 SVG/XML 可解析；8/8 PNG 可打开且均为 2560 × 1440；图 5 / 6 的运行截图来源与合成边界、图 7 既有截图 hash / 非 Q5 身份均已核对；中文无乱码、明显重叠、裁切或溢出，缩放至 DOCX 后主要结论仍可读。详见 [`40-final-visual-fact-audit.md`](40-final-visual-fact-audit.md)。
