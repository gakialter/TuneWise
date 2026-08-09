from __future__ import annotations

import hashlib
import json
import os
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import ContextManager, Iterator, Mapping, Protocol
from urllib.parse import urlparse

from asyncua import ua
from asyncua import Client
from asyncua.ua.uaerrors import BadNotWritable, BadTimeout, BadUserAccessDenied


OPCUA_SANDBOX_MODE = "OPCUA_SANDBOX"
OPCUA_DISABLED_MODE = "DISABLED"
OPCUA_SANDBOX_ENDPOINT = "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/"
OPCUA_NAMESPACE_URI = "urn:tunewise:opcua:sandbox:parameters:v1"
OPCUA_NODE_MAPPING_VERSION = "tw-opcua-node-mapping-v1"
OPCUA_GATEWAY_VERSION = "tw-asyncua-sandbox-gateway-v1"
OPCUA_ENDPOINT_LOCAL_ID = "tunewise-local-opcua-sandbox-v1"
OPCUA_SANDBOX_RUNTIME_PROFILE = "OPCUA_SANDBOX_DEMO"
OPCUA_SANDBOX_APPLICATION_URI = "urn:tunewise:opcua:sandbox:server:v1"
OPCUA_SANDBOX_PATH = "/tunewise/opcua-sandbox/"
OPCUA_SANDBOX_PORT = 4841
OPCUA_SANDBOX_SERVER_VERSION = "tw-opcua-sandbox-server-v3"
OPCUA_PARAMETER_SAFETY_MAPPING_VERSION = "tw-parameter-safety-mapping-v2"
OPCUA_SANDBOX_SECURITY_PROFILE = "LOCAL_ANONYMOUS_SANDBOX"
OPCUA_ATOMIC_METHOD_VERSION = "tw-opcua-atomic-method-v2"
VALUE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class OpcUaNodeMapping:
    parameter_name: str
    identifier: str
    unit: str
    data_type: str = "Double"

    @property
    def expanded_node_id(self) -> str:
        return f"nsu={OPCUA_NAMESPACE_URI};s={self.identifier}"


NODE_MAPPINGS: Mapping[str, OpcUaNodeMapping] = {
    item.parameter_name: item
    for item in (
        OpcUaNodeMapping(
            "x_offset",
            "TuneWiseSandbox.Parameters.x_offset",
            "Normalized Offset Unit",
        ),
        OpcUaNodeMapping(
            "y_offset",
            "TuneWiseSandbox.Parameters.y_offset",
            "Normalized Offset Unit",
        ),
        OpcUaNodeMapping(
            "pitch",
            "TuneWiseSandbox.Parameters.pitch",
            "Normalized Angular Unit",
        ),
        OpcUaNodeMapping(
            "roll",
            "TuneWiseSandbox.Parameters.roll",
            "Normalized Angular Unit",
        ),
        OpcUaNodeMapping(
            "z_offset",
            "TuneWiseSandbox.Parameters.z_offset",
            "Normalized Offset Unit",
        ),
    )
}


def normalize_device_value(value: object) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise OpcUaGatewayError(
            "OPCUA_VALUE_INVALID",
            "OPC-UA 节点返回了无法规范化的数值。",
            "COMMUNICATION",
        ) from error
    if not parsed.is_finite():
        raise OpcUaGatewayError(
            "OPCUA_VALUE_INVALID",
            "OPC-UA 节点返回了非有限数值。",
            "COMMUNICATION",
        )
    return format(parsed.quantize(VALUE_QUANTUM), "f")


def _enabled(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def validate_sandbox_endpoint(endpoint: str) -> None:
    """Reject every endpoint spelling except the frozen loopback sandbox URL."""
    try:
        parsed = urlparse(endpoint)
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            "OPC-UA sandbox endpoint 必须是无凭据的本机 sandbox 地址。"
        ) from error
    if (
        parsed.scheme != "opc.tcp"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed.path != OPCUA_SANDBOX_PATH
        or port != OPCUA_SANDBOX_PORT
        or "%" in parsed.netloc
        or parsed.netloc
        not in {
            f"127.0.0.1:{OPCUA_SANDBOX_PORT}",
            f"localhost:{OPCUA_SANDBOX_PORT}",
        }
    ):
        raise ValueError(
            "OPC-UA sandbox endpoint 必须是无凭据的本机 sandbox 地址。"
        )


@dataclass(frozen=True, slots=True)
class DeviceExecutionConfig:
    enabled: bool = False
    mode: str = OPCUA_DISABLED_MODE
    runtime_profile: str = "DEFAULT"
    endpoint: str = OPCUA_SANDBOX_ENDPOINT
    request_timeout_seconds: float = 2.0
    confirmed_plan_max_age_seconds: int = 1800
    gateway_version: str = OPCUA_GATEWAY_VERSION
    namespace_uri: str = OPCUA_NAMESPACE_URI
    node_mapping_version: str = OPCUA_NODE_MAPPING_VERSION
    endpoint_local_id: str = OPCUA_ENDPOINT_LOCAL_ID

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> DeviceExecutionConfig:
        source = os.environ if environ is None else environ
        enabled = _enabled(source.get("TUNEWISE_DEVICE_EXECUTION_ENABLED"))
        mode = source.get("TUNEWISE_OPCUA_MODE", OPCUA_DISABLED_MODE).strip()
        runtime_profile = source.get("TUNEWISE_RUNTIME_PROFILE", "DEFAULT").strip()
        endpoint = source.get(
            "TUNEWISE_OPCUA_SANDBOX_ENDPOINT",
            OPCUA_SANDBOX_ENDPOINT,
        ).strip()
        timeout_raw = source.get("TUNEWISE_OPCUA_REQUEST_TIMEOUT_SECONDS", "2.0")
        max_age_raw = source.get(
            "TUNEWISE_DEVICE_EXECUTION_PLAN_MAX_AGE_SECONDS",
            "1800",
        )
        try:
            timeout = float(timeout_raw)
        except ValueError as error:
            raise ValueError("TUNEWISE_OPCUA_REQUEST_TIMEOUT_SECONDS 必须是数值。") from error
        try:
            max_age = int(max_age_raw)
        except ValueError as error:
            raise ValueError(
                "TUNEWISE_DEVICE_EXECUTION_PLAN_MAX_AGE_SECONDS 必须是整数。"
            ) from error
        config = cls(
            enabled=enabled,
            mode=mode,
            runtime_profile=runtime_profile,
            endpoint=endpoint,
            request_timeout_seconds=timeout,
            confirmed_plan_max_age_seconds=max_age,
        )
        config.validate()
        return config

    @property
    def endpoint_fingerprint(self) -> str:
        return hashlib.sha256(
            f"{self.endpoint_local_id}|{self.endpoint}".encode("utf-8")
        ).hexdigest()

    def validate(self) -> None:
        if self.request_timeout_seconds <= 0 or self.request_timeout_seconds > 30:
            raise ValueError("OPC-UA sandbox timeout 必须在 (0, 30] 秒内。")
        if (
            self.confirmed_plan_max_age_seconds <= 0
            or self.confirmed_plan_max_age_seconds > 86400
        ):
            raise ValueError("设备执行方案有效期必须在 (0, 86400] 秒内。")
        if not self.enabled:
            return
        if self.mode != OPCUA_SANDBOX_MODE:
            raise ValueError("设备执行启用时只允许 OPCUA_SANDBOX 模式。")
        if self.runtime_profile != OPCUA_SANDBOX_RUNTIME_PROFILE:
            raise ValueError(
                "设备执行只允许在显式 OPCUA_SANDBOX_DEMO runtime profile 中启用。"
            )
        validate_sandbox_endpoint(self.endpoint)
        if self.namespace_uri != OPCUA_NAMESPACE_URI:
            raise ValueError("OPC-UA namespace 必须使用冻结的 sandbox 版本。")
        if self.node_mapping_version != OPCUA_NODE_MAPPING_VERSION:
            raise ValueError("OPC-UA node mapping 版本不受支持。")


@dataclass(frozen=True, slots=True)
class OpcUaHealth:
    connected: bool
    device_status: str
    fault_mode: str


@dataclass(frozen=True, slots=True)
class OpcUaParameterMetadata:
    parameter_name: str
    node_id: str
    browse_name: str
    data_type: str
    engineering_unit: str
    readable: bool
    writable: bool


@dataclass(frozen=True, slots=True)
class OpcUaObservedIdentity:
    endpoint_url: str
    application_uri: str
    namespace_uri: str
    server_version: str
    node_mapping_version: str
    parameter_safety_mapping_version: str
    sandbox_mode: str
    security_profile: str
    certificate_fingerprint: str | None
    parameters: tuple[OpcUaParameterMetadata, ...]
    atomic_method_version: str
    identity_hash: str


@dataclass(frozen=True, slots=True)
class AtomicExecutionResult:
    idempotency_key: str
    parameter_name: str
    expected_before: str
    requested_after: str
    actual_before: str | None
    actual_after: str | None
    result: str
    executed_at: str | None
    physical_write_count: int


def _identity_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class OpcUaGatewayError(RuntimeError):
    def __init__(self, code: str, message: str, stage: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage


class OpcUaSession(Protocol):
    @property
    def observed_identity(self) -> OpcUaObservedIdentity: ...

    def read_health(self) -> OpcUaHealth: ...

    def read_parameter(self, parameter_name: str) -> str: ...

    def apply_confirmed_parameter_change(
        self,
        *,
        idempotency_key: str,
        parameter_name: str,
        expected_before: str,
        requested_after: str,
    ) -> AtomicExecutionResult: ...

    def query_execution_result(
        self,
        idempotency_key: str,
    ) -> AtomicExecutionResult | None: ...


class OpcUaGateway(Protocol):
    version: str

    def session(self) -> ContextManager[OpcUaSession]: ...


class _AsyncuaSession:
    def __init__(
        self,
        runner: asyncio.Runner,
        client: Client,
        namespace_index: int,
        config: DeviceExecutionConfig,
    ) -> None:
        self._runner = runner
        self._client = client
        self._namespace_index = namespace_index
        self._config = config
        self._atomic_supported = False
        self._observed_identity = self._observe_identity()

    @property
    def observed_identity(self) -> OpcUaObservedIdentity:
        return self._observed_identity

    def _node(self, identifier: str):
        return self._client.get_node(ua.NodeId(identifier, self._namespace_index))

    def _read(self, identifier: str) -> object:
        try:
            return self._runner.run(self._node(identifier).read_value())
        except (TimeoutError, BadTimeout) as error:
            raise OpcUaGatewayError(
                "OPCUA_TIMEOUT",
                "OPC-UA sandbox 读取超时。",
                "COMMUNICATION",
            ) from error
        except Exception as error:
            raise OpcUaGatewayError(
                "OPCUA_COMMUNICATION_FAILURE",
                "OPC-UA sandbox 读取失败。",
                "COMMUNICATION",
            ) from error

    def _fault_mode(self) -> str:
        value = str(self._read("TuneWiseSandbox.Device.FaultMode"))
        if value == "TIMEOUT":
            raise OpcUaGatewayError(
                "OPCUA_TIMEOUT",
                "OPC-UA sandbox 已进入超时故障模式。",
                "COMMUNICATION",
            )
        if value in {"COMMUNICATION_FAILURE", "SERVICE_UNAVAILABLE"}:
            raise OpcUaGatewayError(
                "OPCUA_COMMUNICATION_FAILURE",
                "OPC-UA sandbox 已进入通信失败模式。",
                "COMMUNICATION",
            )
        return value

    def read_health(self) -> OpcUaHealth:
        fault_mode = self._fault_mode()
        status = str(self._read("TuneWiseSandbox.Device.Status"))
        healthy = bool(self._read("TuneWiseSandbox.Device.Healthy"))
        return OpcUaHealth(healthy, status, fault_mode)

    def read_parameter(self, parameter_name: str) -> str:
        self._fault_mode()
        mapping = NODE_MAPPINGS.get(parameter_name)
        if mapping is None:
            raise OpcUaGatewayError(
                "PARAMETER_NOT_ALLOWLISTED",
                "参数不在 OPC-UA sandbox 节点白名单中。",
                "VALIDATION",
            )
        return normalize_device_value(self._read(mapping.identifier))

    def _observe_identity(self) -> OpcUaObservedIdentity:
        try:
            endpoints = self._runner.run(self._client.get_endpoints())
            matching = [
                item for item in endpoints if item.EndpointUrl == self._config.endpoint
            ]
            if not matching:
                raise OpcUaGatewayError(
                    "OPCUA_ENDPOINT_IDENTITY_MISMATCH",
                    "observed OPC-UA endpoint URL 与冻结配置不一致。",
                    "IDENTITY",
                )
            endpoint = matching[0]
            observed_endpoint_url = endpoint.EndpointUrl
            application_uri = endpoint.Server.ApplicationUri
            if application_uri != OPCUA_SANDBOX_APPLICATION_URI:
                raise OpcUaGatewayError(
                    "OPCUA_APPLICATION_URI_MISMATCH",
                    "observed OPC-UA ApplicationURI 不匹配。",
                    "IDENTITY",
                )
            namespace_array = self._runner.run(self._client.get_namespace_array())
            namespace_uri = namespace_array[self._namespace_index]
            if namespace_uri != self._config.namespace_uri:
                raise OpcUaGatewayError(
                    "OPCUA_NAMESPACE_URI_MISMATCH",
                    "observed OPC-UA namespace URI 不匹配。",
                    "IDENTITY",
                )
            custom_application_uri = str(
                self._read("TuneWiseSandbox.Device.ApplicationURI")
            )
            server_version = str(self._read("TuneWiseSandbox.Device.ServerVersion"))
            mapping_version = str(
                self._read("TuneWiseSandbox.Device.NodeMappingVersion")
            )
            safety_mapping_version = str(
                self._read("TuneWiseSandbox.Device.ParameterSafetyMappingVersion")
            )
            sandbox_mode = str(self._read("TuneWiseSandbox.Device.SandboxMode"))
            security_profile = str(
                self._read("TuneWiseSandbox.Device.SecurityProfile")
            )
            atomic_method_version = str(
                self._read("TuneWiseSandbox.Device.AtomicMethodVersion")
            )
        except OpcUaGatewayError as error:
            if error.code == "OPCUA_COMMUNICATION_FAILURE":
                raise OpcUaGatewayError(
                    "OPCUA_METADATA_MISSING",
                    "OPC-UA server 缺少冻结 identity/mapping metadata。",
                    "IDENTITY",
                ) from error
            raise
        except Exception as error:
            raise OpcUaGatewayError(
                "OPCUA_METADATA_MISSING",
                "OPC-UA server 缺少冻结 identity/mapping metadata。",
                "IDENTITY",
            ) from error

        if custom_application_uri != application_uri:
            raise OpcUaGatewayError(
                "OPCUA_APPLICATION_URI_MISMATCH",
                "server application metadata 与 observed ApplicationURI 不一致。",
                "IDENTITY",
            )
        if server_version != OPCUA_SANDBOX_SERVER_VERSION:
            raise OpcUaGatewayError(
                "OPCUA_SERVER_VERSION_MISMATCH",
                "observed ServerVersion 不匹配。",
                "IDENTITY",
            )
        if mapping_version != self._config.node_mapping_version:
            raise OpcUaGatewayError(
                "OPCUA_MAPPING_VERSION_MISMATCH",
                "observed NodeMappingVersion 不匹配。",
                "IDENTITY",
            )
        if safety_mapping_version != OPCUA_PARAMETER_SAFETY_MAPPING_VERSION:
            raise OpcUaGatewayError(
                "OPCUA_SAFETY_MAPPING_VERSION_MISMATCH",
                "observed ParameterSafety/Mapping version 不匹配。",
                "IDENTITY",
            )
        if (
            sandbox_mode != OPCUA_SANDBOX_MODE
            or security_profile != OPCUA_SANDBOX_SECURITY_PROFILE
        ):
            raise OpcUaGatewayError(
                "OPCUA_SANDBOX_PROFILE_MISMATCH",
                "observed server 不是冻结的本地匿名 sandbox profile。",
                "IDENTITY",
            )

        parameters: list[OpcUaParameterMetadata] = []
        for name, mapping in sorted(NODE_MAPPINGS.items()):
            node = self._node(mapping.identifier)
            try:
                browse_name = self._runner.run(node.read_browse_name()).Name
                data_type = self._runner.run(
                    node.read_data_type_as_variant_type()
                ).name
                unit = str(self._read(f"{mapping.identifier}.Unit"))
                declared_data_type = str(
                    self._read(f"{mapping.identifier}.DataTypeName")
                )
                access = self._runner.run(node.get_access_level())
                user_access = self._runner.run(node.get_user_access_level())
            except Exception as error:
                raise OpcUaGatewayError(
                    "OPCUA_PARAMETER_METADATA_MISSING",
                    f"参数 {name} 缺少 BrowseName/DataType/Unit/access metadata。",
                    "IDENTITY",
                ) from error
            if browse_name != name:
                raise OpcUaGatewayError(
                    "OPCUA_BROWSE_NAME_MISMATCH",
                    f"参数 {name} 的 BrowseName 不匹配。",
                    "IDENTITY",
                )
            observed_node_id = (
                f"nsu={namespace_uri};s={node.nodeid.Identifier}"
            )
            if observed_node_id != mapping.expanded_node_id:
                raise OpcUaGatewayError(
                    "OPCUA_NODE_MAPPING_MISMATCH",
                    f"参数 {name} 的 observed NodeId 不匹配。",
                    "IDENTITY",
                )
            if data_type != mapping.data_type or declared_data_type != mapping.data_type:
                raise OpcUaGatewayError(
                    "OPCUA_DATATYPE_MISMATCH",
                    f"参数 {name} 的 DataType 不匹配。",
                    "IDENTITY",
                )
            if unit != mapping.unit:
                raise OpcUaGatewayError(
                    "OPCUA_UNIT_MISMATCH",
                    f"参数 {name} 的 Engineering Unit 不匹配。",
                    "IDENTITY",
                )
            readable = (
                ua.AccessLevel.CurrentRead in access
                and ua.AccessLevel.CurrentRead in user_access
            )
            writable = (
                ua.AccessLevel.CurrentWrite in access
                or ua.AccessLevel.CurrentWrite in user_access
            )
            if not readable or writable:
                raise OpcUaGatewayError(
                    "OPCUA_NODE_ACCESS_MISMATCH",
                    f"参数 {name} 节点必须允许客户端读取并永久禁止客户端写入。",
                    "IDENTITY",
                )
            parameters.append(
                OpcUaParameterMetadata(
                    parameter_name=name,
                    node_id=observed_node_id,
                    browse_name=browse_name,
                    data_type=data_type,
                    engineering_unit=unit,
                    readable=readable,
                    writable=writable,
                )
            )
        atomic_method_identity: dict[str, object] | None = None
        try:
            method = self._node(
                "TuneWiseSandbox.Device.ApplyConfirmedParameterChange"
            )
            method_browse_name = self._runner.run(method.read_browse_name()).Name
            method_node_id = f"nsu={namespace_uri};s={method.nodeid.Identifier}"
            executable = bool(
                self._runner.run(
                    method.read_attribute(ua.AttributeIds.Executable)
                ).Value.Value
            )
            user_executable = bool(
                self._runner.run(
                    method.read_attribute(ua.AttributeIds.UserExecutable)
                ).Value.Value
            )
            query = self._node("TuneWiseSandbox.Device.QueryExecutionResult")
            query_browse_name = self._runner.run(query.read_browse_name()).Name
            method_identity_valid = (
                method_node_id
                == f"nsu={namespace_uri};s=TuneWiseSandbox.Device.ApplyConfirmedParameterChange"
                and method_browse_name == "ApplyConfirmedParameterChange"
                and query_browse_name == "QueryExecutionResult"
                and executable
                and user_executable
            )
            self._atomic_supported = (
                method_identity_valid
                and atomic_method_version == OPCUA_ATOMIC_METHOD_VERSION
            )
            atomic_method_identity = {
                "node_id": method_node_id,
                "browse_name": method_browse_name,
                "executable": executable,
                "user_executable": user_executable,
            }
        except Exception:
            self._atomic_supported = False

        content = {
            "endpoint_url": observed_endpoint_url,
            "application_uri": application_uri,
            "namespace_uri": namespace_uri,
            "server_version": server_version,
            "node_mapping_version": mapping_version,
            "parameter_safety_mapping_version": safety_mapping_version,
            "sandbox_mode": sandbox_mode,
            "security_profile": security_profile,
            "certificate_fingerprint": None,
            "parameters": [
                {
                    "parameter_name": item.parameter_name,
                    "node_id": item.node_id,
                    "browse_name": item.browse_name,
                    "data_type": item.data_type,
                    "engineering_unit": item.engineering_unit,
                    "readable": item.readable,
                    "writable": item.writable,
                }
                for item in parameters
            ],
            "atomic_method_version": atomic_method_version,
            "atomic_method": atomic_method_identity,
        }
        return OpcUaObservedIdentity(
            endpoint_url=observed_endpoint_url,
            application_uri=application_uri,
            namespace_uri=namespace_uri,
            server_version=server_version,
            node_mapping_version=mapping_version,
            parameter_safety_mapping_version=safety_mapping_version,
            sandbox_mode=sandbox_mode,
            security_profile=security_profile,
            certificate_fingerprint=None,
            parameters=tuple(parameters),
            atomic_method_version=atomic_method_version,
            identity_hash=_identity_hash(content),
        )

    @staticmethod
    def _execution_result(payload: object) -> AtomicExecutionResult | None:
        if payload in {None, "", "NOT_FOUND"}:
            return None
        try:
            data = json.loads(str(payload))
            return AtomicExecutionResult(
                idempotency_key=str(data["idempotency_key"]),
                parameter_name=str(data["parameter_name"]),
                expected_before=normalize_device_value(data["expected_before"]),
                requested_after=normalize_device_value(data["requested_after"]),
                actual_before=(
                    None
                    if data.get("actual_before") is None
                    else normalize_device_value(data["actual_before"])
                ),
                actual_after=(
                    None
                    if data.get("actual_after") is None
                    else normalize_device_value(data["actual_after"])
                ),
                result=str(data["result"]),
                executed_at=(
                    None if data.get("executed_at") is None else str(data["executed_at"])
                ),
                physical_write_count=int(data.get("physical_write_count", 0)),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OpcUaGatewayError(
                "OPCUA_ATOMIC_RESULT_INVALID",
                "OPC-UA atomic method 返回了无效执行记录。",
                "COMMUNICATION",
            ) from error

    def apply_confirmed_parameter_change(
        self,
        *,
        idempotency_key: str,
        parameter_name: str,
        expected_before: str,
        requested_after: str,
    ) -> AtomicExecutionResult:
        if not self._atomic_supported:
            raise OpcUaGatewayError(
                "ATOMIC_EXECUTION_UNSUPPORTED",
                "server 不支持设备侧原子条件执行 method。",
                "CAPABILITY",
            )
        self._fault_mode()
        request = json.dumps(
            {
                "method_version": OPCUA_ATOMIC_METHOD_VERSION,
                "idempotency_key": idempotency_key,
                "parameter_name": parameter_name,
                "expected_before": normalize_device_value(expected_before),
                "requested_after": normalize_device_value(requested_after),
                "node_mapping_version": self._config.node_mapping_version,
                "observed_identity_hash": self.observed_identity.identity_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            device = self._node("TuneWiseSandbox.Device")
            method = self._node(
                "TuneWiseSandbox.Device.ApplyConfirmedParameterChange"
            )
            payload = self._runner.run(device.call_method(method, request))
            result = self._execution_result(payload)
            if result is None:
                raise ValueError("missing method result")
            return result
        except OpcUaGatewayError:
            raise
        except (TimeoutError, BadTimeout) as error:
            raise OpcUaGatewayError(
                "OPCUA_UNKNOWN_OUTCOME",
                "atomic method 调用超时，设备执行结果未知。",
                "COMMUNICATION",
            ) from error
        except Exception as error:
            raise OpcUaGatewayError(
                "OPCUA_UNKNOWN_OUTCOME",
                "atomic method 通信中断，设备执行结果未知。",
                "COMMUNICATION",
            ) from error

    def query_execution_result(
        self,
        idempotency_key: str,
    ) -> AtomicExecutionResult | None:
        if not self._atomic_supported:
            raise OpcUaGatewayError(
                "ATOMIC_EXECUTION_UNSUPPORTED",
                "server 不支持设备侧幂等执行结果查询。",
                "CAPABILITY",
            )
        try:
            device = self._node("TuneWiseSandbox.Device")
            method = self._node("TuneWiseSandbox.Device.QueryExecutionResult")
            payload = self._runner.run(device.call_method(method, idempotency_key))
            return self._execution_result(payload)
        except OpcUaGatewayError:
            raise
        except Exception as error:
            raise OpcUaGatewayError(
                "OPCUA_RECONCILIATION_UNAVAILABLE",
                "无法只读查询设备侧幂等执行结果。",
                "RECONCILIATION",
            ) from error


class SandboxOpcUaGateway:
    version = OPCUA_GATEWAY_VERSION

    def __init__(self, config: DeviceExecutionConfig) -> None:
        config.validate()
        self._config = config

    @contextmanager
    def session(self) -> Iterator[OpcUaSession]:
        client = Client(
            self._config.endpoint,
            timeout=self._config.request_timeout_seconds,
        )
        runner = asyncio.Runner()
        try:
            runner.run(client.connect())
            namespace_array = runner.run(client.get_namespace_array())
            if self._config.namespace_uri not in namespace_array:
                raise OpcUaGatewayError(
                    "OPCUA_NAMESPACE_URI_MISMATCH",
                    "observed OPC-UA namespace URI 不匹配。",
                    "IDENTITY",
                )
            namespace_index = namespace_array.index(self._config.namespace_uri)
            yield _AsyncuaSession(runner, client, namespace_index, self._config)
        except OpcUaGatewayError:
            raise
        except (TimeoutError, OSError, ConnectionError) as error:
            raise OpcUaGatewayError(
                "OPCUA_ENDPOINT_UNAVAILABLE",
                "本地 OPC-UA sandbox endpoint 不可用。",
                "COMMUNICATION",
            ) from error
        except Exception as error:
            raise OpcUaGatewayError(
                "OPCUA_COMMUNICATION_FAILURE",
                "无法建立本地 OPC-UA sandbox 会话。",
                "COMMUNICATION",
            ) from error
        finally:
            try:
                runner.run(client.disconnect())
            except Exception:
                pass
            runner.close()
