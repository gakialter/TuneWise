from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
import json
from dataclasses import replace
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tunewise.parameter_planning import SafetyValidationResult, ValidationCheck
from tunewise.case_retrieval import ApprovedCaseAssetLoader
from tunewise.store import TaskStore

from .test_parameter_planning_api import _prepare, make_planning_client


def _prepare_plan_ready(client):
    task, diagnostic, retrieval = _prepare(client)
    response = client.post(
        f"/api/tasks/{task['task_id']}/parameter-plans",
        json={
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "case_retrieval_result_id": retrieval["retrieval_result_id"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["task"], payload["planning"]


def test_plan_ready_candidate_can_be_confirmed_atomically(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    confirmed = payload["confirmed_plan"]
    assert payload["task"] == stored
    assert stored["status"] == "PLAN_CONFIRMED"
    assert stored["confirmed_plan"] == confirmed
    assert confirmed["confirmed_plan_version"] == "tw-confirmed-plan-v1"
    assert confirmed["status"] == "VALID"
    assert confirmed["candidate_id"] == candidate["candidate_id"]
    assert confirmed["candidate_hash"] == candidate["candidate_hash"]
    assert confirmed["current_values"] == candidate["current_values"]
    assert confirmed["proposed_values"] == candidate["proposed_values"]
    assert confirmed["actor_id"] == "demo-aa-engineer"
    assert confirmed["actor_role"] == "AA_PROCESS_ENGINEER"
    assert confirmed["display_name"] == "AA工艺工程师"
    assert len(confirmed["confirmed_plan_hash"]) == 64

    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposed_values", {"pitch": "0.000000"}),
        ("deltas", {"pitch": "-0.050000"}),
        ("actor_id", "attacker"),
        ("rule_set_version", "client-rule"),
    ],
)
def test_confirmation_rejects_server_authoritative_fields(
    tmp_path, field, value
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
                field: value,
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FORBIDDEN_CONFIRMATION_FIELDS"
    assert field in response.json()["error"]["actual_version"]
    assert stored["status"] == "PLAN_READY"
    assert stored["confirmed_plan"] is None
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "FORBIDDEN_CONFIRMATION_FIELDS"


def test_candidate_hash_tampering_is_rejected_and_audited(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": "f" * 64,
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"][-1]

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CANDIDATE_HASH_MISMATCH"
    assert error["expected_hash"] == candidate["candidate_hash"]
    assert error["actual_hash"] == "f" * 64
    assert stored["status"] == "PLAN_READY"
    assert stored["confirmed_plan"] is None
    assert audit["result"] == "REJECTED"
    assert audit["expected_hash"] == candidate["candidate_hash"]
    assert audit["actual_hash"] == "f" * 64


def test_confirmation_reuses_parameter_safety_validator(tmp_path, monkeypatch) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        calls = 0

        def reject_on_confirmation(_self, current_candidate, *, snapshot, versions):
            nonlocal calls
            calls += 1
            return SafetyValidationResult(
                validation_status="REJECTED",
                validation_checks=(
                    ValidationCheck(
                        check_code="TEST_CONFIRMATION_REVALIDATION",
                        status="FAILED",
                        detail="测试确认复核拒绝。",
                    ),
                ),
                rejection_reasons=("TEST_CONFIRMATION_REVALIDATION",),
                safety_rule_version=versions.safety_rule_version,
                constraint_snapshot_version=snapshot.snapshot_version,
                validated_candidate_hash=current_candidate.candidate_hash,
            )

        monkeypatch.setattr(
            "tunewise.service.ParameterSafetyValidator.validate",
            reject_on_confirmation,
        )
        monkeypatch.setattr(
            "tunewise.service.TaskService._validated_current_planning",
            lambda _service, current_task, current_planning: (
                current_task,
                current_planning,
            ),
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert calls >= 1
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SAFETY_REVALIDATION_FAILED"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0
        status = connection.execute("SELECT payload_json FROM tasks").fetchone()[0]
        assert '"status":"PLAN_READY"' in status


def test_same_confirmation_is_idempotent_and_different_candidate_conflicts(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        first_candidate, second_candidate = planning["ordered_candidates"][:2]
        request = {
            "candidate_id": first_candidate["candidate_id"],
            "candidate_hash": first_candidate["candidate_hash"],
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
        )
        second = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
        )
        conflict = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": second_candidate["candidate_id"],
                "candidate_hash": second_candidate["candidate_hash"],
            },
        )

    assert second.status_code == 200
    assert second.json()["confirmed_plan"] == first.json()["confirmed_plan"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CONFIRMED_PLAN_CONFLICT"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE result = 'SUCCESS'"
        ).fetchone()[0] == 1


def test_stale_plan_is_not_returned_as_successful_idempotent_confirmation(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        request = {
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
        }
        client.post(f"/api/tasks/{task['task_id']}/confirmed-plans", json=request)
        _change_measurement_parameter(tmp_path / "tunewise.db", task["task_id"])
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "CANDIDATE_STALE"


def test_concurrent_same_confirmation_creates_at_most_one_plan(tmp_path) -> None:
    client, app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        request = {
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
        }

        def confirm():
            thread_client = TestClient(app)
            try:
                return thread_client.post(
                    f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
                )
            finally:
                thread_client.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = tuple(pool.map(lambda _index: confirm(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert (
        responses[0].json()["confirmed_plan"]["confirmed_plan_hash"]
        == responses[1].json()["confirmed_plan"]["confirmed_plan_hash"]
    )
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 1


def test_confirmed_plan_has_no_parameter_patch_business_interface(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        confirmed = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        ).json()["confirmed_plan"]
        response = client.patch(
            f"/api/tasks/{task['task_id']}/confirmed-plans/{confirmed['confirmed_plan_id']}",
            json={"proposed_values": {"pitch": "0.000000"}},
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code in {404, 405}
    assert stored["confirmed_plan"] == confirmed


def _change_measurement_parameter(database_path, task_id, value="0.100000"):
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT sample_index, payload_json FROM measurements "
            "WHERE task_id = ? ORDER BY sample_index LIMIT 1",
            (task_id,),
        ).fetchone()
        payload = json.loads(row[1])
        original = payload["pitch"]
        payload["pitch"] = value
        connection.execute(
            "UPDATE measurements SET payload_json = ? "
            "WHERE task_id = ? AND sample_index = ?",
            (json.dumps(payload), task_id, row[0]),
        )
    return original


def test_confirmation_transaction_rechecks_state_at_write_boundary(
    tmp_path, monkeypatch
) -> None:
    client, _app = make_planning_client(tmp_path)
    original_save = TaskStore.save_confirmation

    def mutate_before_save(
        store,
        updated_task,
        plan,
        event,
        expected_state_token,
        expected_file_asset_token,
        file_asset_token_reader,
    ):
        _change_measurement_parameter(
            tmp_path / "tunewise.db", updated_task.task_id, "0.150000"
        )
        return original_save(
            store,
            updated_task,
            plan,
            event,
            expected_state_token,
            expected_file_asset_token,
            file_asset_token_reader,
        )

    monkeypatch.setattr(TaskStore, "save_confirmation", mutate_before_save)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE result = 'SUCCESS'"
        ).fetchone()[0] == 0
        assert '"status":"PLAN_READY"' in connection.execute(
            "SELECT payload_json FROM tasks WHERE task_id = ?", (task["task_id"],)
        ).fetchone()[0]


def test_persisted_planning_tamper_is_structured_and_audited(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT planning_result_id, payload_json FROM parameter_planning_results "
                "WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            payload = json.loads(row[1])
            payload["ordered_candidates"][0]["proposed_values"]["pitch"] = "0.000000"
            connection.execute(
                "UPDATE parameter_planning_results SET payload_json = ? "
                "WHERE planning_result_id = ?",
                (json.dumps(payload), row[0]),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLANNING_RESULT_STALE"
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "PLANNING_RESULT_STALE"


def test_identical_rejections_are_each_appended_to_audit_log(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        request = {
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": "f" * 64,
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
        )
        second = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert first.status_code == second.status_code == 409
    rejected = [event for event in audit if event["result"] == "REJECTED"]
    assert len(rejected) == 2
    assert rejected[0]["event_id"] != rejected[1]["event_id"]


def test_confirmed_plan_history_allows_future_versions_after_stale(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        client.post("/api/tasks/initial")
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        indexes = connection.execute("PRAGMA index_list('confirmed_plans')").fetchall()
        task_unique_indexes = []
        for index in indexes:
            columns = connection.execute(
                f"PRAGMA index_info('{index[1]}')"
            ).fetchall()
            if [column[2] for column in columns] == ["task_id"] and index[2]:
                task_unique_indexes.append(index[1])

    assert task_unique_indexes == []


def test_upstream_measurement_change_blocks_confirmation_as_stale(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        _change_measurement_parameter(
            tmp_path / "tunewise.db", task["task_id"]
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    assert audit[-1]["action"] == "CONFIRM_PARAMETER_PLAN"
    assert audit[-1]["rejection_code"] == "CANDIDATE_STALE"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0


def test_measurement_change_marks_confirmed_plan_stale_permanently(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        original = _change_measurement_parameter(
            tmp_path / "tunewise.db", task["task_id"]
        )
        startup_task = client.post("/api/tasks/initial").json()
        stale = startup_task["confirmed_plan"]
        _change_measurement_parameter(
            tmp_path / "tunewise.db", task["task_id"], original
        )
        still_stale = client.get(
            f"/api/tasks/{task['task_id']}"
        ).json()["confirmed_plan"]

    assert stale["status"] == "STALE"
    assert startup_task["task_id"] == task["task_id"]
    assert "INPUT_DATA_CHANGED" in stale["stale_reason_codes"]
    assert still_stale["status"] == "STALE"
    assert still_stale["stale_reason_codes"] == stale["stale_reason_codes"]


def test_candidate_must_exist_in_latest_planning_result(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, _planning = _prepare_plan_ready(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={"candidate_id": "missing", "candidate_hash": "f" * 64},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"


def test_non_passed_candidate_is_rejected(tmp_path, monkeypatch) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        original = client.app.state
        from tunewise.store import TaskStore

        stored_method = TaskStore.get_current_parameter_planning

        def rejected_candidate(store, task_id):
            current = stored_method(store, task_id)
            assert current is not None
            candidate = replace(
                current.ordered_candidates[0], validation_status="REJECTED"
            )
            return replace(current, ordered_candidates=(candidate,))

        monkeypatch.setattr(
            "tunewise.store.TaskStore.get_current_parameter_planning",
            rejected_candidate,
        )
        candidate = planning["ordered_candidates"][0]
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert original is not None
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_PASSED"


def test_server_recalculates_candidate_hash_before_confirmation(tmp_path, monkeypatch) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        monkeypatch.setattr(
            "tunewise.service.candidate_content_hash", lambda _candidate: "f" * 64
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "CANDIDATE_HASH_MISMATCH"
    assert error["expected_hash"] == "f" * 64
    assert error["actual_hash"] == candidate["candidate_hash"]


def test_concurrent_different_candidates_allows_only_one_success(tmp_path) -> None:
    client, app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        requests = [
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            }
            for candidate in planning["ordered_candidates"][:2]
        ]

        def confirm(request):
            thread_client = TestClient(app)
            try:
                return thread_client.post(
                    f"/api/tasks/{task['task_id']}/confirmed-plans", json=request
                )
            finally:
                thread_client.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = tuple(pool.map(confirm, requests))

    assert sorted(response.status_code for response in responses) == [200, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["error"]["code"] == "CONFIRMED_PLAN_CONFLICT"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 1


def test_confirmation_transaction_rolls_back_if_audit_insert_fails(tmp_path) -> None:
    client, app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            connection.execute(
                "CREATE TRIGGER reject_confirmation_audit "
                "BEFORE INSERT ON audit_events BEGIN "
                "SELECT RAISE(ABORT, 'audit rejected'); END"
            )
        no_raise_client = TestClient(app, raise_server_exceptions=False)
        with no_raise_client:
            response = no_raise_client.post(
                f"/api/tasks/{task['task_id']}/confirmed-plans",
                json={
                    "candidate_id": candidate["candidate_id"],
                    "candidate_hash": candidate["candidate_hash"],
                },
            )

    assert response.status_code == 500
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM current_confirmed_plans").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
        payload = connection.execute("SELECT payload_json FROM tasks").fetchone()[0]
        assert '"status":"PLAN_READY"' in payload


def test_success_audit_is_complete_and_has_no_mutation_interface(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        confirmed = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        ).json()["confirmed_plan"]
        events = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]
        patch_response = client.patch(
            f"/api/tasks/{task['task_id']}/audit-events/{events[0]['event_id']}",
            json={"result": "REJECTED"},
        )
        delete_response = client.delete(
            f"/api/tasks/{task['task_id']}/audit-events/{events[0]['event_id']}"
        )

    assert len(events) == 1
    event = events[0]
    assert event["action"] == "CONFIRM_PARAMETER_PLAN"
    assert event["result"] == "SUCCESS"
    assert event["actor_id"] == "demo-aa-engineer"
    assert event["actor_role"] == "AA_PROCESS_ENGINEER"
    assert event["display_name"] == "AA工艺工程师"
    assert event["candidate_id"] == candidate["candidate_id"]
    assert event["candidate_hash"] == candidate["candidate_hash"]
    assert event["confirmed_plan_id"] == confirmed["confirmed_plan_id"]
    assert event["confirmed_plan_hash"] == confirmed["confirmed_plan_hash"]
    assert event["planning_result_id"] == planning["planning_result_id"]
    assert event["planning_result_version"] == planning["planning_result_version"]
    assert event["direction_rule_version"] == planning["direction_rule_version"]
    assert event["safety_rule_version"] == planning["safety_rule_version"]
    assert event["planning_rule_version"] == planning["planning_rule_version"]
    assert patch_response.status_code in {404, 405}
    assert delete_response.status_code in {404, 405}


@pytest.mark.parametrize(
    ("table", "mutate", "reason"),
    [
        (
            "control_limit_snapshots",
            lambda payload: payload.update({"asymmetry_limit": "0.990000"}),
            "CONTROL_LIMIT_SNAPSHOT_CHANGED",
        ),
        (
            "parameter_constraint_snapshots",
            lambda payload: payload["constraints"]["pitch"].update(
                {"maximum": "0.950000"}
            ),
            "PARAMETER_CONSTRAINT_SNAPSHOT_CHANGED",
        ),
    ],
)
def test_snapshot_content_change_marks_confirmed_plan_stale(
    tmp_path, table, mutate, reason
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            payload = json.loads(row[0])
            mutate(payload)
            connection.execute(
                f"UPDATE {table} SET payload_json = ? WHERE task_id = ?",
                (json.dumps(payload), task["task_id"]),
            )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert stored["confirmed_plan"]["status"] == "STALE"
    assert reason in stored["confirmed_plan"]["stale_reason_codes"]


def test_rule_asset_change_marks_confirmed_plan_stale(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        rules_path = tmp_path / "planning" / "planning-rules.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        rules["maximum_candidate_count"] = 2
        rules_path.write_text(json.dumps(rules), encoding="utf-8")
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert stored["confirmed_plan"]["status"] == "STALE"
    assert "RULE_VERSION_CHANGED" in stored["confirmed_plan"]["stale_reason_codes"]


@pytest.mark.parametrize(
    ("relative_path", "reason"),
    [
        (("diagnostic", "model.json"), "ASSET_HASH_MISMATCH"),
        (("demo", "aa-demo-batch.csv"), "ASSET_HASH_MISMATCH"),
    ],
)
def test_current_diagnostic_and_dataset_asset_changes_mark_plan_stale(
    tmp_path, relative_path, reason
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        asset_path = tmp_path.joinpath(*relative_path)
        asset_path.write_bytes(asset_path.read_bytes() + b" ")
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert stored["confirmed_plan"]["status"] == "STALE"
    assert reason in stored["confirmed_plan"]["stale_reason_codes"]


def test_stored_dataset_manifest_change_marks_plan_stale_without_secret_access(
    tmp_path,
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM dataset_manifests WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            payload = json.loads(row[0])
            payload["product_model"] = "changed-model"
            connection.execute(
                "UPDATE dataset_manifests SET payload_json = ? WHERE task_id = ?",
                (json.dumps(payload), task["task_id"]),
            )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert stored["confirmed_plan"]["status"] == "STALE"
    assert "ASSET_HASH_MISMATCH" in stored["confirmed_plan"]["stale_reason_codes"]


def test_supporting_case_asset_change_marks_case_guided_plan_stale(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][-1]
        assert candidate["supporting_case_ids"]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        cases_path = tmp_path / "cases" / "approved-cases.json"
        cases_path.write_text(
            cases_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert stored["confirmed_plan"]["status"] == "STALE"
    assert "SUPPORTING_CASE_CHANGED" in stored["confirmed_plan"]["stale_reason_codes"]


def test_confirmation_has_zero_simulator_llm_network_and_hidden_asset_access(
    tmp_path, monkeypatch
) -> None:
    client, app = make_planning_client(tmp_path)
    original_read_bytes = Path.read_bytes
    reads: list[Path] = []
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][-1]

        def record_read(path: Path) -> bytes:
            reads.append(path.resolve())
            return original_read_bytes(path)

        def reject_network(*_args, **_kwargs):
            app.state.planning_boundary_audit.record("external_network_requests")
            raise AssertionError("confirmation attempted an external network request")

        monkeypatch.setattr(Path, "read_bytes", record_read)
        monkeypatch.setattr(socket.socket, "connect", reject_network)
        monkeypatch.setattr(
            ApprovedCaseAssetLoader,
            "load",
            lambda _loader: (_ for _ in ()).throw(
                AssertionError("confirmation parsed historical case outcomes")
            ),
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert response.status_code == 200
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
    assert reads
    assert all(
        "fault" not in path.name.lower()
        and "scenario" not in path.name.lower()
        and "hidden" not in path.name.lower()
        for path in reads
    )
    assert all(path.name != "dataset-manifest.json" for path in reads)


def test_embedded_task_planning_tamper_is_structurally_rejected_and_audited(
    tmp_path,
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            payload = json.loads(row[0])
            payload["parameter_planning_result"]["ordered_candidates"][0][
                "proposed_values"
            ]["pitch"] = "0.999999"
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (json.dumps(payload), task["task_id"]),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLANNING_RESULT_STALE"
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "PLANNING_RESULT_STALE"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0
        stored_status = json.loads(
            connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()[0]
        )["status"]
    assert stored_status == "PLAN_READY"


@pytest.mark.parametrize(
    "tampered_payload",
    (
        "{",
        json.dumps({"ordered_cases": [], "retrieval_result_version": "changed"}),
    ),
)
def test_tampered_case_retrieval_projection_is_rejected_without_unstructured_500(
    tmp_path, tampered_payload
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            connection.execute(
                "UPDATE case_retrieval_results SET payload_json = ? WHERE task_id = ?",
                (tampered_payload, task["task_id"]),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "CANDIDATE_STALE"


@pytest.mark.parametrize(
    "table",
    (
        "control_limit_snapshots",
        "parameter_constraint_snapshots",
        "batches",
        "measurements",
    ),
)
def test_malformed_confirmation_input_is_structurally_rejected_and_audited(
    tmp_path, table
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            connection.execute(
                f"UPDATE {table} SET payload_json = ? WHERE task_id = ?",
                ("{", task["task_id"]),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    assert audit[-1]["result"] == "REJECTED"
    assert audit[-1]["rejection_code"] == "CANDIDATE_STALE"


def test_public_identity_assets_are_rechecked_inside_confirmation_transaction(
    tmp_path, monkeypatch
) -> None:
    client, _app = make_planning_client(tmp_path)
    original_save = TaskStore.save_confirmation
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]

        def mutate_public_asset_before_save(store, *args, **kwargs):
            version_path = tmp_path / "public" / "version.json"
            version_path.write_bytes(version_path.read_bytes() + b" ")
            return original_save(store, *args, **kwargs)

        monkeypatch.setattr(
            TaskStore,
            "save_confirmation",
            mutate_public_asset_before_save,
        )
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        audit = client.get(
            f"/api/tasks/{task['task_id']}/audit-events"
        ).json()["audit_events"]

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_STALE"
    assert audit[-1]["result"] == "REJECTED"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM confirmed_plans").fetchone()[0] == 0


def test_tw06_retrieval_rows_receive_safe_confirmation_hashes_on_upgrade(
    tmp_path,
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            connection.execute(
                "UPDATE case_retrieval_results SET payload_hash = NULL, "
                "safe_payload_hash = NULL WHERE task_id = ?",
                (task["task_id"],),
            )
        TaskStore(tmp_path / "tunewise.db")
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            hashes = connection.execute(
                "SELECT payload_hash, safe_payload_hash "
                "FROM case_retrieval_results WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
        response = client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )

    assert hashes[0] is not None
    assert hashes[1] is not None
    assert response.status_code == 200


def test_confirmed_plan_hash_is_stable_across_independent_runtime_timestamps(
    tmp_path,
) -> None:
    hashes = []
    for name in ("first", "second"):
        client, _app = make_planning_client(tmp_path / name)
        with client:
            task, planning = _prepare_plan_ready(client)
            candidate = planning["ordered_candidates"][0]
            response = client.post(
                f"/api/tasks/{task['task_id']}/confirmed-plans",
                json={
                    "candidate_id": candidate["candidate_id"],
                    "candidate_hash": candidate["candidate_hash"],
                },
            )
        assert response.status_code == 200
        hashes.append(response.json()["confirmed_plan"]["confirmed_plan_hash"])

    assert hashes[0] == hashes[1]


def test_stale_status_payload_cannot_be_rewritten_to_valid(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, planning = _prepare_plan_ready(client)
        candidate = planning["ordered_candidates"][0]
        client.post(
            f"/api/tasks/{task['task_id']}/confirmed-plans",
            json={
                "candidate_id": candidate["candidate_id"],
                "candidate_hash": candidate["candidate_hash"],
            },
        )
        _change_measurement_parameter(tmp_path / "tunewise.db", task["task_id"])
        stale = client.get(f"/api/tasks/{task['task_id']}")
        assert stale.json()["confirmed_plan"]["status"] == "STALE"
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT confirmed_plan_id, payload_json FROM confirmed_plans "
                "WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            payload = json.loads(row[1])
            payload["status"] = "VALID"
            payload["stale_reason_codes"] = []
            connection.execute(
                "UPDATE confirmed_plans SET payload_json = ? "
                "WHERE confirmed_plan_id = ?",
                (json.dumps(payload), row[0]),
            )
        response = client.get(f"/api/tasks/{task['task_id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIRMED_PLAN_STATUS_MISMATCH"
