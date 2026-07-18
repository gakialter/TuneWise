from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
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
from .detection import (
    AnomalyDetectionRecord,
    deserialize_detection_record,
)
from .diagnosis import DiagnosticResultRecord, deserialize_diagnostic_result
from .case_retrieval import (
    CaseRetrievalResultRecord,
    deserialize_case_retrieval_result,
)


class ImportSnapshotConflictError(RuntimeError):
    pass


class DetectionResultConflictError(RuntimeError):
    pass


class DiagnosticResultConflictError(RuntimeError):
    pass


class CaseRetrievalResultConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoredDetectionInput:
    manifest: dict | None
    batch: dict | None
    measurements: tuple[dict, ...]
    control_limits: dict | None
    spc_rules: dict | None


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
                "UNIQUE(task_id, diagnostic_result_id, query_feature_hash, case_index_hash, "
                "scaler_version, compatibility_rule_version, input_hash))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS current_case_retrieval_results ("
                "task_id TEXT PRIMARY KEY, retrieval_result_id TEXT NOT NULL UNIQUE)"
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
                "result_hash, created_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
            connection.execute(
                "INSERT INTO current_case_retrieval_results "
                "(task_id, retrieval_result_id) VALUES (?, ?)",
                (record.task_id, record.retrieval_result_id),
            )
        return current_task, record

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
        )
