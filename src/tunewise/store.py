from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .domain import (
    Actor,
    DataImportSummary,
    ImportHashSummary,
    ImportSnapshotVersions,
    ImportValidationSummary,
    MtfSummary,
    ParameterSummary,
    PlatformSummary,
    Task,
    TaskStatus,
    VersionSnapshot,
    WorkflowStage,
)


class ImportSnapshotConflictError(RuntimeError):
    pass


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
            )
            for table in (
                "dataset_manifests",
                "batches",
                "control_limit_snapshots",
                "parameter_constraint_snapshots",
                "replay_evaluation_rule_snapshots",
            ):
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} ("
                    "task_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS measurements ("
                "task_id TEXT NOT NULL, sample_index INTEGER NOT NULL, "
                "payload_json TEXT NOT NULL, PRIMARY KEY (task_id, sample_index))"
            )

    def get(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return self._deserialize(row["payload_json"])

    def get_or_create(self, task: Task) -> Task:
        payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        statement = (
            "INSERT OR IGNORE INTO tasks (task_id, payload_json) "
            "VALUES (?, ?)"
        )
        with self._connect() as connection:
            connection.execute(statement, (task.task_id, payload))
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("初始任务保存失败。")
        return stored_task

    def save_import(
        self,
        task: Task,
        *,
        manifest: dict,
        batch: dict,
        measurements: tuple[dict, ...],
        control_limits: dict,
        parameter_constraints: dict,
        replay_evaluation_rules: dict,
    ) -> Task:
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current is None:
                raise RuntimeError("调机任务不存在。")
            current_status = json.loads(current["payload_json"])["status"]
            if current_status != TaskStatus.CREATED:
                raise ImportSnapshotConflictError("当前任务状态不允许导入数据。")
            records = (
                ("dataset_manifests", manifest),
                ("batches", batch),
                ("control_limit_snapshots", control_limits),
                ("parameter_constraint_snapshots", parameter_constraints),
                ("replay_evaluation_rule_snapshots", replay_evaluation_rules),
            )
            for table, payload in records:
                connection.execute(
                    f"INSERT INTO {table} (task_id, payload_json) VALUES (?, ?)",
                    (task.task_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
                )
            connection.executemany(
                "INSERT INTO measurements (task_id, sample_index, payload_json) "
                "VALUES (?, ?, ?)",
                (
                    (
                        task.task_id,
                        int(measurement["sample_index"]),
                        json.dumps(measurement, ensure_ascii=False, separators=(",", ":")),
                    )
                    for measurement in measurements
                ),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (task_payload, task.task_id),
            )
        stored = self.get(task.task_id)
        if stored is None:
            raise RuntimeError("导入结果保存失败。")
        return stored

    @staticmethod
    def _deserialize(payload_json: str) -> Task:
        payload = json.loads(payload_json)
        import_payload = payload.get("data_import")
        data_import = None
        if import_payload is not None:
            data_import = DataImportSummary(
                preset_asset_id=import_payload["preset_asset_id"],
                batch_id=import_payload["batch_id"],
                station_id=import_payload["station_id"],
                product_model=import_payload["product_model"],
                sample_count=import_payload["sample_count"],
                validation_summary=ImportValidationSummary(
                    **import_payload["validation_summary"]
                ),
                hashes=ImportHashSummary(**import_payload["hashes"]),
                mtf_summary=MtfSummary(**import_payload["mtf_summary"]),
                parameter_summary=ParameterSummary(**import_payload["parameter_summary"]),
                platform_summary=PlatformSummary(**import_payload["platform_summary"]),
                snapshot_versions=ImportSnapshotVersions(
                    **import_payload["snapshot_versions"]
                ),
            )
        return Task(
            task_id=payload["task_id"],
            status=TaskStatus(payload["status"]),
            actor=Actor(**payload["actor"]),
            versions=VersionSnapshot(**payload["versions"]),
            stages=tuple(
                WorkflowStage(
                    code=TaskStatus(stage["code"]),
                    label=stage["label"],
                    availability=stage["availability"],
                )
                for stage in payload["stages"]
            ),
            data_import=data_import,
        )
