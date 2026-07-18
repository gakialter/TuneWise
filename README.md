# TuneWise MVP

当前实现范围为 TW-01 至 TW-03：启动本地离线应用，校验并导入版本化 AA 演示批次，使用只读控制限与版本化 SPC 规则检测四角 MTF 不对称，并将正常、整体退化和数据不足路由到保护分支。

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

## 重新生成演示资产

以下命令固定使用 `random_seed = 20260718`，生成 `assets/demo/tw-aa-demo-v1/aa-demo-batch.csv`、`dataset-manifest.json` 与 `import-rules.json`：

```powershell
.\generate-demo-assets.cmd
```

相同代码、版本和种子重复运行时，CSV 字节、规范化观测与 SHA-256 哈希保持一致。生成后若版本化资产按计划发生变更，必须同步审阅并更新 `src/tunewise/main.py` 中嵌入的 DatasetManifest 哈希；运行时不会自动接受或修复不匹配资产。

## 当前边界

应用提供固定演示身份、公共版本资产完整性校验、预置 AA CSV/Manifest 导入、双哈希校验、批次/观测/只读快照持久化、派生指标、确定性异常检测、四类检测结果与只读阶段导航。只有 `TARGET_ANOMALY` 推进到 `ANOMALY_DETECTED`；其他结果保留检测证据但不开放后续流程。当前没有根因排序、证据充足度、案例检索、参数候选、人工确认、模拟回放、登录、RBAC、规则编辑、真实设备或在线服务接口。
