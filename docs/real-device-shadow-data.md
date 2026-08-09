# 真实设备数据只读影子适配

本模块用于在取得授权数据后执行显式映射、来源声明、质量校验和只读影子评估。它不验证操作者的来源声明，不写入训练集或 `APPROVED` 案例库，不修改固定演示资产，也不触发模型重训。

## 边界

- 导入入口：`ShadowDataAdapter.import_csv(csv_bytes, manifest_payload)`。
- 分析入口：`ShadowAnalysisRunner.run(dataset, analysis_contract)`。
- 导入输出：冻结的 `ImportedShadowDataset`，存储分区固定为 `SHADOW_READ_ONLY`；canonical measurements 使用不可变 mapping，不能在哈希后被下游修改。
- 输入仅为内存中的 CSV bytes 和 mapping manifest；适配器没有数据库、案例库、训练目录或模型写接口。
- `ShadowAnalysisRunner` 只调用现有纯领域检测、特征工程、Top-3 诊断、方向证据、候选生成和 `ParameterSafetyValidator`；不调用 `TaskService`、`TaskStore`、案例检索或资产生成器。
- `REAL_DEVICE_SHADOW_DECLARED` 表示操作者声明，不表示 TuneWise 已验证企业、设备、授权或数据真实性。
- 单纯完成 mapping/import 不代表可运行算法。只有显式 analysis contract 与当前数据、规则和冻结资产全部匹配后，`diagnostic_runnable` 与 `safety_recommendation_runnable` 才能为 `true`。
- 无有效 review contract 时可以输出离线异常检测、根因排序和规则通过的安全候选，但评估状态必须保持 `NOT_EVALUABLE`。
- 无真实干预前后数据时，不输出真实良率、调机时间、因果收益或参数有效性指标。

## 来源类型

| 值 | 含义 |
| --- | --- |
| `SYNTHETIC_DEMO` | 项目演示合成数据 |
| `CONTRACT_FIXTURE` | 自动化契约测试用合成数据 |
| `REAL_DEVICE_SHADOW_DECLARED` | 操作者声明为真实设备影子导出，真实性未由 TuneWise 验证 |

`source_metadata` 必须显式包含 `declared_by`、`declared_at`、`provenance_statement`、`device_model_declared`、`authorization_reference` 和与来源类型匹配的 `data_reality`。这些字段是声明证据，不是真实性认证。

## Mapping manifest

manifest 版本为 `tw-shadow-mapping-manifest-v1`，并绑定：

- 独立 `mapping_version`；
- `tw-schema-v1` 和现有 `tw-canonicalizer-v1`；
- 来源类型及来源元数据；
- 每个外部列到 16 个冻结 observable 字段的一对一映射；
- `IDENTIFIER`、`TIMESTAMP`、`PARAMETER`、`OBSERVATION` 分类；
- 外部单位、canonical 单位和显式转换；
- required canonical 字段、required/optional batch/lot 字段；
- optional reviewed outcome 字段和显式 review contract；
- 显式 ignored columns；
- raw file SHA-256 与 canonical observation SHA-256。

CSV 中出现未映射且未显式忽略的列会以 `MAPPING_INVALID` 拒绝。列语义、单位、设备型号、根因标签和参数方向均不会自动猜测。

当前单位转换采用关闭白名单。normalized unit 只允许 identity；MTF 额外允许 `PERCENT -> NORMALIZED_MTF`，scale 固定为 `0.01`。设备物理单位到 normalized unit 的换算通常依赖厂商、型号和标定配置，在获得并审核该契约前以 `UNIT_UNKNOWN` 拒绝，不能在 manifest 中任意指定 scale。

## Analysis contract

mapping manifest 只说明“如何把外部数据变成 canonical observation”，不会自行选择控制限、规则或模型。运行 shadow 分析还必须提供 `tw-shadow-analysis-contract-v1`，显式绑定：

- mapping version、raw SHA-256、canonical schema/canonicalizer 版本与 canonical observation SHA-256；
- input data version、product model 与 rule set version；
- 完整 control-limit snapshot 和 SPC rule snapshot；
- 完整 parameter-constraint snapshot 及其 SHA-256；
- diagnostic/planning manifest SHA-256；
- model、preprocessing、feature definition 与 safety rule 版本；
- `case_library_mode = DISABLED_SHADOW_ISOLATION`。

同一 rule version 下修改控制限或 SPC 值会被拒绝；诊断/规划 manifest、参数快照、数据 hash 或版本不匹配也会 fail closed。endpoint、设备凭据和设备写入不属于该契约。

## ShadowEvidenceBundle、质量与哈希

raw hash 直接对收到的 CSV bytes 计算。完成显式映射和单位转换后，适配器把数据交给现有 `ObservableCanonicalizer`，沿用 UTF-8、带时区时间戳、六位 `Decimal` 和稳定 canonical observation hash 规则。版本化 `ShadowEvidenceBundle` 进一步绑定 raw file、mapping manifest、canonical measurements、observation contexts、reviewed outcomes、source/provenance metadata、unit mapping、mapping version、review contract 及 bundle schema/version，并分别生成 context、reviewed-outcome、provenance 与 evidence-bundle SHA-256。最终 analysis/result hash 必须包含 evidence-bundle hash。

质量报告每次都由已验证 bundle 的 measurements、contexts、reviewed outcomes 和 review contract 重新生成；调用方传入或先前缓存的 report 不作为权威输入。任何 context、标签、方向、root cause、来源、reviewer、reviewed_at 或 protocol version 变化都会使 bundle/result hash 改变，旧 report 不能复用。

`ShadowDataQualityReport` 记录：

- schema mapping、required 字段和单位完整性；
- 样本数、分析 group 数、每组最小样本数、缺失值、重复/不连续 `sample_index` 和时间顺序；
- 数值类型、非有限值和允许范围/tick 网格；
- feature 可计算性、SPC 最小样本条件；
- analysis contract 是否绑定，以及 diagnosis 和安全荐参的最终就绪状态；
- 合法 review contract 与 reviewed outcome 是否存在及可评估 group 数。

结构化状态包括 `MAPPING_INVALID`、`UNIT_UNKNOWN`、`FEATURE_UNAVAILABLE`、`INSUFFICIENT_DATA`、`NOT_EVALUABLE` 和 `READY`。映射、单位、数值或哈希错误 fail closed；零样本和每组样本不足均为 `INSUFFICIENT_DATA`，不能进入诊断或安全荐参；无标签数据在 contract 通过后可以运行影子输出，但不能计算准确率。

## 审核结果与影子评估

reviewed outcome mapping 必须四个字段全有或全无；部分 mapping 会以 `MAPPING_INVALID` 拒绝。合法 reviewed outcome 需要按 batch/lot 一致地映射以下字段：

- `reviewed_status = REVIEWED`；
- `reviewed_anomaly` 属于冻结异常标签；
- `reviewed_root_cause` 属于冻结诊断类别或 `NOT_APPLICABLE`；
- `reviewed_parameter_direction` 为 `INCREASE`、`DECREASE`、`NO_CHANGE` 或 `NOT_APPLICABLE`。

review contract 还必须绑定 reviewer reference、reviewer role、带时区 reviewed time、review protocol version、label source、dataset/batch reference、reviewed outcome version 和 provenance declaration。`OPERATOR_DECLARED` 与 `REVIEWED_DECLARED` 都只是声明证据；当前没有外部验证机制，因此不得使用 `EXTERNALLY_VERIFIED`。缺少 reviewer/time/protocol 或 outcome 跨字段冲突时不可评估；synthetic fixture 必须在 provenance 中明确标记 synthetic。

生产入口由 `ShadowAnalysisRunner` 先真实运行 `AnomalyDetector`、`FeatureEngineer`、`RootCauseDiagnoser`、`DirectionEvidenceGenerator`、`ParameterPlanGenerator` 和 `ParameterSafetyValidator`，再把每个 batch/lot 的输出交给 `evaluate_shadow_dataset`。有合法声明式 review 时仅报告描述性覆盖率、Top-1/Top-3 reviewed-label consistency、无法判断比例、安全规则通过率、数据不足拒绝率及方向一致性，状态为 `EVALUATED_DECLARED_REVIEW`，并明确说明未外部验证。报告不计算或声称“专家一致率”，并明确排除真实良率改善、真实调机时间下降、因果参数效果和参数有效性声明。

结果绑定 analysis contract、数据、规则、模型、参数约束与安全版本，并采用稳定 canonical JSON/SHA-256。runner 不读取 `APPROVED` 案例；规则候选以 `cases=()` 生成，结果明确记录 `DISABLED_SHADOW_ISOLATION`。

## 契约 fixture 与测试

`tests/fixtures/shadow-data/synthetic-contract-*` 在文件名、manifest 来源、provenance 和断言中都标记为 synthetic contract fixture，不是真实设备数据。

```powershell
python -m pytest tests/backend/test_shadow_data.py tests/backend/test_shadow_analysis.py -q
```

接入授权数据前，应先复制 manifest 结构并逐项填写经设备/控制工程审核的列、单位、batch/lot、设备型号声明和授权引用，再离线计算并固化 raw/canonical hash。不得修改 contract fixture 来冒充真实来源。

可用只读 CLI 先运行适配器；提供 analysis contract 时再运行完整影子分析。输出包含质量报告、版本/hash、每组模型输出和安全候选，但不包含原始 measurement 列表：

```powershell
validate-shadow-data.cmd `
  --csv <authorized-export.csv> `
  --manifest <mapping-manifest.json> `
  --analysis-contract <reviewed-analysis-contract.json>
```

省略 `--analysis-contract` 时只执行 mapping/import，算法 runnable flags 保持 `false`。该命令不写入任务数据库、训练集、模型或案例库。缺文件、坏 JSON、mapping、单位、hash、contract 或资产不匹配均以退出码 `2` 和结构化状态返回，不输出 traceback；`REAL_DEVICE_SHADOW_DECLARED` 仍只是操作者声明。
