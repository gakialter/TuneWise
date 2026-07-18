from __future__ import annotations

import hashlib

from tools.generate_approved_case_index import generate as generate_cases
from tools.generate_demo_assets import generate as generate_demo
from tools.generate_diagnostic_assets import generate as generate_diagnostic
from tunewise.assets import PublicAssetLoader
from tunewise.service import TaskService
from tunewise.store import TaskStore

from .asset_fixtures import write_public_assets


def test_retrieval_rederives_query_from_observable_measurements_without_hidden_input_read(
    tmp_path,
):
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
    store = TaskStore(tmp_path / "tunewise.db")
    service = TaskService(
        PublicAssetLoader(public_root, public_hash),
        store,
        demo_asset_root=demo_root,
        expected_dataset_manifest_hash=demo_hash,
        diagnostic_asset_root=diagnostic_root,
        expected_diagnostic_manifest_hash=diagnostic_hash,
        case_asset_root=case_root,
        expected_case_manifest_hash=case_hash,
    )
    task = service.create_initial_task()
    task = service.import_preset(task.task_id, "tw-aa-demo-v1")
    task, detection = service.detect_anomaly(task.task_id, task.versions.dataset_version)
    task, diagnostic = service.diagnose_root_cause(
        task.task_id, detection.detection_result_id
    )

    def forbidden_hidden_input_read(_task_id):
        raise AssertionError(
            "案例检索不得加载 DatasetManifest、scenario_ref 或隐藏输入。"
        )

    store.get_detection_input = forbidden_hidden_input_read
    task, result = service.retrieve_approved_cases(
        task.task_id,
        diagnostic.diagnostic_result_id,
        3,
    )

    assert task.status == "DIAGNOSED"
    assert result.returned_count == 3
    assert result.query_feature_hash == diagnostic.input_feature_hash
