from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.generate_approved_case_index import generate as generate_cases
from tools.generate_demo_assets import generate as generate_demo
from tools.generate_diagnostic_assets import generate as generate_diagnostic
from tools.generate_parameter_planning_assets import generate as generate_planning
from tools.generate_replay_assets import generate as generate_replay
from tunewise.api import create_app
from tunewise.simulator_gateway import canonical_json_bytes, canonical_manifest_hash

from .asset_fixtures import write_public_assets
from .test_plan_confirmation_api import _change_measurement_parameter, _prepare_plan_ready


def make_replay_client(tmp_path: Path, mutate_replay=None) -> tuple[TestClient, object]:
    public_root = tmp_path / "public"
    public_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate_demo(demo_root, 20260718)
    demo_hash = hashlib.sha256((demo_root / "dataset-manifest.json").read_bytes()).hexdigest()
    diagnostic_root = tmp_path / "diagnostic"
    generate_diagnostic(diagnostic_root, 20260718)
    diagnostic_hash = hashlib.sha256((diagnostic_root / "manifest.json").read_bytes()).hexdigest()
    case_root = tmp_path / "cases"
    generate_cases(case_root, 20260718)
    case_hash = hashlib.sha256((case_root / "manifest.json").read_bytes()).hexdigest()
    planning_root = tmp_path / "planning"
    generate_planning(planning_root)
    planning_hash = hashlib.sha256((planning_root / "manifest.json").read_bytes()).hexdigest()
    replay_root = tmp_path / "simulator-private"
    replay_manifest = generate_replay(replay_root)
    if mutate_replay is not None:
        mutate_replay(replay_root)
        replay_manifest = json.loads((replay_root / "manifest.json").read_text(encoding="utf-8"))
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=public_hash,
        database_path=tmp_path / "tunewise.db",
        demo_asset_root=demo_root,
        expected_dataset_manifest_hash=demo_hash,
        diagnostic_asset_root=diagnostic_root,
        expected_diagnostic_manifest_hash=diagnostic_hash,
        case_asset_root=case_root,
        expected_case_manifest_hash=case_hash,
        planning_asset_root=planning_root,
        expected_planning_manifest_hash=planning_hash,
        replay_asset_root=replay_root,
        expected_replay_manifest_hash=replay_manifest["canonical_manifest_hash"],
    )
    return TestClient(app), app


def prepare_confirmed(client: TestClient) -> tuple[dict, dict]:
    task, planning = _prepare_plan_ready(client)
    candidate = planning["ordered_candidates"][0]
    response = client.post(
        f"/api/tasks/{task['task_id']}/confirmed-plans",
        json={
            "candidate_id": candidate["candidate_id"],
            "candidate_hash": candidate["candidate_hash"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["task"], response.json()["confirmed_plan"]


def replay_request(task: dict, plan: dict, **overrides) -> dict:
    return {
        "task_id": task["task_id"],
        "confirmed_plan_id": plan["confirmed_plan_id"],
        "confirmed_plan_hash": plan["confirmed_plan_hash"],
        "request_idempotency_key": "tw-replay-request-001",
        **overrides,
    }


def test_valid_confirmed_plan_runs_paired_replay_and_commits_result_state_and_audit(
    tmp_path: Path,
) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()
        audit = client.get(f"/api/tasks/{task['task_id']}/audit-events").json()["audit_events"]

    assert response.status_code == 200, response.text
    payload = response.json()
    result = payload["replay_result"]
    assert payload["task"] == stored
    assert stored["status"] == "REPLAYED"
    assert stored["replay_result"] == result
    assert result["replay_result_version"] == "tw-replay-result-v1"
    assert result["confirmed_plan_id"] == plan["confirmed_plan_id"]
    assert result["confirmed_plan_hash"] == plan["confirmed_plan_hash"]
    assert result["baseline_reproduction_status"] == "PASSED"
    assert result["imported_baseline_canonical_hash"] == result["simulated_baseline_canonical_hash"]
    assert result["replay_status"] == "SUCCESS"
    assert result["attempt_count"] == 1
    assert result["dataset_version"] == task["versions"]["dataset_version"]
    assert result["schema_version"] == task["versions"]["schema_version"]
    assert result["generator_version"] == task["versions"]["generator_version"]
    assert result["rule_set_version"] == task["versions"]["rule_set_version"]
    assert result["model_version"] == task["versions"]["model_version"]
    assert len(result["replay_seed_hash"]) == 64
    assert len(result["baseline_input_hash"]) == 64
    assert len(result["intervention_input_hash"]) == 64
    assert result["baseline_input_hash"] != result["intervention_input_hash"]
    assert result["baseline_output_hash"] == result["before_observation_hash"]
    assert result["intervention_output_hash"] == result["after_observation_hash"]
    assert len(result["result_hash"]) == 64
    assert {
        "dataset_manifest",
        "dataset_raw",
        "replay_evaluation_rule_snapshot",
        "simulator_asset_manifest",
        "simulator_policy",
        "disturbance_sequence",
    } <= result["input_asset_hashes"].keys()
    assert any(
        key.startswith("confirmed_plan_source:")
        for key in result["input_asset_hashes"]
    )
    assert result["disclaimer"] == "规则约束模拟环境中的离线回放结果，不代表真实产线良率改善。"
    assert result["no_device_write_notice"].endswith("未向真实设备写入任何参数。")
    assert "hidden_scenario_content_hash" not in json.dumps(payload, ensure_ascii=False)
    assert "scn_c9b8a8d6bd33f72e893f33da85dfeb8e" not in json.dumps(
        payload, ensure_ascii=False
    )
    assert app.state.replay_boundary_counters == {
        "simulator_gateway_assemblies": 1,
        "simulator_gateway_calls": 2,
        "baseline_runs": 1,
        "intervention_runs": 1,
        "llm_calls": 0,
        "external_network_requests": 0,
        "real_device_calls": 0,
    }
    replay_audit = [event for event in audit if event["action"] == "RUN_PAIRED_REPLAY"]
    assert len(replay_audit) == 1
    assert replay_audit[0]["result"] == "SUCCESS"
    assert replay_audit[0]["replay_result_hash"] == result["result_hash"]
    assert replay_audit[0]["attempt_count"] == 1
    serialized_audit = json.dumps(replay_audit[0], ensure_ascii=False)
    for forbidden in (
        "scenario_ref",
        "FaultTruth",
        "primary_fault_truth",
        "causal_coefficients",
        "nuisance_disturbance",
        str(tmp_path),
    ):
        assert forbidden not in serialized_audit
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM replay_results").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM replay_results WHERE hidden_binding_hash IS NOT NULL").fetchone()[0] == 1
        task_payload = connection.execute("SELECT payload_json FROM tasks").fetchone()[0]
        assert '"status":"REPLAYED"' in task_payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposed_values", {"pitch": "0.000000"}),
        ("current_values", {"pitch": "0.250000"}),
        ("seed", 1),
        ("scenario_ref", "scn_attacker"),
        ("simulator_version", "attacker"),
        ("evaluation_status", "SUCCESS"),
    ],
)
def test_replay_request_rejects_every_server_authoritative_field(
    tmp_path: Path, field: str, value: object
) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan, **{field: value}),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPLAY_REQUEST_FORBIDDEN_FIELDS"
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM replay_results").fetchone()[0] == 0
        assert '"status":"PLAN_CONFIRMED"' in connection.execute("SELECT payload_json FROM tasks").fetchone()[0]


def test_tampered_confirmed_plan_hash_is_blocked_before_simulation(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan, confirmed_plan_hash="f" * 64),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIRMED_PLAN_HASH_MISMATCH"
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0


def test_non_plan_confirmed_task_is_blocked_before_simulation(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task = client.post("/api/tasks/initial").json()
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json={
                "task_id": task["task_id"],
                "confirmed_plan_id": "tw-confirmed-plan-missing",
                "confirmed_plan_hash": "a" * 64,
                "request_idempotency_key": "tw-replay-request-not-ready",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_NOT_PLAN_CONFIRMED"
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0


def test_missing_confirmed_plan_is_blocked_before_simulation(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            connection.execute(
                "DELETE FROM current_confirmed_plans WHERE task_id = ?",
                (task["task_id"],),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFIRMED_PLAN_NOT_FOUND"
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0


def test_stale_confirmed_plan_is_blocked_before_simulation(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        _change_measurement_parameter(tmp_path / "tunewise.db", task["task_id"])
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] in {"CONFIRMED_PLAN_STALE", "CONFIRMED_PLAN_NOT_FRESH"}
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0


def _resign_changed_simulator_baseline(root: Path) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario_path = root / manifest["scenario_asset_file"]
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["observable_baselines"]["mtf_center"] = "0.800000"
    scenario_bytes = canonical_json_bytes(scenario) + b"\n"
    scenario_path.write_bytes(scenario_bytes)
    scenario_hash = hashlib.sha256(scenario_bytes).hexdigest()
    manifest["files"][manifest["scenario_asset_file"]] = scenario_hash
    manifest["hidden_scenario_content_hash"] = scenario_hash
    manifest["canonical_manifest_hash"] = canonical_manifest_hash(manifest)
    manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")


def test_baseline_hash_mismatch_blocks_intervention_and_result(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path, _resign_changed_simulator_baseline)
    with client:
        task, plan = prepare_confirmed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "BASELINE_REPRODUCTION_FAILED"
    assert error["expected_hash"] == task["data_import"]["hashes"]["canonical_observation_hash"]
    assert len(error["actual_hash"]) == 64
    assert stored["status"] == "PLAN_CONFIRMED"
    assert stored["replay_result"] is None
    assert app.state.replay_boundary_counters["baseline_runs"] == 1
    assert app.state.replay_boundary_counters["intervention_runs"] == 0
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 1
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM replay_results").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_evaluation_snapshot_missing_or_tampered_is_blocked_before_simulation(
    tmp_path: Path, mutation: str
) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            if mutation == "missing":
                connection.execute(
                    "DELETE FROM replay_evaluation_rule_snapshots WHERE task_id = ?",
                    (task["task_id"],),
                )
            else:
                row = connection.execute(
                    "SELECT payload_json FROM replay_evaluation_rule_snapshots WHERE task_id = ?",
                    (task["task_id"],),
                ).fetchone()
                payload = json.loads(row[0])
                payload["center_regression_tolerance"] = "9.999999"
                connection.execute(
                    "UPDATE replay_evaluation_rule_snapshots SET payload_json = ? WHERE task_id = ?",
                    (json.dumps(payload, separators=(",", ":")), task["task_id"]),
                )
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] in {
        "REPLAY_INPUT_MISSING",
        "REPLAY_INPUT_HASH_MISMATCH",
    }
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_simulator_asset_missing_or_tampered_is_blocked_without_result(
    tmp_path: Path, mutation: str
) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        disturbance = tmp_path / "simulator-private" / "disturbance-sequence.json"
        if mutation == "missing":
            disturbance.unlink()
        else:
            disturbance.write_text("{}\n", encoding="utf-8")
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] in {
        "SIMULATOR_ASSET_MISSING",
        "SIMULATOR_ASSET_HASH_MISMATCH",
    }
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 0
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM replay_results").fetchone()[0] == 0


def test_second_business_replay_does_not_create_duplicate_result(tmp_path: Path) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        request = replay_request(task, plan)
        first = client.post(f"/api/tasks/{task['task_id']}/replays", json=request)
        second = client.post(f"/api/tasks/{task['task_id']}/replays", json=request)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REPLAY_RESULT_CONFLICT"
    assert app.state.replay_boundary_counters["simulator_gateway_calls"] == 2
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM replay_results").fetchone()[0] == 1


def test_replay_result_has_no_patch_business_interface(tmp_path: Path) -> None:
    client, _app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        result = client.post(
            f"/api/tasks/{task['task_id']}/replays", json=replay_request(task, plan)
        ).json()["replay_result"]
        response = client.patch(
            f"/api/tasks/{task['task_id']}/replay-results/{result['replay_result_id']}",
            json={"replay_status": "REGRESSION"},
        )

    assert response.status_code in {404, 405}


def test_persisted_replay_disclaimer_must_match_its_trusted_version(tmp_path: Path) -> None:
    client, _app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays", json=replay_request(task, plan)
        )
        assert response.status_code == 200
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?", (task["task_id"],)
            ).fetchone()
            payload = json.loads(row[0])
            payload["replay_result"]["disclaimer"] = "tampered"
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (json.dumps(payload, separators=(",", ":")), task["task_id"]),
            )
        stored = client.get(f"/api/tasks/{task['task_id']}")

    assert stored.status_code == 409
    assert stored.json()["error"]["code"] == "REPLAY_RESULT_HASH_MISMATCH"


def test_replay_runtime_uses_no_network_llm_or_real_device_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, app = make_replay_client(tmp_path)
    with client:
        task, plan = prepare_confirmed(client)

        def reject_network(*_args, **_kwargs):
            raise AssertionError("paired replay attempted an external network request")

        monkeypatch.setattr(socket.socket, "connect", reject_network)
        response = client.post(
            f"/api/tasks/{task['task_id']}/replays",
            json=replay_request(task, plan),
        )

    assert response.status_code == 200, response.text
    assert app.state.replay_boundary_counters["external_network_requests"] == 0
    assert app.state.replay_boundary_counters["llm_calls"] == 0
    assert app.state.replay_boundary_counters["real_device_calls"] == 0
