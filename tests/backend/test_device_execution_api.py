from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tunewise.opcua_gateway import (
    OPCUA_SANDBOX_MODE,
    DeviceExecutionConfig,
    OpcUaGatewayError,
)

from .test_device_execution import FakeGateway
from .test_replay_api import (
    make_replay_client,
    prepare_confirmed,
    replay_request,
)
from .test_opcua_sandbox import running_sandbox


def prepare_replayed(client):
    task, plan = prepare_confirmed(client)
    response = client.post(
        f"/api/tasks/{task['task_id']}/replays",
        json=replay_request(task, plan),
    )
    assert response.status_code == 200, response.text
    return response.json()["task"], plan


def request_payload(plan: dict) -> dict:
    return {
        "confirmed_plan_id": plan["confirmed_plan_id"],
        "confirmed_plan_hash": plan["confirmed_plan_hash"],
        "execution_mode": OPCUA_SANDBOX_MODE,
        "sandbox_execution_acknowledged": True,
    }


def test_device_execution_api_uses_server_mapping_and_returns_immutable_receipt(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    client, app = make_replay_client(
        tmp_path,
        device_execution_config=DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
        ),
        opcua_gateway=gateway,
    )
    with client:
        task, plan = prepare_replayed(client)
        eligibility = client.get(
            f"/api/tasks/{task['task_id']}/device-executions/eligibility",
            params={
                "confirmed_plan_id": plan["confirmed_plan_id"],
                "confirmed_plan_hash": plan["confirmed_plan_hash"],
            },
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json=request_payload(plan),
        )
        repeated = client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json=request_payload(plan),
        )
        execution = response.json()["device_execution"]
        queried = client.get(
            f"/api/tasks/{task['task_id']}/device-executions/"
            f"{execution['device_execution_id']}"
        )
        receipt = client.get(
            f"/api/tasks/{task['task_id']}/device-executions/"
            f"{execution['device_execution_id']}/receipt"
        )

    assert eligibility.status_code == 200
    assert eligibility.json()["eligible"] is True
    assert eligibility.json()["parameter_name"] == "pitch"
    assert response.status_code == 201
    assert execution["execution_status"] == "SUCCEEDED"
    assert execution["expected_before_value"] == "0.250000"
    assert execution["actual_before_value"] == "0.250000"
    assert execution["requested_after_value"] == "0.200000"
    assert execution["actual_after_value"] == "0.200000"
    assert len(execution["receipt_hash"]) == 64
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True
    assert repeated.json()["device_execution"] == execution
    assert queried.json()["device_execution"] == execution
    assert receipt.json()["receipt"] == execution
    assert gateway.write_count == 1
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 2
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_receipts"
        ).fetchone()[0] == 1


def test_device_execution_api_rejects_client_endpoint_node_parameter_and_value(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    client, _app = make_replay_client(
        tmp_path,
        device_execution_config=DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
        ),
        opcua_gateway=gateway,
    )
    with client:
        task, plan = prepare_replayed(client)
        payload = {
            **request_payload(plan),
            "endpoint": "opc.tcp://attacker.example:4840/",
            "node_id": "ns=2;s=attacker",
            "parameter_name": "pitch",
            "parameter_value": "999.000000",
        }
        response = client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json=payload,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == (
        "DEVICE_EXECUTION_REQUEST_FORBIDDEN_FIELDS"
    )
    assert "device_execution" not in response.json()
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_claims"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_receipts"
        ).fetchone()[0] == 0
    assert gateway.write_count == 0


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("sandbox_execution_acknowledged", "yes"),
        ("sandbox_execution_acknowledged", 1),
        ("sandbox_execution_acknowledged", None),
        ("execution_mode", "PRODUCTION"),
    ),
)
def test_device_execution_api_rejects_coerced_acknowledgement_and_other_modes(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    gateway = FakeGateway()
    client, _app = make_replay_client(
        tmp_path,
        device_execution_config=DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
        ),
        opcua_gateway=gateway,
    )
    with client:
        task, plan = prepare_replayed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json={**request_payload(plan), field: invalid_value},
        )

    payload = response.json()
    assert response.status_code == 422
    assert payload["error"]["code"] == "DEVICE_EXECUTION_REQUEST_INVALID"
    assert "device_execution" not in payload
    assert gateway.write_count == 0


def test_nonexistent_task_and_malformed_requests_do_not_create_audit_rows(
    tmp_path: Path,
) -> None:
    gateway = FakeGateway()
    client, _app = make_replay_client(
        tmp_path,
        device_execution_config=DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
        ),
        opcua_gateway=gateway,
    )
    first_body = {"endpoint": "opc.tcp://attacker.invalid:4840/a"}
    second_body = {"endpoint": "opc.tcp://attacker.invalid:4840/b"}
    with client:
        first = client.post(
            "/api/tasks/task-a/device-executions",
            json=first_body,
        )
        repeated = client.post(
            "/api/tasks/task-a/device-executions",
            json=first_body,
        )
        different_body = client.post(
            "/api/tasks/task-a/device-executions",
            json=second_body,
        )
        different_task = client.post(
            "/api/tasks/task-b/device-executions",
            json=first_body,
        )

    assert {first.status_code, repeated.status_code, different_body.status_code, different_task.status_code} == {404}
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_claims"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_receipts"
        ).fetchone()[0] == 0
    assert gateway.write_count == 0


def test_existing_task_business_rejection_is_audited(tmp_path: Path) -> None:
    gateway = FakeGateway()
    client, _app = make_replay_client(
        tmp_path,
        device_execution_config=DeviceExecutionConfig(
            enabled=True,
            mode=OPCUA_SANDBOX_MODE,
            runtime_profile="OPCUA_SANDBOX_DEMO",
        ),
        opcua_gateway=gateway,
    )
    with client:
        task, plan = prepare_replayed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json={
                **request_payload(plan),
                "sandbox_execution_acknowledged": False,
            },
        )

    assert response.status_code == 201
    receipt = response.json()["device_execution"]
    assert receipt["execution_status"] == "REJECTED"
    assert receipt["failure_code"] == "DEVICE_EXECUTION_ACKNOWLEDGEMENT_REQUIRED"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_claims"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM device_execution_receipts"
        ).fetchone()[0] == 1
    assert gateway.write_count == 0


def test_app_startup_reconciles_unknown_outcome_without_rewriting(tmp_path: Path) -> None:
    gateway = FakeGateway(
        after_apply_error=OpcUaGatewayError(
            "OPCUA_UNKNOWN_OUTCOME", "response lost", "COMMUNICATION"
        )
    )
    config = DeviceExecutionConfig(
        enabled=True,
        mode=OPCUA_SANDBOX_MODE,
        runtime_profile="OPCUA_SANDBOX_DEMO",
    )
    first_client, _first_app = make_replay_client(
        tmp_path, device_execution_config=config, opcua_gateway=gateway
    )
    with first_client:
        task, plan = prepare_replayed(first_client)
        unknown_response = first_client.post(
            f"/api/tasks/{task['task_id']}/device-executions",
            json=request_payload(plan),
        )
    unknown = unknown_response.json()["device_execution"]
    assert unknown["execution_status"] == "UNKNOWN_OUTCOME"

    gateway.after_apply_error = None
    restarted_client, restarted_app = make_replay_client(
        tmp_path, device_execution_config=config, opcua_gateway=gateway
    )
    with restarted_client:
        recovered_response = restarted_client.get(
            f"/api/tasks/{task['task_id']}/device-executions/"
            f"{unknown['device_execution_id']}/receipt"
        )

    recovered = recovered_response.json()["receipt"]
    assert restarted_app.state.device_execution_reconciliation_count == 1
    assert recovered["execution_status"] == "SUCCEEDED"
    assert recovered["actual_after_value"] == "0.200000"
    assert gateway.write_count == 1


def test_full_api_writes_and_reads_back_through_real_local_opcua_sandbox(
    tmp_path: Path,
) -> None:
    with running_sandbox() as endpoint:
        client, _app = make_replay_client(
            tmp_path,
            device_execution_config=DeviceExecutionConfig(
                enabled=True,
                mode=OPCUA_SANDBOX_MODE,
                runtime_profile="OPCUA_SANDBOX_DEMO",
                endpoint=endpoint,
                request_timeout_seconds=1,
            ),
        )
        with client:
            task, plan = prepare_replayed(client)
            response = client.post(
                f"/api/tasks/{task['task_id']}/device-executions",
                json=request_payload(plan),
            )

    assert response.status_code == 201
    receipt = response.json()["device_execution"]
    assert receipt["execution_status"] == "SUCCEEDED"
    assert receipt["actual_before_value"] == "0.250000"
    assert receipt["requested_after_value"] == "0.200000"
    assert receipt["actual_after_value"] == "0.200000"
