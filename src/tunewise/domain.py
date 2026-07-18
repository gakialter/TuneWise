from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    DATA_IMPORTED = "DATA_IMPORTED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    DIAGNOSED = "DIAGNOSED"
    PLAN_READY = "PLAN_READY"
    PLAN_CONFIRMED = "PLAN_CONFIRMED"
    REPLAYING = "REPLAYING"
    REPLAYED = "REPLAYED"
    CLOSED = "CLOSED"
    CASE_SUBMITTED = "CASE_SUBMITTED"


@dataclass(frozen=True, slots=True)
class Actor:
    actor_id: str
    actor_role: str
    display_name: str


@dataclass(frozen=True, slots=True)
class VersionSnapshot:
    public_asset_version: str
    application_version: str
    dataset_version: str
    schema_version: str
    rule_set_version: str
    model_version: str
    preprocessing_version: str
    evaluation_rule_version: str
    canonicalizer_version: str


@dataclass(frozen=True, slots=True)
class PublicAssetSnapshot:
    actor: Actor
    versions: VersionSnapshot


@dataclass(frozen=True, slots=True)
class WorkflowStage:
    code: TaskStatus
    label: str
    availability: str


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    status: TaskStatus
    actor: Actor
    versions: VersionSnapshot
    stages: tuple[WorkflowStage, ...]


STAGE_LABELS: tuple[tuple[TaskStatus, str], ...] = (
    (TaskStatus.CREATED, "任务创建"),
    (TaskStatus.DATA_IMPORTED, "数据导入"),
    (TaskStatus.ANOMALY_DETECTED, "异常检测"),
    (TaskStatus.DIAGNOSED, "根因诊断"),
    (TaskStatus.PLAN_READY, "候选方案"),
    (TaskStatus.PLAN_CONFIRMED, "人工确认"),
    (TaskStatus.REPLAYING, "回放执行"),
    (TaskStatus.REPLAYED, "回放结果"),
    (TaskStatus.CLOSED, "复盘关闭"),
    (TaskStatus.CASE_SUBMITTED, "案例提交"),
)


def workflow_for(status: TaskStatus) -> tuple[WorkflowStage, ...]:
    current_index = next(
        index
        for index, (stage_status, _) in enumerate(STAGE_LABELS)
        if stage_status == status
    )
    return tuple(
        WorkflowStage(
            code=stage_status,
            label=label,
            availability=(
                "completed"
                if index < current_index
                else "current"
                if index == current_index
                else "locked"
            ),
        )
        for index, (stage_status, label) in enumerate(STAGE_LABELS)
    )
