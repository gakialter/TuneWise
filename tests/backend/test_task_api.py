from __future__ import annotations

from fastapi.testclient import TestClient

from tunewise.api import create_app

from .asset_fixtures import write_public_assets


def make_client(tmp_path) -> TestClient:
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=tmp_path / "tunewise.db",
    )
    return TestClient(app)


def test_create_initial_task_returns_domain_created_state_and_full_locked_workflow(tmp_path):
    with make_client(tmp_path) as client:
        response = client.post("/api/tasks/initial")

    assert response.status_code == 201
    task = response.json()
    assert task["task_id"] == "tw-demo-task-001"
    assert task["status"] == "CREATED"
    assert task["actor"] == {
        "actor_id": "demo-aa-engineer",
        "actor_role": "AA_PROCESS_ENGINEER",
        "display_name": "AA工艺工程师",
    }
    assert [stage["code"] for stage in task["stages"]] == [
        "CREATED",
        "DATA_IMPORTED",
        "ANOMALY_DETECTED",
        "DIAGNOSED",
        "PLAN_READY",
        "PLAN_CONFIRMED",
        "REPLAYING",
        "REPLAYED",
        "CLOSED",
        "CASE_SUBMITTED",
    ]
    assert task["stages"][0]["availability"] == "current"
    assert {stage["availability"] for stage in task["stages"][1:]} == {"locked"}


def test_repeated_startup_preserves_initial_task_semantics(tmp_path):
    first_client = make_client(tmp_path)
    with first_client:
        first_task = first_client.post("/api/tasks/initial").json()

    second_client = make_client(tmp_path)
    with second_client:
        second_task = second_client.post("/api/tasks/initial").json()

    assert second_task == first_task


def test_task_can_be_read_back_from_backend_store(tmp_path):
    with make_client(tmp_path) as client:
        created = client.post("/api/tasks/initial").json()
        response = client.get(f"/api/tasks/{created['task_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_task_creation_is_rejected_with_clear_error_when_asset_is_tampered(tmp_path):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    (public_root / "version.json").write_text("{}\n", encoding="utf-8")
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=tmp_path / "tunewise.db",
    )

    with TestClient(app) as client:
        response = client.post("/api/tasks/initial")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "PUBLIC_ASSET_HASH_MISMATCH",
            "message": "公共版本资产内容哈希不匹配。",
        }
    }


def test_existing_task_is_not_usable_after_public_asset_tampering(tmp_path):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=tmp_path / "tunewise.db",
    )
    with TestClient(app) as client:
        created = client.post("/api/tasks/initial").json()
        (public_root / "version.json").write_text("{}\n", encoding="utf-8")
        response = client.get(f"/api/tasks/{created['task_id']}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PUBLIC_ASSET_HASH_MISMATCH"


def test_api_exposes_no_auth_rules_or_later_stage_mutation_routes(tmp_path):
    with make_client(tmp_path) as client:
        openapi = client.get("/openapi.json").json()
        docs_response = client.get("/docs")
        redoc_response = client.get("/redoc")

    assert set(openapi["paths"]) == {
        "/api/health",
        "/api/tasks/initial",
        "/api/tasks/{task_id}",
    }
    assert openapi.get("components", {}).get("securitySchemes") is None
    assert docs_response.status_code == 404
    assert redoc_response.status_code == 404
