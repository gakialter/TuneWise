from __future__ import annotations

import hashlib
import json
import sqlite3

from fastapi.testclient import TestClient

from tools.generate_approved_case_index import generate as generate_cases
from tools.generate_demo_assets import generate as generate_demo
from tools.generate_diagnostic_assets import generate as generate_diagnostic
from tunewise.api import create_app

from .asset_fixtures import write_public_assets
from .test_root_cause_diagnosis_api import prepare_target_task


def make_retrieval_client(tmp_path) -> tuple[TestClient, object]:
    public_root = tmp_path / "public"
    public_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate_demo(demo_root, 20260718)
    demo_hash = hashlib.sha256(
        (demo_root / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    diagnostic_root = tmp_path / "diagnostic"
    generate_diagnostic(diagnostic_root, 20260718)
    diagnostic_hash = hashlib.sha256(
        (diagnostic_root / "manifest.json").read_bytes()
    ).hexdigest()
    case_root = tmp_path / "cases"
    generate_cases(case_root, 20260718)
    case_hash = hashlib.sha256((case_root / "manifest.json").read_bytes()).hexdigest()
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
    )
    return TestClient(app), app


def prepare_diagnosed_task(client: TestClient) -> tuple[dict, dict]:
    task, detection = prepare_target_task(client)
    diagnosed = client.post(
        f"/api/tasks/{task['task_id']}/diagnoses",
        json={"detection_result_id": detection["detection_result_id"]},
    ).json()
    return diagnosed["task"], diagnosed["diagnostic"]


def test_diagnosed_task_retrieves_and_persists_three_cases_without_advancing_state(
    tmp_path,
):
    client, app = make_retrieval_client(tmp_path)
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "top_k": 3,
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"retrieval"}
    assert stored["status"] == "DIAGNOSED"
    result = payload["retrieval"]
    assert result["retrieval_status"] == "CASES_FOUND"
    assert result["returned_count"] == 3
    assert [case["rank"] for case in result["ordered_cases"]] == [1, 2, 3]
    assert {case["retrieval_stage"] for case in result["ordered_cases"]} == {
        "TOP3_ROOT_CAUSE"
    }
    assert result["diagnostic_result_id"] == diagnostic["diagnostic_result_id"]
    assert result["query_feature_hash"] == diagnostic["input_feature_hash"]
    assert len(result["result_hash"]) == 64
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM case_retrieval_results"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM current_case_retrieval_results"
        ).fetchone()[0] == 1


def test_repeated_retrieval_is_idempotent_and_keeps_one_current_result(tmp_path):
    client, _app = make_retrieval_client(tmp_path)
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        request = {
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "top_k": 3,
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals", json=request
        ).json()["retrieval"]
        second = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals", json=request
        ).json()["retrieval"]

    assert second == first
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM case_retrieval_results"
        ).fetchone()[0] == 1


def test_repeated_retrieval_rejects_tampered_persisted_business_payload(tmp_path):
    client, _app = make_retrieval_client(tmp_path)
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        request = {
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "top_k": 3,
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals", json=request
        )
        assert first.status_code == 200
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT retrieval_result_id, payload_json FROM case_retrieval_results"
            ).fetchone()
            payload = json.loads(row[1])
            payload["ordered_cases"][0]["case_id"] = "tampered-case"
            connection.execute(
                "UPDATE case_retrieval_results SET payload_json = ? "
                "WHERE retrieval_result_id = ?",
                (json.dumps(payload), row[0]),
            )
        repeated = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals", json=request
        )

    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == (
        "CASE_RETRIEVAL_RESULT_HASH_MISMATCH"
    )


def test_retrieval_rejects_client_supplied_case_fields_and_non_fixed_top_k(tmp_path):
    client, _app = make_retrieval_client(tmp_path)
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        path = f"/api/tasks/{task['task_id']}/case-retrievals"
        forbidden = client.post(
            path,
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "top_k": 3,
                "query_features": [0] * 50,
                "status": "APPROVED",
                "reviewed_root_cause": "PLANE_TILT",
                "distance": 0,
                "case_index_version": "client-value",
                "ordered_cases": [],
                "historical_action": {},
            },
        )
        wrong_count = client.post(
            path,
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "top_k": 2,
            },
        )

    assert forbidden.status_code == 422
    assert forbidden.json()["error"]["code"] == (
        "CASE_RETRIEVAL_REQUEST_FORBIDDEN_FIELDS"
    )
    assert wrong_count.status_code == 422
    assert wrong_count.json()["error"]["code"] == "CASE_RETRIEVAL_REQUEST_INVALID"


def test_retrieval_guards_task_state_and_stale_diagnostic_reference(tmp_path):
    client, _app = make_retrieval_client(tmp_path)
    with client:
        created = client.post("/api/tasks/initial").json()
        wrong_state = client.post(
            f"/api/tasks/{created['task_id']}/case-retrievals",
            json={"diagnostic_result_id": "missing", "top_k": 3},
        )
        task, diagnostic = prepare_diagnosed_task(client)
        stale = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals",
            json={"diagnostic_result_id": "tw-diagnostic-stale", "top_k": 3},
        )

    assert wrong_state.status_code == 409
    assert wrong_state.json()["error"]["code"] == (
        "CASE_RETRIEVAL_TASK_STATE_INVALID"
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CASE_RETRIEVAL_DIAGNOSTIC_STALE"
    assert diagnostic["diagnostic_result_id"] != "tw-diagnostic-stale"


def test_tampered_case_asset_fails_without_persisting_partial_result_or_state_change(
    tmp_path,
):
    client, _app = make_retrieval_client(tmp_path)
    case_root = tmp_path / "cases"
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        scaler_path = case_root / "scaler.json"
        scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
        scaler["mean"][0] = "999.000000000000"
        scaler_path.write_text(json.dumps(scaler), encoding="utf-8")
        response = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "top_k": 3,
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CASE_ASSET_HASH_MISMATCH"
    assert stored == task
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM case_retrieval_results"
        ).fetchone()[0] == 0


def test_retrieval_response_contains_no_hidden_or_training_label_fields(tmp_path):
    client, app = make_retrieval_client(tmp_path)
    with client:
        task, diagnostic = prepare_diagnosed_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/case-retrievals",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "top_k": 3,
            },
        )

    serialized = response.text.lower()
    assert response.status_code == 200
    assert "faulttruth" not in serialized
    assert "scenario_ref" not in serialized
    assert "hidden" not in serialized
    assert "simulator" not in serialized
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
