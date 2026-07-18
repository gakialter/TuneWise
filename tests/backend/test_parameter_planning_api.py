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
from tools.generate_diagnostic_assets import build_partition
from tools.generate_parameter_planning_assets import generate as generate_planning
from tunewise.api import create_app
from tunewise.diagnosis import DerivedFeatureSet
from tunewise.diagnostic_contract import FEATURE_NAMES
from tunewise.parameter_planning import SafetyValidationResult, ValidationCheck
from tunewise.service import TaskService

from .asset_fixtures import write_public_assets
from .test_root_cause_diagnosis_api import (
    freeze_evidence_as_insufficient,
    prepare_target_task,
)


def make_planning_client(
    tmp_path, mutate_diagnostic=None, mutate_demo=None
) -> tuple[TestClient, object]:
    public_root = tmp_path / "public"
    public_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate_demo(demo_root, 20260718)
    if mutate_demo is not None:
        mutate_demo(demo_root)
    demo_hash = hashlib.sha256((demo_root / "dataset-manifest.json").read_bytes()).hexdigest()
    diagnostic_root = tmp_path / "diagnostic"
    generate_diagnostic(diagnostic_root, 20260718)
    if mutate_diagnostic is not None:
        mutate_diagnostic(diagnostic_root)
    diagnostic_hash = hashlib.sha256((diagnostic_root / "manifest.json").read_bytes()).hexdigest()
    case_root = tmp_path / "cases"
    generate_cases(case_root, 20260718)
    case_hash = hashlib.sha256((case_root / "manifest.json").read_bytes()).hexdigest()
    planning_root = tmp_path / "planning"
    generate_planning(planning_root)
    planning_hash = hashlib.sha256((planning_root / "manifest.json").read_bytes()).hexdigest()
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
    )
    return TestClient(app), app


def _prepare(client: TestClient) -> tuple[dict, dict, dict]:
    task, detection = prepare_target_task(client)
    diagnosed = client.post(
        f"/api/tasks/{task['task_id']}/diagnoses",
        json={"detection_result_id": detection["detection_result_id"]},
    ).json()
    retrieval = client.post(
        f"/api/tasks/{task['task_id']}/case-retrievals",
        json={
            "diagnostic_result_id": diagnosed["diagnostic"]["diagnostic_result_id"],
            "top_k": 3,
        },
    ).json()["retrieval"]
    return diagnosed["task"], diagnosed["diagnostic"], retrieval


def test_demo_generates_three_validated_candidates_and_advances_to_plan_ready(tmp_path) -> None:
    client, app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    result = payload["planning"]
    assert payload["task"] == stored
    assert stored["status"] == "PLAN_READY"
    assert result["planning_status"] == "CANDIDATES_AVAILABLE"
    assert result["refusal_code"] is None
    assert [item["parameter_name"] for item in result["direction_evidence"]] == [
        "pitch",
        "roll",
    ]
    assert [candidate["total_absolute_delta_ticks"] for candidate in result["ordered_candidates"]] == [1, 2, 3]
    assert [candidate["delta_ticks"]["pitch"] for candidate in result["ordered_candidates"]] == [-1, -2, -3]
    assert all(candidate["validation_status"] == "PASSED" for candidate in result["ordered_candidates"])
    assert all(candidate["candidate_hash"] for candidate in result["ordered_candidates"])
    assert result["case_guidance_status"] == "COMPATIBLE_APPROVED_CASES_USED"
    assert len(result["result_hash"]) == 64
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
    assert (
        app.state.boundary_counters
        is app.state.planning_boundary_audit.counters
    )
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM parameter_planning_results").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM current_parameter_planning_results").fetchone()[0] == 1


def test_planning_runtime_reads_no_fault_truth_hidden_scenario_or_scenario_reference_content(
    tmp_path, monkeypatch
) -> None:
    client, _app = make_planning_client(tmp_path)
    original_read_bytes = Path.read_bytes
    planning_reads: list[Path] = []

    with client:
        task, diagnostic, retrieval = _prepare(client)

        def record_read(path: Path) -> bytes:
            planning_reads.append(path.resolve())
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", record_read)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )

    assert response.status_code == 200
    assert planning_reads
    assert all(
        "fault" not in path.name.lower()
        and "scenario" not in path.name.lower()
        and "hidden" not in path.name.lower()
        for path in planning_reads
    )
    assert all(
        path.is_relative_to(tmp_path / "public")
        or path.is_relative_to(tmp_path / "planning")
        or path.is_relative_to(tmp_path / "cases")
        for path in planning_reads
    )


def test_parameter_planning_runtime_performs_no_external_network_request(
    tmp_path, monkeypatch
) -> None:
    client, app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)

        def reject_network(*_args, **_kwargs):
            app.state.planning_boundary_audit.record("external_network_requests")
            raise AssertionError("parameter planning attempted an external network request")

        monkeypatch.setattr(socket.socket, "connect", reject_network)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )

    assert response.status_code == 200
    assert app.state.boundary_counters["external_network_requests"] == 0


def test_repeated_planning_is_idempotent_and_does_not_advance_state_twice(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        request = {
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "case_retrieval_result_id": retrieval["retrieval_result_id"],
        }
        first = client.post(f"/api/tasks/{task['task_id']}/parameter-plans", json=request).json()
        second = client.post(f"/api/tasks/{task['task_id']}/parameter-plans", json=request).json()

    assert second == first
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM parameter_planning_results").fetchone()[0] == 1


def test_task_must_be_diagnosed_before_parameter_planning(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task = client.post("/api/tasks/initial").json()
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={"diagnostic_result_id": "not-current", "case_retrieval_result_id": None},
        )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "PARAMETER_PLANNING_TASK_STATE_INVALID"
    assert error["supporting_evidence"] == ["task_status=CREATED"]
    assert error["recommended_inspection_actions"] == []
    assert error["rule_set_version"] == "tw-rules-v1"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM parameter_planning_refusals"
        ).fetchone()[0] == 1


def test_all_validator_rejected_candidates_persist_refusal_and_keep_diagnosed(
    tmp_path, monkeypatch
) -> None:
    def reject_candidate(_self, candidate, *, snapshot, versions):
        return SafetyValidationResult(
            validation_status="REJECTED",
            validation_checks=(
                ValidationCheck(
                    check_code="TEST_FORCED_REJECTION",
                    status="FAILED",
                    detail="测试替身拒绝候选。",
                ),
            ),
            rejection_reasons=("TEST_FORCED_REJECTION",),
            safety_rule_version=versions.safety_rule_version,
            constraint_snapshot_version=snapshot.snapshot_version,
            validated_candidate_hash=candidate.candidate_hash,
        )

    monkeypatch.setattr(
        "tunewise.parameter_planning.ParameterSafetyValidator.validate",
        reject_candidate,
    )
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )

    assert response.status_code == 200
    assert response.json()["planning"]["refusal_code"] == "ALL_CANDIDATES_REJECTED"
    assert response.json()["planning"]["ordered_candidates"] == []
    assert response.json()["task"]["status"] == "DIAGNOSED"


def test_frontend_cannot_override_parameters_direction_constraints_or_validation(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
                "proposed_values": {"pitch": "0.000000"},
                "deltas": {"pitch": "-0.250000"},
                "recommended_direction": "DECREASE",
                "nominal_value": "0.000000",
                "maximum_single_plan_delta": "9.000000",
                "root_cause": "PLANE_TILT",
                "generation_type": "STANDARD",
                "validation_status": "PASSED",
                "rule_set_version": "client-rule",
            },
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "PARAMETER_PLANNING_REQUEST_FORBIDDEN_FIELDS"
    assert "proposed_values" in error["supporting_evidence"][0]
    assert error["recommended_inspection_actions"] == []
    assert error["rule_set_version"] == "tw-rules-v1"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM parameter_planning_refusals"
        ).fetchone()[0] == 1


def test_stale_or_missing_case_retrieval_reference_is_refused(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, _retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": None,
            },
        )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "PARAMETER_PLANNING_RETRIEVAL_STALE"
    assert error["supporting_evidence"]
    assert error["rule_set_version"] == "tw-rules-v1"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM parameter_planning_refusals"
        ).fetchone()[0] == 1


def test_idempotent_retry_revalidates_snapshot_before_returning_plan_ready(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        request = {
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "case_retrieval_result_id": retrieval["retrieval_result_id"],
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans", json=request
        )
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM parameter_constraint_snapshots WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            snapshot = json.loads(row[0])
            snapshot["constraints"]["pitch"]["maximum"] = "9.000000"
            connection.execute(
                "UPDATE parameter_constraint_snapshots SET payload_json = ? WHERE task_id = ?",
                (json.dumps(snapshot), task["task_id"]),
            )
        repeated = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans", json=request
        )

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "PLANNING_SNAPSHOT_OR_RULE_TAMPERED"


def test_idempotent_retry_binds_approved_case_manifest_content(
    tmp_path, monkeypatch
) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        request = {
            "diagnostic_result_id": diagnostic["diagnostic_result_id"],
            "case_retrieval_result_id": retrieval["retrieval_result_id"],
        }
        first = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans", json=request
        )
        original = TaskService._planning_cases

        def changed_manifest(self, current_task, current_retrieval):
            cases, index_hash, _manifest_hash = original(
                self, current_task, current_retrieval
            )
            return cases, index_hash, "f" * 64

        monkeypatch.setattr(TaskService, "_planning_cases", changed_manifest)
        repeated = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans", json=request
        )

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "PARAMETER_PLANNING_INPUT_STALE"


def test_insufficient_evidence_persists_structured_refusal_and_keeps_diagnosed(tmp_path) -> None:
    client, _app = make_planning_client(
        tmp_path, mutate_diagnostic=freeze_evidence_as_insufficient
    )
    with client:
        task, diagnostic, retrieval = _prepare(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["status"] == "DIAGNOSED"
    assert payload["planning"]["planning_status"] == "PARAMETER_RECOMMENDATION_REFUSED"
    assert payload["planning"]["refusal_code"] == "INSUFFICIENT_EVIDENCE"
    assert payload["planning"]["ordered_candidates"] == []


def _fixed_features(row_index: int) -> DerivedFeatureSet:
    rows, _labels = build_partition(20260718, "REPRESENTATIVE", 1)
    values = tuple(rows[row_index])
    content = json.dumps(
        {
            "feature_names": FEATURE_NAMES,
            "values": [f"{value:.12f}" for value in values],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return DerivedFeatureSet(
        feature_definition_version="tw-feature-definition-v1",
        feature_names=FEATURE_NAMES,
        values=values,
        input_feature_hash=hashlib.sha256(content).hexdigest(),
    )


@pytest.mark.parametrize(
    ("row_index", "root_cause", "actions"),
    [
        (
            2,
            "PLATFORM_INSTABILITY",
            ["检查重复定位误差", "检查振动或回差证据", "复核平台稳定性"],
        ),
        (
            3,
            "REFERENCE_DRIFT",
            ["检查夹具基准", "复核标定残差", "执行受控标定检查"],
        ),
    ],
)
def test_inspection_only_root_causes_return_templates_without_candidates(
    tmp_path, monkeypatch, row_index, root_cause, actions
) -> None:
    client, _app = make_planning_client(tmp_path)
    fixed = _fixed_features(row_index)
    monkeypatch.setattr(
        "tunewise.service.FeatureEngineer.derive", lambda _self, _measurements: fixed
    )
    with client:
        task, detection = prepare_target_task(client)
        diagnosed = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": detection["detection_result_id"]},
        ).json()
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnosed["diagnostic"]["diagnostic_result_id"],
                "case_retrieval_result_id": None,
            },
        )

    assert diagnosed["diagnostic"]["ordered_top3"][0]["root_cause"] == root_cause
    planning = response.json()["planning"]
    assert planning["refusal_code"] == f"{root_cause}_INSPECTION_ONLY"
    assert planning["ordered_candidates"] == []
    assert planning["recommended_inspection_actions"] == actions


def test_parameter_constraint_snapshot_tampering_is_persisted_as_refusal(tmp_path) -> None:
    client, _app = make_planning_client(tmp_path)
    with client:
        task, diagnostic, retrieval = _prepare(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM parameter_constraint_snapshots WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            snapshot = json.loads(row[0])
            snapshot["constraints"]["pitch"]["maximum"] = "9.000000"
            connection.execute(
                "UPDATE parameter_constraint_snapshots SET payload_json = ? WHERE task_id = ?",
                (json.dumps(snapshot), task["task_id"]),
            )
        response = client.post(
            f"/api/tasks/{task['task_id']}/parameter-plans",
            json={
                "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                "case_retrieval_result_id": retrieval["retrieval_result_id"],
            },
        )

    assert response.status_code == 200
    assert response.json()["planning"]["refusal_code"] == "PLANNING_SNAPSHOT_OR_RULE_TAMPERED"
    assert response.json()["task"]["status"] == "DIAGNOSED"


def test_candidate_and_result_hashes_ignore_time_and_are_repeatable_across_tasks(tmp_path) -> None:
    first_client, _first_app = make_planning_client(tmp_path / "first")
    second_client, _second_app = make_planning_client(tmp_path / "second")

    def run(client: TestClient):
        with client:
            task, diagnostic, retrieval = _prepare(client)
            return client.post(
                f"/api/tasks/{task['task_id']}/parameter-plans",
                json={
                    "diagnostic_result_id": diagnostic["diagnostic_result_id"],
                    "case_retrieval_result_id": retrieval["retrieval_result_id"],
                },
            ).json()["planning"]

    first = run(first_client)
    second = run(second_client)

    assert first["created_at"] != second["created_at"]
    assert first["result_hash"] == second["result_hash"]
    assert [item["candidate_hash"] for item in first["ordered_candidates"]] == [
        item["candidate_hash"] for item in second["ordered_candidates"]
    ]
