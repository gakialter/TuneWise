# TuneWise｜演示应急卡

原则：先保留现场状态，再采用最小恢复动作。所有命令均在仓库根目录执行；数据库操作前先在启动终端按 `Ctrl+C` 停止服务。

| 情况 | 现象 | 最短恢复 | 不应采取的危险操作 |
|---|---|---|---|
| 服务未启动 | 浏览器显示无法连接 | `cmd /c ".venv\Scripts\activate.bat && start-tunewise.cmd"` | 不要临时改业务代码或关闭系统安全软件 |
| 8000 端口占用 | Uvicorn 报 `address already in use` | `$env:PYTHONPATH="$PWD\src"; .\.venv\Scripts\python.exe -m uvicorn tunewise.main:app --host 127.0.0.1 --port 8001`，访问 `http://127.0.0.1:8001` | 不要盲目结束未知系统进程，不要绑定 `0.0.0.0` 暴露服务 |
| 前端未构建 | 首页 404、空白或静态文件缺失 | `cd frontend; npm ci; npm run build; cd ..`，然后重启服务 | 不要从不明地址下载构建产物，不要手改压缩后的 JS |
| 数据库已有旧任务 | 打开后已经处于流程中段或 `REPLAYED` | `Move-Item -LiteralPath .\var\tunewise.db -Destination .\var\tunewise.db.recovery`，再启动服务 | 不要编辑 SQLite 结果，不要删除 checked-in 资产 |
| 页面不是初始状态 | 页面仍显示旧阶段，但数据库已重置 | `Ctrl+F5`；仍异常则关闭当前标签后重新打开本地地址 | 不要用 DevTools 注入状态，不要修改前端请求 |
| 演示资产校验失败 | 导入被拒绝，提示 Manifest/hash/version 错误 | `.\.venv\Scripts\python.exe -m pytest tests/backend/test_public_assets.py tests/backend/test_demo_asset_generation.py tests/backend/test_replay_assets_and_gateway.py` | 不要修改规则、Manifest、seed、hash 或 `main.py` 中预期值来“通过” |
| 浏览器缓存问题 | 样式旧、按钮文字不一致、资源加载异常 | `Ctrl+F5`；必要时用无痕窗口访问本地地址 | 不要清空整个浏览器个人资料，不要安装临时扩展 |
| 回放已执行，无法再次演示 | 按钮显示已完成，任务为 `REPLAYED` | 停止服务，移动 `var\tunewise.db` 为备份，重新启动并刷新 | 不要篡改 ReplayResult、`attempt_count` 或幂等键，不要直接改数据库 |
| 网络不可用 | 外网页面打不开，但本地依赖已安装 | 无需处理；继续访问 `http://127.0.0.1:8000` | 不要连接临时热点上传项目；不要引入在线 API、LLM 或 CDN |
| 投影分辨率过低 | 内容过密或关键卡片不在一屏 | 浏览器按 `F11` 全屏，再用 `Ctrl+-` 调到 80%～90%；保留页面滚动 | 不要临时改 CSS、缩放系统 DPI 或隐藏免责声明 |
| 时间不足 | 剩余时间不足以逐项展开 | 使用[5 分钟脚本](demo-script-5min.md)的超时方案：只读 Top-3、APPROVED-only、安全 `PASSED`、关键回放数值和免责声明 | 不要跳过人工确认后直接调用接口，不要伪造结果或口头外推真实效果 |

## 30 秒恢复顺序

1. 看启动终端：若未运行，启动；若端口占用，改用 8001。
2. 看页面阶段：若不是初始状态，停止服务并移动本地数据库，再启动和强制刷新。
3. 若资产校验失败，停止现场交互，改用已提交真实截图说明流程，并明确“现场资产校验未通过”；不要绕过校验。
4. 时间不足时直接使用 30 秒备用介绍和回放结果截图，保留完整免责声明。

## 绝对禁止

- 不删除或改写 `assets/` 下的 checked-in 资产；
- 不修改规则、模型、seed、Manifest 或任何 hash；
- 不临时篡改数据库结果、候选、确认方案或回放状态；
- 不使用 `force`、`force-with-lease`、rebase 或其他 Git 历史改写；
- 不把仓库临时改为 PUBLIC，不创建未经授权的 Release；
- 不把模拟结果描述为真实产线效果。

> 规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。
