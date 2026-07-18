from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path

from .assets import AssetIntegrityError, PublicAssetLoader
from .domain import Task, TaskStatus, workflow_for
from .importing import DemoDatasetImporter, ImportValidationError
from .store import ImportSnapshotConflictError, TaskStore


@dataclass(frozen=True, slots=True)
class DemoTaskIdGenerator:
    def new_id(self) -> str:
        return "tw-demo-task-001"


class TaskService:
    def __init__(
        self,
        asset_loader: PublicAssetLoader,
        store: TaskStore,
        id_generator: DemoTaskIdGenerator | None = None,
        demo_asset_root: Path | None = None,
        expected_dataset_manifest_hash: str | None = None,
    ) -> None:
        self._asset_loader = asset_loader
        self._store = store
        self._id_generator = id_generator or DemoTaskIdGenerator()
        self._demo_asset_root = demo_asset_root
        self._expected_dataset_manifest_hash = expected_dataset_manifest_hash

    def create_initial_task(self) -> Task:
        assets = self._asset_loader.load()
        task = Task(
            task_id=self._id_generator.new_id(),
            status=TaskStatus.CREATED,
            actor=assets.actor,
            versions=assets.versions,
            stages=workflow_for(TaskStatus.CREATED),
        )
        return self._store.get_or_create(task)

    def get_task(self, task_id: str) -> Task | None:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is not None and (
            task.actor != assets.actor or task.versions != assets.versions
        ):
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        return task

    def import_preset(self, task_id: str, preset_asset_id: str) -> Task:
        assets = self._asset_loader.load()
        task = self._store.get(task_id)
        if task is None:
            raise ImportValidationError("TASK_NOT_FOUND", "调机任务不存在。", 404)
        if task.actor != assets.actor or task.versions != assets.versions:
            raise AssetIntegrityError(
                "TASK_ASSET_SNAPSHOT_MISMATCH",
                "任务绑定的公共版本快照与当前资产不一致。",
            )
        if task.status not in (TaskStatus.CREATED, TaskStatus.DATA_IMPORTED):
            raise ImportValidationError("TASK_STATE_INVALID", "当前任务状态不允许导入数据。", 409)
        if self._demo_asset_root is None or self._expected_dataset_manifest_hash is None:
            raise ImportValidationError("DATASET_ASSET_MISSING", "预置演示资产不可用。", 409)
        imported = DemoDatasetImporter(
            self._demo_asset_root,
            self._expected_dataset_manifest_hash,
            task.versions,
        ).load(preset_asset_id)
        if task.status == TaskStatus.DATA_IMPORTED and task.data_import is not None:
            if task.data_import != imported.summary:
                raise ImportValidationError(
                    "IMPORTED_DATA_SNAPSHOT_MISMATCH",
                    "当前演示资产与任务已保存的数据快照不匹配。",
                    409,
                )
            return task
        imported_task = replace(
            task,
            status=TaskStatus.DATA_IMPORTED,
            stages=workflow_for(TaskStatus.DATA_IMPORTED),
            data_import=imported.summary,
        )
        try:
            return self._store.save_import(
                imported_task,
                manifest=imported.manifest,
                batch=imported.batch,
                measurements=imported.measurements,
                control_limits=imported.control_limits,
                parameter_constraints=imported.parameter_constraints,
                replay_evaluation_rules=imported.replay_evaluation_rules,
            )
        except ImportSnapshotConflictError as error:
            stored = self._store.get(task_id)
            if (
                stored is not None
                and stored.status == TaskStatus.DATA_IMPORTED
                and stored.data_import == imported.summary
            ):
                return stored
            raise ImportValidationError(
                "IMPORT_SNAPSHOT_CONFLICT",
                "当前任务的数据导入快照已发生变化。",
                409,
            ) from error
