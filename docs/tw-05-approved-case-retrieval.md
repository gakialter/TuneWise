# TW-05 APPROVED 案例检索资产

TW-05 使用版本化离线资产完成 AA 工站相似案例检索。运行时只读取该目录中的 `APPROVED` 案例、只读产品兼容规则、独立检索标准化器和结构化索引：

`assets/cases/tw-approved-case-index-v1/`

## 确定性生成

在仓库根目录运行：

```bat
generate-approved-case-index.cmd
```

固定种子为 `20260718`。生成器只从 TW-04 的允许训练分区 `diagnostic-dev-train-v1` 重建 60 个案例，并校验该分区的来源 Manifest；验证、测试、盲测、演示、`PENDING_REVIEW` 和运行时提交均不参与生成、拟合或索引。

## 版本与用途边界

- Case schema：`tw-approved-case-schema-v1`
- Case index：`tw-approved-case-index-v1`
- Retrieval scaler：`tw-case-retrieval-scaler-v1`
- Compatibility rules：`tw-product-compatibility-v1`
- Retrieval rules：`tw-case-retrieval-rules-v1`
- Feature definition：`tw-feature-definition-v1`，固定 50 项可观测批次特征

`tw-case-retrieval-scaler-v1` 只用于案例间结构化距离，由允许进入案例库的 `APPROVED` 训练来源案例特征拟合。它与 TW-04 逻辑回归模型使用的 `tw-preprocessing-v1` 目的、拟合边界和版本契约不同，运行时不得互相替代或隐式复用。零方差特征的 scale 固定为 `1`。

## 运行时契约

页面请求只发送任务路径中的 `task_id`，以及请求体中的最新 `diagnostic_result_id` 和固定 `top_k = 3`。查询特征由服务端从当前持久化 Measurement 重新生成，并与诊断的 `input_feature_hash` 核对。

检索先在当前诊断 Top-3 根因对应的兼容案例池中按标准化欧氏距离排序；不足 3 条时，才从其余兼容 `APPROVED` 案例补足。阶段内依次按距离升序和 `case_id` 升序排序。根因仅用于候选池划分和展示，不进入距离；历史动作、历史模拟结果、状态、ID、分区及任何隐藏场景字段同样不进入距离。

TW-05 的历史动作仅供展示。它不会被转换为当前参数候选，也不构成采用建议；参数方向证据、候选生成与 `ParameterSafetyValidator` 属于 TW-06。
