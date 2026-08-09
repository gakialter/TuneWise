from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock

import pytest

from tunewise.device_execution import (
    DEVICE_EXECUTION_DISCLAIMER,
    DeviceExecutionQualification,
    DeviceExecutionReceiptCanonicalizer,
    DeviceExecutionService,
    DeviceQualificationError,
    deserialize_device_execution_receipt,
    device_execution_receipt_payload,
)
from tunewise.opcua_gateway import (
    NODE_MAPPINGS,
    OPCUA_SANDBOX_MODE,
    AtomicExecutionResult,
    DeviceExecutionConfig,
    OpcUaGatewayError,
    OpcUaHealth,
    OpcUaObservedIdentity,
    OpcUaParameterMetadata,
)
from tunewise.store import TaskStore


class FixedClock:
    def __init__(self) -> None:
        self._counter = 0

    def now(self) -> str:
        self._counter += 1
        return f"2026-08-04T12:00:00.{self._counter:03d}+00:00"


class FakeSession:
    def __init__(self, gateway: FakeGateway) -> None:
        self.gateway = gateway

    def read_health(self) -> OpcUaHealth:
        if self.gateway.health_error is not None:
            raise self.gateway.health_error
        return OpcUaHealth(
            self.gateway.healthy,
            "SANDBOX_READY" if self.gateway.healthy else "SANDBOX_UNHEALTHY",
            "NORMAL",
        )

    @property
    def observed_identity(self) -> OpcUaObservedIdentity:
        return self.gateway.observed_identity

    def read_parameter(self, parameter_name: str) -> str:
        if self.gateway.read_error is not None:
            raise self.gateway.read_error
        return self.gateway.current_values[parameter_name]

    def apply_confirmed_parameter_change(
        self,
        *,
        idempotency_key: str,
        parameter_name: str,
        expected_before: str,
        requested_after: str,
    ) -> AtomicExecutionResult:
        if not self.gateway.atomic_supported:
            raise OpcUaGatewayError(
                "ATOMIC_EXECUTION_UNSUPPORTED",
                "atomic method unavailable",
                "CAPABILITY",
            )
        if self.gateway.write_error is not None:
            raise self.gateway.write_error
        if self.gateway.before_apply is not None:
            self.gateway.before_apply(self.gateway)
        with self.gateway.lock:
            existing = self.gateway.execution_records.get(idempotency_key)
            if existing is not None:
                return existing
            actual_before = self.gateway.current_values[parameter_name]
            if actual_before != expected_before:
                result = AtomicExecutionResult(
                    idempotency_key,
                    parameter_name,
                    expected_before,
                    requested_after,
                    actual_before,
                    actual_before,
                    "EXPECTED_BEFORE_MISMATCH",
                    "2026-08-04T12:00:00+00:00",
                    0,
                )
            else:
                self.gateway.write_count += 1
                actual_after = (
                    "0.150000"
                    if self.gateway.readback_mismatch
                    else requested_after
                )
                self.gateway.current_values[parameter_name] = actual_after
                result = AtomicExecutionResult(
                    idempotency_key,
                    parameter_name,
                    expected_before,
                    requested_after,
                    actual_before,
                    actual_after,
                    "APPLIED" if actual_after == requested_after else "READBACK_MISMATCH",
                    "2026-08-04T12:00:00+00:00",
                    1,
                )
            self.gateway.execution_records[idempotency_key] = result
            if self.gateway.after_apply_error is not None and result.result == "APPLIED":
                raise self.gateway.after_apply_error
            return result

    def query_execution_result(self, idempotency_key: str):
        if self.gateway.query_error is not None:
            raise self.gateway.query_error
        return self.gateway.execution_records.get(idempotency_key)


class FakeGateway:
    version = "tw-asyncua-sandbox-gateway-v1"

    def __init__(
        self,
        *,
        pitch: str = "0.250000",
        healthy: bool = True,
        health_error: OpcUaGatewayError | None = None,
        read_error: OpcUaGatewayError | None = None,
        write_error: OpcUaGatewayError | None = None,
        readback_mismatch: bool = False,
        before_apply=None,
        after_apply_error: OpcUaGatewayError | None = None,
        query_error: OpcUaGatewayError | None = None,
        atomic_supported: bool = True,
    ) -> None:
        self.current_values = {"pitch": pitch}
        self.healthy = healthy
        self.health_error = health_error
        self.read_error = read_error
        self.write_error = write_error
        self.readback_mismatch = readback_mismatch
        self.write_count = 0
        self.session_count = 0
        self.before_apply = before_apply
        self.after_apply_error = after_apply_error
        self.query_error = query_error
        self.atomic_supported = atomic_supported
        self.lock = Lock()
        self.execution_records: dict[str, AtomicExecutionResult] = {}
        parameters = tuple(
            OpcUaParameterMetadata(
                name,
                mapping.expanded_node_id,
                name,
                mapping.data_type,
                mapping.unit,
                True,
                False,
            )
            for name, mapping in sorted(NODE_MAPPINGS.items())
        )
        self.observed_identity = OpcUaObservedIdentity(
            "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/",
            "urn:tunewise:opcua:sandbox:server:v1",
            "urn:tunewise:opcua:sandbox:parameters:v1",
            "tw-opcua-sandbox-server-v3",
            "tw-opcua-node-mapping-v1",
            "tw-parameter-safety-mapping-v2",
            "OPCUA_SANDBOX",
            "LOCAL_ANONYMOUS_SANDBOX",
            None,
            parameters,
            "tw-opcua-atomic-method-v2",
            "e" * 64,
        )

    @contextmanager
    def session(self):
        self.session_count += 1
        if self.health_error is not None and self.health_error.code == "OPCUA_ENDPOINT_UNAVAILABLE":
            raise self.health_error
        yield FakeSession(self)


def qualification(**overrides) -> DeviceExecutionQualification:
    values = {
        "task_id": "tw-demo-task-001",
        "confirmed_plan_id": "tw-confirmed-plan-test0001",
        "confirmed_plan_hash": "a" * 64,
        "replay_result_id": "tw-replay-result-test0001",
        "replay_result_hash": "b" * 64,
        "replay_status": "SUCCESS",
        "baseline_reproduction_status": "PASSED",
        "parameter_family": "PITCH_ROLL",
        "current_values": {"pitch": "0.250000"},
        "proposed_values": {"pitch": "0.200000"},
        "delta_ticks": {"pitch": -1},
        "changed_parameters": ("pitch",),
        "safety_validator_version": "tw-parameter-safety-v1",
        "safety_validation_result": "PASSED",
        "actor_id": "tw-aa-engineer-demo",
        "actor_role": "AA_PROCESS_ENGINEER",
        "display_name": "AA 工艺工程师",
        "confirmed_at": "2026-08-04T12:00:00.000+00:00",
    }
    values.update(overrides)
    return DeviceExecutionQualification(**values)


def enabled_config() -> DeviceExecutionConfig:
    return DeviceExecutionConfig(
        enabled=True,
        mode=OPCUA_SANDBOX_MODE,
        runtime_profile="OPCUA_SANDBOX_DEMO",
    )


def make_service(
    tmp_path: Path,
    *,
    qualified: DeviceExecutionQualification | None = None,
    qualification_error: DeviceQualificationError | None = None,
    gateway: FakeGateway | None = None,
    config: DeviceExecutionConfig | None = None,
    node_mappings=None,
) -> tuple[DeviceExecutionService, FakeGateway, TaskStore]:
    resolved_gateway = gateway or FakeGateway()

    def provider(_task_id: str, _plan_id: str, _plan_hash: str):
        if qualification_error is not None:
            raise qualification_error
        return qualified or qualification()

    store = TaskStore(tmp_path / "device-execution.db")
    with sqlite3.connect(tmp_path / "device-execution.db") as connection:
        connection.execute(
            "INSERT OR IGNORE INTO tasks(task_id, payload_json) VALUES (?, '{}')",
            ("tw-demo-task-001",),
        )
    service = DeviceExecutionService(
        config=config or enabled_config(),
        repository=store,
        qualification_provider=provider,
        gateway=resolved_gateway,
        clock=FixedClock(),
        node_mappings=node_mappings,
        instance_id="executor-test-instance",
    )
    return service, resolved_gateway, store


def execute(service: DeviceExecutionService, **overrides):
    request = {
        "task_id": "tw-demo-task-001",
        "confirmed_plan_id": "tw-confirmed-plan-test0001",
        "confirmed_plan_hash": "a" * 64,
        "execution_mode": OPCUA_SANDBOX_MODE,
        "sandbox_execution_acknowledged": True,
    }
    request.update(overrides)
    return service.execute(**request)


@pytest.mark.parametrize(
    "code",
    [
        "CONFIRMED_PLAN_NOT_FOUND",
        "CONFIRMED_PLAN_HASH_MISMATCH",
        "CONFIRMED_PLAN_STALE",
        "CONFIRMED_PLAN_NOT_FRESH",
        "REPLAY_RESULT_NOT_FOUND",
        "REPLAY_PLAN_BINDING_MISMATCH",
        "BASELINE_REPRODUCTION_FAILED",
    ],
)
def test_qualification_failures_are_fail_closed_and_receipted(tmp_path: Path, code: str):
    service, gateway, _store = make_service(
        tmp_path,
        qualification_error=DeviceQualificationError(code, "资格门禁失败。"),
    )

    outcome = execute(service)

    assert outcome.receipt.execution_status == "REJECTED"
    assert outcome.receipt.failure_code == code
    assert outcome.receipt.failure_stage == "QUALIFICATION"
    assert outcome.receipt.validation_result == "REJECTED"
    assert gateway.write_count == 0
    assert len(outcome.receipt.receipt_hash) == 64


@pytest.mark.parametrize(
    "replay_status",
    ["REGRESSION", "PARTIAL_IMPROVEMENT", "NO_IMPROVEMENT"],
)
def test_only_success_replay_is_executable(tmp_path: Path, replay_status: str):
    service, gateway, _store = make_service(
        tmp_path,
        qualified=qualification(replay_status=replay_status),
    )

    outcome = execute(service)

    assert outcome.receipt.execution_status == "REJECTED"
    assert outcome.receipt.failure_code == f"REPLAY_STATUS_{replay_status}_NOT_EXECUTABLE"
    assert gateway.write_count == 0


def test_safety_revalidation_failure_is_rejected(tmp_path: Path):
    service, gateway, _store = make_service(
        tmp_path,
        qualified=qualification(safety_validation_result="REJECTED"),
    )
    outcome = execute(service)
    assert outcome.receipt.failure_code == "SAFETY_REVALIDATION_FAILED"
    assert gateway.write_count == 0


def test_expired_confirmed_plan_is_rejected(tmp_path: Path):
    service, gateway, _store = make_service(
        tmp_path,
        qualified=qualification(confirmed_at="2026-08-04T11:00:00.000+00:00"),
    )
    outcome = execute(service)
    assert outcome.receipt.failure_code == "CONFIRMED_PLAN_EXPIRED"
    assert gateway.write_count == 0


def test_non_allowlisted_parameter_is_rejected(tmp_path: Path):
    service, gateway, _store = make_service(
        tmp_path,
        qualified=qualification(
            current_values={"laser_power": "0.250000"},
            proposed_values={"laser_power": "0.200000"},
            delta_ticks={"laser_power": -1},
            changed_parameters=("laser_power",),
        ),
    )
    outcome = execute(service)
    assert outcome.receipt.failure_code == "PARAMETER_NOT_ALLOWLISTED"
    assert gateway.write_count == 0


def test_non_allowlisted_node_is_rejected(tmp_path: Path):
    service, gateway, _store = make_service(tmp_path, node_mappings={})
    outcome = execute(service)
    assert outcome.receipt.failure_code == "NODE_NOT_ALLOWLISTED"
    assert gateway.write_count == 0


def test_multi_parameter_plan_is_rejected_before_any_write(tmp_path: Path):
    service, gateway, _store = make_service(
        tmp_path,
        qualified=qualification(
            current_values={"pitch": "0.250000", "roll": "0.100000"},
            proposed_values={"pitch": "0.200000", "roll": "0.050000"},
            delta_ticks={"pitch": -1, "roll": -1},
            changed_parameters=("pitch", "roll"),
        ),
    )
    outcome = execute(service)
    assert outcome.receipt.failure_code == "MULTI_PARAMETER_ATOMICITY_UNSUPPORTED"
    assert gateway.write_count == 0


def test_disabled_mode_and_missing_independent_acknowledgement_are_rejected(tmp_path: Path):
    disabled, gateway, _store = make_service(
        tmp_path / "disabled",
        config=DeviceExecutionConfig(),
    )
    disabled_outcome = execute(disabled)
    assert disabled_outcome.receipt.failure_code == "DEVICE_EXECUTION_DISABLED"
    assert gateway.write_count == 0

    enabled, enabled_gateway, _store = make_service(tmp_path / "ack")
    ack_outcome = execute(enabled, sandbox_execution_acknowledged=False)
    assert ack_outcome.receipt.failure_code == "DEVICE_EXECUTION_ACKNOWLEDGEMENT_REQUIRED"
    assert enabled_gateway.write_count == 0


def test_environment_configuration_defaults_off_and_rejects_non_demo_or_remote_endpoints():
    default = DeviceExecutionConfig.from_env({})
    assert default.enabled is False
    assert default.mode == "DISABLED"

    with pytest.raises(ValueError, match="runtime profile"):
        DeviceExecutionConfig.from_env(
            {
                "TUNEWISE_DEVICE_EXECUTION_ENABLED": "true",
                "TUNEWISE_OPCUA_MODE": OPCUA_SANDBOX_MODE,
            }
        )


@pytest.mark.parametrize(
    "endpoint",
    [
        "opc.tcp://127.0.0.1:4841@0.0.0.0:4841/tunewise/opcua-sandbox/",
        "opc.tcp://user@127.0.0.1:4841/tunewise/opcua-sandbox/",
        "opc.tcp://0.0.0.0:4841/tunewise/opcua-sandbox/",
        "opc.tcp://[::]:4841/tunewise/opcua-sandbox/",
        "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/?query=1",
        "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/#fragment",
        "opc.tcp://127.0.0.1:4841/not-the-sandbox/",
        "opc.tcp://127.0.0.1:4842/tunewise/opcua-sandbox/",
        "opc.tcp://%31%32%37.0.0.1:4841/tunewise/opcua-sandbox/",
    ],
)
def test_environment_configuration_strictly_rejects_ambiguous_sandbox_endpoints(
    endpoint: str,
):
    with pytest.raises(ValueError, match="本机 sandbox"):
        DeviceExecutionConfig.from_env(
            {
                "TUNEWISE_DEVICE_EXECUTION_ENABLED": "true",
                "TUNEWISE_OPCUA_MODE": OPCUA_SANDBOX_MODE,
                "TUNEWISE_RUNTIME_PROFILE": "OPCUA_SANDBOX_DEMO",
                "TUNEWISE_OPCUA_SANDBOX_ENDPOINT": endpoint,
            }
        )
    with pytest.raises(ValueError, match="本机 sandbox"):
        DeviceExecutionConfig.from_env(
            {
                "TUNEWISE_DEVICE_EXECUTION_ENABLED": "true",
                "TUNEWISE_OPCUA_MODE": OPCUA_SANDBOX_MODE,
                "TUNEWISE_RUNTIME_PROFILE": "OPCUA_SANDBOX_DEMO",
                "TUNEWISE_OPCUA_SANDBOX_ENDPOINT": (
                    "opc.tcp://public.example:4840/tunewise/opcua-sandbox/"
                ),
            }
        )


def test_valid_single_parameter_write_reads_before_and_after(tmp_path: Path):
    service, gateway, store = make_service(tmp_path)

    outcome = execute(service)

    receipt = outcome.receipt
    assert receipt.execution_status == "SUCCEEDED"
    assert receipt.parameter_name == "pitch"
    assert receipt.node_id.endswith("TuneWiseSandbox.Parameters.pitch")
    assert receipt.expected_before_value == "0.250000"
    assert receipt.actual_before_value == "0.250000"
    assert receipt.requested_after_value == "0.200000"
    assert receipt.actual_after_value == "0.200000"
    assert receipt.tick_delta == -1
    assert receipt.write_attempt_count == 1
    assert receipt.state_trace == (
        "CREATED",
        "VALIDATING",
        "WRITE_STARTED",
        "SUCCEEDED",
    )
    assert receipt.disclaimer == DEVICE_EXECUTION_DISCLAIMER
    assert gateway.write_count == 1
    assert store.get_device_execution_receipt(receipt.device_execution_id) == receipt


def test_device_value_changed_rejects_without_write(tmp_path: Path):
    service, gateway, _store = make_service(
        tmp_path,
        gateway=FakeGateway(pitch="0.300000"),
    )
    outcome = execute(service)
    assert outcome.receipt.execution_status == "REJECTED"
    assert outcome.receipt.failure_code == "DEVICE_VALUE_CHANGED_AT_ATOMIC_EXECUTION"
    assert outcome.receipt.actual_before_value == "0.300000"
    assert gateway.write_count == 0


@pytest.mark.parametrize(
    ("gateway", "expected_status", "expected_code", "expected_stage", "writes"),
    [
        (
            FakeGateway(
                health_error=OpcUaGatewayError(
                    "OPCUA_ENDPOINT_UNAVAILABLE", "endpoint unavailable", "COMMUNICATION"
                )
            ),
            "REJECTED",
            "OPCUA_ENDPOINT_UNAVAILABLE",
            "QUALIFICATION",
            0,
        ),
        (
            FakeGateway(
                write_error=OpcUaGatewayError(
                    "OPCUA_WRITE_REJECTED", "write rejected", "WRITE"
                )
            ),
            "FAILED_DEFINITE",
            "OPCUA_WRITE_REJECTED",
            "WRITE",
            0,
        ),
        (
            FakeGateway(readback_mismatch=True),
            "FAILED_DEFINITE",
            "FAILED_READBACK_MISMATCH",
            "READBACK",
            1,
        ),
    ],
)
def test_gateway_failures_are_structured_receipts(
    tmp_path: Path,
    gateway: FakeGateway,
    expected_status: str,
    expected_code: str,
    expected_stage: str,
    writes: int,
):
    service, _gateway, _store = make_service(tmp_path, gateway=gateway)
    outcome = execute(service)
    assert outcome.receipt.execution_status == expected_status
    assert outcome.receipt.failure_code == expected_code
    assert outcome.receipt.failure_stage == expected_stage
    assert gateway.write_count == writes


def test_same_idempotency_request_and_service_restart_do_not_write_twice(tmp_path: Path):
    service, gateway, store = make_service(tmp_path)
    first = execute(service)
    second = execute(service)
    restarted = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: qualification(),
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-restarted-instance",
    )
    third = execute(restarted)

    assert first.receipt == second.receipt == third.receipt
    assert second.idempotent_replay is True
    assert third.idempotent_replay is True
    assert gateway.write_count == 1


def test_different_plan_hash_cannot_reuse_old_execution(tmp_path: Path):
    first_qualification = qualification()
    current = {"value": first_qualification}
    gateway = FakeGateway()
    store = TaskStore(tmp_path / "device-execution.db")
    with sqlite3.connect(tmp_path / "device-execution.db") as connection:
        connection.execute(
            "INSERT INTO tasks(task_id, payload_json) VALUES (?, '{}')",
            ("tw-demo-task-001",),
        )
    service = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: current["value"],
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-test-instance",
    )
    first = execute(service)
    current["value"] = qualification(
        confirmed_plan_id="tw-confirmed-plan-test0002",
        confirmed_plan_hash="c" * 64,
        replay_result_id="tw-replay-result-test0002",
        replay_result_hash="d" * 64,
        current_values={"pitch": "0.200000"},
        proposed_values={"pitch": "0.150000"},
    )
    second = execute(
        service,
        confirmed_plan_id="tw-confirmed-plan-test0002",
        confirmed_plan_hash="c" * 64,
    )

    assert first.receipt.device_execution_id != second.receipt.device_execution_id
    assert first.receipt.idempotency_key != second.receipt.idempotency_key
    assert gateway.write_count == 2


def test_receipt_hash_is_recomputable_and_tampering_is_detected(tmp_path: Path):
    service, _gateway, _store = make_service(tmp_path)
    receipt = execute(service).receipt
    assert DeviceExecutionReceiptCanonicalizer().sha256(
        device_execution_receipt_payload(receipt)
    ) == receipt.receipt_hash

    tampered = replace(receipt, actual_after_value="0.300000")
    with pytest.raises(Exception) as caught:
        deserialize_device_execution_receipt(asdict(tampered))
    assert getattr(caught.value, "code", None) == "DEVICE_EXECUTION_RECEIPT_HASH_MISMATCH"


def test_eligibility_reads_health_and_optimistic_before_value(tmp_path: Path):
    service, gateway, _store = make_service(tmp_path)
    eligibility = service.eligibility(
        "tw-demo-task-001",
        "tw-confirmed-plan-test0001",
        "a" * 64,
    )
    assert eligibility.eligible is True
    assert eligibility.code == "ELIGIBLE"
    assert eligibility.device_connected is True
    assert eligibility.actual_before_value == "0.250000"
    assert eligibility.requested_after_value == "0.200000"
    assert gateway.write_count == 0


def test_value_change_after_eligibility_is_rejected_by_atomic_method_without_write(
    tmp_path: Path,
):
    gateway = FakeGateway(before_apply=lambda current: current.current_values.update(pitch="0.300000"))
    service, _gateway, _store = make_service(tmp_path, gateway=gateway)

    eligibility = service.eligibility(
        "tw-demo-task-001", "tw-confirmed-plan-test0001", "a" * 64
    )
    outcome = execute(service)

    assert eligibility.eligible is True
    assert outcome.receipt.execution_status == "REJECTED"
    assert outcome.receipt.failure_code == "DEVICE_VALUE_CHANGED_AT_ATOMIC_EXECUTION"
    assert outcome.receipt.actual_before_value == "0.300000"
    assert gateway.current_values["pitch"] == "0.300000"
    assert gateway.write_count == 0


def test_server_without_atomic_method_fails_closed_without_generic_write(tmp_path: Path):
    gateway = FakeGateway(atomic_supported=False)
    service, _gateway, _store = make_service(tmp_path, gateway=gateway)

    outcome = execute(service)

    assert outcome.receipt.execution_status == "REJECTED"
    assert outcome.receipt.failure_code == "ATOMIC_EXECUTION_UNSUPPORTED"
    assert gateway.write_count == 0
    assert not hasattr(FakeSession(gateway), "write_parameter")


def test_applied_then_timeout_reconciles_by_device_record_without_second_write(
    tmp_path: Path,
):
    gateway = FakeGateway(
        after_apply_error=OpcUaGatewayError(
            "OPCUA_UNKNOWN_OUTCOME", "response lost", "COMMUNICATION"
        )
    )
    service, _gateway, store = make_service(tmp_path, gateway=gateway)

    unknown = execute(service)
    gateway.after_apply_error = None
    restarted = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: qualification(),
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-restarted-reconcile",
    )
    recovered = restarted.reconcile_pending()[0]

    assert unknown.receipt.execution_status == "UNKNOWN_OUTCOME"
    assert recovered.receipt.execution_status == "SUCCEEDED"
    assert recovered.receipt.actual_after_value == "0.200000"
    assert gateway.write_count == 1


def test_target_value_without_device_execution_evidence_never_forges_success(
    tmp_path: Path,
):
    gateway = FakeGateway(
        after_apply_error=OpcUaGatewayError(
            "OPCUA_UNKNOWN_OUTCOME", "response lost", "COMMUNICATION"
        )
    )
    service, _gateway, store = make_service(tmp_path, gateway=gateway)
    unknown = execute(service)
    assert unknown.receipt.execution_status == "UNKNOWN_OUTCOME"
    gateway.after_apply_error = None
    gateway.execution_records.clear()
    assert gateway.current_values["pitch"] == "0.200000"

    restarted = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: qualification(),
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-restarted-no-evidence",
    )
    reconciled = restarted.reconcile_pending()[0]

    assert reconciled.receipt.execution_status == "RECONCILIATION_REQUIRED"
    assert reconciled.receipt.failure_code == "DEVICE_EXECUTION_EVIDENCE_NOT_FOUND"
    assert gateway.write_count == 1


def test_receipt_insert_failure_leaves_write_started_and_restart_reconciles(
    tmp_path: Path,
):
    class FailOnceStore(TaskStore):
        fail_once = True

        def finalize_device_execution(self, receipt, *, owner_instance_id):
            if self.fail_once and receipt.execution_status == "SUCCEEDED":
                self.fail_once = False
                raise sqlite3.OperationalError("simulated receipt insert failure")
            return super().finalize_device_execution(
                receipt, owner_instance_id=owner_instance_id
            )

    database = tmp_path / "receipt-failure.db"
    store = FailOnceStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks(task_id, payload_json) VALUES (?, '{}')",
            ("tw-demo-task-001",),
        )
    gateway = FakeGateway()
    service = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: qualification(),
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-before-restart",
    )

    unknown = execute(service)
    assert unknown.receipt.execution_status == "UNKNOWN_OUTCOME"
    assert unknown.receipt.failure_code == "LOCAL_RECEIPT_PERSISTENCE_UNKNOWN"

    restarted = DeviceExecutionService(
        config=enabled_config(),
        repository=store,
        qualification_provider=lambda *_args: qualification(),
        gateway=gateway,
        clock=FixedClock(),
        instance_id="executor-after-restart",
    )
    recovered = restarted.reconcile_pending()[0]

    assert recovered.receipt.execution_status == "SUCCEEDED"
    assert gateway.write_count == 1
