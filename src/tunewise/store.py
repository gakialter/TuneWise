from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .domain import Actor, Task, TaskStatus, VersionSnapshot, WorkflowStage


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
        statement = (
            "CREATE TABLE IF NOT EXISTS tasks ("
            "task_id TEXT PRIMARY KEY, "
            "payload_json TEXT NOT NULL)"
        )
        with self._connect() as connection:
            connection.execute(statement)

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

    @staticmethod
    def _deserialize(payload_json: str) -> Task:
        payload = json.loads(payload_json)
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
        )
