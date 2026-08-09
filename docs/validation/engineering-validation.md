# TuneWise 复赛工程验证记录

验证日期：2026-08-09
验证基线：`main` / `1fdc526cc8794965b6c591a2fa5bc399e50a4e2b`

## 自动化验证

以下命令在仓库 `.venv`（Python 3.12.13、asyncua 1.1.8）以及 Node.js 22.15.0 / npm 10.9.2 上执行：

| 验证项 | 命令 | 实际结果 |
| --- | --- | --- |
| 后端全量 | `.\.venv\Scripts\python.exe -m pytest` | `433 passed in 328.82s` |
| 固定资产专项 | `.\.venv\Scripts\python.exe -m pytest tests/backend/test_diagnostic_asset_generation.py tests/backend/test_public_assets.py tests/backend/test_demo_asset_generation.py tests/backend/test_approved_case_asset_generation.py tests/backend/test_parameter_planning_assets.py tests/backend/test_replay_assets_and_gateway.py -q` | `22 passed` |
| 前端全量 | `cd frontend; npm test` | `40 passed` |
| Production build | `cd frontend; npm run build` | 成功；生成 `index-DPV54KOG.css`、`index-DuCC5mWP.js` |
| Python 编译 | `.\.venv\Scripts\python.exe -m compileall -q src tools tests` | 通过 |
| Python 依赖 | `.\.venv\Scripts\python.exe -m pip check` | `No broken requirements found.` |
| Windows 脚本 | `.\.venv\Scripts\python.exe -m pytest tests/backend/test_windows_startup_scripts.py -q` | `6 passed`；真实 `cmd.exe`、缺 venv、端口占用、Ctrl+Break 清理 |
| LF 干净检出 | `.\.venv\Scripts\python.exe -m pytest tests/backend/test_windows_lf_checkout.py -q` | `1 passed`；`core.autocrlf=true` 临时 commit/clone/rebuild 字节一致 |
| Diff 格式 | `git diff --check` | 通过；仅有 Git 的 CRLF 转换提示 |

固定诊断资产仍记录原始生成环境 Python 3.11.9；生成器已冻结该 provenance 字段，避免在当前 Python 3.12.13 下重算时改变固定资产字节。现有 manifest 与固定演示资产未修改。

## Shadow CLI 证据

执行：

```powershell
.\validate-shadow-data.cmd `
  --csv tests/fixtures/shadow-data/synthetic-contract-observations.csv `
  --manifest tests/fixtures/shadow-data/synthetic-contract-mapping-v1.json `
  --analysis-contract tests/fixtures/shadow-data/synthetic-contract-analysis-v1.json
```

实际输出摘要：

- 来源为 `CONTRACT_FIXTURE`，真实性状态为 `SYNTHETIC`，评估状态为 `NOT_EVALUABLE`。
- raw SHA-256：`2afcbec6eb50f8dd555b84758b8f71fd0138fc464735fffcde66bc77bd27e6bc`。
- canonical SHA-256：`aca64480cbef2a9da8f919d5a70df5d0718c5dbb6d8a8d496ff66af386c44c2f`。
- evidence bundle hash：`def1e164ed8ddcc6aeaad67337a745114b360b66b76eb08cec0490d2500dee2a`。
- analysis result hash：`22bdce589970f0e30f53e7a41d34cd8c7d493765d549f38dd8d1d8ae7085f5a7`。
- Top-3 为 `PLANE_TILT`、`REFERENCE_DRIFT`、`XY_DECENTER`；CONSERVATIVE 候选为 `pitch -1 tick -> 0.200000`。
- 数据保持在 `SHADOW_READ_ONLY`，没有进入训练集或 `APPROVED` 案例库，也没有触发重训或修改固定演示资产。

## 固定资产 SHA-256

使用 PowerShell `Get-FileHash -Algorithm SHA256` 独立复算各 manifest 及其声明文件：

| 资产 | Manifest SHA-256 | 受管文件 | 结果 |
| --- | --- | ---: | --- |
| public | `2de0019bb69bc9d73c97811bf0362c6c390e2186abc10874d18e8e96bf34697c` | 1 | 全部匹配 |
| diagnostic | `d2d287fcd830771c3b8c6e91f41152d950ea2a02820107c1ca802fb268b5ed4b` | 5 | 全部匹配 |
| approved cases | `3259575b170a617a9314a7c6883d829b64df9a022be7a90529bf7e50db7acb81` | 4 | 全部匹配 |
| parameter planning | `fc73d61a29bcfbe89ab3b8f34cd0cf7436ff10c0716c59be8882b21be2881f4b` | 3 | 全部匹配 |
| replay simulator | `b97ca12e0f987ac98a5c4da69267eb7ba7d82161be401c86876eb13caaaa5141` | 4 | 全部匹配 |
| demo dataset | `d66077f880e6d4c470772be30a771ca20d26520ab39c08fc4f4340fa4e31950c` | CSV + rules | raw/rules 全部匹配；canonical hash `c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668` |

## 浏览器与本地 OPC-UA 证据

浏览器实测记录见 `browser-qa-evidence.json` 和同目录截图。实际执行为本地 OPC-UA sandbox atomic method：`pitch 0.250000 -> 0.200000`，写后回读 `0.200000`。sandbox 参数 Variable 对普通 OPC-UA client 全生命周期只读；唯一运行期 mutation 入口是受单一执行锁保护的 `ApplyConfirmedParameterChange`。该边界仅对本地模拟设备成立，不表示 OPC-UA 天然提供 CAS，也不表示已验证真实 PLC 原子写或真实设备安全联锁。

390px 视口下 `scrollWidth == clientWidth == 390`；桌面宽度 1440px 同样无溢出。观察到 17 个同源 HTTP 请求；外部 HTTP 请求、console error、page error 和 failed request 均为 0。系统 socket 检查确认 4841 与 8000 均只监听 `127.0.0.1`。

当前 OPC-UA 通道连接的是本地模拟设备，不代表已经完成真实设备接入或真实设备安全验证。规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。
