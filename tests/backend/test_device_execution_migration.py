from __future__ import annotations

import sqlite3
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tunewise.device_execution import DeviceExecutionState, DeviceExecutionStatus
from tunewise.store import TaskStore


def schema_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_fresh_database_and_repeat_initialization_keep_code_schema_enums_aligned(
    tmp_path: Path,
):
    database = tmp_path / "fresh.db"
    TaskStore(database)
    TaskStore(database)

    with sqlite3.connect(database) as connection:
        claim_sql = schema_sql(connection, "device_execution_claims")
        receipt_sql = schema_sql(connection, "device_execution_receipts")
        for state in {
            "VALIDATING",
            "WRITE_STARTED",
            "UNKNOWN_OUTCOME",
            "RECONCILIATION_REQUIRED",
            "FINALIZED",
        }:
            assert state in claim_sql
        for status in {item.value for item in DeviceExecutionStatus}:
            assert status in receipt_sql
        assert {item.value for item in DeviceExecutionState} >= {
            "VALIDATING",
            "WRITE_STARTED",
            "UNKNOWN_OUTCOME",
            "RECONCILIATION_REQUIRED",
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = '0001_device_execution'"
        ).fetchone()[0] == 1


def test_baseline_tasks_database_upgrades_without_modifying_existing_task(tmp_path: Path):
    database = tmp_path / "baseline.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO tasks(task_id, payload_json) VALUES ('baseline-task', '{}')"
        )

    TaskStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT payload_json FROM tasks WHERE task_id = 'baseline-task'"
        ).fetchone()[0] == "{}"
        assert schema_sql(connection, "device_execution_claims")
        assert schema_sql(connection, "device_execution_receipts")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_competition_submission_v1_database_upgrades_in_place(tmp_path: Path):
    repository = Path(__file__).resolve().parents[2]
    archive = tmp_path / "competition-submission-v1.zip"
    baseline = tmp_path / "baseline-source"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--output={archive}",
            "competition-submission-v1",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        timeout=30,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(baseline)
    database = tmp_path / "competition-baseline.db"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(baseline / "src")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from tunewise.store import TaskStore; "
            f"TaskStore(Path({str(database)!r}))",
        ],
        cwd=baseline,
        env=environment,
        check=True,
        capture_output=True,
        timeout=30,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO tasks(task_id, payload_json) VALUES ('competition-task', '{}')"
        )

    TaskStore(database)
    TaskStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT payload_json FROM tasks WHERE task_id = 'competition-task'"
        ).fetchone()[0] == "{}"
        assert schema_sql(connection, "device_execution_claims")
        assert schema_sql(connection, "device_execution_receipts")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_device_audit_schema_enforces_task_foreign_key_and_length_limits(tmp_path: Path):
    database = tmp_path / "constraints.db"
    TaskStore(database)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO device_execution_claims("
                "device_execution_id, task_id, idempotency_key, owner_instance_id, "
                "status, started_at, server_identity_hash, node_mapping_version"
                ") VALUES (?, ?, ?, ?, 'VALIDATING', ?, 'NOT_OBSERVED', ?)",
                ("execution-1", "missing-task", "a" * 64, "owner", "now", "mapping-v1"),
            )
        connection.execute(
            "INSERT INTO tasks(task_id, payload_json) VALUES ('existing-task', '{}')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO device_execution_claims("
                "device_execution_id, task_id, idempotency_key, owner_instance_id, "
                "status, started_at, server_identity_hash, node_mapping_version"
                ") VALUES (?, ?, ?, ?, 'VALIDATING', ?, 'NOT_OBSERVED', ?)",
                (
                    "execution-2",
                    "existing-task",
                    "short-key",
                    "owner",
                    "now",
                    "mapping-v1",
                ),
            )
