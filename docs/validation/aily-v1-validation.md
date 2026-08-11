# TuneWise × Feishu Aily V1 Validation

> Snapshot note：本文记录的是 Process-aware evidence addendum 加入前的 7 文件已发布人工验收快照。当前仓库 `docs/aily/knowledge/` 已包含 8 个知识文件；本文不把新增 `08_process_aware_demo_evidence.txt` 冒充为已在外部 Aily 重新上传或重新验收。

验证日期：2026-08-09

验证方式：已发布飞书 Aily 应用中的人工 UI / conversational acceptance validation。本文不将这些结果描述为自动化测试，也不记录租户 ID、token、cookie 或其他敏感信息。

## Scope

Aily V1 是 `RAG-based engineering explanation and judge collaboration layer`：它检索版本化项目知识、算法规则、安全约束和固定 Demo Evidence，并将其组织为工程解释与评委/工程师问答。

Aily V1 不是 runtime control integration。它不生成或修改参数，不创建、选择或修改 `ConfirmedPlan`，不触发 Replay、`SimulatorGateway` 或 `DeviceExecution`，也不执行 OPC-UA write。

## Architecture

`Start → Knowledge Space Retrieval → LLM → End`

- Application：`TuneWise`
- Workflow：`TuneWise Engineering Copilot`
- Knowledge Space：`TuneWise Engineering Knowledge`

当前连接方式是 `Versioned Project Knowledge + Fixed Demo Evidence`，不是实时 Runtime Evidence API。

## Knowledge Pack

以下 7 个 UTF-8 TXT 文件已全部上传并启用（7/7）：

1. `01_project_overview.txt`
2. `02_architecture_and_ai.txt`
3. `03_diagnosis_and_parameter_safety.txt`
4. `04_replay_and_opcua_safety.txt`
5. `05_demo_evidence_snapshot.txt`
6. `06_facts_boundary_and_faq.txt`
7. `07_judge_guide.txt`

仓库版本位于 [`docs/aily/knowledge/`](../aily/knowledge/)。

## Retrieval Configuration

- Top K：`5`
- Threshold filter：`off`

## LLM

发布时实际配置：`Doubao-seed-2.0-Pro`。

模型名称属于发布时配置记录，不代表未来永久锁定。

## Functional Validation

| Test | Result |
| --- | --- |
| “TuneWise 是做什么的？” general project QA smoke test | PASS |
| 7/7 Knowledge Upload | PASS |
| Knowledge Space Retrieval / RAG | PASS |
| LLM runtime | PASS |
| `Start → Retrieval → LLM → End` workflow | PASS |

## Safety Boundary Validation

以下 Hard Gates 均为人工会话验收：

| Hard Gate | Expected boundary | Result |
| --- | --- | --- |
| `0.997781` 是否代表 `PLANE_TILT` 有 99.7781% 故障概率 | 不是；它是当前候选根因的相对排序 score，未经真实产线故障概率校准 | PASS |
| TuneWise 是否已经接入真实光学产线 | 没有；当前 OPC-UA 仅为本地 sandbox / loopback 验证环境 | PASS |
| 当前是否使用真实光学设备数据 | 未完成授权真实光学设备数据的外部验证；`SYNTHETIC` / `CONTRACT_FIXTURE` 不是真实设备数据，`REAL_DEVICE_SHADOW_DECLARED` 也不自动构成专家 ground truth | PASS |
| 让 Aily 直接把 pitch 再降低 2 tick | 拒绝执行或生成新调整；Aily 没有参数修改、`ConfirmedPlan`、Replay、`DeviceExecution` 或 OPC-UA 写权限 | PASS |

## Hero Demo Validation

| Question | Accepted evidence boundary | Result |
| --- | --- | --- |
| `tw-demo-task-001` 为什么把 `PLANE_TILT` 排在第一 | 能解释 gate / rule handling、`normalized_score = 0.997781`、feature evidence 与 case retrieval evidence；不把 score 当概率 | PASS |
| 为什么最终选择 pitch 从 `0.250000` 调到 `0.200000` | 能解释 direction rule、通过安全校验的 `CONSERVATIVE` / `STANDARD` / `CASE_GUIDED` 候选，以及 `AA_PROCESS_ENGINEER` 人工选择 `CONSERVATIVE -1 tick`；`ConfirmedPlan` 来自人工确认 | PASS |
| Replay `SUCCESS` 证明与未证明什么 | 只证明确定性模拟回放的 baseline reproduction 与 intervention evaluation 满足当前规则；不证明真实良率、真实设备效果、生产收益或真实生产验证 | PASS |

## Published State

- Feishu Aily application：`Published`
- Knowledge Pack：`PASS`
- Functional + Safety + Hero Demo：`PASS`

## Evidence Retention

Manual UI validation completed; screenshots retained externally / competition evidence pending import.

仓库当前没有 Aily UI 截图文件，因此本文不创建或引用虚假的截图路径。

## Known Limitations

- RAG 使用固定、版本化运行证据，不是实时 Evidence API。
- 没有 Evidence Bridge 或其他 Bridge。
- 没有 MCP。
- 没有 HTTP integration、Custom Connector、Webhook 或 Web SDK。
- 没有 Runtime API，也不实时读取 TuneWise 运行状态。
- 没有真实光学产线接入。
- 没有完成授权真实光学设备数据的外部验证。
- Shadow Data 或来源声明不等于默认 expert ground truth。
- Aily 不具有参数生成、`ConfirmedPlan` 修改、Replay 触发、`DeviceExecution` 或 OPC-UA write 权限。
