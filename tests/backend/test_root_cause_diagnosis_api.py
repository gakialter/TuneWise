from __future__ import annotations

import hashlib
import csv
import io
import json
import sqlite3

from fastapi.testclient import TestClient

from tools.generate_demo_assets import generate as generate_demo
from tools.generate_diagnostic_assets import canonical_bytes, generate as generate_diagnostic
from tunewise.api import create_app
from tunewise.diagnosis import FeatureEngineer, FeatureEngineeringError
from tunewise.importing import ObservableCanonicalizer

from .asset_fixtures import write_public_assets


def make_diagnosis_client(
    tmp_path, mutate_diagnostic=None, mutate_demo=None
) -> tuple[TestClient, object]:
    public_root = tmp_path / "public"
    public_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate_demo(demo_root, 20260718)
    if mutate_demo is not None:
        csv_path = demo_root / "aa-demo-batch.csv"
        rows = list(csv.reader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
        mutate_demo(rows)
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerows(rows)
        csv_bytes = stream.getvalue().encode("utf-8")
        csv_path.write_bytes(csv_bytes)
        manifest_path = demo_root / "dataset-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["raw_file_hash"] = hashlib.sha256(csv_bytes).hexdigest()
        manifest["canonical_observation_hash"] = (
            ObservableCanonicalizer().canonicalize_csv(csv_bytes).sha256
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    demo_hash = hashlib.sha256((demo_root / "dataset-manifest.json").read_bytes()).hexdigest()
    diagnostic_root = tmp_path / "diagnostic"
    generate_diagnostic(diagnostic_root, 20260718)
    if mutate_diagnostic is not None:
        mutate_diagnostic(diagnostic_root)
    diagnostic_hash = hashlib.sha256((diagnostic_root / "manifest.json").read_bytes()).hexdigest()
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=public_hash,
        database_path=tmp_path / "tunewise.db",
        demo_asset_root=demo_root,
        expected_dataset_manifest_hash=demo_hash,
        diagnostic_asset_root=diagnostic_root,
        expected_diagnostic_manifest_hash=diagnostic_hash,
    )
    return TestClient(app), app


def freeze_evidence_as_insufficient(root):
    rules_path = root / "evidence-rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    rules["top1_score_minimum"] = "1.000000"
    rules_path.write_bytes(canonical_bytes(rules))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["evidence-rules.json"] = hashlib.sha256(
        rules_path.read_bytes()
    ).hexdigest()
    manifest_path.write_bytes(canonical_bytes(manifest))


def make_global_degradation(rows):
    header = rows[0]
    indexes = {
        field: header.index(field)
        for field in ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
    }
    for row in rows[1:]:
        row[indexes["mtf_center"]] = "0.680000"
        for field, value in zip(
            ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb"),
            ("0.580000", "0.590000", "0.575000", "0.585000"),
            strict=True,
        ):
            row[indexes[field]] = value


def prepare_target_task(client: TestClient) -> tuple[dict, dict]:
    created = client.post("/api/tasks/initial").json()
    imported = client.post(
        f"/api/tasks/{created['task_id']}/imports",
        json={"preset_asset_id": "tw-aa-demo-v1"},
    ).json()
    detected = client.post(
        f"/api/tasks/{created['task_id']}/detections",
        json={"input_data_version": imported["versions"]["dataset_version"]},
    ).json()
    return detected["task"], detected["detection"]


def test_demo_target_creates_immutable_top3_and_advances_task_to_diagnosed(tmp_path):
    client, app = make_diagnosis_client(tmp_path)
    with client:
        task, detection = prepare_target_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": detection["detection_result_id"]},
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task"] == stored
    assert payload["task"]["status"] == "DIAGNOSED"
    assert payload["task"]["stages"][3]["availability"] == "current"
    result = payload["diagnostic"]
    assert stored["diagnostic_result"] == result
    assert [candidate["root_cause"] for candidate in result["ordered_top3"]] == [
        "PLANE_TILT",
        "XY_DECENTER",
        "REFERENCE_DRIFT",
    ]
    assert result["evidence_status"] == "SUFFICIENT_EVIDENCE"
    assert result["parameter_candidate_count"] == 0
    assert result["z_gate_result"]["removed_category"] == "Z_DEFOCUS_CONDITIONAL"
    assert result["model_version"] == "tw-model-v1"
    assert result["preprocessing_version"] == "tw-preprocessing-v1"
    assert result["feature_definition_version"] == "tw-feature-definition-v1"
    assert result["evidence_rule_version"] == "tw-evidence-rules-v1"
    assert result["diagnostic_result_version"] == "tw-diagnostic-result-v1"
    assert len(result["result_hash"]) == 64
    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM current_diagnostic_results"
        ).fetchone()[0] == 1


def test_frontend_cannot_submit_scores_classes_thresholds_or_model_versions(tmp_path):
    client, _app = make_diagnosis_client(tmp_path)
    with client:
        task, detection = prepare_target_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={
                "detection_result_id": detection["detection_result_id"],
                "normalized_score": "1.000000",
                "root_cause": "PLANE_TILT",
                "top3": ["PLANE_TILT"],
                "evidence_threshold": "0.000000",
                "model_version": "forged",
                "feature_values": [1],
                "matched_rules": ["forged"],
            },
        )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "DIAGNOSTIC_REQUEST_FORBIDDEN_FIELDS",
        "message": "诊断请求只能提交 task_id 路径参数与最新 detection_result_id。",
    }


def test_feature_engineering_failure_is_structured_and_does_not_advance_task(
    tmp_path, monkeypatch
):
    client, _app = make_diagnosis_client(tmp_path)

    def reject_features(_engine, _measurements):
        raise FeatureEngineeringError(
            "DIAGNOSTIC_FEATURE_NON_FINITE",
            "诊断特征包含非有限数值。",
        )

    monkeypatch.setattr(FeatureEngineer, "derive", reject_features)
    with client:
        task, detection = prepare_target_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": detection["detection_result_id"]},
        )
        stored = client.get(f"/api/tasks/{task['task_id']}").json()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DIAGNOSTIC_FEATURE_NON_FINITE"
    assert stored["status"] == "ANOMALY_DETECTED"
    assert stored["diagnostic_result"] is None


def test_repeated_diagnosis_returns_identical_current_result_without_duplicate(tmp_path):
    client, _app = make_diagnosis_client(tmp_path)
    with client:
        task, detection = prepare_target_task(client)
        responses = [
            client.post(
                f"/api/tasks/{task['task_id']}/diagnoses",
                json={"detection_result_id": detection["detection_result_id"]},
            )
            for _ in range(10)
        ]

    assert {response.status_code for response in responses} == {200}
    assert {response.content for response in responses} == {responses[0].content}
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[0] == 1


def test_insufficient_evidence_still_diagnoses_but_keeps_parameter_candidates_closed(tmp_path):
    client, _app = make_diagnosis_client(
        tmp_path, mutate_diagnostic=freeze_evidence_as_insufficient
    )
    with client:
        task, detection = prepare_target_task(client)
        response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": detection["detection_result_id"]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["status"] == "DIAGNOSED"
    assert payload["diagnostic"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert payload["diagnostic"]["parameter_candidate_count"] == 0
    assert payload["task"]["stages"][4]["availability"] == "locked"


def test_wrong_task_state_or_stale_detection_reference_does_not_persist_diagnosis(tmp_path):
    client, _app = make_diagnosis_client(tmp_path)
    with client:
        created = client.post("/api/tasks/initial").json()
        state_response = client.post(
            f"/api/tasks/{created['task_id']}/diagnoses",
            json={"detection_result_id": "missing"},
        )
        task, _detection = prepare_target_task(client)
        stale_response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": "tw-detection-stale"},
        )

    assert state_response.status_code == 409
    assert state_response.json()["error"]["code"] == "DIAGNOSTIC_TASK_STATE_INVALID"
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "DIAGNOSTIC_DETECTION_STALE"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[0] == 0


def test_non_target_detection_cannot_enter_diagnosis(tmp_path):
    client, _app = make_diagnosis_client(tmp_path, mutate_demo=make_global_degradation)
    with client:
        created = client.post("/api/tasks/initial").json()
        imported = client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        ).json()
        detected = client.post(
            f"/api/tasks/{created['task_id']}/detections",
            json={"input_data_version": imported["versions"]["dataset_version"]},
        ).json()
        response = client.post(
            f"/api/tasks/{created['task_id']}/diagnoses",
            json={
                "detection_result_id": detected["detection"]["detection_result_id"]
            },
        )

    assert detected["detection"]["anomaly_result"] == "NON_TARGET_GLOBAL_DEGRADATION"
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DIAGNOSTIC_TASK_STATE_INVALID"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[0] == 0


def test_missing_or_tampered_runtime_assets_are_structurally_rejected(tmp_path):
    for name, mutate, expected_code in (
        (
            "missing-model",
            lambda root: (root / "model.json").unlink(),
            "DIAGNOSTIC_MODEL_MISSING",
        ),
        (
            "missing-preprocessing",
            lambda root: (root / "preprocessing.json").unlink(),
            "DIAGNOSTIC_PREPROCESSING_MISSING",
        ),
        (
            "missing-feature-definition",
            lambda root: (root / "feature-definition.json").unlink(),
            "DIAGNOSTIC_FEATURE_DEFINITION_MISSING",
        ),
        (
            "missing-evidence-rules",
            lambda root: (root / "evidence-rules.json").unlink(),
            "DIAGNOSTIC_EVIDENCE_RULE_MISSING",
        ),
        (
            "tampered-model",
            lambda root: (root / "model.json").write_text("{}\n", encoding="utf-8"),
            "DIAGNOSTIC_ASSET_HASH_MISMATCH",
        ),
        (
            "tampered-preprocessing",
            lambda root: (root / "preprocessing.json").write_text("{}\n", encoding="utf-8"),
            "DIAGNOSTIC_ASSET_HASH_MISMATCH",
        ),
        (
            "tampered-evidence-rules",
            lambda root: (root / "evidence-rules.json").write_text("{}\n", encoding="utf-8"),
            "DIAGNOSTIC_ASSET_HASH_MISMATCH",
        ),
    ):
        case_root = tmp_path / name
        client, _app = make_diagnosis_client(case_root)
        with client:
            task, detection = prepare_target_task(client)
            mutate(case_root / "diagnostic")
            response = client.post(
                f"/api/tasks/{task['task_id']}/diagnoses",
                json={"detection_result_id": detection["detection_result_id"]},
            )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == expected_code
        with sqlite3.connect(case_root / "tunewise.db") as connection:
            assert connection.execute("SELECT COUNT(*) FROM diagnostic_results").fetchone()[0] == 0


def test_diagnosis_reads_only_public_and_runtime_diagnostic_assets(tmp_path, monkeypatch):
    client, _app = make_diagnosis_client(tmp_path)
    with client:
        task, detection = prepare_target_task(client)
        original_read_bytes = type(tmp_path).read_bytes
        reads = []

        def record_read(path):
            reads.append(path.resolve())
            return original_read_bytes(path)

        monkeypatch.setattr(type(tmp_path), "read_bytes", record_read)
        response = client.post(
            f"/api/tasks/{task['task_id']}/diagnoses",
            json={"detection_result_id": detection["detection_result_id"]},
        )

    assert response.status_code == 200
    assert reads == [
        (tmp_path / "public" / "manifest.json").resolve(),
        (tmp_path / "public" / "version.json").resolve(),
        (tmp_path / "diagnostic" / "manifest.json").resolve(),
        (tmp_path / "diagnostic" / "class-order.json").resolve(),
        (tmp_path / "diagnostic" / "evidence-rules.json").resolve(),
        (tmp_path / "diagnostic" / "feature-definition.json").resolve(),
        (tmp_path / "diagnostic" / "model.json").resolve(),
        (tmp_path / "diagnostic" / "preprocessing.json").resolve(),
    ]
    serialized = response.text.lower()
    assert "faulttruth" not in serialized
    assert "fault_truth" not in serialized
    assert '"scenario_ref":' not in serialized
    assert "scn_" not in serialized
    assert "training_labels" not in serialized
    assert "validation_labels" not in serialized
