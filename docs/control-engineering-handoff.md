# 控制工程接入交接

本文供未来控制工程成员核对 TuneWise 的本地 OPC-UA sandbox 边界。它不表示项目已经具备控制工程成员、真实设备连接或生产安全认证。

## 模块边界

- `DeviceExecutionService` 只接收当前任务、`ConfirmedPlan` 身份/hash、服务端 `ReplayResult` 和独立 sandbox 确认。它不接收 endpoint、node id、参数名或参数值。
- `SandboxOpcUaGateway` 是唯一 OPC-UA client adapter。`SimulatorGateway` 仍只由 Replay 调用，两者互不调用。
- `opcua_sandbox` 是本地模拟设备，namespace 固定为 `urn:tunewise:opcua:sandbox:parameters:v1`，mapping 固定为 `tw-opcua-node-mapping-v1`。
- 最终 `DeviceExecutionReceipt` 单独持久化，不扩展 `TaskStatus`。receipt 使用稳定 canonical JSON 和 SHA-256，业务 API 只有创建与查询，没有修改接口。

## 启动

```powershell
# Web 应用 + 正常 sandbox，设备执行显式开启
start-tunewise-opcua-demo.cmd

# 仅启动正常 sandbox
start-tunewise-opcua-sandbox.cmd

# 故障模式示例
$env:PYTHONPATH = "$PWD\src"
python -m tunewise.opcua_sandbox --fault WRITE_REJECTED
```

默认 `start-tunewise.cmd` 未改变，且不会开启设备执行。服务端配置为：

- `TUNEWISE_DEVICE_EXECUTION_ENABLED=true`；
- `TUNEWISE_OPCUA_MODE=OPCUA_SANDBOX`；
- `TUNEWISE_RUNTIME_PROFILE=OPCUA_SANDBOX_DEMO`；
- `TUNEWISE_OPCUA_SANDBOX_ENDPOINT=opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/`。

启用时 endpoint 必须是无凭据的 `localhost`/`127.0.0.1` sandbox 路径。浏览器不能覆盖配置。

## Namespace 与节点

| 参数 | String identifier | DataType | 单位 | sandbox 可写 |
| --- | --- | --- | --- | --- |
| `x_offset` | `TuneWiseSandbox.Parameters.x_offset` | `Double` | Normalized Offset Unit | 是 |
| `y_offset` | `TuneWiseSandbox.Parameters.y_offset` | `Double` | Normalized Offset Unit | 是 |
| `pitch` | `TuneWiseSandbox.Parameters.pitch` | `Double` | Normalized Angular Unit | 是 |
| `roll` | `TuneWiseSandbox.Parameters.roll` | `Double` | Normalized Angular Unit | 是 |
| `z_offset` | `TuneWiseSandbox.Parameters.z_offset` | `Double` | Normalized Offset Unit | 是 |

健康节点为 `TuneWiseSandbox.Device.Healthy`、`Status`、`FaultMode`。receipt 使用稳定 expanded node id，例如 `nsu=urn:tunewise:opcua:sandbox:parameters:v1;s=TuneWiseSandbox.Parameters.pitch`，不依赖运行时 namespace index。

## 门禁与状态

执行资格按服务端顺序 fail closed：配置/模式、独立确认、ConfirmedPlan 存在与 hash、有效期、VALID/freshness、上游版本和资产、ReplayResult 绑定、baseline reproduction、`SUCCESS`、写前 `ParameterSafetyValidator`、参数族、参数/节点白名单、单参数限制、observed server identity/mapping/datatype/unit/access、Method identity/capability、设备健康。parameter identity 要求 `AccessLevel` 与 `UserAccessLevel` 都允许 `CurrentRead` 且都不包含 `CurrentWrite`；任一参数意外可由客户端写入即拒绝执行。`ApplyConfirmedParameterChange` 还必须具有冻结的 NodeId/BrowseName、atomic capability，并保持 `Executable` 与 `UserExecutable`。资格阶段的普通读取只用于展示；安全 compare-and-set 由设备侧 atomic method 执行。默认设备执行有效期为确认后 1800 秒，可通过受限环境配置缩短或调整，但不能超过 86400 秒。

状态轨迹至少表达 `CREATED -> VALIDATING -> WRITE_STARTED -> SUCCEEDED`；明确业务拒绝进入 `REJECTED`，明确设备失败进入 `FAILED_DEFINITE`。设备可能已应用但响应丢失、通信中断或本地 receipt 首次持久化失败时进入 `UNKNOWN_OUTCOME`，随后仅按同一 idempotency key 查询设备记录；无证据或身份无法确认时保持 `RECONCILIATION_REQUIRED`。应用启动会查找未完成 claim 并执行只读 reconciliation，不自动重写。关键失败码：

- `MULTI_PARAMETER_ATOMICITY_UNSUPPORTED`：当前只支持恰好一个实际变化参数，写前整体拒绝；
- `DEVICE_VALUE_CHANGED_AT_ATOMIC_EXECUTION`：设备侧临界区发现值不等于 expected-before，物理写入次数为零；
- `ATOMIC_EXECUTION_UNSUPPORTED`：server 不提供受控条件执行能力，禁止普通 variable write fallback；
- `OPCUA_ENDPOINT_UNAVAILABLE` / `OPCUA_TIMEOUT` / `OPCUA_COMMUNICATION_FAILURE`：若发生于 `WRITE_STARTED` 后，不得当作明确失败；
- `FAILED_READBACK_MISMATCH`：写调用返回后回读不等于目标，不能标成功。

系统不实现多节点原子性，不先写部分节点，不宣称自动回滚。在 TuneWise 本地 OPC-UA sandbox 中，调机参数节点对普通 OPC-UA 客户端保持只读；参数变化只能通过受控 `ApplyConfirmedParameterChange` Method，并在 sandbox 单一执行锁内完成 idempotency lookup、权威节点值读取与规范化、expected-before 比较、目标校验、服务端写入、回读和执行记录创建。相同 key 返回首个设备记录，不产生第二次物理写入，不同 key 必须重新比较。外部普通 write 的安全边界来自 protocol/access-level 层拒绝；内部运行期 mutation 由同一 `execution_lock` 串行化，不能把 `asyncio.Lock` 描述为能够阻止 OPC-UA Write Service。启动前的初值设置和持久状态恢复不属于运行期 mutation。键还绑定 observed server identity hash、`task_id`、plan ID/hash、ReplayResult hash、mode、gateway、namespace、mapping 和 endpoint 指纹。当前 demo 进程内默认保存设备记录；CLI 可用 `--state-file` 启用轻量 JSON 持久化，相关测试覆盖 sandbox 重启恢复。OPC-UA 协议并不天然提供 CAS；当前结果不表示已验证真实 PLC 原子写或真实设备安全联锁。真实设备若没有设备侧 CAS、受控 Method 或 PLC/上位机联锁能力，TuneWise 只能使用 Shadow/Read-only 模式。

## 测试入口

```powershell
python -m pytest tests/backend/test_device_execution.py
python -m pytest tests/backend/test_device_execution_api.py
python -m pytest tests/backend/test_opcua_sandbox.py
```

`opcua_sandbox --fault` 还覆盖 `APPLY_THEN_TIMEOUT`、`ATOMIC_UNSUPPORTED` 及 identity/mapping/unit/datatype/metadata/access mismatch。监听 endpoint 固定为 `opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/`，不提供绑定全网卡的 CLI 参数。

## 真实设备接入前置问题

接入真实设备前必须由设备、工艺、安全和 IT/OT 责任方共同确认：设备厂商与型号；OPC-UA server 能力和版本；namespace 与节点类型；工程单位与 normalized 值的经审核换算；写权限；会话认证；证书与信任链；PLC/上位机联锁；安全停止；审批流程；真实设备回滚策略；多参数原子性；设备值刷新周期；并发写入与所有权；断线后的不确定写入处理；审计保留和凭据管理。

在这些问题、现场协议测试和授权未完成前，只能保留 `OPCUA_SANDBOX`，不得把 endpoint 改为真实设备地址。
