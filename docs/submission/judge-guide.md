# TuneWise｜评委快速体验指南

## 1. 项目定位

TuneWise 是面向精密光学主动对准（AA）单一工站的本地离线调机决策支持原型。它把异常证据、Top-3 根因、已审核案例、安全参数候选、人工确认和模拟回放串成可追溯流程；它不直接控制设备，也不代表舜宇真实内部系统。

预计用时：依赖已安装时，启动约数秒；从初始页面完成主流程约 1～2 分钟，配合讲解约 4 分 30 秒。

## 2. 环境要求

- Windows 10/11；
- Python `>=3.11,<3.13`；
- 仅运行已构建应用时不需要 Node.js；运行前端测试或 production build 时建议使用本基线验证过的 Node 22.x 与 npm 10.x；
- 首次安装 Python/npm 依赖需要可用的软件源或离线缓存；依赖安装完成后，应用运行和演示不需要外部网络。

评委不需要 API Key、云服务账号、企业数据、真实设备或外部网络连接。

## 3. 最短启动命令

在仓库根目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"
```

看到 `Uvicorn running on http://127.0.0.1:8000` 后保持终端开启。

## 4. 默认访问地址

浏览器打开：<http://127.0.0.1:8000>

健康检查：<http://127.0.0.1:8000/api/health>，应返回 `{"status":"ok","mode":"offline"}`。

## 5. 完整点击路径与预期结果

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

8. **“运行离线模拟回放”**
   - 看到 baseline reproduction `PASSED`；
   - replay status 为 `SUCCESS`，`attempt_count = 1`；
   - center MTF `0.831003 → 0.832128`；
   - worst corner `0.567683 → 0.651478`；
   - corner range `0.184837 → 0.102292`；
   - corner std `0.071709 → 0.042654`；
   - control limit `false → true`，target anomaly `true → false`；
   - ReplayResult hash 为 `e639cf3f2e69e217338f0f7e96ecabfa45523ca7d92ab45a320eb2b3b1435350`。

当前 `tw-08-complete` 的产品流程止于 `REPLAYED`。界面中的“复盘关闭”和“案例提交”仍保持锁定，它们属于 TW-10，不应在本次演示中尝试。

## 6. 演示数据说明

- 演示资产：`assets/demo/tw-aa-demo-v1/`；
- 使用公开知识与固定规则、固定 seed 生成的模拟观测；
- 不包含舜宇或其他企业内部数据；
- 归一化参数和 MTF 不代表真实设备物理单位或企业规格；
- `scenario_ref` 对业务侧保持不透明，隐藏内容不会进入 CSV、API 或界面。

## 7. 重置演示状态

先在启动终端按 `Ctrl+C` 停止服务，再在仓库根目录执行：

```powershell
Remove-Item -LiteralPath .\var\tunewise.db -ErrorAction SilentlyContinue
cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"
```

刷新浏览器后会自动创建新的本地演示数据库。`var/` 已被 Git 忽略；不要删除 `assets/` 中的 checked-in 文件，也不要修改规则或哈希。

## 8. 常见启动问题

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

## 9. 测试命令

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

## 10. 结果免责声明

TuneWise 未连接 MES、QMS 或真实设备，未向真实设备写入参数，不使用企业内部数据。界面中的模型相对分数不是真实故障概率，候选不是最优参数，模拟对照不证明真实世界因果关系。

> **规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。**
