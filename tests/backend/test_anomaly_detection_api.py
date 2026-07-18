from __future__ import annotations

import hashlib
import csv
import io
import json
import sqlite3

from fastapi.testclient import TestClient

from tools.generate_demo_assets import generate
from tunewise.api import create_app
from tunewise.importing import ObservableCanonicalizer

from .asset_fixtures import write_public_assets


def make_detection_client(tmp_path, mutate_rows=None) -> tuple[TestClient, object]:
    public_root = tmp_path / "public"
    public_manifest_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    if mutate_rows is not None:
        csv_path = demo_root / "aa-demo-batch.csv"
        rows = list(
            csv.reader(
                io.StringIO(csv_path.read_text(encoding="utf-8")),
            )
        )
        mutate_rows(rows)
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
    dataset_manifest_hash = hashlib.sha256(
        (demo_root / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=public_manifest_hash,
        database_path=tmp_path / "tunewise.db",
        demo_asset_root=demo_root,
        expected_dataset_manifest_hash=dataset_manifest_hash,
    )
    return TestClient(app), app


def replace_quality(rows, *, center: str, corners: tuple[str, str, str, str]):
    header = rows[0]
    indexes = {
        field: header.index(field)
        for field in ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
    }
    for row in rows[1:]:
        row[indexes["mtf_center"]] = center
        for field, value in zip(
            ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb"),
            corners,
            strict=True,
        ):
            row[indexes[field]] = value


def create_and_import(client: TestClient) -> dict:
    created = client.post("/api/tasks/initial").json()
    imported = client.post(
        f"/api/tasks/{created['task_id']}/imports",
        json={"preset_asset_id": "tw-aa-demo-v1"},
    )
    assert imported.status_code == 200, imported.text
    return imported.json()


def detect(client: TestClient, task: dict, **overrides):
    payload = {"input_data_version": task["versions"]["dataset_version"]}
    payload.update(overrides)
    return client.post(
        f"/api/tasks/{task['task_id']}/detections",
        json=payload,
    )


def test_preset_demo_batch_detects_target_and_persists_backend_evidence(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        response = detect(client, imported)
        stored = client.get(f"/api/tasks/{imported['task_id']}").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["task"] == stored
    assert payload["task"]["status"] == "ANOMALY_DETECTED"
    assert payload["task"]["stages"][2]["availability"] == "current"
    result = payload["detection"]
    assert result["detection_result_id"].startswith("tw-detection-")
    assert result["task_id"] == imported["task_id"]
    assert result["batch_id"] == "tw-aa-demo-batch-001"
    assert result["anomaly_result"] == "TARGET_ANOMALY"
    assert result["aggregate_metrics"] == {
        "mtf_center": "0.831003",
        "mtf_lt": "0.714968",
        "mtf_rt": "0.752520",
        "mtf_lb": "0.633978",
        "mtf_rb": "0.567683",
        "corner_mtf_min": "0.567683",
        "corner_mtf_range": "0.184837",
        "corner_mtf_std": "0.071709",
    }
    assert result["control_limits"] == {
        "center_lower_limit": "0.720000",
        "corner_lower_limit": "0.620000",
        "asymmetry_limit": "0.120000",
        "corner_std_limit": "0.050000",
    }
    assert result["persistence_evidence"] == {
        "sample_count": 24,
        "violating_sample_count": 24,
        "violation_ratio": "1.000000",
        "maximum_consecutive_violations": 24,
        "minimum_consecutive_violations": 3,
        "minimum_violation_ratio": "0.250000",
        "consecutive_condition_met": True,
        "ratio_condition_met": True,
    }
    assert result["control_limit_snapshot_version"] == "tw-control-limits-v1"
    assert result["rule_set_version"] == "tw-rules-v1"
    assert result["rule_snapshot_version"] == "tw-spc-detection-v1"
    assert result["input_data_version"] == "tw-dataset-v1"
    assert result["input_hash"] == imported["data_import"]["hashes"][
        "canonical_observation_hash"
    ]
    assert (
        result["result_hash"]
        == "28e412a0c72e7e43e5df567e380f1d5240819577a0ac6fb1f842076bfe480dcf"
    )
    assert result["created_at"].endswith("Z")
    assert stored["anomaly_detection"] == result

    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM anomaly_detection_results"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM current_anomaly_detection_results"
        ).fetchone()[0] == 1


def test_repeated_detection_returns_byte_equivalent_current_result_without_duplicate(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        responses = [detect(client, imported) for _ in range(10)]

    assert {response.status_code for response in responses} == {200}
    assert {response.content for response in responses} == {responses[0].content}
    assert len({response.json()["detection"]["result_hash"] for response in responses}) == 1
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM anomaly_detection_results"
        ).fetchone()[0] == 1


def test_detection_before_data_import_is_rejected_without_running_or_persisting(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        created = client.post("/api/tasks/initial").json()
        response = detect(client, created)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DETECTION_TASK_STATE_INVALID"
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM anomaly_detection_results"
        ).fetchone()[0] == 0


def test_stale_input_version_is_rejected_as_structured_guard_response(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        response = detect(client, imported, input_data_version="stale-dataset")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "DETECTION_INPUT_VERSION_STALE",
            "message": "请求的数据版本不是当前任务最新导入版本。",
        }
    }


def test_frontend_cannot_submit_detection_result_limits_thresholds_or_rule_version(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        response = detect(
            client,
            imported,
            anomaly_result="TARGET_ANOMALY",
            center_lower_limit="0.000000",
            minimum_violation_ratio="0.000000",
            rule_set_version="forged",
            aggregate_metrics={"corner_mtf_min": "0.000000"},
        )

    assert response.status_code == 422
    assert detect(client, imported).json()["detection"]["rule_set_version"] == "tw-rules-v1"


def test_missing_control_limit_or_spc_rule_snapshot_is_rejected_before_detection(tmp_path):
    for missing_table in ("control_limit_snapshots", "spc_rule_snapshots"):
        case_root = tmp_path / missing_table
        client, _app = make_detection_client(case_root)
        with client:
            imported = create_and_import(client)
            with sqlite3.connect(case_root / "tunewise.db") as connection:
                connection.execute(f"DELETE FROM {missing_table}")
            response = detect(client, imported)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DETECTION_SNAPSHOT_MISSING"


def test_persisted_measurement_tampering_is_rejected_by_input_hash(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT sample_index, payload_json FROM measurements ORDER BY sample_index LIMIT 1"
            ).fetchone()
            payload = json.loads(row[1])
            payload["mtf_center"] = "0.100000"
            connection.execute(
                "UPDATE measurements SET payload_json = ? WHERE sample_index = ?",
                (json.dumps(payload), row[0]),
            )
        response = detect(client, imported)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DETECTION_INPUT_HASH_MISMATCH"


def test_rule_snapshot_version_tampering_is_rejected_before_detection(tmp_path):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM spc_rule_snapshots"
            ).fetchone()
            payload = json.loads(row[0])
            payload["rule_set_version"] = "forged"
            connection.execute(
                "UPDATE spc_rule_snapshots SET payload_json = ?",
                (json.dumps(payload),),
            )
        response = detect(client, imported)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DETECTION_RULE_VERSION_STALE"


def test_control_limit_snapshot_content_tampering_is_rejected_before_detection(
    tmp_path,
):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        with sqlite3.connect(tmp_path / "tunewise.db") as connection:
            row = connection.execute(
                "SELECT payload_json FROM control_limit_snapshots"
            ).fetchone()
            payload = json.loads(row[0])
            payload["center_lower_limit"] = "0.000000"
            connection.execute(
                "UPDATE control_limit_snapshots SET payload_json = ?",
                (json.dumps(payload),),
            )
        response = detect(client, imported)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DETECTION_CONTROL_SNAPSHOT_INVALID"


def test_detection_has_zero_simulator_llm_and_external_network_boundary_counts(tmp_path):
    client, app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        assert detect(client, imported).status_code == 200

    assert app.state.boundary_counters == {
        "simulator_gateway_assemblies": 0,
        "simulator_gateway_calls": 0,
        "llm_calls": 0,
        "external_network_requests": 0,
    }


def test_detection_does_not_read_demo_asset_or_hidden_scenario_content(
    tmp_path,
    monkeypatch,
):
    client, _app = make_detection_client(tmp_path)
    with client:
        imported = create_and_import(client)
        original_read_bytes = type(tmp_path).read_bytes
        reads = []

        def record_read(path):
            reads.append(path.resolve())
            return original_read_bytes(path)

        monkeypatch.setattr(type(tmp_path), "read_bytes", record_read)
        response = detect(client, imported)

    assert response.status_code == 200
    assert reads == [
        (tmp_path / "public" / "manifest.json").resolve(),
        (tmp_path / "public" / "version.json").resolve(),
    ]
    serialized = response.text.lower()
    assert "faulttruth" not in serialized
    assert "fault_truth" not in serialized
    assert '"scenario_ref":' not in serialized
    assert "scn_" not in serialized

    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        payloads = "\n".join(
            str(row[0])
            for table in (
                "tasks",
                "dataset_manifests",
                "batches",
                "measurements",
                "anomaly_detection_results",
            )
            for row in connection.execute(f"SELECT payload_json FROM {table}")
        ).lower()
    assert "faulttruth" not in payloads
    assert "fault_truth" not in payloads
    assert '"scenario_ref":' not in payloads
    assert "scn_" not in payloads


def test_normal_result_is_persisted_but_does_not_advance_task(tmp_path):
    client, _app = make_detection_client(
        tmp_path,
        lambda rows: replace_quality(
            rows,
            center="0.800000",
            corners=("0.700000", "0.700000", "0.700000", "0.700000"),
        ),
    )
    with client:
        imported = create_and_import(client)
        response = detect(client, imported)

    assert response.status_code == 200
    payload = response.json()
    assert payload["detection"]["anomaly_result"] == "NORMAL"
    assert payload["task"]["status"] == "DATA_IMPORTED"
    assert payload["task"]["stages"][1]["availability"] == "current"
    assert payload["task"]["stages"][2]["availability"] == "locked"


def test_global_degradation_result_is_persisted_but_does_not_advance_task(tmp_path):
    client, _app = make_detection_client(
        tmp_path,
        lambda rows: replace_quality(
            rows,
            center="0.680000",
            corners=("0.580000", "0.590000", "0.575000", "0.585000"),
        ),
    )
    with client:
        imported = create_and_import(client)
        response = detect(client, imported)

    assert response.status_code == 200
    payload = response.json()
    assert (
        payload["detection"]["anomaly_result"]
        == "NON_TARGET_GLOBAL_DEGRADATION"
    )
    assert payload["task"]["status"] == "DATA_IMPORTED"
    assert payload["task"]["stages"][2]["availability"] == "locked"


def test_insufficient_data_result_is_persisted_but_does_not_advance_task(tmp_path):
    client, _app = make_detection_client(
        tmp_path,
        lambda rows: rows.__setitem__(slice(8, None), []),
    )
    with client:
        imported = create_and_import(client)
        response = detect(client, imported)

    assert imported["data_import"]["sample_count"] == 7
    assert response.status_code == 200
    payload = response.json()
    assert payload["detection"]["anomaly_result"] == "INSUFFICIENT_DATA"
    assert payload["detection"]["rule_checks"][0]["status"] == "FAILED"
    assert payload["task"]["status"] == "DATA_IMPORTED"
    assert payload["task"]["stages"][2]["availability"] == "locked"
