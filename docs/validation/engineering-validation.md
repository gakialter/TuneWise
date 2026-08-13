# TuneWise 复赛工程验证记录

验证日期：2026-08-11

当前验证基线：`feat/process-aware-retrieval` / `b78eb0d75bad6670b60cecba2ce51706ff4380bc`

验证口径：当前主结果、历史 commit-bound 快照、浏览器人工 QA 与飞书 Aily 人工会话验收分别记录，不互相替代。

## 当前自动化验证（主展示）

以下命令在当前工作树执行；数量为本轮实际结果：

| 验证项 | 命令 | 实际结果 |
| --- | --- | --- |
| 后端全量 | `.\.venv\Scripts\python.exe -m pytest` | **454 / 454 PASS** |
| 前端全量 | `cd frontend; npm test` | **46 / 46 PASS** |

上述结果是工程回归状态，不是模型准确率、真实设备验证或业务收益证明。

## 历史自动化快照（降级保留）

2026-08-09 的历史基线 `main` / `1fdc526cc8794965b6c591a2fa5bc399e50a4e2b` 曾记录：

| 验证项 | 历史实际结果 |
| --- | --- |
| 后端全量 | `433 passed in 328.82s` |
| 固定资产专项 | `22 passed` |
| 前端全量 | `40 passed` |
| Production build | 成功；生成 `index-DPV54KOG.css`、`index-DuCC5mWP.js` |
| Python 编译 | 通过 |
| Python 依赖 | `No broken requirements found.` |
| Windows 脚本 | `6 passed` |
| LF 干净检出 | `1 passed` |

这些数字只属于 `1fdc526` 历史快照，不作为当前主验证数字。固定诊断资产仍记录原始生成环境 Python 3.11.9；生成器冻结该 provenance 字段，避免在不同 Python 环境下重算时改变固定资产字节。

## 固定 Demo 浏览器与本地 OPC-UA 证据

固定 Demo 浏览器 QA：**PASS**。记录见 [`browser-qa-evidence.json`](browser-qa-evidence.json) 与同目录截图。

- 固定参数变化：pitch `0.250000 → 0.200000`；
- 本地模拟设备执行：`LOCAL_OPCUA_SANDBOX` / `SUCCEEDED`；
- 写后回读：`0.200000`；
- 390px 视口 `scrollWidth == clientWidth == 390`，桌面 1440px 同样无横向溢出；
- 17 个同源 HTTP 请求，外部请求、console error、page error 与 failed request 均为 0；
- 4841 与 8000 端口只监听 `127.0.0.1`。

本地 sandbox 参数 Variable 对普通 OPC-UA client 全生命周期只读；唯一运行期 mutation 入口是受单一执行锁保护的 `ApplyConfirmedParameterChange`。这不表示 OPC-UA 天然提供 CAS，也不表示已验证真实 PLC 原子写、真实设备安全联锁或生产安全环境。

## Process-aware Demo 浏览器证据

结合调机步骤的决策演示浏览器 QA：**PASS**。验证覆盖桌面与 390px 移动端，以及下列固定 A/B 事实：

| 共同条件 / 场景 | 验证结果 |
| --- | --- |
| 测量数据、50 维检索特征、Top-1 / Top-3 根因 | A / B 相同；Top-1 均为 `PLANE_TILT` |
| A｜初始评估 | 无上一步调整；当前适用案例 `tw-aa-approved-011`；案例参考方案 pitch `-3 ticks` |
| B｜调整后评估 | 上一步 pitch `0.250000 → 0.200000`；结果 `NO_MATERIAL_IMPROVEMENT`；当前适用案例 `tw-aa-approved-003`；案例参考方案 pitch `-4 ticks` |
| 不受调机过程信息影响的控制项 | 保守调整方案均 `-1 tick`；标准调整方案均 `-2 ticks`；参数安全校验全部 `PASSED` |

这是 `SYNTHETIC_TEST_FIXTURE` 调机过程演示。它只证明调机过程信息可以确定性改变历史案例资格及案例参考方案，不代表舜宇真实 SOP、真实生产数据、推荐准确率、真实调参效果或良率提升。调机过程信息不进入 Logistic Regression classifier，不修改 `StandardScaler` 或 Root Cause Top-3，也不直接计算参数值。

## 飞书 Aily 人工验收

验证类型：**Manual UI / conversational acceptance validation**。当前状态见 [`aily-v1-validation.md`](aily-v1-validation.md)：

- Live Knowledge Pack：**8 / 8**；
- Legacy Safety Hard Gates：**PASS**；
- Process-aware QA：**PASS**；
- Published Environment：**PASS**。

该结果不是 automated benchmark、100% model accuracy、production accuracy validation 或 real-device validation。Aily 只负责知识检索与解释，不生成新参数、不创建或修改 `ConfirmedPlan`、不触发执行前仿真验证或 `DeviceExecution`，也无 OPC-UA 写权限。

## Shadow CLI 历史证据

历史 Shadow contract fixture 验证记录为：来源 `CONTRACT_FIXTURE`，真实性 `SYNTHETIC`，评估 `NOT_EVALUABLE`；Top-3 为 `PLANE_TILT`、`REFERENCE_DRIFT`、`XY_DECENTER`，保守候选为 pitch `-1 tick → 0.200000`。数据保持在 `SHADOW_READ_ONLY`，没有进入训练集或 `APPROVED` 案例库，也没有触发重训或修改固定演示资产。

对应固定哈希：

- raw SHA-256：`2afcbec6eb50f8dd555b84758b8f71fd0138fc464735fffcde66bc77bd27e6bc`；
- canonical SHA-256：`aca64480cbef2a9da8f919d5a70df5d0718c5dbb6d8a8d496ff66af386c44c2f`；
- evidence bundle：`def1e164ed8ddcc6aeaad67337a745114b360b66b76eb08cec0490d2500dee2a`；
- analysis result：`22bdce589970f0e30f53e7a41d34cd8c7d493765d549f38dd8d1d8ae7085f5a7`。

## 公开真实数据验证边界审查

按照 Coach 建议核验了 Rikkyo University 的 LOROS 公开真实光学实验数据。审查结论为 **NO-GO / semantic mismatch**，不是“完成公开真实数据验证”。详细一手来源审计见 [`loros-public-optical-dataset.md`](../research/loros-public-optical-dataset.md)。

LOROS 可证明公开真实 slanted-edge 光学测量存在，MTF / SFR / processed ROI、provenance 与 `CC-BY-4.0` 许可可追溯；当前 record DOI 为 `10.5281/zenodo.17493261`，配套论文 DOI 为 `10.1186/s40645-025-00783-7`。

LOROS 不提供 AA production identity、x/y/z/pitch/roll 设备状态、调机动作、root-cause ground truth、参数方向、before/after intervention、process stage 或 production outcome。TuneWise 因此没有把 edge angle 当 pitch、把 `Pos 0..5` 当空间五点、把 wavelength 当参数、把中心 MTF 复制到四角，也没有修改 frozen classifier contract。真实 AA 业务效果继续保留至授权企业数据验证阶段。

## 当前事实边界

- 固定 Demo 与 Process-aware Demo 均为 synthetic，且必须彼此分离展示；
- “仿真验证通过”只表示当前固定 simulator、seed、disturbance 和评价规则下满足预设条件；
- 当前 OPC-UA 通道只连接本地模拟设备；
- 未完成舜宇或其他真实 AA 产线、真实设备安全、真实业务 KPI 或授权企业数据验证；
- TuneWise 是 Human-in-the-loop 的 **AA 工站 AI 调机决策支持**原型，不是 AI 自动调机、无人值守调机、LLM 控机或自动接管真实设备。
