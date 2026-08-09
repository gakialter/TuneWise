from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from .opcua_gateway import (
    NODE_MAPPINGS,
    OPCUA_SANDBOX_MODE,
    DeviceExecutionConfig,
    AtomicExecutionResult,
    OpcUaGateway,
    OpcUaGatewayError,
    OpcUaNodeMapping,
    OpcUaObservedIdentity,
    SandboxOpcUaGateway,
    normalize_device_value,
)
from .parameter_planning import TICK_SIZE


DEVICE_EXECUTION_RECEIPT_VERSION = "tw-device-execution-receipt-v1"
DEVICE_EXECUTION_CANONICALIZER_VERSION = "tw-device-execution-canonicalizer-v1"
DEVICE_EXECUTION_IDEMPOTENCY_VERSION = "tw-device-execution-idempotency-v2"
DEVICE_EXECUTION_STATE_MACHINE_VERSION = "tw-device-execution-state-machine-v1"
DEVICE_EXECUTION_DISCLAIMER = (
    "当前 OPC-UA 通道连接的是本地模拟设备，不代表已经完成真实设备接入或真实设备安全验证。"
)
ALLOWED_PARAMETER_FAMILIES = frozenset({"PITCH_ROLL", "XY_OFFSET", "Z_OFFSET"})


class DeviceExecutionStatus(StrEnum):
    REJECTED = "REJECTED"
    FAILED_DEFINITE = "FAILED_DEFINITE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    SUCCEEDED = "SUCCEEDED"


class DeviceExecutionState(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    WRITE_STARTED = "WRITE_STARTED"
    REJECTED = "REJECTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED_DEFINITE = "FAILED_DEFINITE"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class DeviceQualificationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        replay_result_id: str | None = None,
        replay_result_hash: str | None = None,
        safety_validator_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.replay_result_id = replay_result_id
        self.replay_result_hash = replay_result_hash
        self.safety_validator_version = safety_validator_version


class DeviceExecutionConflictError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DeviceExecutionQualification:
    task_id: str
    confirmed_plan_id: str
    confirmed_plan_hash: str
    replay_result_id: str
    replay_result_hash: str
    replay_status: str
    baseline_reproduction_status: str
    parameter_family: str
    current_values: Mapping[str, str]
    proposed_values: Mapping[str, str]
    delta_ticks: Mapping[str, int]
    changed_parameters: tuple[str, ...]
    safety_validator_version: str
    safety_validation_result: str
    actor_id: str
    actor_role: str
    display_name: str
    confirmed_at: str


@dataclass(frozen=True, slots=True)
class DeviceExecutionEligibility:
    eligible: bool
    code: str
    message: str
    execution_mode: str
    gateway_version: str
    node_mapping_version: str
    endpoint_local_id: str
    endpoint_fingerprint: str
    observed_server_identity_hash: str | None
    observed_application_uri: str | None
    security_profile: str | None
    device_connected: bool
    device_status: str
    safety_gate_status: str
    replay_status: str | None
    parameter_name: str | None
    node_id: str | None
    expected_before_value: str | None
    actual_before_value: str | None
    requested_after_value: str | None
    tick_delta: int | None
    disclaimer: str = DEVICE_EXECUTION_DISCLAIMER


@dataclass(frozen=True, slots=True)
class DeviceExecutionReceipt:
    receipt_version: str
    receipt_canonicalizer_version: str
    state_machine_version: str
    device_execution_id: str
    task_id: str
    confirmed_plan_id: str
    confirmed_plan_hash: str
    replay_result_id: str | None
    replay_result_hash: str | None
    execution_mode: str
    gateway_version: str
    namespace_uri: str
    node_mapping_version: str
    endpoint_local_id: str
    endpoint_fingerprint: str
    observed_server_identity_hash: str | None
    observed_application_uri: str | None
    security_profile: str | None
    certificate_fingerprint: str | None
    parameter_name: str | None
    node_id: str | None
    expected_before_value: str | None
    actual_before_value: str | None
    requested_after_value: str | None
    actual_after_value: str | None
    tick_delta: int | None
    safety_validator_version: str | None
    validation_result: str
    execution_status: str
    failure_stage: str | None
    failure_code: str | None
    message: str
    device_status: str | None
    actor_id: str
    actor_role: str
    display_name: str
    started_at: str
    completed_at: str
    idempotency_key: str
    attempt_count: int
    internal_retry_count: int
    write_attempt_count: int
    state_trace: tuple[str, ...]
    disclaimer: str
    receipt_hash: str


@dataclass(frozen=True, slots=True)
class DeviceExecutionOutcome:
    receipt: DeviceExecutionReceipt
    created: bool
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class DeviceExecutionClaim:
    status: str
    owner_instance_id: str
    started_at: str
    receipt: DeviceExecutionReceipt | None = None
    device_execution_id: str = ""
    task_id: str = ""
    idempotency_key: str = ""
    server_identity_hash: str = "NOT_OBSERVED"
    recovery_payload: Mapping[str, object] | None = None


class DeviceExecutionRepository(Protocol):
    def claim_device_execution(
        self,
        *,
        device_execution_id: str,
        task_id: str,
        idempotency_key: str,
        owner_instance_id: str,
        started_at: str,
        server_identity_hash: str,
        server_identity_json: str | None,
        node_mapping_version: str,
        expected_before_value: str | None,
        requested_after_value: str | None,
        confirmed_plan_hash: str | None,
        replay_result_hash: str | None,
        parameter_name: str | None,
        node_id: str | None,
        recovery_payload_json: str | None,
    ) -> DeviceExecutionClaim: ...

    def list_reconcilable_device_executions(self) -> tuple[DeviceExecutionClaim, ...]: ...

    def mark_device_execution_write_started(
        self,
        *,
        idempotency_key: str,
        owner_instance_id: str,
        started_at: str,
    ) -> None: ...

    def mark_device_execution_unknown(
        self,
        *,
        idempotency_key: str,
        failure_code: str,
    ) -> None: ...

    def mark_device_execution_reconciliation_required(
        self,
        *,
        idempotency_key: str,
        failure_code: str,
    ) -> None: ...

    def finalize_device_execution(
        self,
        receipt: DeviceExecutionReceipt,
        *,
        owner_instance_id: str,
    ) -> DeviceExecutionReceipt: ...

    def get_device_execution_receipt(
        self,
        device_execution_id: str,
    ) -> DeviceExecutionReceipt | None: ...


class DeviceExecutionClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DeviceExecutionReceiptCanonicalizer:
    version = DEVICE_EXECUTION_CANONICALIZER_VERSION

    def canonicalize(self, payload: Mapping[str, object]) -> bytes:
        stable = {
            key: value
            for key, value in payload.items()
            if key != "receipt_hash"
        }
        envelope = {
            "receipt_canonicalizer_version": self.version,
            "business_content": stable,
        }
        return json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def sha256(self, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(self.canonicalize(payload)).hexdigest()


def device_execution_receipt_payload(
    receipt: DeviceExecutionReceipt,
) -> dict[str, object]:
    return asdict(receipt)


def deserialize_device_execution_receipt(
    payload: Mapping[str, object],
) -> DeviceExecutionReceipt:
    try:
        receipt = DeviceExecutionReceipt(
            **{
                **payload,
                "state_trace": tuple(payload["state_trace"]),
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DeviceExecutionConflictError(
            "DEVICE_EXECUTION_RECEIPT_INVALID",
            "已保存设备执行凭证结构无效。",
        ) from error
    expected_hash = DeviceExecutionReceiptCanonicalizer().sha256(
        device_execution_receipt_payload(receipt)
    )
    expected_id = f"tw-device-execution-{receipt.idempotency_key[:16]}"
    if (
        receipt.receipt_version != DEVICE_EXECUTION_RECEIPT_VERSION
        or receipt.receipt_canonicalizer_version
        != DEVICE_EXECUTION_CANONICALIZER_VERSION
        or receipt.state_machine_version != DEVICE_EXECUTION_STATE_MACHINE_VERSION
        or receipt.execution_status
        not in {status.value for status in DeviceExecutionStatus}
        or receipt.attempt_count != 1
        or receipt.internal_retry_count != 0
        or receipt.device_execution_id != expected_id
        or receipt.receipt_hash != expected_hash
        or receipt.disclaimer != DEVICE_EXECUTION_DISCLAIMER
    ):
        raise DeviceExecutionConflictError(
            "DEVICE_EXECUTION_RECEIPT_HASH_MISMATCH",
            "已保存设备执行凭证内容哈希不匹配。",
        )
    return receipt


def device_execution_idempotency_key(
    *,
    task_id: str,
    confirmed_plan_id: str,
    confirmed_plan_hash: str,
    replay_result_hash: str | None,
    execution_mode: str,
    gateway_version: str,
    namespace_uri: str,
    node_mapping_version: str,
    endpoint_fingerprint: str,
    observed_server_identity_hash: str = "NOT_OBSERVED",
    request_fingerprint: str | None = None,
) -> str:
    payload = {
        "idempotency_version": DEVICE_EXECUTION_IDEMPOTENCY_VERSION,
        "task_id": task_id,
        "confirmed_plan_id": confirmed_plan_id,
        "confirmed_plan_hash": confirmed_plan_hash,
        "replay_result_hash": replay_result_hash or "UNAVAILABLE",
        "execution_mode": execution_mode,
        "gateway_version": gateway_version,
        "namespace_uri": namespace_uri,
        "node_mapping_version": node_mapping_version,
        "endpoint_fingerprint": endpoint_fingerprint,
        "observed_server_identity_hash": observed_server_identity_hash,
        "request_fingerprint": request_fingerprint,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class DeviceExecutionService:
    def __init__(
        self,
        *,
        config: DeviceExecutionConfig,
        repository: DeviceExecutionRepository,
        qualification_provider: Callable[
            [str, str, str], DeviceExecutionQualification
        ],
        gateway: OpcUaGateway | None = None,
        clock: DeviceExecutionClock | None = None,
        node_mappings: Mapping[str, OpcUaNodeMapping] | None = None,
        instance_id: str | None = None,
    ) -> None:
        config.validate()
        self._config = config
        self._repository = repository
        self._qualification_provider = qualification_provider
        if gateway is not None and gateway.version != config.gateway_version:
            raise ValueError("注入的 OPC-UA gateway version 与配置绑定不一致。")
        self._gateway = gateway or SandboxOpcUaGateway(config)
        self._clock = clock or DeviceExecutionClock()
        self._node_mappings = dict(NODE_MAPPINGS if node_mappings is None else node_mappings)
        self._instance_id = instance_id or f"tw-device-executor-{uuid4().hex}"

    def eligibility(
        self,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
    ) -> DeviceExecutionEligibility:
        if not self._config.enabled or self._config.mode != OPCUA_SANDBOX_MODE:
            return self._eligibility(
                False,
                "DEVICE_EXECUTION_DISABLED",
                "OPC-UA sandbox 设备执行未显式开启。",
            )
        try:
            qualification = self._qualification_provider(
                task_id,
                confirmed_plan_id,
                confirmed_plan_hash,
            )
            parameter_name, mapping = self._validate_qualification(qualification)
            with self._gateway.session() as session:
                identity = session.observed_identity
                health = session.read_health()
                actual_before = session.read_parameter(parameter_name)
            expected_before = normalize_device_value(
                qualification.current_values[parameter_name]
            )
            if not health.connected:
                return self._eligibility(
                    False,
                    "DEVICE_NOT_HEALTHY",
                    "本地 OPC-UA sandbox 当前未处于健康状态。",
                    qualification=qualification,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    actual_before=actual_before,
                    device_status=health.device_status,
                    identity=identity,
                )
            if actual_before != expected_before:
                return self._eligibility(
                    False,
                    "DEVICE_VALUE_CHANGED",
                    "设备当前值已变化，必须重新确认方案后再执行。",
                    qualification=qualification,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    actual_before=actual_before,
                    device_status=health.device_status,
                    identity=identity,
                )
            return self._eligibility(
                True,
                "ELIGIBLE",
                "回放、安全、节点白名单和设备当前值门禁均已通过。",
                qualification=qualification,
                parameter_name=parameter_name,
                mapping=mapping,
                actual_before=actual_before,
                device_status=health.device_status,
                identity=identity,
            )
        except DeviceQualificationError as error:
            return self._eligibility(False, error.code, error.message)
        except DeviceExecutionConflictError as error:
            return self._eligibility(False, error.code, error.message)
        except OpcUaGatewayError as error:
            return self._eligibility(False, error.code, error.message)

    def execute(
        self,
        *,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
        execution_mode: str,
        sandbox_execution_acknowledged: bool,
    ) -> DeviceExecutionOutcome:
        started_at = self._clock.now()
        if not self._config.enabled:
            return self._reject_without_qualification(
                task_id=task_id,
                confirmed_plan_id=confirmed_plan_id,
                confirmed_plan_hash=confirmed_plan_hash,
                execution_mode=execution_mode,
                code="DEVICE_EXECUTION_DISABLED",
                message="OPC-UA sandbox 设备执行未显式开启。",
                started_at=started_at,
            )
        if execution_mode != OPCUA_SANDBOX_MODE or self._config.mode != OPCUA_SANDBOX_MODE:
            return self._reject_without_qualification(
                task_id=task_id,
                confirmed_plan_id=confirmed_plan_id,
                confirmed_plan_hash=confirmed_plan_hash,
                execution_mode=execution_mode,
                code="EXECUTION_MODE_NOT_ALLOWED",
                message="当前运行模式不是明确启用的 OPCUA_SANDBOX。",
                started_at=started_at,
            )
        if sandbox_execution_acknowledged is not True:
            return self._reject_without_qualification(
                task_id=task_id,
                confirmed_plan_id=confirmed_plan_id,
                confirmed_plan_hash=confirmed_plan_hash,
                execution_mode=execution_mode,
                code="DEVICE_EXECUTION_ACKNOWLEDGEMENT_REQUIRED",
                message="设备执行需要独立于方案确认的 sandbox 下发确认。",
                started_at=started_at,
            )
        try:
            qualification = self._qualification_provider(
                task_id,
                confirmed_plan_id,
                confirmed_plan_hash,
            )
            parameter_name, mapping = self._validate_qualification(qualification)
        except DeviceQualificationError as error:
            return self._reject_without_qualification(
                task_id=task_id,
                confirmed_plan_id=confirmed_plan_id,
                confirmed_plan_hash=confirmed_plan_hash,
                execution_mode=execution_mode,
                code=error.code,
                message=error.message,
                started_at=started_at,
                replay_result_id=error.replay_result_id,
                replay_result_hash=error.replay_result_hash,
                safety_validator_version=error.safety_validator_version,
            )
        except DeviceExecutionConflictError as error:
            return self._reject_without_qualification(
                task_id=task_id,
                confirmed_plan_id=confirmed_plan_id,
                confirmed_plan_hash=confirmed_plan_hash,
                execution_mode=execution_mode,
                code=error.code,
                message=error.message,
                started_at=started_at,
            )

        expected_before = normalize_device_value(
            qualification.current_values[parameter_name]
        )
        requested_after = normalize_device_value(
            qualification.proposed_values[parameter_name]
        )
        identity: OpcUaObservedIdentity | None = None
        idempotency_key: str | None = None
        claim: DeviceExecutionClaim | None = None
        write_started = False
        device_status: str | None = None
        try:
            with self._gateway.session() as session:
                identity = session.observed_identity
                health = session.read_health()
                device_status = health.device_status
                idempotency_key = self._idempotency_key(
                    task_id=task_id,
                    confirmed_plan_id=qualification.confirmed_plan_id,
                    confirmed_plan_hash=qualification.confirmed_plan_hash,
                    replay_result_hash=qualification.replay_result_hash,
                    execution_mode=execution_mode,
                    observed_server_identity_hash=identity.identity_hash,
                )
                claim = self._claim(
                    task_id=task_id,
                    idempotency_key=idempotency_key,
                    started_at=started_at,
                    qualification=qualification,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    expected_before=expected_before,
                    requested_after=requested_after,
                    identity=identity,
                    execution_mode=execution_mode,
                )
                if claim.status == "FINALIZED" and claim.receipt is not None:
                    return DeviceExecutionOutcome(claim.receipt, False, True)
                if claim.status in {
                    "WRITE_STARTED",
                    "UNKNOWN_OUTCOME",
                    "RECONCILIATION_REQUIRED",
                }:
                    record = session.query_execution_result(idempotency_key)
                    return self._finalize_atomic_result(
                        record=record,
                        qualification=qualification,
                        parameter_name=parameter_name,
                        mapping=mapping,
                        expected_before=expected_before,
                        requested_after=requested_after,
                        identity=identity,
                        idempotency_key=idempotency_key,
                        started_at=claim.started_at,
                        device_status=device_status,
                        reconciling=True,
                    )
                if claim.status == "VALIDATING" and claim.owner_instance_id != self._instance_id:
                    raise DeviceExecutionConflictError(
                        "DEVICE_EXECUTION_IN_PROGRESS",
                        "相同幂等设备执行请求正在验证。",
                    )
                if not health.connected:
                    return self._finalize_atomic_result(
                        record=None,
                        qualification=qualification,
                        parameter_name=parameter_name,
                        mapping=mapping,
                        expected_before=expected_before,
                        requested_after=requested_after,
                        identity=identity,
                        idempotency_key=idempotency_key,
                        started_at=started_at,
                        device_status=device_status,
                        rejection=("DEVICE_NOT_HEALTHY", "本地 OPC-UA sandbox 当前未处于健康状态。"),
                    )
                self._repository.mark_device_execution_write_started(
                    idempotency_key=idempotency_key,
                    owner_instance_id=self._instance_id,
                    started_at=started_at,
                )
                write_started = True
                record = session.apply_confirmed_parameter_change(
                    idempotency_key=idempotency_key,
                    parameter_name=parameter_name,
                    expected_before=expected_before,
                    requested_after=requested_after,
                )
                return self._finalize_atomic_result(
                    record=record,
                    qualification=qualification,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    expected_before=expected_before,
                    requested_after=requested_after,
                    identity=identity,
                    idempotency_key=idempotency_key,
                    started_at=started_at,
                    device_status=device_status,
                )
        except OpcUaGatewayError as error:
            unknown_codes = {
                "OPCUA_TIMEOUT",
                "OPCUA_UNKNOWN_OUTCOME",
                "OPCUA_COMMUNICATION_FAILURE",
                "OPCUA_ENDPOINT_UNAVAILABLE",
            }
            if (
                write_started
                and idempotency_key is not None
                and error.code in unknown_codes
            ):
                self._repository.mark_device_execution_unknown(
                    idempotency_key=idempotency_key,
                    failure_code=error.code,
                )
                receipt = self._receipt(
                    task_id=task_id,
                    confirmed_plan_id=qualification.confirmed_plan_id,
                    confirmed_plan_hash=qualification.confirmed_plan_hash,
                    replay_result_id=qualification.replay_result_id,
                    replay_result_hash=qualification.replay_result_hash,
                    execution_mode=execution_mode,
                    idempotency_key=idempotency_key,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    expected_before=expected_before,
                    requested_after=requested_after,
                    tick_delta=qualification.delta_ticks[parameter_name],
                    safety_validator_version=qualification.safety_validator_version,
                    validation_result="PASSED",
                    execution_status=DeviceExecutionStatus.UNKNOWN_OUTCOME,
                    failure_stage="COMMUNICATION",
                    failure_code=error.code,
                    message=(
                        "设备侧 atomic method 结果未知；禁止盲目重写，必须按幂等键 reconciliation。"
                    ),
                    actor=(qualification.actor_id, qualification.actor_role, qualification.display_name),
                    started_at=started_at,
                    write_attempt_count=1,
                    state_trace=(DeviceExecutionState.CREATED, DeviceExecutionState.VALIDATING, DeviceExecutionState.WRITE_STARTED, DeviceExecutionState.UNKNOWN_OUTCOME),
                    identity=identity,
                    device_status=device_status,
                )
                return self._finalize(receipt)
            if write_started and idempotency_key is not None:
                execution_status = (
                    DeviceExecutionStatus.REJECTED
                    if error.code == "ATOMIC_EXECUTION_UNSUPPORTED"
                    else DeviceExecutionStatus.FAILED_DEFINITE
                )
                final_state = (
                    DeviceExecutionState.REJECTED
                    if execution_status is DeviceExecutionStatus.REJECTED
                    else DeviceExecutionState.FAILED_DEFINITE
                )
                receipt = self._receipt(
                    task_id=task_id,
                    confirmed_plan_id=qualification.confirmed_plan_id,
                    confirmed_plan_hash=qualification.confirmed_plan_hash,
                    replay_result_id=qualification.replay_result_id,
                    replay_result_hash=qualification.replay_result_hash,
                    execution_mode=execution_mode,
                    idempotency_key=idempotency_key,
                    parameter_name=parameter_name,
                    mapping=mapping,
                    expected_before=expected_before,
                    requested_after=requested_after,
                    tick_delta=qualification.delta_ticks[parameter_name],
                    safety_validator_version=qualification.safety_validator_version,
                    validation_result="PASSED",
                    execution_status=execution_status,
                    failure_stage=error.stage,
                    failure_code=error.code,
                    message=error.message,
                    actor=(qualification.actor_id, qualification.actor_role, qualification.display_name),
                    started_at=started_at,
                    write_attempt_count=0,
                    state_trace=(DeviceExecutionState.CREATED, DeviceExecutionState.VALIDATING, DeviceExecutionState.WRITE_STARTED, final_state),
                    identity=identity,
                    device_status=device_status,
                )
                return self._finalize(receipt)
            return self._reject_gateway_failure(
                error,
                qualification=qualification,
                parameter_name=parameter_name,
                mapping=mapping,
                expected_before=expected_before,
                requested_after=requested_after,
                identity=identity,
                started_at=started_at,
                device_status=device_status,
            )

    def get_receipt(self, device_execution_id: str) -> DeviceExecutionReceipt | None:
        return self._repository.get_device_execution_receipt(device_execution_id)

    def reconcile_pending(self) -> tuple[DeviceExecutionOutcome, ...]:
        """Resolve incomplete writes from device-side evidence without issuing a write."""
        outcomes: list[DeviceExecutionOutcome] = []
        for claim in self._repository.list_reconcilable_device_executions():
            try:
                payload = claim.recovery_payload
                if payload is None:
                    raise ValueError("missing recovery payload")
                qualification_payload = dict(payload["qualification"])
                qualification_payload["changed_parameters"] = tuple(
                    qualification_payload["changed_parameters"]
                )
                qualification = DeviceExecutionQualification(**qualification_payload)
                parameter_name = str(payload["parameter_name"])
                mapping = self._node_mappings[parameter_name]
                if (
                    str(payload["node_id"]) != mapping.expanded_node_id
                    or str(payload["node_mapping_version"])
                    != self._config.node_mapping_version
                ):
                    raise ValueError("mapping snapshot mismatch")
                expected_before = str(payload["expected_before"])
                requested_after = str(payload["requested_after"])
                execution_mode = str(payload["execution_mode"])
                if execution_mode != OPCUA_SANDBOX_MODE:
                    raise ValueError("execution mode mismatch")
                with self._gateway.session() as session:
                    identity = session.observed_identity
                    if identity.identity_hash != claim.server_identity_hash:
                        raise ValueError("observed server identity changed")
                    health = session.read_health()
                    record = session.query_execution_result(claim.idempotency_key)
                    outcomes.append(
                        self._finalize_atomic_result(
                            record=record,
                            qualification=qualification,
                            parameter_name=parameter_name,
                            mapping=mapping,
                            expected_before=expected_before,
                            requested_after=requested_after,
                            identity=identity,
                            idempotency_key=claim.idempotency_key,
                            started_at=claim.started_at,
                            device_status=health.device_status,
                            reconciling=True,
                        )
                    )
            except (KeyError, TypeError, ValueError, OpcUaGatewayError):
                self._repository.mark_device_execution_reconciliation_required(
                    idempotency_key=claim.idempotency_key,
                    failure_code="DEVICE_EXECUTION_RECONCILIATION_UNRESOLVED",
                )
        return tuple(outcomes)

    def _finalize_atomic_result(
        self,
        *,
        record: AtomicExecutionResult | None,
        qualification: DeviceExecutionQualification,
        parameter_name: str,
        mapping: OpcUaNodeMapping,
        expected_before: str,
        requested_after: str,
        identity: OpcUaObservedIdentity,
        idempotency_key: str,
        started_at: str,
        device_status: str | None,
        reconciling: bool = False,
        rejection: tuple[str, str] | None = None,
    ) -> DeviceExecutionOutcome:
        if rejection is not None:
            status = DeviceExecutionStatus.REJECTED
            failure_code, message = rejection
            failure_stage = "VALIDATION"
            actual_before = None
            actual_after = None
            writes = 0
            final_state = DeviceExecutionState.REJECTED
        elif record is None:
            status = DeviceExecutionStatus.RECONCILIATION_REQUIRED
            failure_code = "DEVICE_EXECUTION_EVIDENCE_NOT_FOUND"
            message = (
                "设备侧没有该幂等键的执行证据；即使当前值等于目标值也不能伪造成功。"
            )
            failure_stage = "RECONCILIATION"
            actual_before = None
            actual_after = None
            writes = 0
            final_state = DeviceExecutionState.RECONCILIATION_REQUIRED
        else:
            actual_before = record.actual_before
            actual_after = record.actual_after
            writes = record.physical_write_count
            if (
                record.idempotency_key != idempotency_key
                or record.parameter_name != parameter_name
                or record.expected_before != expected_before
                or record.requested_after != requested_after
            ):
                status = DeviceExecutionStatus.FAILED_DEFINITE
                failure_code = "DEVICE_EXECUTION_RECORD_BINDING_MISMATCH"
                message = "设备侧幂等执行记录与已确认请求绑定不一致。"
                failure_stage = "RECONCILIATION" if reconciling else "WRITE"
                final_state = DeviceExecutionState.FAILED_DEFINITE
            elif record.result == "APPLIED" and actual_after == requested_after:
                status = DeviceExecutionStatus.SUCCEEDED
                failure_code = None
                message = "本地 OPC-UA 模拟设备原子条件执行与回读验证成功。"
                failure_stage = None
                final_state = DeviceExecutionState.SUCCEEDED
            elif record.result == "EXPECTED_BEFORE_MISMATCH":
                status = DeviceExecutionStatus.REJECTED
                failure_code = "DEVICE_VALUE_CHANGED_AT_ATOMIC_EXECUTION"
                message = "设备侧原子比较发现 expected-before 已变化，零写入拒绝。"
                failure_stage = "ATOMIC_COMPARE"
                final_state = DeviceExecutionState.REJECTED
            elif record.result == "READBACK_MISMATCH":
                status = DeviceExecutionStatus.FAILED_DEFINITE
                failure_code = "FAILED_READBACK_MISMATCH"
                message = "设备侧 atomic method 回读值与目标值不一致。"
                failure_stage = "READBACK"
                final_state = DeviceExecutionState.FAILED_DEFINITE
            else:
                status = DeviceExecutionStatus.FAILED_DEFINITE
                failure_code = f"ATOMIC_EXECUTION_{record.result}"
                message = "设备侧 atomic method 明确拒绝或返回冲突。"
                failure_stage = "WRITE"
                final_state = DeviceExecutionState.FAILED_DEFINITE
        trace = [DeviceExecutionState.CREATED, DeviceExecutionState.VALIDATING]
        if record is not None or reconciling:
            trace.append(DeviceExecutionState.WRITE_STARTED)
        trace.append(final_state)
        receipt = self._receipt(
            task_id=qualification.task_id,
            confirmed_plan_id=qualification.confirmed_plan_id,
            confirmed_plan_hash=qualification.confirmed_plan_hash,
            replay_result_id=qualification.replay_result_id,
            replay_result_hash=qualification.replay_result_hash,
            execution_mode=self._config.mode,
            idempotency_key=idempotency_key,
            parameter_name=parameter_name,
            mapping=mapping,
            expected_before=expected_before,
            actual_before=actual_before,
            requested_after=requested_after,
            actual_after=actual_after,
            tick_delta=qualification.delta_ticks[parameter_name],
            safety_validator_version=qualification.safety_validator_version,
            validation_result="PASSED",
            execution_status=status,
            failure_stage=failure_stage,
            failure_code=failure_code,
            message=message,
            device_status=device_status,
            actor=(qualification.actor_id, qualification.actor_role, qualification.display_name),
            started_at=started_at,
            write_attempt_count=writes,
            state_trace=tuple(trace),
            identity=identity,
        )
        try:
            return self._finalize(receipt)
        except Exception:
            stored = self._repository.get_device_execution_receipt(
                receipt.device_execution_id
            )
            if stored is not None and stored.receipt_hash == receipt.receipt_hash:
                return DeviceExecutionOutcome(stored, False, True)
            self._repository.mark_device_execution_unknown(
                idempotency_key=idempotency_key,
                failure_code="LOCAL_RECEIPT_PERSISTENCE_UNKNOWN",
            )
            unknown = self._receipt(
                task_id=qualification.task_id,
                confirmed_plan_id=qualification.confirmed_plan_id,
                confirmed_plan_hash=qualification.confirmed_plan_hash,
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                execution_mode=self._config.mode,
                idempotency_key=idempotency_key,
                parameter_name=parameter_name,
                mapping=mapping,
                expected_before=expected_before,
                actual_before=actual_before,
                requested_after=requested_after,
                actual_after=actual_after,
                tick_delta=qualification.delta_ticks[parameter_name],
                safety_validator_version=qualification.safety_validator_version,
                validation_result="PASSED",
                execution_status=DeviceExecutionStatus.UNKNOWN_OUTCOME,
                failure_stage="PERSISTENCE",
                failure_code="LOCAL_RECEIPT_PERSISTENCE_UNKNOWN",
                message=(
                    "设备调用已返回但本地 receipt 首次持久化失败；"
                    "状态保持 UNKNOWN_OUTCOME 并等待按设备侧幂等记录恢复。"
                ),
                device_status=device_status,
                actor=(qualification.actor_id, qualification.actor_role, qualification.display_name),
                started_at=started_at,
                write_attempt_count=writes,
                state_trace=(DeviceExecutionState.CREATED, DeviceExecutionState.VALIDATING, DeviceExecutionState.WRITE_STARTED, DeviceExecutionState.UNKNOWN_OUTCOME),
                identity=identity,
            )
            return self._finalize(unknown)

    def _reject_gateway_failure(
        self,
        error: OpcUaGatewayError,
        *,
        qualification: DeviceExecutionQualification,
        parameter_name: str,
        mapping: OpcUaNodeMapping,
        expected_before: str,
        requested_after: str,
        identity: OpcUaObservedIdentity | None,
        started_at: str,
        device_status: str | None,
    ) -> DeviceExecutionOutcome:
        return self._reject_without_qualification(
            task_id=qualification.task_id,
            confirmed_plan_id=qualification.confirmed_plan_id,
            confirmed_plan_hash=qualification.confirmed_plan_hash,
            execution_mode=self._config.mode,
            code=error.code,
            message=error.message,
            started_at=started_at,
            replay_result_id=qualification.replay_result_id,
            replay_result_hash=qualification.replay_result_hash,
            safety_validator_version=qualification.safety_validator_version,
            observed_server_identity_hash=(
                None if identity is None else identity.identity_hash
            ),
        )

    def record_request_rejection(
        self,
        *,
        task_id: str,
        confirmed_plan_id: str | None,
        confirmed_plan_hash: str | None,
        execution_mode: str | None,
        code: str,
        message: str,
        request_payload: Mapping[str, object],
    ) -> DeviceExecutionOutcome:
        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "rejection_code": code,
                    "request_payload": request_payload,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return self._reject_without_qualification(
            task_id=task_id,
            confirmed_plan_id=confirmed_plan_id or "MISSING",
            confirmed_plan_hash=confirmed_plan_hash or "MISSING",
            execution_mode=execution_mode or "MISSING",
            code=code,
            message=message,
            started_at=self._clock.now(),
            request_fingerprint=request_fingerprint,
        )

    def _validate_qualification(
        self,
        qualification: DeviceExecutionQualification,
    ) -> tuple[str, OpcUaNodeMapping]:
        try:
            confirmed_at = datetime.fromisoformat(qualification.confirmed_at)
            evaluated_at = datetime.fromisoformat(self._clock.now())
            if confirmed_at.tzinfo is None or evaluated_at.tzinfo is None:
                raise ValueError("timezone required")
            plan_age_seconds = (evaluated_at - confirmed_at).total_seconds()
        except (TypeError, ValueError) as error:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_TIME_INVALID",
                "ConfirmedPlan 确认时间无法用于设备执行有效期校验。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
            ) from error
        if (
            plan_age_seconds < -5
            or plan_age_seconds > self._config.confirmed_plan_max_age_seconds
        ):
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_EXPIRED",
                "ConfirmedPlan 已超过设备执行有效期，必须重新确认并回放。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        if qualification.baseline_reproduction_status != "PASSED":
            raise DeviceQualificationError(
                "BASELINE_REPRODUCTION_FAILED",
                "ReplayResult baseline reproduction 未通过。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        if qualification.replay_status != "SUCCESS":
            raise DeviceQualificationError(
                f"REPLAY_STATUS_{qualification.replay_status}_NOT_EXECUTABLE",
                "只有 ReplayResult=SUCCESS 才允许进入设备执行。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        if qualification.safety_validation_result != "PASSED":
            raise DeviceQualificationError(
                "SAFETY_REVALIDATION_FAILED",
                "ParameterSafetyValidator 写入前复核未通过。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        if qualification.parameter_family not in ALLOWED_PARAMETER_FAMILIES:
            raise DeviceQualificationError(
                "PARAMETER_FAMILY_NOT_EXECUTABLE",
                "参数族不在设备执行白名单中。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        changed = qualification.changed_parameters
        if len(changed) == 0:
            raise DeviceQualificationError(
                "NO_PARAMETER_CHANGE",
                "ConfirmedPlan 没有实际发生变化的参数。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        if len(changed) != 1:
            raise DeviceQualificationError(
                "MULTI_PARAMETER_ATOMICITY_UNSUPPORTED",
                "当前 OPC-UA sandbox 不提供多节点原子写入，已在写入前整体拒绝。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
                safety_validator_version=qualification.safety_validator_version,
            )
        parameter_name = changed[0]
        if parameter_name not in NODE_MAPPINGS:
            raise DeviceQualificationError(
                "PARAMETER_NOT_ALLOWLISTED",
                "ConfirmedPlan 包含非白名单参数。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
            )
        mapping = self._node_mappings.get(parameter_name)
        if mapping is None:
            raise DeviceQualificationError(
                "NODE_NOT_ALLOWLISTED",
                "参数对应节点不在服务器端 OPC-UA 节点白名单中。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
            )
        try:
            current = Decimal(normalize_device_value(qualification.current_values[parameter_name]))
            proposed = Decimal(normalize_device_value(qualification.proposed_values[parameter_name]))
            delta_ticks = qualification.delta_ticks[parameter_name]
        except (KeyError, InvalidOperation, TypeError, ValueError) as error:
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_PARAMETER_INVALID",
                "ConfirmedPlan 参数值或 tick 绑定无效。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
            ) from error
        if (
            isinstance(delta_ticks, bool)
            or not isinstance(delta_ticks, int)
            or proposed - current != TICK_SIZE * delta_ticks
        ):
            raise DeviceQualificationError(
                "CONFIRMED_PLAN_TICK_MISMATCH",
                "ConfirmedPlan Decimal 值与 tick delta 不一致。",
                replay_result_id=qualification.replay_result_id,
                replay_result_hash=qualification.replay_result_hash,
            )
        return parameter_name, mapping

    def _reject_without_qualification(
        self,
        *,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
        execution_mode: str,
        code: str,
        message: str,
        started_at: str,
        replay_result_id: str | None = None,
        replay_result_hash: str | None = None,
        safety_validator_version: str | None = None,
        request_fingerprint: str | None = None,
        observed_server_identity_hash: str | None = None,
    ) -> DeviceExecutionOutcome:
        idempotency_key = self._idempotency_key(
            task_id=task_id,
            confirmed_plan_id=confirmed_plan_id,
            confirmed_plan_hash=confirmed_plan_hash,
            replay_result_hash=replay_result_hash,
            execution_mode=execution_mode,
            request_fingerprint=request_fingerprint,
            observed_server_identity_hash=(
                observed_server_identity_hash or "NOT_OBSERVED"
            ),
        )
        claim = self._claim(
            task_id=task_id,
            idempotency_key=idempotency_key,
            started_at=started_at,
        )
        if claim.status == "FINALIZED" and claim.receipt is not None:
            return DeviceExecutionOutcome(claim.receipt, False, True)
        if claim.status == "VALIDATING" and claim.owner_instance_id != self._instance_id:
            raise DeviceExecutionConflictError(
                "DEVICE_EXECUTION_IN_PROGRESS",
                "相同幂等设备执行请求正在处理。",
            )
        receipt = self._receipt(
            task_id=task_id,
            confirmed_plan_id=confirmed_plan_id,
            confirmed_plan_hash=confirmed_plan_hash,
            replay_result_id=replay_result_id,
            replay_result_hash=replay_result_hash,
            execution_mode=execution_mode,
            idempotency_key=idempotency_key,
            parameter_name=None,
            mapping=None,
            expected_before=None,
            requested_after=None,
            tick_delta=None,
            safety_validator_version=safety_validator_version,
            validation_result="REJECTED",
            execution_status=DeviceExecutionStatus.REJECTED,
            failure_stage="QUALIFICATION",
            failure_code=code,
            message=message,
            actor=("SYSTEM", "SYSTEM", "TuneWise 服务端"),
            started_at=started_at,
            state_trace=(DeviceExecutionState.CREATED, DeviceExecutionState.VALIDATING, DeviceExecutionState.REJECTED),
        )
        return self._finalize(receipt)

    def _claim(
        self,
        *,
        task_id: str,
        idempotency_key: str,
        started_at: str,
        qualification: DeviceExecutionQualification | None = None,
        parameter_name: str | None = None,
        mapping: OpcUaNodeMapping | None = None,
        expected_before: str | None = None,
        requested_after: str | None = None,
        identity: OpcUaObservedIdentity | None = None,
        execution_mode: str | None = None,
    ) -> DeviceExecutionClaim:
        recovery_payload_json = None
        if (
            qualification is not None
            and parameter_name is not None
            and mapping is not None
            and expected_before is not None
            and requested_after is not None
            and identity is not None
            and execution_mode is not None
        ):
            recovery_payload_json = json.dumps(
                {
                    "qualification": asdict(qualification),
                    "parameter_name": parameter_name,
                    "node_id": mapping.expanded_node_id,
                    "node_mapping_version": self._config.node_mapping_version,
                    "expected_before": expected_before,
                    "requested_after": requested_after,
                    "execution_mode": execution_mode,
                    "observed_server_identity_hash": identity.identity_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        return self._repository.claim_device_execution(
            device_execution_id=f"tw-device-execution-{idempotency_key[:16]}",
            task_id=task_id,
            idempotency_key=idempotency_key,
            owner_instance_id=self._instance_id,
            started_at=started_at,
            server_identity_hash=(
                "NOT_OBSERVED" if identity is None else identity.identity_hash
            ),
            server_identity_json=(
                None
                if identity is None
                else json.dumps(asdict(identity), ensure_ascii=False, sort_keys=True)
            ),
            node_mapping_version=self._config.node_mapping_version,
            expected_before_value=expected_before,
            requested_after_value=requested_after,
            confirmed_plan_hash=(
                None if qualification is None else qualification.confirmed_plan_hash
            ),
            replay_result_hash=(
                None if qualification is None else qualification.replay_result_hash
            ),
            parameter_name=parameter_name,
            node_id=None if mapping is None else mapping.expanded_node_id,
            recovery_payload_json=recovery_payload_json,
        )

    def _finalize(self, receipt: DeviceExecutionReceipt) -> DeviceExecutionOutcome:
        stored = self._repository.finalize_device_execution(
            receipt,
            owner_instance_id=self._instance_id,
        )
        return DeviceExecutionOutcome(stored, True, False)

    def _idempotency_key(
        self,
        *,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
        replay_result_hash: str | None,
        execution_mode: str,
        request_fingerprint: str | None = None,
        observed_server_identity_hash: str = "NOT_OBSERVED",
    ) -> str:
        return device_execution_idempotency_key(
            task_id=task_id,
            confirmed_plan_id=confirmed_plan_id,
            confirmed_plan_hash=confirmed_plan_hash,
            replay_result_hash=replay_result_hash,
            execution_mode=execution_mode,
            gateway_version=self._config.gateway_version,
            namespace_uri=self._config.namespace_uri,
            node_mapping_version=self._config.node_mapping_version,
            endpoint_fingerprint=self._config.endpoint_fingerprint,
            observed_server_identity_hash=observed_server_identity_hash,
            request_fingerprint=request_fingerprint,
        )

    def _receipt(
        self,
        *,
        task_id: str,
        confirmed_plan_id: str,
        confirmed_plan_hash: str,
        replay_result_id: str | None,
        replay_result_hash: str | None,
        execution_mode: str,
        idempotency_key: str,
        parameter_name: str | None,
        mapping: OpcUaNodeMapping | None,
        expected_before: str | None,
        requested_after: str | None,
        tick_delta: int | None,
        safety_validator_version: str | None,
        validation_result: str,
        execution_status: DeviceExecutionStatus,
        failure_stage: str | None,
        failure_code: str | None,
        message: str,
        actor: tuple[str, str, str],
        started_at: str,
        state_trace: tuple[str, ...],
        actual_before: str | None = None,
        actual_after: str | None = None,
        device_status: str | None = None,
        write_attempt_count: int = 0,
        identity: OpcUaObservedIdentity | None = None,
    ) -> DeviceExecutionReceipt:
        provisional = DeviceExecutionReceipt(
            receipt_version=DEVICE_EXECUTION_RECEIPT_VERSION,
            receipt_canonicalizer_version=DEVICE_EXECUTION_CANONICALIZER_VERSION,
            state_machine_version=DEVICE_EXECUTION_STATE_MACHINE_VERSION,
            device_execution_id=f"tw-device-execution-{idempotency_key[:16]}",
            task_id=task_id,
            confirmed_plan_id=confirmed_plan_id,
            confirmed_plan_hash=confirmed_plan_hash,
            replay_result_id=replay_result_id,
            replay_result_hash=replay_result_hash,
            execution_mode=execution_mode,
            gateway_version=self._config.gateway_version,
            namespace_uri=self._config.namespace_uri,
            node_mapping_version=self._config.node_mapping_version,
            endpoint_local_id=self._config.endpoint_local_id,
            endpoint_fingerprint=self._config.endpoint_fingerprint,
            observed_server_identity_hash=(
                None if identity is None else identity.identity_hash
            ),
            observed_application_uri=(
                None if identity is None else identity.application_uri
            ),
            security_profile=(None if identity is None else identity.security_profile),
            certificate_fingerprint=(
                None if identity is None else identity.certificate_fingerprint
            ),
            parameter_name=parameter_name,
            node_id=None if mapping is None else mapping.expanded_node_id,
            expected_before_value=None if expected_before is None else normalize_device_value(expected_before),
            actual_before_value=None if actual_before is None else normalize_device_value(actual_before),
            requested_after_value=None if requested_after is None else normalize_device_value(requested_after),
            actual_after_value=None if actual_after is None else normalize_device_value(actual_after),
            tick_delta=tick_delta,
            safety_validator_version=safety_validator_version,
            validation_result=validation_result,
            execution_status=execution_status.value,
            failure_stage=failure_stage,
            failure_code=failure_code,
            message=message,
            device_status=device_status,
            actor_id=actor[0],
            actor_role=actor[1],
            display_name=actor[2],
            started_at=started_at,
            completed_at=self._clock.now(),
            idempotency_key=idempotency_key,
            attempt_count=1,
            internal_retry_count=0,
            write_attempt_count=write_attempt_count,
            state_trace=tuple(str(value) for value in state_trace),
            disclaimer=DEVICE_EXECUTION_DISCLAIMER,
            receipt_hash="",
        )
        receipt_hash = DeviceExecutionReceiptCanonicalizer().sha256(
            device_execution_receipt_payload(provisional)
        )
        return replace(provisional, receipt_hash=receipt_hash)

    def _eligibility(
        self,
        eligible: bool,
        code: str,
        message: str,
        *,
        qualification: DeviceExecutionQualification | None = None,
        parameter_name: str | None = None,
        mapping: OpcUaNodeMapping | None = None,
        actual_before: str | None = None,
        device_status: str = "DISCONNECTED",
        identity: OpcUaObservedIdentity | None = None,
    ) -> DeviceExecutionEligibility:
        return DeviceExecutionEligibility(
            eligible=eligible,
            code=code,
            message=message,
            execution_mode=self._config.mode,
            gateway_version=self._config.gateway_version,
            node_mapping_version=self._config.node_mapping_version,
            endpoint_local_id=self._config.endpoint_local_id,
            endpoint_fingerprint=self._config.endpoint_fingerprint,
            observed_server_identity_hash=(
                None if identity is None else identity.identity_hash
            ),
            observed_application_uri=(
                None if identity is None else identity.application_uri
            ),
            security_profile=(None if identity is None else identity.security_profile),
            device_connected=device_status != "DISCONNECTED",
            device_status=device_status,
            safety_gate_status=(
                "NOT_EVALUATED"
                if qualification is None
                else qualification.safety_validation_result
            ),
            replay_status=None if qualification is None else qualification.replay_status,
            parameter_name=parameter_name,
            node_id=None if mapping is None else mapping.expanded_node_id,
            expected_before_value=(
                None
                if qualification is None or parameter_name is None
                else normalize_device_value(qualification.current_values[parameter_name])
            ),
            actual_before_value=actual_before,
            requested_after_value=(
                None
                if qualification is None or parameter_name is None
                else normalize_device_value(qualification.proposed_values[parameter_name])
            ),
            tick_delta=(
                None
                if qualification is None or parameter_name is None
                else qualification.delta_ticks[parameter_name]
            ),
        )
