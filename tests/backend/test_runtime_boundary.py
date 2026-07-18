from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from tunewise.api import create_app

from .asset_fixtures import write_public_assets


def test_single_process_serves_built_frontend_and_backend_api(tmp_path):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    static_root = tmp_path / "static"
    static_root.mkdir()
    (static_root / "index.html").write_text(
        "<!doctype html><title>TuneWise production</title>",
        encoding="utf-8",
    )
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=tmp_path / "tunewise.db",
        static_root=static_root,
    )

    with TestClient(app) as client:
        page = client.get("/")
        task = client.post("/api/tasks/initial")

    assert page.status_code == 200
    assert "TuneWise production" in page.text
    assert task.status_code == 201
    assert task.json()["status"] == "CREATED"


def test_runtime_source_has_no_network_simulator_or_isolated_asset_dependency():
    runtime_root = Path(__file__).parents[2] / "src" / "tunewise"
    runtime_files = tuple(runtime_root.rglob("*.py"))
    imported_roots: set[str] = set()
    semantic_source = []
    for path in runtime_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        semantic_source.append(ast.dump(tree).lower())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots.add(node.module.partition(".")[0])

    assert imported_roots <= {
        "__future__",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "enum",
        "fastapi",
        "hashlib",
        "io",
        "json",
        "pathlib",
        "pydantic",
        "re",
        "sqlite3",
        "statistics",
        "typing",
    }
    assert not {
        token
        for token in (
            "simulatorgateway",
            "faulttruth",
            "fault_truth",
            "hidden_scenario",
            "training_labels",
            "evaluation_labels",
        )
        if token in "\n".join(semantic_source)
    }


def test_initial_task_reads_only_public_version_assets(tmp_path, monkeypatch):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    original_read_bytes = Path.read_bytes
    asset_reads: list[Path] = []

    def record_asset_read(path: Path) -> bytes:
        asset_reads.append(path.resolve())
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", record_asset_read)
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=tmp_path / "tunewise.db",
    )

    with TestClient(app) as client:
        response = client.post("/api/tasks/initial")

    assert response.status_code == 201
    assert asset_reads == [
        (public_root / "manifest.json").resolve(),
        (public_root / "version.json").resolve(),
    ]


def test_sqlite_task_record_has_one_authoritative_status_source(tmp_path):
    public_root = tmp_path / "public"
    expected_manifest_hash = write_public_assets(public_root)
    database_path = tmp_path / "tunewise.db"
    app = create_app(
        public_asset_root=public_root,
        expected_manifest_hash=expected_manifest_hash,
        database_path=database_path,
    )
    with TestClient(app) as client:
        assert client.post("/api/tasks/initial").status_code == 201

    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
    assert columns == {"task_id", "payload_json"}


def test_frontend_source_has_no_external_network_target():
    frontend_source_root = Path(__file__).parents[2] / "frontend" / "src"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in frontend_source_root.rglob("*")
        if path.is_file()
    ).lower()

    assert "https://" not in source
    assert "http://" not in source
    assert "websocket" not in source
