# TuneWise MVP

当前实现范围为 TW-01 至 TW-04：启动本地离线应用，校验并导入版本化 AA 演示批次，使用只读控制限与版本化 SPC 规则检测四角 MTF 不对称，并以固定 StandardScaler 与 multinomial logistic regression 输出稳定 Top-3 根因、Z 类硬门控、证据充足度和结构化 logit 贡献解释。

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

## 重新生成诊断资产

以下命令使用固定主 `random_seed = 20260718`，并确定性派生互不相同的训练 seed `20260819` 与验证 seed `20260920`，从开发规模的隔离训练/验证分区拟合 StandardScaler 与五类 multinomial logistic regression，并生成固定特征定义、类别顺序、验证集冻结证据规则、资产清单、各文件 SHA-256 与规范化模型指纹：

```powershell
.\generate-diagnostic-assets.cmd
```

运行时制品写入 `assets/diagnostic/tw-diagnostic-v1`。训练/验证标签只在离线生成进程内使用，不写入运行时目录；清单仅保存隔离源资产的 seed、分区名、批次数、Batch 身份清单哈希、观测/标签哈希和分区清单哈希。50 个 `tw-feature-definition-v1` 特征仅来自当前 Batch 的 Measurement 可观测字段，固定覆盖 MTF、参数、平台/标定的均值、population standard deviation、线性趋势，以及四角聚合与左右/上下/对角差异。

相同生成器、输入、seed 与依赖版本应产生相同系数、截距、类别顺序、证据阈值和文件哈希。模型采用规范化 JSON 指纹；运行时会同时校验嵌入的 Manifest 根哈希、逐文件 SHA-256、模型指纹、特征顺序、类别顺序和版本绑定。资产按计划变化后，必须同步审阅并更新 `src/tunewise/main.py` 的诊断 Manifest 根哈希。

## 当前边界

应用提供固定演示身份、公共与诊断资产完整性校验、预置 AA CSV/Manifest 导入、双哈希校验、批次/观测/只读快照持久化、派生指标、确定性异常检测与根因诊断，以及只读阶段导航。只有 `TARGET_ANOMALY` 可诊断；合法的 `tw-diagnostic-result-v1` 结果推进至 `DIAGNOSED`。`INSUFFICIENT_EVIDENCE` 仍显示 Top-3 排查顺序，但参数候选数量固定为 0，且不开放 `PLAN_READY`。

当前没有 TW-05 案例检索，也没有 APPROVED 案例、参数方向证据、参数候选、安全验证、人工确认、SimulatorGateway、结果回放、报告、知识案例、登录、RBAC、规则编辑、真实设备、大模型或网络 API 依赖。
