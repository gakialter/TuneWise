from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest
from asyncua import Client, ua
from asyncua.ua.uaerrors import UaStatusCodeError

from tunewise.opcua_gateway import (
    NODE_MAPPINGS,
    OPCUA_ATOMIC_METHOD_VERSION,
    OPCUA_NODE_MAPPING_VERSION,
    OPCUA_NAMESPACE_URI,
    OPCUA_SANDBOX_MODE,
    DeviceExecutionConfig,
    OpcUaGatewayError,
    SandboxOpcUaGateway,
)
from tunewise.opcua_sandbox import create_sandbox


def unused_port() -> int:
    return 4841


def wait_until_listening(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _stdout, stderr = process.communicate()
            raise RuntimeError(
                f"sandbox process exited with {process.returncode}: {stderr}"
            )
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError("sandbox did not start listening")


@contextmanager
def running_sandbox(fault: str = "NORMAL", state_file=None):
    port = unused_port()
    endpoint = f"opc.tcp://127.0.0.1:{port}/tunewise/opcua-sandbox/"
    command = [
            sys.executable,
            "-m",
            "tunewise.opcua_sandbox",
            "--endpoint",
            endpoint,
            "--fault",
            fault,
        ]
    if state_file is not None:
        command.extend(["--state-file", str(state_file)])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_until_listening(port, process)
        yield endpoint
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def gateway(endpoint: str) -> SandboxOpcUaGateway:
    return SandboxOpcUaGateway(
        DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
            endpoint=endpoint,
            request_timeout_seconds=1,
        )
    )


async def parameter_access(endpoint: str, parameter_name: str):
    client = Client(endpoint)
    await client.connect()
    try:
        namespace_index = (await client.get_namespace_array()).index(
            OPCUA_NAMESPACE_URI
        )
        node = client.get_node(
            ua.NodeId(NODE_MAPPINGS[parameter_name].identifier, namespace_index)
        )
        return await node.get_access_level(), await node.get_user_access_level()
    finally:
        await client.disconnect()


async def rejected_client_write(
    endpoint: str,
    parameter_name: str,
    requested_value: float,
):
    client = Client(endpoint)
    await client.connect()
    try:
        namespace_index = (await client.get_namespace_array()).index(
            OPCUA_NAMESPACE_URI
        )
        node = client.get_node(
            ua.NodeId(NODE_MAPPINGS[parameter_name].identifier, namespace_index)
        )
        before = await node.read_value()
        error = None
        try:
            await node.write_value(
                ua.Variant(requested_value, ua.VariantType.Double)
            )
        except UaStatusCodeError as caught:
            error = caught
        after = await node.read_value()
        return before, after, error
    finally:
        await client.disconnect()


def assert_client_read_only(access, user_access) -> None:
    assert ua.AccessLevel.CurrentRead in access
    assert ua.AccessLevel.CurrentRead in user_access
    assert ua.AccessLevel.CurrentWrite not in access
    assert ua.AccessLevel.CurrentWrite not in user_access


def test_real_opcua_sandbox_exposes_typed_read_only_parameter_and_health_nodes():
    with running_sandbox() as endpoint:
        with gateway(endpoint).session() as session:
            health = session.read_health()
            before = session.read_parameter("pitch")
            result = session.apply_confirmed_parameter_change(
                idempotency_key="a" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
            after = session.read_parameter("pitch")

    assert health.connected is True
    assert health.device_status == "SANDBOX_READY"
    assert health.fault_mode == "NORMAL"
    assert before == "0.250000"
    assert after == "0.200000"
    assert result.result == "APPLIED"
    assert result.physical_write_count == 1
    assert session.observed_identity.security_profile == "LOCAL_ANONYMOUS_SANDBOX"
    assert session.observed_identity.certificate_fingerprint is None
    assert all(item.readable and not item.writable for item in session.observed_identity.parameters)


def test_ordinary_client_write_is_rejected_without_execution_record_or_receipt(tmp_path):
    state_file = tmp_path / "sandbox-executions.json"
    key = "1" * 64
    with running_sandbox(state_file=state_file) as endpoint:
        with gateway(endpoint).session() as session:
            assert session.query_execution_result(key) is None
        before, after, error = asyncio.run(
            rejected_client_write(endpoint, "pitch", 0.30)
        )
        with gateway(endpoint).session() as session:
            assert session.query_execution_result(key) is None

    assert before == after == 0.25
    assert error is not None
    assert not state_file.exists()


def test_all_parameter_nodes_reject_ordinary_client_writes():
    with running_sandbox() as endpoint:
        for index, parameter_name in enumerate(NODE_MAPPINGS, start=1):
            before, after, error = asyncio.run(
                rejected_client_write(endpoint, parameter_name, index / 10)
            )
            assert after == before
            assert error is not None


def test_real_opcua_sandbox_can_force_readback_mismatch():
    with running_sandbox("READBACK_MISMATCH") as endpoint:
        with gateway(endpoint).session() as session:
            result = session.apply_confirmed_parameter_change(
                idempotency_key="b" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )

    assert result.result == "READBACK_MISMATCH"


def test_real_opcua_sandbox_can_expose_external_value_change():
    with running_sandbox("EXTERNAL_CHANGE") as endpoint:
        with gateway(endpoint).session() as session:
            actual = session.read_parameter("pitch")
            rejected = session.apply_confirmed_parameter_change(
                idempotency_key="0" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )

    assert actual == "0.300000"
    assert rejected.result == "EXPECTED_BEFORE_MISMATCH"
    assert rejected.actual_after == "0.300000"
    assert rejected.physical_write_count == 0


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("TIMEOUT", "OPCUA_TIMEOUT"),
        ("COMMUNICATION_FAILURE", "OPCUA_COMMUNICATION_FAILURE"),
    ],
)
def test_real_opcua_sandbox_can_signal_communication_faults(fault: str, code: str):
    with running_sandbox(fault) as endpoint:
        with gateway(endpoint).session() as session:
            with pytest.raises(OpcUaGatewayError) as caught:
                session.read_health()

    assert caught.value.code == code
    assert caught.value.stage == "COMMUNICATION"


def test_unavailable_local_endpoint_is_structured_failure():
    port = unused_port()
    endpoint = f"opc.tcp://127.0.0.1:{port}/tunewise/opcua-sandbox/"
    with pytest.raises(OpcUaGatewayError) as caught:
        with gateway(endpoint).session():
            pass

    assert caught.value.code == "OPCUA_ENDPOINT_UNAVAILABLE"
    assert caught.value.stage == "COMMUNICATION"


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("WRONG_APPLICATION_URI", "OPCUA_APPLICATION_URI_MISMATCH"),
        ("WRONG_NAMESPACE_URI", "OPCUA_NAMESPACE_URI_MISMATCH"),
        ("WRONG_MAPPING_VERSION", "OPCUA_MAPPING_VERSION_MISMATCH"),
        ("WRONG_PITCH_UNIT", "OPCUA_UNIT_MISMATCH"),
        ("WRONG_PITCH_DATATYPE", "OPCUA_DATATYPE_MISMATCH"),
        ("MISSING_METADATA", "OPCUA_METADATA_MISSING"),
        ("WRITABLE_PITCH", "OPCUA_NODE_ACCESS_MISMATCH"),
    ],
)
def test_gateway_fails_closed_on_observed_identity_or_mapping_mismatch(
    fault: str,
    code: str,
):
    with running_sandbox(fault) as endpoint:
        with pytest.raises(OpcUaGatewayError) as caught:
            with gateway(endpoint).session():
                pass

    assert caught.value.code == code
    assert caught.value.stage == "IDENTITY"


def test_atomic_method_is_required_and_generic_write_is_not_exposed():
    with running_sandbox("ATOMIC_UNSUPPORTED") as endpoint:
        with gateway(endpoint).session() as session:
            with pytest.raises(OpcUaGatewayError) as caught:
                session.apply_confirmed_parameter_change(
                    idempotency_key="c" * 64,
                    parameter_name="pitch",
                    expected_before="0.250000",
                    requested_after="0.200000",
                )

    assert caught.value.code == "ATOMIC_EXECUTION_UNSUPPORTED"
    assert not hasattr(session, "write_parameter")


def test_parameter_access_remains_read_only_after_success_and_rejection():
    with running_sandbox() as endpoint:
        assert_client_read_only(*asyncio.run(parameter_access(endpoint, "pitch")))
        with gateway(endpoint).session() as session:
            applied = session.apply_confirmed_parameter_change(
                idempotency_key="2" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
            rejected = session.apply_confirmed_parameter_change(
                idempotency_key="3" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.150000",
            )
        assert applied.result == "APPLIED"
        assert rejected.result == "EXPECTED_BEFORE_MISMATCH"
        assert_client_read_only(*asyncio.run(parameter_access(endpoint, "pitch")))


def test_parameter_access_remains_read_only_after_timeout_and_reconciliation():
    key = "4" * 64
    with running_sandbox("APPLY_THEN_TIMEOUT") as endpoint:
        with pytest.raises(OpcUaGatewayError):
            with gateway(endpoint).session() as session:
                session.apply_confirmed_parameter_change(
                    idempotency_key=key,
                    parameter_name="pitch",
                    expected_before="0.250000",
                    requested_after="0.200000",
                )
        assert_client_read_only(*asyncio.run(parameter_access(endpoint, "pitch")))
        with gateway(endpoint).session() as session:
            assert session.query_execution_result(key) is not None
        assert_client_read_only(*asyncio.run(parameter_access(endpoint, "pitch")))


def test_compare_write_race_rejects_real_client_injection():
    async def scenario():
        runtime = await create_sandbox()
        runtime.compare_completed_event = asyncio.Event()
        runtime.continue_after_compare_event = asyncio.Event()
        await runtime.server.start()
        method_client = Client("opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/")
        writer_client = Client("opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/")
        await method_client.connect()
        await writer_client.connect()
        try:
            namespace_index = (await method_client.get_namespace_array()).index(
                OPCUA_NAMESPACE_URI
            )
            device = method_client.get_node(
                ua.NodeId("TuneWiseSandbox.Device", namespace_index)
            )
            method = method_client.get_node(
                ua.NodeId(
                    "TuneWiseSandbox.Device.ApplyConfirmedParameterChange",
                    namespace_index,
                )
            )
            request = json.dumps(
                {
                    "method_version": OPCUA_ATOMIC_METHOD_VERSION,
                    "idempotency_key": "5" * 64,
                    "parameter_name": "pitch",
                    "expected_before": "0.250000",
                    "requested_after": "0.200000",
                    "node_mapping_version": OPCUA_NODE_MAPPING_VERSION,
                    "observed_identity_hash": "6" * 64,
                }
            )
            method_task = asyncio.create_task(device.call_method(method, request))
            await asyncio.wait_for(runtime.compare_completed_event.wait(), timeout=2)
            pitch = writer_client.get_node(
                ua.NodeId(NODE_MAPPINGS["pitch"].identifier, namespace_index)
            )
            access = await pitch.get_access_level()
            user_access = await pitch.get_user_access_level()
            injection_error = None
            try:
                await pitch.write_value(ua.Variant(0.30, ua.VariantType.Double))
            except UaStatusCodeError as caught:
                injection_error = caught
            value_after_injection = await pitch.read_value()
            runtime.continue_after_compare_event.set()
            result = json.loads(str(await method_task))
            final_value = await pitch.read_value()
            return (
                result,
                final_value,
                value_after_injection,
                injection_error,
                access,
                user_access,
                runtime.physical_write_count,
            )
        finally:
            runtime.continue_after_compare_event.set()
            await method_client.disconnect()
            await writer_client.disconnect()
            await runtime.server.stop()

    (
        result,
        final_value,
        value_after_injection,
        injection_error,
        access,
        user_access,
        physical_write_count,
    ) = asyncio.run(scenario())

    assert injection_error is not None
    assert value_after_injection == 0.25
    assert result["result"] == "APPLIED"
    assert result["actual_before"] == "0.250000"
    assert result["actual_after"] == "0.200000"
    assert final_value == 0.20
    assert physical_write_count == 1
    assert_client_read_only(access, user_access)


def test_device_side_idempotency_survives_sandbox_restart(tmp_path):
    state_file = tmp_path / "sandbox-executions.json"
    key = "d" * 64
    with running_sandbox(state_file=state_file) as endpoint:
        with gateway(endpoint).session() as session:
            first = session.apply_confirmed_parameter_change(
                idempotency_key=key,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
            repeated = session.apply_confirmed_parameter_change(
                idempotency_key=key,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
    with running_sandbox(state_file=state_file) as endpoint:
        with gateway(endpoint).session() as session:
            queried = session.query_execution_result(key)
            after_restart = session.apply_confirmed_parameter_change(
                idempotency_key=key,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
            actual = session.read_parameter("pitch")

    assert first == repeated == queried == after_restart
    assert first.result == "APPLIED"
    assert first.physical_write_count == 1
    assert actual == "0.200000"


def test_server_applies_then_client_times_out_and_read_only_query_recovers():
    key = "d" * 64
    with running_sandbox("APPLY_THEN_TIMEOUT") as endpoint:
        with pytest.raises(OpcUaGatewayError) as caught:
            with gateway(endpoint).session() as session:
                session.apply_confirmed_parameter_change(
                    idempotency_key=key,
                    parameter_name="pitch",
                    expected_before="0.250000",
                    requested_after="0.200000",
                )
        with gateway(endpoint).session() as recovery_session:
            recovered = recovery_session.query_execution_result(key)
            actual = recovery_session.read_parameter("pitch")

    assert caught.value.code == "OPCUA_UNKNOWN_OUTCOME"
    assert recovered is not None
    assert recovered.result == "APPLIED"
    assert recovered.physical_write_count == 1
    assert actual == "0.200000"


def test_different_idempotency_key_rechecks_expected_before_and_writes_zero():
    with running_sandbox() as endpoint:
        with gateway(endpoint).session() as session:
            first = session.apply_confirmed_parameter_change(
                idempotency_key="e" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )
            second = session.apply_confirmed_parameter_change(
                idempotency_key="f" * 64,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.150000",
            )

    assert first.result == "APPLIED"
    assert second.result == "EXPECTED_BEFORE_MISMATCH"
    assert second.actual_before == "0.200000"
    assert second.actual_after == "0.200000"
    assert second.physical_write_count == 0


def test_concurrent_same_idempotency_key_is_one_physical_write():
    key = "7" * 64

    def apply(endpoint: str):
        with gateway(endpoint).session() as session:
            return session.apply_confirmed_parameter_change(
                idempotency_key=key,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )

    with running_sandbox() as endpoint:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(apply, (endpoint, endpoint)))

    assert {item.result for item in results} == {"APPLIED"}
    assert {item.physical_write_count for item in results} == {1}
    assert len({item.executed_at for item in results}) == 1


def test_concurrent_different_keys_cannot_overwrite_changed_value():
    keys = ("8" * 64, "9" * 64)

    def apply(item: tuple[str, str]):
        endpoint, key = item
        with gateway(endpoint).session() as session:
            return session.apply_confirmed_parameter_change(
                idempotency_key=key,
                parameter_name="pitch",
                expected_before="0.250000",
                requested_after="0.200000",
            )

    with running_sandbox() as endpoint:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(apply, ((endpoint, key) for key in keys)))

    assert sorted(item.result for item in results) == [
        "APPLIED",
        "EXPECTED_BEFORE_MISMATCH",
    ]
    assert sum(item.physical_write_count for item in results) == 1
