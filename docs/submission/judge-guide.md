# TuneWise｜评委快速体验指南

## 1. 项目定位

TuneWise 是面向精密光学 Active Alignment（AA）工站的 Human-in-the-loop AI 调机决策支持原型。AI 分析异常、进行根因排序、检索适用案例并形成参数候选与证据；工程师审核并选择/确认；之后才进入 Simulation Validation (Replay) / 执行前仿真验证和受控 sandbox 执行原型。它不是自动调机系统，也不代表舜宇真实内部系统。

比赛版本采用双层 AI：本地 `TuneWise Deterministic AI Core` 产生可验证的工业决策证据；已发布的 `Feishu Aily Generative AI Collaboration Layer` 通过 Knowledge Space、RAG 与 LLM 检索并解释版本化项目知识和固定 Demo Evidence。Aily 不进入安全关键链，不生成参数、不修改 `ConfirmedPlan`、不触发 Replay，也没有 OPC-UA write 权限。

预计用时：依赖已安装时，启动约数秒；从初始页面完成主流程约 1～2 分钟。Replay-only 讲解约 4 分 30 秒；使用显式本地 sandbox 完成 OPC-UA execution 的完整 Demo A 为 5 分钟。独立 Demo B 另需 60～90 秒，不计入 Demo A 主槽。

## 2. 环境要求

- Windows 10/11；
- Python `>=3.11,<3.13`；
- 仅运行已构建应用时不需要 Node.js；运行前端测试或 production build 时建议使用本基线验证过的 Node 22.x 与 npm 10.x；
- 首次安装 Python/npm 依赖需要可用的软件源或离线缓存；依赖安装完成后，应用运行和演示不需要外部网络。

评委不需要 API Key、云服务账号、企业数据、真实设备或外部网络连接。

上述要求只针对 TuneWise Core 本地演示。Aily 是独立发布的飞书会话应用，其发布配置与人工验收结果见 [Aily V1 验证记录](../validation/aily-v1-validation.md)；仓库没有 Aily 租户凭据，也不通过 Bridge 或 Runtime API 连接本地 Core。

## 3. 最短启动命令

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"
```

上面是默认只读到 Simulation Validation 的启动方式。若要完整演示 Demo A 的本地 OPC-UA sandbox execution，依赖安装完成后改用：

```powershell
start-tunewise-opcua-demo.cmd
```

该脚本只启用固定 loopback 本地模拟设备；不得替换为真实设备地址。

看到 `Uvicorn running on http://127.0.0.1:8000` 后保持终端开启。

## 4. 默认访问地址

浏览器打开：<http://127.0.0.1:8000>

健康检查：<http://127.0.0.1:8000/api/health>，应返回 `{"status":"ok","mode":"offline"}`。

## 5. Demo A — End-to-End Fixed Demo

`Detect → Diagnose → Recommend → Human Confirm → Simulation Validation → OPC-UA Sandbox Execution`

该路径证明完整受控决策链可以运行。它与第 6 节 Process-aware Decision Demo 是两个独立证据，不应合并成一个虚构生产故事。

### 完整点击路径与预期结果

请从新建数据库的初始页面开始，按以下顺序操作。按钮名称与当前界面一致。

1. **“导入预置 AA 异常批次”**
   - 看到任务进入 `DATA_IMPORTED`；
   - 数据集为 `tw-aa-demo-v1`，样本数为 24；
   - CSV schema、Manifest、raw file hash、canonical observation hash 和版本均为 `PASSED`。

2. **“运行异常检测”**
   - 看到“检测到四角 MTF 不对称下降”；
   - 路由为 `TARGET_ANOMALY`；
   - 中心 MTF `0.831003`，最差角落 `0.567683`，四角极差 `0.184837`，四角标准差 `0.071709`；
   - 24/24 样本满足当前路由信号，持续性检查通过。

3. **“运行根因诊断”**
   - 看到“诊断证据满足冻结规则”和 `SUFFICIENT_EVIDENCE`；
   - Top-3 依次为 `PLANE_TILT`、`XY_DECENTER`、`REFERENCE_DRIFT`；
   - Top-1 相对分数 `0.997781`，该值只用于当前候选排序，不是真实故障概率；
   - 每项包含显式规则、关键观测与主要正向 logit 贡献。

4. **“检索已审核案例”**
   - 看到“仅检索 APPROVED 案例”；
   - 返回 3 个兼容案例，展示结构化距离、关键特征差异、历史动作和规则约束模拟结果；
   - 历史结果不等于当前建议，也不代表真实产线效果。

5. **“生成安全参数候选”**
   - 看到 `CANDIDATES_AVAILABLE` 与 3 个 `PASSED` 候选；
   - `Pitch` 具有 `NO_CONFLICT` 方向证据，`Roll` 因 `INSUFFICIENT_SUPPORT` 不进入候选；
   - 每个候选展示当前值、建议值、delta、范围、步长、最大变化、支持案例和安全检查。

6. **选择候选单选项**
   - 建议选择第一个“选择 CONSERVATIVE 候选”，便于与固定演示结果一致；
   - 看到人工确认区显示所选候选、候选哈希和只读参数。

7. **“人工确认候选方案”**
   - 看到“方案已人工确认并冻结”；
   - 状态为 `VALID`，确认身份为固定的 AA 工艺工程师；
   - `ConfirmedPlan` 绑定候选、版本、时间和哈希，页面不能改写参数。

8. **“运行离线模拟回放”（Simulation Validation）**
   - 看到 baseline reproduction `PASSED`；
   - replay status 为 `SUCCESS`，`attempt_count = 1`；
   - center MTF `0.831003 → 0.832128`；
   - worst corner `0.567683 → 0.651478`；
   - corner range `0.184837 → 0.102292`；
   - corner std `0.071709 → 0.042654`；
   - control limit `false → true`，target anomaly `true → false`；
   - ReplayResult hash 为 `e639cf3f2e69e217338f0f7e96ecabfa45523ca7d92ab45a320eb2b3b1435350`。

9. **“检查设备执行资格”**（仅 `start-tunewise-opcua-demo.cmd`）
   - 看到“设备执行资格已通过”；
   - 执行模式为 `OPCUA_SANDBOX`，设备连接与安全门禁通过；
   - expected-before、设备当前值与目标值由服务端读取，浏览器不能提交 endpoint、node ID 或参数值。

10. **独立确认并点击“向模拟设备执行受控下发”**
   - 勾选“我确认当前目标是本地 OPC-UA 模拟设备，并授权执行这一次写入与回读验证”；
   - 看到“写入并回读验证成功”、execution status `SUCCEEDED`；
   - pitch 写后回读为 `0.200000`，页面显示写入次数、幂等结果与 receipt hash；
   - 这只证明固定 loopback sandbox 的受控 Method、expected-before、单参数写入、readback 和幂等语义，不代表真实设备或真实 PLC 安全验证。

当前固定 Demo 的任务主状态仍止于 `REPLAYED`；DeviceExecution 是独立 receipt 聚合，不扩展任务主状态机。界面中的“复盘关闭”和“案例提交”仍保持锁定，它们属于 TW-10，不应在本次演示中尝试。内部工程术语和 API 继续使用 Replay、`ReplayResult`、`/replays` 与 Replay Engine。

## 6. Demo B — Process-aware Decision Demo（独立 60–90 秒，不计入 Demo A 的 5 分钟主槽）

浏览器打开：<http://127.0.0.1:8000/process-aware-demo/>

`Same Measurement Evidence + Different Process Context → Different Eligible Historical Evidence → Different CASE_GUIDED`

预期看到：

- Shared Evidence：相同 measurement evidence、相同 50-D query fingerprint、相同 Top-3 `PLANE_TILT / XY_DECENTER / REFERENCE_DRIFT`；
- Scenario A：`INITIAL_ASSESSMENT`，previous action 为 None，eligible case `tw-aa-approved-011`，`CONTEXT_MATCH`，`CASE_GUIDED pitch -3 ticks`；
- Scenario B：`POST_ADJUSTMENT_EVALUATION`，previous action 为 pitch `0.250000 → 0.200000`，previous outcome 为 `NO_MATERIAL_IMPROVEMENT`，eligible case `tw-aa-approved-003`，`CONTEXT_MATCH`，`CASE_GUIDED pitch -4 ticks`；
- Stable controls：`CONSERVATIVE -1 tick`、`STANDARD -2 ticks` 在两侧一致，Safety Validator 为 `PASSED`。

这证明 Process Context 可以先改变 eligible historical cases，再间接改变 `CASE_GUIDED` supporting case IDs、幅值与解释。Process Context 不进入现有 Logistic Regression classifier，不改变 Engineering Feature Contract、`StandardScaler`、Root Cause labels、50-D distance、`CONSERVATIVE` / `STANDARD`、`ParameterSafetyValidator`、人工确认、`ConfirmedPlan`、Replay Engine、OPC-UA safety contract 或 Execution Receipt。

Facts Boundary：这是 synthetic process-context demonstration。`ProcessContext` / `CaseProcessProfile` 使用 synthetic fixtures；`INITIAL_ASSESSMENT`、`POST_ADJUSTMENT_EVALUATION` 与 `NO_MATERIAL_IMPROVEMENT` 是 TuneWise abstractions，不是行业标准状态或舜宇 SOP。当前 compatibility rules 未经真实企业过程数据验证，pitch `-3 / -4 ticks` 仅为 synthetic demonstration output，不证明真实 AA 推荐准确率、真实良率提升、production tuning effectiveness、causal effectiveness 或 sequential optimization。

## 7. 演示数据说明

- 演示资产：`assets/demo/tw-aa-demo-v1/`；
- 使用公开知识与固定规则、固定 seed 生成的模拟观测；
- 不包含舜宇或其他企业内部数据；
- 归一化参数和 MTF 不代表真实设备物理单位或企业规格；
- `scenario_ref` 对业务侧保持不透明，隐藏内容不会进入 CSV、API 或界面。

## 8. 重置演示状态

先在启动终端按 `Ctrl+C` 停止服务，再在仓库根目录执行：

```powershell
Remove-Item -LiteralPath .\var\tunewise.db -ErrorAction SilentlyContinue
cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"
```

刷新浏览器后会自动创建新的本地演示数据库。`var/` 已被 Git 忽略；不要删除 `assets/` 中的 checked-in 文件，也不要修改规则或哈希。

## 9. 常见启动问题

| 现象 | 最短处理 |
|---|---|
| `python` 不存在或版本不符 | 安装 Python 3.11/3.12，并确认 `python --version` 可用 |
| 缺少 `fastapi` / `uvicorn` | 运行 `.\.venv\Scripts\python.exe -m pip install -e ".[test]"` |
| PowerShell 禁止执行 Activate.ps1 | 使用文档中的 `cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"`，无需修改执行策略 |
| 8000 端口占用 | 停止占用进程；或用同样参数临时改到 8001，并访问对应地址 |
| 页面空白或旧内容 | 强制刷新 `Ctrl+F5`，确认服务终端无 4xx/5xx |
| 前端构建产物缺失 | 在 `frontend` 运行 `npm ci` 和 `npm run build`，再重启服务 |
| 资产完整性拒绝 | 执行下方资产测试；不要临时修改 Manifest、规则或代码中的预期哈希 |

更完整的一页恢复说明见[演示应急卡](demo-recovery.md)。

## 10. 测试命令

后端完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

前端完整测试与 production build：

```powershell
cd frontend
npm ci
npm test
npm run build
```

Python 编译检查：

```powershell
cd ..
.\.venv\Scripts\python.exe -m compileall -q src tools tests
```

## 11. 结果免责声明

TuneWise 未连接 MES、QMS 或真实设备，未向真实设备写入参数，不使用企业内部数据。界面中的模型相对分数不是真实故障概率，候选不是最优参数，模拟对照不证明真实世界因果关系。

> **Simulation Validation SUCCESS 只表示固定模拟评价规则通过，不代表真实产线良率改善、真实设备效果、参数最优、生产收益或真实因果证明。**

## 12. Aily V1 评审问答

已发布应用可用于询问项目定位、算法规则、安全边界、固定 Demo Evidence 与 Process-aware evidence。当前 Live Knowledge Pack 为 8/8；人工 UI / conversational acceptance validation 已覆盖既有 Safety Hard Gates、`PLANE_TILT` 排名解释、pitch `0.250000 → 0.200000` 的人工选择链、Replay `SUCCESS` 的证明边界，以及 Process-aware A/B 问答。该验收不是 automated benchmark、模型准确率或生产环境验证。

评审时必须保持以下事实：`0.997781` 是相对排序 score，不是校准故障概率；没有真实光学产线或已验证真实设备数据；Aily 只做 Retrieve / Explain / Trace / Answer，不做参数生成或设备控制。
