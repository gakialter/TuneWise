from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from tunewise.api import create_app


REPOSITORY_ROOT = Path(__file__).parents[2]
FACTS_BOUNDARY = (
    "Synthetic process-context demonstration.\n"
    "Demonstrates deterministic context-sensitive evidence selection.\n"
    "Does not represent Sunny Optical SOP or validated production tuning accuracy."
)
ABSTRACTION_NOTE = (
    "TuneWise process-context abstractions; not industry-standard states."
)
TOP3 = ("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configured_app(
    tmp_path: Path,
    *,
    process_aware_demo_asset_root: Path | None = None,
    expected_process_aware_demo_manifest_hash: str | None = None,
    process_aware_demo_static_root: Path | None = None,
):
    public_root = REPOSITORY_ROOT / "assets" / "public"
    demo_root = REPOSITORY_ROOT / "assets" / "demo" / "tw-aa-demo-v1"
    diagnostic_root = (
        REPOSITORY_ROOT / "assets" / "diagnostic" / "tw-diagnostic-v1"
    )
    case_root = (
        REPOSITORY_ROOT / "assets" / "cases" / "tw-approved-case-index-v1"
    )
    planning_root = (
        REPOSITORY_ROOT / "assets" / "planning" / "tw-parameter-planning-v1"
    )
    return create_app(
        public_asset_root=public_root,
        expected_manifest_hash=_sha256(public_root / "manifest.json"),
        database_path=tmp_path / "tunewise.db",
        demo_asset_root=demo_root,
        expected_dataset_manifest_hash=_sha256(
            demo_root / "dataset-manifest.json"
        ),
        diagnostic_asset_root=diagnostic_root,
        expected_diagnostic_manifest_hash=_sha256(
            diagnostic_root / "manifest.json"
        ),
        case_asset_root=case_root,
        expected_case_manifest_hash=_sha256(case_root / "manifest.json"),
        planning_asset_root=planning_root,
        expected_planning_manifest_hash=_sha256(
            planning_root / "manifest.json"
        ),
        process_aware_demo_asset_root=process_aware_demo_asset_root,
        expected_process_aware_demo_manifest_hash=(
            expected_process_aware_demo_manifest_hash
        ),
        process_aware_demo_static_root=process_aware_demo_static_root,
    )


def _demo_app(tmp_path: Path):
    process_root = (
        REPOSITORY_ROOT / "assets" / "demo" / "tw-process-aware-demo-v1"
    )
    return _configured_app(
        tmp_path,
        process_aware_demo_asset_root=process_root,
        expected_process_aware_demo_manifest_hash=_sha256(
            process_root / "manifest.json"
        ),
        process_aware_demo_static_root=(
            REPOSITORY_ROOT / "src" / "tunewise" / "process_aware_demo_static"
        ),
    )


def _scenario(payload: dict, scenario_id: str) -> dict:
    return next(
        item for item in payload["scenarios"] if item["scenario_id"] == scenario_id
    )


def test_process_aware_demo_is_deterministic_read_only_and_process_sensitive(
    tmp_path,
) -> None:
    app = _demo_app(tmp_path)
    database_path = tmp_path / "tunewise.db"
    with TestClient(app) as client:
        storage_hash_before = _sha256(database_path)
        task_before = client.get("/api/tasks/tw-demo-task-001")
        first = client.get("/api/demos/process-aware")
        second = client.get("/api/demos/process-aware")
        task_after = client.get("/api/tasks/tw-demo-task-001")
        storage_hash_after = _sha256(database_path)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert task_before.status_code == task_after.status_code == 404
    assert storage_hash_after == storage_hash_before
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
    assert all(value == 0 for value in app.state.replay_boundary_counters.values())

    payload = first.json()
    assert payload["demo_version"] == "tw-process-aware-demo-v1"
    assert payload["title"] == "Process-aware Decision Demo"
    assert payload["facts_boundary"] == FACTS_BOUNDARY
    assert payload["abstraction_note"] == ABSTRACTION_NOTE
    assert payload["synthetic"] is True
    assert payload["provenance"]["source_kind"] == "SYNTHETIC_TEST_FIXTURE"
    assert payload["provenance"]["fixture_version"] == (
        "tw-process-aware-demo-fixture-v1"
    )
    assert len(payload["provenance"]["fixture_manifest_hash"]) == 64
    assert payload["provenance"]["demo_dataset_asset_id"] == "tw-aa-demo-v1"

    shared = payload["shared_evidence"]
    assert shared["measurement_evidence_label"] == "Same measurement evidence"
    assert shared["measurement_hash"] == (
        "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668"
    )
    assert shared["query_feature_hash"] == (
        "7fa3c96138dbeb938466fcd12b00b2b8c1a9fcb61ee78dcad77f29a545462040"
    )
    assert shared["feature_dimension"] == 50
    assert tuple(
        item["root_cause"] for item in shared["ordered_root_causes"]
    ) == TOP3
    assert [item["rank"] for item in shared["ordered_root_causes"]] == [1, 2, 3]
    assert shared["top1_root_cause"] == "PLANE_TILT"
    assert shared["same_across_scenarios"] is True

    scenario_a = _scenario(payload, "A")
    scenario_b = _scenario(payload, "B")
    assert scenario_a["process_context"]["process_stage"] == "INITIAL_ASSESSMENT"
    assert scenario_a["process_context"]["iteration_index"] == 0
    assert scenario_a["process_context"]["previous_action"] is None
    assert scenario_a["process_context"]["previous_action_outcome"] is None
    assert scenario_b["process_context"]["process_stage"] == (
        "POST_ADJUSTMENT_EVALUATION"
    )
    assert scenario_b["process_context"]["iteration_index"] == 1
    assert scenario_b["process_context"]["previous_action"] == {
        "parameter_name": "pitch",
        "before_value": "0.250000",
        "after_value": "0.200000",
        "delta_ticks": -1,
        "action_version": "tw-approved-case-action-v1",
    }
    assert scenario_b["process_context"]["previous_action_outcome"] == (
        "NO_MATERIAL_IMPROVEMENT"
    )
    assert scenario_b["process_context"]["previous_action_outcome_display"] == {
        "zh": "未观察到显著改善",
        "en": "No Material Improvement",
    }
    for scenario in (scenario_a, scenario_b):
        context = scenario["process_context"]
        assert context["source_kind"] == "SYNTHETIC_TEST_FIXTURE"
        assert context["synthetic"] is True
        assert len(context["context_hash"]) == 64
        assert set(context["process_stage_display"]) == {"zh", "en"}

    assert scenario_a["eligible_case"]["case_id"] == "tw-aa-approved-011"
    assert scenario_b["eligible_case"]["case_id"] == "tw-aa-approved-003"
    for scenario in (scenario_a, scenario_b):
        eligible = scenario["eligible_case"]
        assert eligible["compatibility"]["reason_code"] == "CONTEXT_MATCH"
        assert eligible["compatibility"]["explanation"]
        assert eligible["process_profile"]["source_kind"] == (
            "SYNTHETIC_TEST_FIXTURE"
        )
        assert eligible["process_profile"]["synthetic"] is True
        assert len(eligible["process_profile"]["profile_hash"]) == 64

    guided_a = scenario_a["case_guided_candidate"]
    guided_b = scenario_b["case_guided_candidate"]
    assert guided_a["generation_type"] == guided_b["generation_type"] == (
        "CASE_GUIDED"
    )
    assert guided_a["delta_ticks"] == -3
    assert guided_b["delta_ticks"] == -4
    assert guided_a["supporting_case_ids"] == ["tw-aa-approved-011"]
    assert guided_b["supporting_case_ids"] == ["tw-aa-approved-003"]
    for candidate in (guided_a, guided_b):
        assert candidate["validation_status"] == "PASSED"
        assert candidate["safety_rule_version"] == "tw-parameter-safety-v1"
        assert candidate["validation_checks"]
        assert {
            check["status"] for check in candidate["validation_checks"]
        } == {"PASSED"}

    controls = payload["unchanged_controls"]
    assert controls["identical_across_scenarios"] is True
    hashes = controls["scenario_candidate_hashes"]
    assert hashes["A"] == hashes["B"]
    assert hashes["A"]["CONSERVATIVE"] == controls["conservative_candidate"][
        "candidate_hash"
    ]
    assert hashes["A"]["STANDARD"] == controls["standard_candidate"][
        "candidate_hash"
    ]
    assert controls["conservative_candidate"]["delta_ticks"] == -1
    assert controls["standard_candidate"]["delta_ticks"] == -2
    assert controls["safety_validator"]["unchanged_across_scenarios"] is True
    assert controls["safety_validator"]["status"] == "PASSED"
    assert {
        check["status"]
        for check in controls["safety_validator"]["validation_checks"]
    } == {"PASSED"}


def test_process_aware_demo_route_is_absent_without_optional_fixture(tmp_path) -> None:
    app = _configured_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/demos/process-aware")
        openapi = client.get("/openapi.json").json()

    assert response.status_code == 404
    assert "/api/demos/process-aware" not in openapi["paths"]


def test_process_aware_demo_openapi_has_no_request_contract(tmp_path) -> None:
    app = _demo_app(tmp_path)
    with TestClient(app) as client:
        operation = client.get("/openapi.json").json()["paths"][
            "/api/demos/process-aware"
        ]["get"]
        page = client.get("/process-aware-demo/")

    assert "requestBody" not in operation
    assert operation.get("parameters", []) == []
    assert page.status_code == 200
    assert "Process-aware Decision Demo" in page.text


def test_process_aware_demo_tampered_fixture_fails_closed(tmp_path) -> None:
    source = REPOSITORY_ROOT / "assets" / "demo" / "tw-process-aware-demo-v1"
    tampered = tmp_path / "tw-process-aware-demo-v1"
    shutil.copytree(source, tampered)
    expected_manifest_hash = _sha256(tampered / "manifest.json")
    fixture_path = tampered / "process-aware-demo.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["contexts"][0]["scenario_id"] = "TAMPERED"
    fixture_path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    app = _configured_app(
        tmp_path / "app",
        process_aware_demo_asset_root=tampered,
        expected_process_aware_demo_manifest_hash=expected_manifest_hash,
    )

    with TestClient(app) as client:
        response = client.get("/api/demos/process-aware")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "PROCESS_AWARE_DEMO_ASSET_HASH_MISMATCH"
    )
