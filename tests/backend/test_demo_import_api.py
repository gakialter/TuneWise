from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from tools.generate_demo_assets import generate
from tunewise.api import create_app
from tunewise.importing import DemoDatasetImporter, ObservableCanonicalizer
from tunewise.store import TaskStore

from .asset_fixtures import write_public_assets


def make_import_client(tmp_path) -> TestClient:
    public_root = tmp_path / "public"
    public_manifest_hash = write_public_assets(public_root)
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
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
    return TestClient(app)


def make_client_for_demo(tmp_path, demo_root, expected_manifest_hash) -> TestClient:
    public_root = tmp_path / "public"
    public_manifest_hash = write_public_assets(public_root)
    return TestClient(
        create_app(
            public_asset_root=public_root,
            expected_manifest_hash=public_manifest_hash,
            database_path=tmp_path / "tunewise.db",
            demo_asset_root=demo_root,
            expected_dataset_manifest_hash=expected_manifest_hash,
        )
    )


def rewrite_manifest(demo_root, mutate) -> str:
    path = demo_root / "dataset-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_csv(demo_root, mutate, *, bind_canonical: bool) -> str:
    path = demo_root / "aa-demo-batch.csv"
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))
    mutate(rows)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    csv_bytes = stream.getvalue().encode("utf-8")
    path.write_bytes(csv_bytes)

    def bind(manifest):
        manifest["raw_file_hash"] = hashlib.sha256(csv_bytes).hexdigest()
        if bind_canonical:
            manifest["canonical_observation_hash"] = (
                ObservableCanonicalizer().canonicalize_csv(csv_bytes).sha256
            )

    return rewrite_manifest(demo_root, bind)


def import_error(client: TestClient) -> tuple[dict, dict]:
    created = client.post("/api/tasks/initial").json()
    response = client.post(
        f"/api/tasks/{created['task_id']}/imports",
        json={"preset_asset_id": "tw-aa-demo-v1"},
    )
    stored = client.get(f"/api/tasks/{created['task_id']}").json()
    assert stored["status"] == "CREATED"
    assert stored["data_import"] is None
    return response.json(), {"status_code": response.status_code}


def test_valid_preset_csv_import_advances_task_and_returns_verified_summary(tmp_path):
    with make_import_client(tmp_path) as client:
        created = client.post("/api/tasks/initial").json()
        response = client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        )
        stored = client.get(f"/api/tasks/{created['task_id']}").json()

    assert response.status_code == 200, response.text
    task = response.json()
    assert task == stored
    assert task["status"] == "DATA_IMPORTED"
    assert task["stages"][0]["availability"] == "completed"
    assert task["stages"][1]["availability"] == "current"
    assert task["data_import"] == {
        "preset_asset_id": "tw-aa-demo-v1",
        "batch_id": "tw-aa-demo-batch-001",
        "station_id": "AA",
        "product_model": "TW-AA-PROTOTYPE-V1",
        "sample_count": 24,
        "validation_summary": {
            "canonical_observation_hash": "PASSED",
            "csv_schema": "PASSED",
            "manifest": "PASSED",
            "raw_file_hash": "PASSED",
            "versions": "PASSED",
        },
        "hashes": {
            "raw_file_hash": "a7f13e1cf537f0a78c6adb482abd49a0b88e0a5fd96eeb33c0c3cef5957619b3",
            "canonical_observation_hash": "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668",
            "scenario_ref_hash": "5c210f78b07a053aebb4ddf1875f1d975d5725e9c9bf028aecedc6677796808a",
        },
        "mtf_summary": {
            "mtf_center": "0.831003",
            "mtf_lt": "0.714968",
            "mtf_rt": "0.752520",
            "mtf_lb": "0.633978",
            "mtf_rb": "0.567683",
            "corner_mtf_min": "0.567683",
            "corner_mtf_range": "0.184837",
            "corner_mtf_std": "0.071709",
        },
        "parameter_summary": {
            "x_offset": "0.100000",
            "y_offset": "-0.050000",
            "pitch": "0.250000",
            "roll": "-0.200000",
            "z_offset": "0.000000",
        },
        "platform_summary": {
            "vibration_rms": "0.017882",
            "repeat_position_error": "0.014082",
            "calibration_residual_x": "0.005973",
            "calibration_residual_y": "-0.004003",
        },
        "snapshot_versions": {
            "control_limit_snapshot": "tw-control-limits-v1",
            "parameter_constraint_snapshot": "tw-parameter-constraints-v1",
            "replay_evaluation_rule_snapshot": "tw-evaluation-v1",
        },
    }


def test_success_persists_batch_measurements_and_read_only_snapshots_atomically(tmp_path):
    with make_import_client(tmp_path) as client:
        created = client.post("/api/tasks/initial").json()
        assert client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        ).status_code == 200

    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "dataset_manifests",
                "batches",
                "measurements",
                "control_limit_snapshots",
                "parameter_constraint_snapshots",
                "replay_evaluation_rule_snapshots",
            )
        }
        manifest_payload = connection.execute(
            "SELECT payload_json FROM dataset_manifests"
        ).fetchone()[0]
        batch_payload = json.loads(
            connection.execute("SELECT payload_json FROM batches").fetchone()[0]
        )
        replay_rules_payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM replay_evaluation_rule_snapshots"
            ).fetchone()[0]
        )

    assert counts == {
        "dataset_manifests": 1,
        "batches": 1,
        "measurements": 24,
        "control_limit_snapshots": 1,
        "parameter_constraint_snapshots": 1,
        "replay_evaluation_rule_snapshots": 1,
    }
    assert '"scenario_ref_hash"' in manifest_payload
    assert '"scenario_ref"' not in manifest_payload
    assert "scn_" not in manifest_payload
    stored_manifest = json.loads(manifest_payload)
    assert stored_manifest["manifest_version"] == "1"
    assert stored_manifest["dataset_manifest_hash"]
    assert stored_manifest["rules_file_hash"]
    assert stored_manifest["versions"]["dataset_version"] == "tw-dataset-v1"
    derived = batch_payload["derived_observation_metrics"]
    assert derived["rolling_method"] == "EXPANDING"
    assert len(derived["series"]) == 24
    assert derived["series"][-1]["rolling"]["mtf_center"]["mean"]
    assert derived["series"][-1]["rolling"]["mtf_center"]["std"]
    assert derived["series"][-1]["control_limit_deviations"] == {
        "mtf_center": "0.111815",
        "corner_mtf_min": "-0.051553",
        "corner_mtf_range": "0.060727",
        "corner_mtf_std": "0.020519",
    }
    assert derived["final_control_limit_status"] == "OUTSIDE_LIMITS"
    assert replay_rules_payload["evaluation_rule_version"] == "tw-evaluation-v1"


def test_missing_required_csv_field_is_rejected_without_partial_task_progress(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = rewrite_csv(
        demo_root,
        lambda rows: rows[0].pop(),
        bind_canonical=False,
    )

    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, response = import_error(client)

    assert response["status_code"] == 422
    assert payload["error"]["code"] == "CSV_VALIDATION_FAILED"
    assert "冻结可观测字段" in payload["error"]["message"]
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert all(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            for table in (
                "dataset_manifests",
                "batches",
                "measurements",
                "control_limit_snapshots",
                "parameter_constraint_snapshots",
                "replay_evaluation_rule_snapshots",
            )
        )


@pytest.mark.parametrize(
    "forbidden_field",
    [
        "FaultTruth",
        "root_cause",
        "corner_mtf_min",
        "parameter_recommendation",
        "adjusted_mtf_center",
    ],
)
def test_forbidden_label_derived_or_adjusted_csv_fields_are_rejected(
    tmp_path,
    forbidden_field,
):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)

    def add_field(rows):
        rows[0].append(forbidden_field)
        for row in rows[1:]:
            row.append("forbidden")

    expected_hash = rewrite_csv(demo_root, add_field, bind_canonical=False)
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, response = import_error(client)

    assert response["status_code"] == 422
    assert payload["error"]["code"] == "CSV_VALIDATION_FAILED"


def test_duplicate_csv_header_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)

    def duplicate_field(rows):
        rows[0].append("x_offset")
        for row in rows[1:]:
            row.append(row[2])

    expected_hash = rewrite_csv(demo_root, duplicate_field, bind_canonical=False)
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "CSV_VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("column", "value", "expected_code"),
    [
        ("x_offset", "not-a-number", "CSV_VALIDATION_FAILED"),
        ("mtf_rb", "1.000001", "MTF_OUT_OF_RANGE"),
        ("pitch", "0.230000", "PARAMETER_VALUE_INVALID"),
        ("vibration_rms", "-0.000001", "PLATFORM_VALUE_INVALID"),
    ],
)
def test_invalid_numeric_mtf_parameter_grid_and_platform_values_are_rejected(
    tmp_path,
    column,
    value,
    expected_code,
):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)

    def replace_value(rows):
        rows[1][rows[0].index(column)] = value

    expected_hash = rewrite_csv(
        demo_root,
        replace_value,
        bind_canonical=value != "not-a-number",
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("mtf_rb", "1.0000004"),
        ("x_offset", "0.0500004"),
        ("vibration_rms", "-0.0000004"),
        ("mtf_center", "1e999999"),
    ],
)
def test_values_that_cannot_be_represented_at_canonical_precision_are_rejected(
    tmp_path,
    column,
    value,
):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)

    def replace_value(rows):
        rows[1][rows[0].index(column)] = value

    expected_hash = rewrite_csv(
        demo_root,
        replace_value,
        bind_canonical=False,
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, response = import_error(client)

    assert response["status_code"] == 422
    assert payload["error"]["code"] == "CSV_VALIDATION_FAILED"
    assert "数值精度" in payload["error"]["message"]


def test_non_aa_manifest_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = rewrite_manifest(
        demo_root,
        lambda manifest: manifest.update(station_id="ASSEMBLY"),
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "STATION_NOT_ALLOWED"


def test_manifest_root_hash_tampering_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    manifest_path = demo_root / "dataset-manifest.json"
    expected_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest_path.write_text("{}\n", encoding="utf-8")

    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "DATASET_MANIFEST_HASH_MISMATCH"


def test_trusted_manifest_with_tampered_version_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)

    def change_version(manifest):
        manifest["versions"]["schema_version"] = "forged-schema"

    expected_hash = rewrite_manifest(demo_root, change_version)
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "DATASET_VERSION_MISMATCH"


def test_trusted_manifest_with_tampered_canonical_hash_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = rewrite_manifest(
        demo_root,
        lambda manifest: manifest.update(canonical_observation_hash="0" * 64),
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "CANONICAL_OBSERVATION_HASH_MISMATCH"


def test_trusted_manifest_with_tampered_scenario_binding_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = rewrite_manifest(
        demo_root,
        lambda manifest: manifest.update(scenario_ref_hash="0" * 64),
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "SCENARIO_REFERENCE_HASH_MISMATCH"


def test_manifest_invalid_asset_path_type_returns_structured_rejection(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = rewrite_manifest(
        demo_root,
        lambda manifest: manifest.update(csv_file=42),
    )
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, response = import_error(client)

    assert response["status_code"] == 422
    assert payload["error"]["code"] == "DATASET_MANIFEST_INVALID"


def test_csv_content_tampering_is_rejected_by_raw_byte_hash(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = hashlib.sha256(
        (demo_root / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    csv_path = demo_root / "aa-demo-batch.csv"
    csv_path.write_bytes(csv_path.read_bytes().replace(b"0.100000", b"0.150000", 1))

    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "RAW_FILE_HASH_MISMATCH"


def test_repeated_import_revalidates_current_asset_bytes_before_idempotent_return(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = hashlib.sha256(
        (demo_root / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        created = client.post("/api/tasks/initial").json()
        first = client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        )
        csv_path = demo_root / "aa-demo-batch.csv"
        csv_path.write_bytes(csv_path.read_bytes().replace(b"0.100000", b"0.150000", 1))
        repeated = client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        )
        stored = client.get(f"/api/tasks/{created['task_id']}").json()

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "RAW_FILE_HASH_MISMATCH"
    assert stored["status"] == "DATA_IMPORTED"


def test_store_refuses_to_overwrite_an_imported_task_snapshot(tmp_path):
    with make_import_client(tmp_path) as client:
        created = client.post("/api/tasks/initial").json()
        assert client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={"preset_asset_id": "tw-aa-demo-v1"},
        ).status_code == 200

    store = TaskStore(tmp_path / "tunewise.db")
    imported_task = store.get(created["task_id"])
    assert imported_task is not None
    with pytest.raises(RuntimeError, match="不允许"):
        store.save_import(
            imported_task,
            manifest={"forged": True},
            batch={"forged": True},
            measurements=({"sample_index": "0"},),
            control_limits={"forged": True},
            parameter_constraints={"forged": True},
            replay_evaluation_rules={"forged": True},
        )

    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        manifest_payload = connection.execute(
            "SELECT payload_json FROM dataset_manifests"
        ).fetchone()[0]
    assert '"forged"' not in manifest_payload


def test_concurrent_identical_imports_return_the_same_persisted_snapshot(
    tmp_path,
    monkeypatch,
):
    client = make_import_client(tmp_path)
    created = client.post("/api/tasks/initial").json()
    barrier = threading.Barrier(2)
    original_load = DemoDatasetImporter.load

    def synchronized_load(importer, preset_asset_id):
        imported = original_load(importer, preset_asset_id)
        barrier.wait(timeout=5)
        return imported

    monkeypatch.setattr(DemoDatasetImporter, "load", synchronized_load)
    with client, ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                client.post,
                f"/api/tasks/{created['task_id']}/imports",
                json={"preset_asset_id": "tw-aa-demo-v1"},
            )
            for _ in range(2)
        ]
        responses = [future.result() for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    with sqlite3.connect(tmp_path / "tunewise.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 24


def test_rule_asset_tampering_is_rejected(tmp_path):
    demo_root = tmp_path / "demo"
    generate(demo_root, 20260718)
    expected_hash = hashlib.sha256(
        (demo_root / "dataset-manifest.json").read_bytes()
    ).hexdigest()
    rules_path = demo_root / "import-rules.json"
    rules_path.write_bytes(rules_path.read_bytes().replace(b"0.720000", b"0.710000", 1))

    with make_client_for_demo(tmp_path, demo_root, expected_hash) as client:
        payload, _response = import_error(client)

    assert payload["error"]["code"] == "RULE_ASSET_HASH_MISMATCH"


def test_frontend_cannot_submit_server_authoritative_versions_or_seed(tmp_path):
    with make_import_client(tmp_path) as client:
        created = client.post("/api/tasks/initial").json()
        response = client.post(
            f"/api/tasks/{created['task_id']}/imports",
            json={
                "preset_asset_id": "tw-aa-demo-v1",
                "dataset_version": "forged",
                "random_seed": 1,
            },
        )
        stored = client.get(f"/api/tasks/{created['task_id']}").json()

    assert response.status_code == 422
    assert stored["status"] == "CREATED"
    assert stored["data_import"] is None
