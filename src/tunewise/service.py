from __future__ import annotations

from dataclasses import dataclass

from .assets import AssetIntegrityError, PublicAssetLoader
from .domain import Task, TaskStatus, workflow_for
from .store import TaskStore


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
    ) -> None:
        self._asset_loader = asset_loader
        self._store = store
        self._id_generator = id_generator or DemoTaskIdGenerator()

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
