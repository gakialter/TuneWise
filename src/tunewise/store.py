from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
from typing import Callable

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
from .detection import (
    AnomalyDetectionRecord,
    deserialize_detection_record,
)
from .diagnosis import DiagnosticResultRecord, deserialize_diagnostic_result
from .case_retrieval import (
    CASE_RETRIEVAL_RESULT_VERSION,
    RETRIEVAL_RULE_VERSION,
    CaseRetrievalResultRecord,
    CaseRetrievalGuardError,
    deserialize_case_retrieval_result,
)
from .parameter_planning import (
    ParameterPlanningGuardError,
    ParameterPlanningRefusalRecord,
    ParameterPlanningResultRecord,
    deserialize_parameter_planning_result,
)
from .plan_confirmation import (
    AuditEvent,
    ConfirmedPlan,
    PlanConfirmationGuardError,
    deserialize_confirmed_plan,
)
from .replay import ReplayResult, deserialize_replay_result


class ImportSnapshotConflictError(RuntimeError):
    pass


class DetectionResultConflictError(RuntimeError):
    pass


class DiagnosticResultConflictError(RuntimeError):
    pass


class CaseRetrievalResultConflictError(RuntimeError):
    pass


class ParameterPlanningResultConflictError(RuntimeError):
    pass


class ConfirmedPlanConflictError(RuntimeError):
    pass


class ConfirmationStateChangedError(ConfirmedPlanConflictError):
    pass


class ReplayResultConflictError(RuntimeError):
    pass


def _canonical_sha256(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _confirmation_safe_retrieval_payload(payload: dict) -> dict:
    safe_payload = dict(payload)
    safe_payload["ordered_cases"] = [
        {
            key: value
            for key, value in item.items()
            if key != "historical_simulated_result"
        }
        for item in payload.get("ordered_cases", [])
    ]
    return safe_payload


@dataclass(frozen=True, slots=True)
class StoredDetectionInput:
    manifest: dict | None
    batch: dict | None
    measurements: tuple[dict, ...]
    control_limits: dict | None
    spc_rules: dict | None


@dataclass(frozen=True, slots=True)
class StoredPlanningInput:
    manifest: dict | None
    batch: dict | None
    measurements: tuple[dict, ...]
    control_limits: dict | None
    parameter_constraints: dict | None


@dataclass(frozen=True, slots=True)
class StoredReplayInput:
    manifest: dict | None
    batch: dict | None
    measurements: tuple[dict, ...]
    control_limits: dict | None
    parameter_constraints: dict | None
    replay_evaluation_rules: dict | None


@dataclass(frozen=True, slots=True)
class StoredCaseRetrievalBinding:
    retrieval_result_version: str
    retrieval_result_id: str
    task_id: str
    diagnostic_result_id: str
    case_index_version: str
    case_index_hash: str
    scaler_version: str
    feature_definition_version: str
    compatibility_rule_version: str
    retrieval_rule_version: str
    input_hash: str
    result_hash: str
    safe_payload_hash: str
    ordered_case_ids: tuple[str, ...]
    case_content_hashes: dict[str, str]


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _backfill_case_retrieval_confirmation_hashes(
        connection: sqlite3.Connection,
    ) -> None:
        rows = connection.execute(
            "SELECT retrieval_result_id, hex(CAST(payload_json AS BLOB)) AS payload_hex "
            "FROM case_retrieval_results "
            "WHERE payload_hash IS NULL OR safe_payload_hash IS NULL"
        ).fetchall()
        for row in rows:
            try:
                safe_top_row = connection.execute(
                    "SELECT json_remove(payload_json, '$.ordered_cases') "
                    "AS safe_top_json FROM case_retrieval_results "
                    "WHERE retrieval_result_id = ?",
                    (row["retrieval_result_id"],),
                ).fetchone()
                case_rows = connection.execute(
                    "SELECT json_remove(value, '$.historical_simulated_result') "
                    "AS safe_case_json FROM case_retrieval_results, "
                    "json_each(payload_json, '$.ordered_cases') "
                    "WHERE retrieval_result_id = ? "
                    "ORDER BY CAST(json_extract(value, '$.rank') AS INTEGER)",
                    (row["retrieval_result_id"],),
                ).fetchall()
                safe_payload = json.loads(safe_top_row["safe_top_json"])
                safe_payload["ordered_cases"] = [
                    json.loads(case["safe_case_json"]) for case in case_rows
                ]
                payload_hash = hashlib.sha256(
                    bytes.fromhex(row["payload_hex"])
                ).hexdigest()
                safe_payload_hash = _canonical_sha256(safe_payload)
            except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
                continue
            connection.execute(
                "UPDATE case_retrieval_results SET payload_hash = ?, "
                "safe_payload_hash = ? WHERE retrieval_result_id = ?",
                (
                    payload_hash,
                    safe_payload_hash,
                    row["retrieval_result_id"],
                ),
            )

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
                "spc_rule_snapshots",
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
            connection.execute(
                "CREATE TABLE IF NOT EXISTS anomaly_detection_results ("
                "detection_result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "input_data_version TEXT NOT NULL, rule_set_version TEXT NOT NULL, "
                "input_hash TEXT NOT NULL, result_hash TEXT NOT NULL, "
                "created_at TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "UNIQUE(task_id, input_data_version, rule_set_version, input_hash))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_anomaly_detection_results ("
                "task_id TEXT PRIMARY KEY, detection_result_id TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS diagnostic_results ("
                "diagnostic_result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "detection_result_id TEXT NOT NULL, input_data_version TEXT NOT NULL, "
                "input_feature_hash TEXT NOT NULL, model_version TEXT NOT NULL, "
                "preprocessing_version TEXT NOT NULL, evidence_rule_version TEXT NOT NULL, "
                "result_hash TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "UNIQUE(task_id, detection_result_id, input_feature_hash, model_version, "
                "preprocessing_version, evidence_rule_version))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_diagnostic_results ("
                "task_id TEXT PRIMARY KEY, diagnostic_result_id TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS case_retrieval_results ("
                "retrieval_result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "diagnostic_result_id TEXT NOT NULL, query_feature_hash TEXT NOT NULL, "
                "case_index_version TEXT NOT NULL, case_index_hash TEXT NOT NULL, "
                "scaler_version TEXT NOT NULL, feature_definition_version TEXT NOT NULL, "
                "compatibility_rule_version TEXT NOT NULL, input_hash TEXT NOT NULL, "
                "result_hash TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL, "
                "payload_hash TEXT, safe_payload_hash TEXT, "
                "UNIQUE(task_id, diagnostic_result_id, query_feature_hash, case_index_hash, "
                "scaler_version, compatibility_rule_version, input_hash))"
            )
            case_retrieval_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(case_retrieval_results)"
                ).fetchall()
            }
            for column in ("payload_hash", "safe_payload_hash"):
                if column not in case_retrieval_columns:
                    connection.execute(
                        f"ALTER TABLE case_retrieval_results ADD COLUMN {column} TEXT"
                    )
            self._backfill_case_retrieval_confirmation_hashes(connection)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_case_retrieval_results ("
                "task_id TEXT PRIMARY KEY, retrieval_result_id TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS parameter_planning_results ("
                "planning_result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "diagnostic_result_id TEXT NOT NULL, case_retrieval_result_id TEXT, "
                "input_hash TEXT NOT NULL, result_hash TEXT NOT NULL, "
                "planning_status TEXT NOT NULL, created_at TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, "
                "UNIQUE(task_id, diagnostic_result_id, case_retrieval_result_id, input_hash))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_parameter_planning_results ("
                "task_id TEXT PRIMARY KEY, planning_result_id TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS parameter_planning_refusals ("
                "refusal_record_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "refusal_code TEXT NOT NULL, result_hash TEXT NOT NULL, "
                "created_at TEXT NOT NULL, payload_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS confirmed_plans ("
                "confirmed_plan_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "planning_result_id TEXT NOT NULL, candidate_id TEXT NOT NULL, "
                "candidate_hash TEXT NOT NULL, confirmed_plan_hash TEXT NOT NULL, "
                "status TEXT NOT NULL, confirmed_at TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS confirmed_plans_task_id_idx "
                "ON confirmed_plans(task_id)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_confirmed_plans ("
                "task_id TEXT PRIMARY KEY, confirmed_plan_id TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS audit_events ("
                "event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "action TEXT NOT NULL, result TEXT NOT NULL, occurred_at TEXT NOT NULL, "
                "payload_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS replay_results ("
                "replay_result_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
                "confirmed_plan_id TEXT NOT NULL UNIQUE, confirmed_plan_hash TEXT NOT NULL, "
                "request_idempotency_key_hash TEXT NOT NULL, result_hash TEXT NOT NULL, "
                "replay_status TEXT NOT NULL, attempt_count INTEGER NOT NULL, "
                "hidden_binding_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
                "completed_at TEXT NOT NULL, payload_json TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_replay_results ("
                "task_id TEXT PRIMARY KEY, replay_result_id TEXT NOT NULL UNIQUE)"
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

    def has_task(self, task_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return row is not None

    def get_confirmation_task(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            try:
                row = connection.execute(
                    "SELECT json_remove(payload_json, '$.parameter_planning_result', "
                    "'$.confirmed_plan') AS payload_json FROM tasks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            except sqlite3.Error as error:
                raise ConfirmationStateChangedError(
                    "任务确认投影格式无效。"
                ) from error
        if row is None:
            return None
        try:
            return self._deserialize(row["payload_json"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ConfirmationStateChangedError(
                "任务确认投影格式无效。"
            ) from error

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
        spc_rules: dict | None = None,
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
            if spc_rules is not None:
                records = (*records, ("spc_rule_snapshots", spc_rules))
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

    def get_detection_input(self, task_id: str) -> StoredDetectionInput:
        with self._connect() as connection:
            payloads: dict[str, dict | None] = {}
            for key, table in (
                ("manifest", "dataset_manifests"),
                ("batch", "batches"),
                ("control_limits", "control_limit_snapshots"),
                ("spc_rules", "spc_rule_snapshots"),
            ):
                row = connection.execute(
                    f"SELECT payload_json FROM {table} WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                payloads[key] = None if row is None else json.loads(row["payload_json"])
            measurement_rows = connection.execute(
                "SELECT payload_json FROM measurements WHERE task_id = ? "
                "ORDER BY sample_index",
                (task_id,),
            ).fetchall()
        return StoredDetectionInput(
            manifest=payloads["manifest"],
            batch=payloads["batch"],
            measurements=tuple(
                json.loads(row["payload_json"]) for row in measurement_rows
            ),
            control_limits=payloads["control_limits"],
            spc_rules=payloads["spc_rules"],
        )

    def get_observable_measurements(self, task_id: str) -> tuple[dict, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM measurements WHERE task_id = ? "
                "ORDER BY sample_index",
                (task_id,),
            ).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    def get_current_detection(
        self, task_id: str
    ) -> AnomalyDetectionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result.payload_json FROM current_anomaly_detection_results current "
                "JOIN anomaly_detection_results result "
                "ON result.detection_result_id = current.detection_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        return (
            None
            if row is None
            else deserialize_detection_record(json.loads(row["payload_json"]))
        )

    def get_current_diagnostic(
        self, task_id: str
    ) -> DiagnosticResultRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result.payload_json FROM current_diagnostic_results current "
                "JOIN diagnostic_results result "
                "ON result.diagnostic_result_id = current.diagnostic_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        return (
            None
            if row is None
            else deserialize_diagnostic_result(json.loads(row["payload_json"]))
        )

    def get_planning_input(self, task_id: str) -> StoredPlanningInput:
        with self._connect() as connection:
            payloads: dict[str, dict | None] = {}
            for key, table in (
                ("manifest", "dataset_manifests"),
                ("batch", "batches"),
                ("control_limits", "control_limit_snapshots"),
                ("parameter_constraints", "parameter_constraint_snapshots"),
            ):
                row = connection.execute(
                    f"SELECT payload_json FROM {table} WHERE task_id = ?", (task_id,)
                ).fetchone()
                payloads[key] = None if row is None else json.loads(row["payload_json"])
            rows = connection.execute(
                "SELECT payload_json FROM measurements WHERE task_id = ? ORDER BY sample_index",
                (task_id,),
            ).fetchall()
        return StoredPlanningInput(
            manifest=payloads["manifest"],
            batch=payloads["batch"],
            measurements=tuple(json.loads(row["payload_json"]) for row in rows),
            control_limits=payloads["control_limits"],
            parameter_constraints=payloads["parameter_constraints"],
        )

    def get_confirmation_input(self, task_id: str) -> StoredPlanningInput:
        with self._connect() as connection:
            payloads: dict[str, dict | None] = {}
            try:
                manifest_row = connection.execute(
                    "SELECT json_remove(payload_json, '$.scenario_ref') AS payload_json "
                    "FROM dataset_manifests WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                payloads["manifest"] = (
                    None
                    if manifest_row is None
                    else json.loads(manifest_row["payload_json"])
                )
                for key, table in (
                    ("batch", "batches"),
                    ("control_limits", "control_limit_snapshots"),
                    ("parameter_constraints", "parameter_constraint_snapshots"),
                ):
                    row = connection.execute(
                        f"SELECT payload_json FROM {table} WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    payloads[key] = (
                        None if row is None else json.loads(row["payload_json"])
                    )
                rows = connection.execute(
                    "SELECT payload_json FROM measurements WHERE task_id = ? "
                    "ORDER BY sample_index",
                    (task_id,),
                ).fetchall()
                measurements = tuple(
                    json.loads(row["payload_json"]) for row in rows
                )
            except (sqlite3.Error, json.JSONDecodeError, TypeError) as error:
                raise ConfirmationStateChangedError(
                    "确认输入或快照格式无效。"
                ) from error
        return StoredPlanningInput(
            manifest=payloads["manifest"],
            batch=payloads["batch"],
            measurements=measurements,
            control_limits=payloads["control_limits"],
            parameter_constraints=payloads["parameter_constraints"],
        )

    def get_replay_input(self, task_id: str) -> StoredReplayInput:
        with self._connect() as connection:
            payloads: dict[str, dict | None] = {}
            for key, table in (
                ("manifest", "dataset_manifests"),
                ("batch", "batches"),
                ("control_limits", "control_limit_snapshots"),
                ("parameter_constraints", "parameter_constraint_snapshots"),
                ("replay_evaluation_rules", "replay_evaluation_rule_snapshots"),
            ):
                row = connection.execute(
                    f"SELECT payload_json FROM {table} WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                payloads[key] = None if row is None else json.loads(row["payload_json"])
            rows = connection.execute(
                "SELECT payload_json FROM measurements WHERE task_id = ? ORDER BY sample_index",
                (task_id,),
            ).fetchall()
        return StoredReplayInput(
            manifest=payloads["manifest"],
            batch=payloads["batch"],
            measurements=tuple(json.loads(row["payload_json"]) for row in rows),
            control_limits=payloads["control_limits"],
            parameter_constraints=payloads["parameter_constraints"],
            replay_evaluation_rules=payloads["replay_evaluation_rules"],
        )

    def save_detection(
        self,
        task: Task,
        record: AnomalyDetectionRecord,
    ) -> tuple[Task, AnomalyDetectionRecord]:
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        record_payload = json.dumps(
            asdict(record), ensure_ascii=False, separators=(",", ":")
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_result = connection.execute(
                "SELECT result.payload_json FROM current_anomaly_detection_results current "
                "JOIN anomaly_detection_results result "
                "ON result.detection_result_id = current.detection_result_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current_result is not None:
                stored_record = deserialize_detection_record(
                    json.loads(current_result["payload_json"])
                )
                if stored_record.detection_result_id != record.detection_result_id:
                    raise DetectionResultConflictError(
                        "任务已有不同的当前检测结果。"
                    )
                stored_task = self.get(task.task_id)
                if stored_task is None:
                    raise RuntimeError("检测结果关联任务不存在。")
                return stored_task, stored_record
            current_task = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current_task is None:
                raise RuntimeError("调机任务不存在。")
            current_status = json.loads(current_task["payload_json"])["status"]
            if current_status != TaskStatus.DATA_IMPORTED:
                raise DetectionResultConflictError("当前任务状态不允许保存检测结果。")
            connection.execute(
                "INSERT INTO anomaly_detection_results ("
                "detection_result_id, task_id, input_data_version, rule_set_version, "
                "input_hash, result_hash, created_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.detection_result_id,
                    record.task_id,
                    record.input_data_version,
                    record.rule_set_version,
                    record.input_hash,
                    record.result_hash,
                    record.created_at,
                    record_payload,
                ),
            )
            connection.execute(
                "INSERT INTO current_anomaly_detection_results "
                "(task_id, detection_result_id) VALUES (?, ?)",
                (record.task_id, record.detection_result_id),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (task_payload, task.task_id),
            )
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("检测结果保存失败。")
        return stored_task, record

    def save_diagnosis(
        self,
        task: Task,
        record: DiagnosticResultRecord,
    ) -> tuple[Task, DiagnosticResultRecord]:
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        record_payload = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT result.payload_json FROM current_diagnostic_results current "
                "JOIN diagnostic_results result "
                "ON result.diagnostic_result_id = current.diagnostic_result_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current is not None:
                stored_record = deserialize_diagnostic_result(json.loads(current["payload_json"]))
                if stored_record.diagnostic_result_id != record.diagnostic_result_id:
                    raise DiagnosticResultConflictError(
                        "任务已有不同的当前诊断结果。"
                    )
                stored_task = self.get(task.task_id)
                if stored_task is None:
                    raise RuntimeError("诊断结果关联任务不存在。")
                return stored_task, stored_record
            current_task = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current_task is None:
                raise RuntimeError("调机任务不存在。")
            if json.loads(current_task["payload_json"])["status"] != TaskStatus.ANOMALY_DETECTED:
                raise DiagnosticResultConflictError("当前任务状态不允许保存诊断结果。")
            connection.execute(
                "INSERT INTO diagnostic_results ("
                "diagnostic_result_id, task_id, detection_result_id, input_data_version, "
                "input_feature_hash, model_version, preprocessing_version, "
                "evidence_rule_version, result_hash, created_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.diagnostic_result_id,
                    record.task_id,
                    record.detection_result_id,
                    record.input_data_version,
                    record.input_feature_hash,
                    record.model_version,
                    record.preprocessing_version,
                    record.evidence_rule_version,
                    record.result_hash,
                    record.created_at,
                    record_payload,
                ),
            )
            connection.execute(
                "INSERT INTO current_diagnostic_results (task_id, diagnostic_result_id) "
                "VALUES (?, ?)",
                (record.task_id, record.diagnostic_result_id),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (task_payload, task.task_id),
            )
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("诊断结果保存失败。")
        return stored_task, record

    def get_current_case_retrieval(
        self,
        task_id: str,
    ) -> CaseRetrievalResultRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result.payload_json FROM current_case_retrieval_results current "
                "JOIN case_retrieval_results result "
                "ON result.retrieval_result_id = current.retrieval_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_case_retrieval_result(json.loads(row["payload_json"]))

    def get_current_case_retrieval_binding(
        self,
        task_id: str,
    ) -> StoredCaseRetrievalBinding | None:
        with self._connect() as connection:
            return self._get_current_case_retrieval_binding(connection, task_id)

    @staticmethod
    def _get_current_case_retrieval_binding(
        connection: sqlite3.Connection,
        task_id: str,
    ) -> StoredCaseRetrievalBinding | None:
        try:
            row = connection.execute(
                "SELECT result.retrieval_result_id, result.task_id, "
                "result.diagnostic_result_id, "
                "result.case_index_version, result.case_index_hash, "
                "result.scaler_version, result.feature_definition_version, "
                "result.compatibility_rule_version, result.input_hash, result.result_hash, "
                "result.payload_hash, result.safe_payload_hash, "
                "hex(CAST(result.payload_json AS BLOB)) AS payload_hex, "
                "json_remove(result.payload_json, '$.ordered_cases') AS safe_top_json "
                "FROM current_case_retrieval_results current "
                "JOIN case_retrieval_results result "
                "ON result.retrieval_result_id = current.retrieval_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            case_rows = connection.execute(
                "SELECT CAST(json_extract(value, '$.rank') AS INTEGER) AS rank, "
                "json_extract(value, '$.case_id') AS case_id, "
                "json_extract(value, '$.case_content_hash') AS case_content_hash, "
                "json_remove(value, '$.historical_simulated_result') AS safe_case_json "
                "FROM current_case_retrieval_results current "
                "JOIN case_retrieval_results result "
                "ON result.retrieval_result_id = current.retrieval_result_id, "
                "json_each(result.payload_json, '$.ordered_cases') "
                "WHERE current.task_id = ? ORDER BY rank",
                (task_id,),
            ).fetchall()
            safe_top = json.loads(row["safe_top_json"])
            safe_cases = [json.loads(case["safe_case_json"]) for case in case_rows]
        except (sqlite3.Error, json.JSONDecodeError, TypeError) as error:
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_RESULT_HASH_MISMATCH",
                "当前案例检索结果的安全确认投影无效。",
            ) from error
        safe_payload = dict(safe_top)
        safe_payload["ordered_cases"] = safe_cases
        actual_payload_hash = hashlib.sha256(
            bytes.fromhex(row["payload_hex"])
        ).hexdigest()
        actual_safe_payload_hash = _canonical_sha256(safe_payload)
        ordered_case_ids = tuple(case_row["case_id"] for case_row in case_rows)
        if (
            row["payload_hash"] is None
            or row["safe_payload_hash"] is None
            or actual_payload_hash != row["payload_hash"]
            or actual_safe_payload_hash != row["safe_payload_hash"]
            or safe_top.get("retrieval_result_version")
            != CASE_RETRIEVAL_RESULT_VERSION
            or safe_top.get("retrieval_result_id") != row["retrieval_result_id"]
            or safe_top.get("task_id") != row["task_id"]
            or safe_top.get("diagnostic_result_id") != row["diagnostic_result_id"]
            or safe_top.get("case_index_version") != row["case_index_version"]
            or safe_top.get("case_index_hash") != row["case_index_hash"]
            or safe_top.get("scaler_version") != row["scaler_version"]
            or safe_top.get("feature_definition_version")
            != row["feature_definition_version"]
            or safe_top.get("compatibility_rule_version")
            != row["compatibility_rule_version"]
            or safe_top.get("retrieval_rule_version") != RETRIEVAL_RULE_VERSION
            or safe_top.get("input_hash") != row["input_hash"]
            or safe_top.get("result_hash") != row["result_hash"]
            or safe_top.get("returned_count") != len(safe_cases)
            or tuple(case.get("rank") for case in safe_cases)
            != tuple(range(1, len(safe_cases) + 1))
            or len(set(ordered_case_ids)) != len(ordered_case_ids)
        ):
            raise CaseRetrievalGuardError(
                "CASE_RETRIEVAL_RESULT_HASH_MISMATCH",
                "当前案例检索结果的内容、版本或哈希已变化。",
            )
        return StoredCaseRetrievalBinding(
            retrieval_result_version=safe_top["retrieval_result_version"],
            retrieval_result_id=row["retrieval_result_id"],
            task_id=row["task_id"],
            diagnostic_result_id=row["diagnostic_result_id"],
            case_index_version=row["case_index_version"],
            case_index_hash=row["case_index_hash"],
            scaler_version=row["scaler_version"],
            feature_definition_version=row["feature_definition_version"],
            compatibility_rule_version=row["compatibility_rule_version"],
            retrieval_rule_version=safe_top["retrieval_rule_version"],
            input_hash=row["input_hash"],
            result_hash=row["result_hash"],
            safe_payload_hash=actual_safe_payload_hash,
            ordered_case_ids=ordered_case_ids,
            case_content_hashes={
                case_row["case_id"]: case_row["case_content_hash"]
                for case_row in case_rows
            },
        )

    def save_case_retrieval(
        self,
        task: Task,
        record: CaseRetrievalResultRecord,
    ) -> tuple[Task, CaseRetrievalResultRecord]:
        if record.task_id != task.task_id:
            raise CaseRetrievalResultConflictError(
                "案例检索结果与任务标识不一致。"
            )
        record_payload = json.dumps(
            asdict(record), ensure_ascii=False, separators=(",", ":")
        )
        payload_hash = hashlib.sha256(record_payload.encode("utf-8")).hexdigest()
        safe_payload_hash = _canonical_sha256(
            _confirmation_safe_retrieval_payload(asdict(record))
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_task_row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current_task_row is None:
                raise RuntimeError("调机任务不存在。")
            current_task = self._deserialize(current_task_row["payload_json"])
            if (
                current_task.status is not TaskStatus.DIAGNOSED
                or current_task.diagnostic_result is None
                or current_task.diagnostic_result.diagnostic_result_id
                != record.diagnostic_result_id
            ):
                raise CaseRetrievalResultConflictError(
                    "当前任务状态或诊断版本不允许保存案例检索结果。"
                )
            current = connection.execute(
                "SELECT result.payload_json FROM current_case_retrieval_results current "
                "JOIN case_retrieval_results result "
                "ON result.retrieval_result_id = current.retrieval_result_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current is not None:
                stored_record = deserialize_case_retrieval_result(
                    json.loads(current["payload_json"])
                )
                if (
                    stored_record.retrieval_result_id != record.retrieval_result_id
                    or stored_record.result_hash != record.result_hash
                    or stored_record.input_hash != record.input_hash
                ):
                    raise CaseRetrievalResultConflictError(
                        "任务已有不同的当前案例检索结果。"
                    )
                return current_task, stored_record
            diagnostic = connection.execute(
                "SELECT diagnostic_result_id FROM current_diagnostic_results "
                "WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if (
                diagnostic is None
                or diagnostic["diagnostic_result_id"] != record.diagnostic_result_id
            ):
                raise CaseRetrievalResultConflictError(
                    "案例检索引用的诊断结果不是当前版本。"
                )
            connection.execute(
                "INSERT INTO case_retrieval_results ("
                "retrieval_result_id, task_id, diagnostic_result_id, query_feature_hash, "
                "case_index_version, case_index_hash, scaler_version, "
                "feature_definition_version, compatibility_rule_version, input_hash, "
                "result_hash, created_at, payload_json, payload_hash, safe_payload_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.retrieval_result_id,
                    record.task_id,
                    record.diagnostic_result_id,
                    record.query_feature_hash,
                    record.case_index_version,
                    record.case_index_hash,
                    record.scaler_version,
                    record.feature_definition_version,
                    record.compatibility_rule_version,
                    record.input_hash,
                    record.result_hash,
                    record.created_at,
                    record_payload,
                    payload_hash,
                    safe_payload_hash,
                ),
            )
            connection.execute(
                "INSERT INTO current_case_retrieval_results "
                "(task_id, retrieval_result_id) VALUES (?, ?)",
                (record.task_id, record.retrieval_result_id),
            )
        return current_task, record

    def get_current_parameter_planning(
        self, task_id: str
    ) -> ParameterPlanningResultRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result.payload_json FROM current_parameter_planning_results current "
                "JOIN parameter_planning_results result "
                "ON result.planning_result_id = current.planning_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_parameter_planning_result(json.loads(row["payload_json"]))

    def save_parameter_planning_refusal(
        self, record: ParameterPlanningRefusalRecord
    ) -> None:
        payload = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO parameter_planning_refusals ("
                "refusal_record_id, task_id, refusal_code, result_hash, created_at, "
                "payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.refusal_record_id,
                    record.task_id,
                    record.refusal_code,
                    record.result_hash,
                    record.created_at,
                    payload,
                ),
            )

    def save_parameter_planning(
        self,
        task: Task,
        record: ParameterPlanningResultRecord,
    ) -> tuple[Task, ParameterPlanningResultRecord]:
        if record.task_id != task.task_id:
            raise ParameterPlanningResultConflictError(
                "参数规划结果与任务标识不一致。"
            )
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        record_payload = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_task_row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current_task_row is None:
                raise RuntimeError("调机任务不存在。")
            current_task = self._deserialize(current_task_row["payload_json"])
            if (
                current_task.status is not TaskStatus.DIAGNOSED
                or current_task.diagnostic_result is None
                or current_task.diagnostic_result.diagnostic_result_id
                != record.diagnostic_result_id
            ):
                raise ParameterPlanningResultConflictError(
                    "当前任务状态或诊断版本不允许保存参数规划结果。"
                )
            current = connection.execute(
                "SELECT result.payload_json FROM current_parameter_planning_results current "
                "JOIN parameter_planning_results result "
                "ON result.planning_result_id = current.planning_result_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current is not None:
                stored = deserialize_parameter_planning_result(
                    json.loads(current["payload_json"])
                )
                if (
                    stored.planning_result_id != record.planning_result_id
                    or stored.result_hash != record.result_hash
                ):
                    raise ParameterPlanningResultConflictError(
                        "任务已有不同的当前参数规划结果。"
                    )
                return current_task, stored
            diagnostic = connection.execute(
                "SELECT diagnostic_result_id FROM current_diagnostic_results WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if diagnostic is None or diagnostic["diagnostic_result_id"] != record.diagnostic_result_id:
                raise ParameterPlanningResultConflictError(
                    "参数规划引用的诊断结果不是当前版本。"
                )
            connection.execute(
                "INSERT INTO parameter_planning_results ("
                "planning_result_id, task_id, diagnostic_result_id, "
                "case_retrieval_result_id, input_hash, result_hash, planning_status, "
                "created_at, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.planning_result_id,
                    record.task_id,
                    record.diagnostic_result_id,
                    record.case_retrieval_result_id,
                    record.input_hash,
                    record.result_hash,
                    record.planning_status,
                    record.created_at,
                    record_payload,
                ),
            )
            connection.execute(
                "INSERT INTO current_parameter_planning_results (task_id, planning_result_id) "
                "VALUES (?, ?)",
                (record.task_id, record.planning_result_id),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (task_payload, task.task_id),
            )
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("参数规划结果保存失败。")
        return stored_task, record

    def get_current_confirmed_plan(self, task_id: str) -> ConfirmedPlan | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan.payload_json, plan.status FROM current_confirmed_plans current "
                "JOIN confirmed_plans plan "
                "ON plan.confirmed_plan_id = current.confirmed_plan_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        plan = deserialize_confirmed_plan(json.loads(row["payload_json"]))
        if plan.status != row["status"]:
            raise PlanConfirmationGuardError(
                "CONFIRMED_PLAN_STATUS_MISMATCH",
                "ConfirmedPlan 状态列与不可变载荷不一致。",
            )
        return plan

    def get_current_replay_result(self, task_id: str) -> ReplayResult | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result.payload_json FROM current_replay_results current "
                "JOIN replay_results result ON result.replay_result_id = current.replay_result_id "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
        return None if row is None else deserialize_replay_result(json.loads(row["payload_json"]))

    def confirmation_state_token(self, task_id: str) -> str:
        with self._connect() as connection:
            try:
                return self._confirmation_state_token(connection, task_id)
            except (sqlite3.Error, CaseRetrievalGuardError) as error:
                raise ConfirmationStateChangedError(
                    "确认状态投影格式无效或完整性校验失败。"
                ) from error

    @staticmethod
    def _confirmation_state_token(
        connection: sqlite3.Connection,
        task_id: str,
    ) -> str:
        state: dict[str, object] = {}
        for table in (
            "tasks",
            "batches",
            "control_limit_snapshots",
            "parameter_constraint_snapshots",
        ):
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            state[table] = None if row is None else row["payload_json"]
        manifest = connection.execute(
            "SELECT json_remove(payload_json, '$.scenario_ref') AS payload_json "
            "FROM dataset_manifests WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        state["dataset_manifest"] = (
            None if manifest is None else manifest["payload_json"]
        )
        state["measurements"] = [
            (row["sample_index"], row["payload_json"])
            for row in connection.execute(
                "SELECT sample_index, payload_json FROM measurements "
                "WHERE task_id = ? ORDER BY sample_index",
                (task_id,),
            ).fetchall()
        ]
        for name, current_table, result_table, result_id in (
            (
                "detection",
                "current_anomaly_detection_results",
                "anomaly_detection_results",
                "detection_result_id",
            ),
            (
                "diagnostic",
                "current_diagnostic_results",
                "diagnostic_results",
                "diagnostic_result_id",
            ),
            (
                "planning",
                "current_parameter_planning_results",
                "parameter_planning_results",
                "planning_result_id",
            ),
        ):
            row = connection.execute(
                f"SELECT current.{result_id} AS result_id, result.payload_json "
                f"FROM {current_table} current JOIN {result_table} result "
                f"ON result.{result_id} = current.{result_id} "
                "WHERE current.task_id = ?",
                (task_id,),
            ).fetchone()
            state[name] = (
                None
                if row is None
                else (row["result_id"], row["payload_json"])
            )
        retrieval = TaskStore._get_current_case_retrieval_binding(
            connection, task_id
        )
        state["retrieval"] = None if retrieval is None else asdict(retrieval)
        canonical = json.dumps(
            state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def save_confirmation(
        self,
        task: Task,
        plan: ConfirmedPlan,
        event: AuditEvent,
        expected_state_token: str,
        expected_file_asset_token: str,
        file_asset_token_reader: Callable[[], str],
    ) -> tuple[Task, ConfirmedPlan, bool]:
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        plan_payload = json.dumps(asdict(plan), ensure_ascii=False, separators=(",", ":"))
        event_payload = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current_state_token = self._confirmation_state_token(
                    connection, task.task_id
                )
            except (sqlite3.Error, CaseRetrievalGuardError) as error:
                raise ConfirmationStateChangedError(
                    "确认提交点的状态投影无效或完整性校验失败。"
                ) from error
            if current_state_token != expected_state_token:
                raise ConfirmationStateChangedError(
                    "确认期间任务输入、快照或当前结果已变化。"
                )
            try:
                current_file_asset_token = file_asset_token_reader()
            except Exception as error:
                raise ConfirmationStateChangedError(
                    "确认提交点的受信任文件资产已缺失或变化。"
                ) from error
            if current_file_asset_token != expected_file_asset_token:
                raise ConfirmationStateChangedError(
                    "确认提交点的受信任文件资产哈希已变化。"
                )
            current_task_row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()
            if current_task_row is None:
                raise ConfirmedPlanConflictError("调机任务不存在。")
            current_task = self._deserialize(current_task_row["payload_json"])
            current_plan_row = connection.execute(
                "SELECT plan.payload_json, plan.status FROM current_confirmed_plans current "
                "JOIN confirmed_plans plan "
                "ON plan.confirmed_plan_id = current.confirmed_plan_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if current_plan_row is not None:
                stored_plan = deserialize_confirmed_plan(
                    json.loads(current_plan_row["payload_json"])
                )
                if stored_plan.status != current_plan_row["status"]:
                    raise ConfirmedPlanConflictError(
                        "当前 ConfirmedPlan 状态绑定不一致。"
                    )
                if (
                    stored_plan.candidate_id == plan.candidate_id
                    and stored_plan.candidate_hash == plan.candidate_hash
                    and stored_plan.planning_result_id == plan.planning_result_id
                ):
                    return current_task, stored_plan, False
                raise ConfirmedPlanConflictError("任务已有不同的当前确认方案。")
            if current_task.status is not TaskStatus.PLAN_READY:
                raise ConfirmedPlanConflictError("当前任务状态不允许确认参数方案。")
            current_planning = connection.execute(
                "SELECT planning_result_id FROM current_parameter_planning_results "
                "WHERE task_id = ?",
                (task.task_id,),
            ).fetchone()
            if (
                current_planning is None
                or current_planning["planning_result_id"] != plan.planning_result_id
            ):
                raise ConfirmedPlanConflictError("确认候选不属于当前参数规划结果。")
            connection.execute(
                "INSERT INTO confirmed_plans ("
                "confirmed_plan_id, task_id, planning_result_id, candidate_id, "
                "candidate_hash, confirmed_plan_hash, status, confirmed_at, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.confirmed_plan_id,
                    plan.task_id,
                    plan.planning_result_id,
                    plan.candidate_id,
                    plan.candidate_hash,
                    plan.confirmed_plan_hash,
                    plan.status,
                    plan.confirmed_at,
                    plan_payload,
                ),
            )
            connection.execute(
                "INSERT INTO current_confirmed_plans (task_id, confirmed_plan_id) "
                "VALUES (?, ?)",
                (plan.task_id, plan.confirmed_plan_id),
            )
            connection.execute(
                "INSERT INTO audit_events ("
                "event_id, task_id, action, result, occurred_at, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.task_id,
                    event.action,
                    event.result,
                    event.occurred_at,
                    event_payload,
                ),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (task_payload, task.task_id),
            )
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("确认方案保存失败。")
        return stored_task, plan, True

    def append_audit_event(self, event: AuditEvent) -> None:
        payload = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_events ("
                "event_id, task_id, action, result, occurred_at, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.task_id,
                    event.action,
                    event.result,
                    event.occurred_at,
                    payload,
                ),
            )

    def save_replay_success(
        self,
        replaying_task: Task,
        completed_task: Task,
        result: ReplayResult,
        event: AuditEvent,
        hidden_binding_hash: str,
    ) -> tuple[Task, ReplayResult]:
        replaying_payload = json.dumps(asdict(replaying_task), ensure_ascii=False, separators=(",", ":"))
        completed_payload = json.dumps(asdict(completed_task), ensure_ascii=False, separators=(",", ":"))
        result_payload = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":"))
        event_payload = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task_row = connection.execute(
                "SELECT payload_json FROM tasks WHERE task_id = ?",
                (result.task_id,),
            ).fetchone()
            if task_row is None:
                raise ReplayResultConflictError("调机任务不存在。")
            current_task = self._deserialize(task_row["payload_json"])
            if current_task.status is not TaskStatus.PLAN_CONFIRMED:
                raise ReplayResultConflictError("当前任务状态不允许保存回放结果。")
            plan_row = connection.execute(
                "SELECT plan.confirmed_plan_id, plan.confirmed_plan_hash, plan.status "
                "FROM current_confirmed_plans current JOIN confirmed_plans plan "
                "ON plan.confirmed_plan_id = current.confirmed_plan_id WHERE current.task_id = ?",
                (result.task_id,),
            ).fetchone()
            if (
                plan_row is None
                or plan_row["confirmed_plan_id"] != result.confirmed_plan_id
                or plan_row["confirmed_plan_hash"] != result.confirmed_plan_hash
                or plan_row["status"] != "VALID"
            ):
                raise ReplayResultConflictError("当前 ConfirmedPlan 绑定不允许保存回放结果。")
            existing = connection.execute(
                "SELECT 1 FROM current_replay_results WHERE task_id = ?",
                (result.task_id,),
            ).fetchone()
            if existing is not None:
                raise ReplayResultConflictError("当前任务已存在有效 ReplayResult。")
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (replaying_payload, result.task_id),
            )
            connection.execute(
                "INSERT INTO replay_results (replay_result_id, task_id, confirmed_plan_id, "
                "confirmed_plan_hash, request_idempotency_key_hash, result_hash, replay_status, "
                "attempt_count, hidden_binding_hash, created_at, completed_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.replay_result_id,
                    result.task_id,
                    result.confirmed_plan_id,
                    result.confirmed_plan_hash,
                    result.request_idempotency_key_hash,
                    result.result_hash,
                    result.replay_status,
                    result.attempt_count,
                    hidden_binding_hash,
                    result.created_at,
                    result.completed_at,
                    result_payload,
                ),
            )
            connection.execute(
                "INSERT INTO current_replay_results (task_id, replay_result_id) VALUES (?, ?)",
                (result.task_id, result.replay_result_id),
            )
            connection.execute(
                "INSERT INTO audit_events (event_id, task_id, action, result, occurred_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.event_id, event.task_id, event.action, event.result, event.occurred_at, event_payload),
            )
            connection.execute(
                "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                (completed_payload, result.task_id),
            )
        stored = self.get(result.task_id)
        if stored is None:
            raise RuntimeError("回放结果保存失败。")
        return stored, result

    def mark_confirmed_plan_stale(
        self,
        task: Task,
        plan: ConfirmedPlan,
    ) -> Task:
        task_payload = json.dumps(asdict(task), ensure_ascii=False, separators=(",", ":"))
        plan_payload = json.dumps(asdict(plan), ensure_ascii=False, separators=(",", ":"))
        already_stale = False
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT plan.payload_json, plan.status FROM current_confirmed_plans current "
                "JOIN confirmed_plans plan "
                "ON plan.confirmed_plan_id = current.confirmed_plan_id "
                "WHERE current.task_id = ?",
                (task.task_id,),
            ).fetchone()
            if row is None:
                raise ConfirmedPlanConflictError("当前 ConfirmedPlan 不存在。")
            stored = deserialize_confirmed_plan(json.loads(row["payload_json"]))
            if stored.status != row["status"]:
                raise ConfirmedPlanConflictError(
                    "当前 ConfirmedPlan 状态绑定不一致。"
                )
            if stored.confirmed_plan_id != plan.confirmed_plan_id:
                raise ConfirmedPlanConflictError("当前 ConfirmedPlan 已发生冲突。")
            if stored.status == "STALE":
                already_stale = True
            else:
                connection.execute(
                    "UPDATE confirmed_plans SET status = ?, payload_json = ? "
                    "WHERE confirmed_plan_id = ? AND status = 'VALID'",
                    ("STALE", plan_payload, plan.confirmed_plan_id),
                )
                connection.execute(
                    "UPDATE tasks SET payload_json = ? WHERE task_id = ?",
                    (task_payload, task.task_id),
                )
        stored_task = self.get(task.task_id)
        if stored_task is None:
            raise RuntimeError("过期方案状态保存失败。")
        if already_stale and stored_task.confirmed_plan is None:
            raise RuntimeError("过期方案关联任务缺少 ConfirmedPlan。")
        return stored_task

    def get_audit_events(self, task_id: str) -> tuple[AuditEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM audit_events WHERE task_id = ? "
                "ORDER BY occurred_at, event_id",
                (task_id,),
            ).fetchall()
        return tuple(AuditEvent(**json.loads(row["payload_json"])) for row in rows)

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
        detection_payload = payload.get("anomaly_detection")
        diagnostic_payload = payload.get("diagnostic_result")
        planning_payload = payload.get("parameter_planning_result")
        confirmed_plan_payload = payload.get("confirmed_plan")
        replay_result_payload = payload.get("replay_result")
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
            anomaly_detection=(
                None
                if detection_payload is None
                else deserialize_detection_record(detection_payload)
            ),
            diagnostic_result=(
                None
                if diagnostic_payload is None
                else deserialize_diagnostic_result(diagnostic_payload)
            ),
            parameter_planning_result=(
                None
                if planning_payload is None
                else deserialize_parameter_planning_result(planning_payload)
            ),
            confirmed_plan=(
                None
                if confirmed_plan_payload is None
                else deserialize_confirmed_plan(confirmed_plan_payload)
            ),
            replay_result=(
                None
                if replay_result_payload is None
                else deserialize_replay_result(replay_result_payload)
            ),
        )
