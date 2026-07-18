# TuneWise MVP

当前实现范围为 TW-01：启动最小离线应用并显示任务与版本状态。

## Windows 本地启动

前置条件：Python 3.11 或 3.12，并已安装项目锁定的 FastAPI 与 Uvicorn 版本。

```powershell
.\start-tunewise.cmd
```

启动后访问 `http://127.0.0.1:8000`。该命令只绑定本机 loopback，直接由 FastAPI 服务仓库中已构建的前端，不需要 Node.js、外部网络、在线模型或其他服务。

## 测试

后端与运行边界：

```powershell
python -m pytest
```

前端状态测试：

```powershell
cd frontend
npm test
```

重新构建前端：

```powershell
cd frontend
npm ci
npm run build
```

构建产物写入 `src/tunewise/static`，生产运行时不访问 npm registry。

## TW-01 边界

应用只提供固定演示身份、公共版本资产完整性校验、`CREATED` 任务、SQLite 最小任务状态和只读阶段导航。当前没有 CSV 导入、异常检测、根因排序、案例检索、参数候选、人工确认、模拟回放、登录、RBAC、规则编辑、真实设备或在线服务接口。
