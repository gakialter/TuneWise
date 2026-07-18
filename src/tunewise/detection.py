from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_EVEN
from enum import StrEnum

from .importing import CANONICAL_PRECISION, OBSERVABLE_FIELDS


CORNER_FIELDS: tuple[str, ...] = ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")


class AnomalyResult(StrEnum):
    TARGET_ANOMALY = "TARGET_ANOMALY"
    NORMAL = "NORMAL"
    NON_TARGET_GLOBAL_DEGRADATION = "NON_TARGET_GLOBAL_DEGRADATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RuleCheckStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_EVALUATED = "NOT_EVALUATED"


@dataclass(frozen=True, slots=True)
class ControlLimitSnapshot:
    snapshot_version: str
    rule_set_version: str
    center_lower_limit: Decimal
    corner_lower_limit: Decimal
    asymmetry_limit: Decimal
    corner_std_limit: Decimal


@dataclass(frozen=True, slots=True)
class SpcRuleSnapshot:
    snapshot_version: str
    rule_set_version: str
    minimum_sample_count: int
    minimum_consecutive_violations: int
    minimum_violation_ratio: Decimal
    center_clear_degradation_margin: Decimal
    global_corner_fraction: Decimal


@dataclass(frozen=True, slots=True)
class DetectionInput:
    task_id: str
    batch_id: str
    measurements: tuple[dict[str, str], ...]
    control_limits: ControlLimitSnapshot
    rule_snapshot: SpcRuleSnapshot
    input_data_version: str
    input_hash: str


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    mtf_center: str | None
    mtf_lt: str | None
    mtf_rt: str | None
    mtf_lb: str | None
    mtf_rb: str | None
    corner_mtf_min: str | None
    corner_mtf_range: str | None
    corner_mtf_std: str | None


@dataclass(frozen=True, slots=True)
class ControlLimitEvidence:
    center_lower_limit: str
    corner_lower_limit: str
    asymmetry_limit: str
    corner_std_limit: str


@dataclass(frozen=True, slots=True)
class RuleCheck:
    rule_id: str
    status: RuleCheckStatus
    actual: str | None
    threshold: str | None
    operator: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class PersistenceEvidence:
    sample_count: int
    violating_sample_count: int
    violation_ratio: str
    maximum_consecutive_violations: int
    minimum_consecutive_violations: int
    minimum_violation_ratio: str
    consecutive_condition_met: bool
    ratio_condition_met: bool


@dataclass(frozen=True, slots=True)
class DetectionDecision:
    task_id: str
    batch_id: str
    anomaly_result: AnomalyResult
    aggregate_metrics: AggregateMetrics
    control_limits: ControlLimitEvidence
    rule_checks: tuple[RuleCheck, ...]
    persistence_evidence: PersistenceEvidence
    control_limit_snapshot_version: str
    rule_set_version: str
    rule_snapshot_version: str
    input_data_version: str
    input_hash: str
    result_hash: str


@dataclass(frozen=True, slots=True)
class AnomalyDetectionRecord:
    detection_result_id: str
    task_id: str
    batch_id: str
    anomaly_result: AnomalyResult
    aggregate_metrics: AggregateMetrics
    control_limits: ControlLimitEvidence
    rule_checks: tuple[RuleCheck, ...]
    persistence_evidence: PersistenceEvidence
    control_limit_snapshot_version: str
    rule_set_version: str
    rule_snapshot_version: str
    input_data_version: str
    input_hash: str
    result_hash: str
    created_at: str


class DetectionGuardError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now(self) -> str:
        return (
            datetime.now(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )


class SpcRuleRegistry:
    @staticmethod
    def snapshot_for(rule_set_version: str) -> SpcRuleSnapshot:
        if rule_set_version != "tw-rules-v1":
            raise KeyError(rule_set_version)
        return SpcRuleSnapshot(
            snapshot_version="tw-spc-detection-v1",
            rule_set_version=rule_set_version,
            minimum_sample_count=8,
            minimum_consecutive_violations=3,
            minimum_violation_ratio=Decimal("0.250000"),
            center_clear_degradation_margin=Decimal("0.020000"),
            global_corner_fraction=Decimal("0.750000"),
        )


class ControlLimitRegistry:
    @staticmethod
    def snapshot_for(rule_set_version: str) -> ControlLimitSnapshot:
        if rule_set_version != "tw-rules-v1":
            raise KeyError(rule_set_version)
        return ControlLimitSnapshot(
            snapshot_version="tw-control-limits-v1",
            rule_set_version=rule_set_version,
            center_lower_limit=Decimal("0.720000"),
            corner_lower_limit=Decimal("0.620000"),
            asymmetry_limit=Decimal("0.120000"),
            corner_std_limit=Decimal("0.050000"),
        )


def serialize_spc_rule_snapshot(snapshot: SpcRuleSnapshot) -> dict[str, str | int]:
    return {
        "snapshot_version": snapshot.snapshot_version,
        "rule_set_version": snapshot.rule_set_version,
        "minimum_sample_count": snapshot.minimum_sample_count,
        "minimum_consecutive_violations": snapshot.minimum_consecutive_violations,
        "minimum_violation_ratio": _format(snapshot.minimum_violation_ratio),
        "center_clear_degradation_margin": _format(
            snapshot.center_clear_degradation_margin
        ),
        "global_corner_fraction": _format(snapshot.global_corner_fraction),
    }


def deserialize_spc_rule_snapshot(payload: dict) -> SpcRuleSnapshot:
    return SpcRuleSnapshot(
        snapshot_version=payload["snapshot_version"],
        rule_set_version=payload["rule_set_version"],
        minimum_sample_count=int(payload["minimum_sample_count"]),
        minimum_consecutive_violations=int(
            payload["minimum_consecutive_violations"]
        ),
        minimum_violation_ratio=Decimal(payload["minimum_violation_ratio"]),
        center_clear_degradation_margin=Decimal(
            payload["center_clear_degradation_margin"]
        ),
        global_corner_fraction=Decimal(payload["global_corner_fraction"]),
    )


def canonical_measurement_hash(
    measurements: tuple[dict[str, str], ...],
) -> str:
    try:
        records = [
            [measurement[field] for field in OBSERVABLE_FIELDS]
            for measurement in sorted(
                measurements,
                key=lambda item: int(item["sample_index"]),
            )
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise DetectionGuardError(
            "DETECTION_INPUT_INTEGRITY_INVALID",
            "持久化 Measurement 无法按冻结字段规范化。",
        ) from error
    content = json.dumps(
        {
            "canonicalizer_version": "tw-canonicalizer-v1",
            "fields": list(OBSERVABLE_FIELDS),
            "records": records,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def record_detection(
    decision: DetectionDecision,
    *,
    created_at: str,
) -> AnomalyDetectionRecord:
    return AnomalyDetectionRecord(
        detection_result_id=f"tw-detection-{decision.result_hash}",
        task_id=decision.task_id,
        batch_id=decision.batch_id,
        anomaly_result=decision.anomaly_result,
        aggregate_metrics=decision.aggregate_metrics,
        control_limits=decision.control_limits,
        rule_checks=decision.rule_checks,
        persistence_evidence=decision.persistence_evidence,
        control_limit_snapshot_version=decision.control_limit_snapshot_version,
        rule_set_version=decision.rule_set_version,
        rule_snapshot_version=decision.rule_snapshot_version,
        input_data_version=decision.input_data_version,
        input_hash=decision.input_hash,
        result_hash=decision.result_hash,
        created_at=created_at,
    )


def deserialize_detection_record(payload: dict) -> AnomalyDetectionRecord:
    return AnomalyDetectionRecord(
        detection_result_id=payload["detection_result_id"],
        task_id=payload["task_id"],
        batch_id=payload["batch_id"],
        anomaly_result=AnomalyResult(payload["anomaly_result"]),
        aggregate_metrics=AggregateMetrics(**payload["aggregate_metrics"]),
        control_limits=ControlLimitEvidence(**payload["control_limits"]),
        rule_checks=tuple(
            RuleCheck(
                rule_id=check["rule_id"],
                status=RuleCheckStatus(check["status"]),
                actual=check["actual"],
                threshold=check["threshold"],
                operator=check["operator"],
                detail=check["detail"],
            )
            for check in payload["rule_checks"]
        ),
        persistence_evidence=PersistenceEvidence(
            **payload["persistence_evidence"]
        ),
        control_limit_snapshot_version=payload[
            "control_limit_snapshot_version"
        ],
        rule_set_version=payload["rule_set_version"],
        rule_snapshot_version=payload["rule_snapshot_version"],
        input_data_version=payload["input_data_version"],
        input_hash=payload["input_hash"],
        result_hash=payload["result_hash"],
        created_at=payload["created_at"],
    )


def _format(value: Decimal) -> str:
    return format(
        value.quantize(CANONICAL_PRECISION, rounding=ROUND_HALF_EVEN),
        "f",
    )


class AnomalyDetector:
    def detect(self, detection_input: DetectionInput) -> DetectionDecision:
        invalid_reason = self._invalid_reason(detection_input)
        if invalid_reason is not None:
            return self._insufficient(detection_input, invalid_reason)

        rows = tuple(
            sorted(
                detection_input.measurements,
                key=lambda row: int(row["sample_index"]),
            )
        )
        limits = detection_input.control_limits
        rules = detection_input.rule_snapshot
        parsed = tuple(self._parse_measurement(row) for row in rows)
        metrics = self._aggregate(parsed)
        center_clear_floor = (
            limits.center_lower_limit - rules.center_clear_degradation_margin
        )

        corner_min_hits: list[bool] = []
        corner_range_hits: list[bool] = []
        corner_std_hits: list[bool] = []
        corner_min_values: list[Decimal] = []
        corner_range_values: list[Decimal] = []
        corner_std_values: list[Decimal] = []
        target_hits: list[bool] = []
        global_hits: list[bool] = []
        minimum_global_corners = int(
            (Decimal(len(CORNER_FIELDS)) * rules.global_corner_fraction)
            .to_integral_value(rounding=ROUND_CEILING)
        )
        for row in parsed:
            corners = tuple(row[field] for field in CORNER_FIELDS)
            corner_min = min(corners)
            corner_range = max(corners) - corner_min
            corner_std = statistics.pstdev(corners)
            corner_min_hit = corner_min < limits.corner_lower_limit
            corner_range_hit = corner_range > limits.asymmetry_limit
            corner_std_hit = corner_std > limits.corner_std_limit
            corner_signal = corner_min_hit or corner_range_hit or corner_std_hit
            center_not_clearly_low = row["mtf_center"] >= center_clear_floor
            globally_low_corners = sum(
                corner < limits.corner_lower_limit for corner in corners
            ) >= minimum_global_corners
            corner_min_hits.append(corner_min_hit)
            corner_range_hits.append(corner_range_hit)
            corner_std_hits.append(corner_std_hit)
            corner_min_values.append(corner_min)
            corner_range_values.append(corner_range)
            corner_std_values.append(corner_std)
            target_hits.append(center_not_clearly_low and corner_signal)
            global_hits.append(
                row["mtf_center"] < center_clear_floor and globally_low_corners
            )

        target_persistence = self._persistence(target_hits, rules)
        global_persistence = self._persistence(global_hits, rules)
        center_gate = Decimal(metrics.mtf_center) >= center_clear_floor
        any_corner_signal = any(corner_min_hits) or any(corner_range_hits) or any(
            corner_std_hits
        )
        global_degradation = (
            any(global_hits)
            and (
                global_persistence.consecutive_condition_met
                or global_persistence.ratio_condition_met
            )
        )
        persistence_met = (
            target_persistence.consecutive_condition_met
            or target_persistence.ratio_condition_met
        )
        if global_degradation:
            anomaly_result = AnomalyResult.NON_TARGET_GLOBAL_DEGRADATION
        elif center_gate and any_corner_signal and persistence_met:
            anomaly_result = AnomalyResult.TARGET_ANOMALY
        else:
            anomaly_result = AnomalyResult.NORMAL

        route_persistence = (
            global_persistence if global_degradation else target_persistence
        )
        checks = self._evaluated_checks(
            metrics=metrics,
            limits=limits,
            rules=rules,
            corner_min_hits=corner_min_hits,
            corner_range_hits=corner_range_hits,
            corner_std_hits=corner_std_hits,
            corner_min_values=corner_min_values,
            corner_range_values=corner_range_values,
            corner_std_values=corner_std_values,
            center_gate=center_gate,
            global_degradation=global_degradation,
            persistence=route_persistence,
            anomaly_result=anomaly_result,
        )
        return self._decision(
            detection_input=detection_input,
            anomaly_result=anomaly_result,
            metrics=metrics,
            checks=checks,
            persistence=route_persistence,
        )

    @staticmethod
    def _invalid_reason(detection_input: DetectionInput) -> str | None:
        rules = detection_input.rule_snapshot
        rows = detection_input.measurements
        if len(rows) < rules.minimum_sample_count:
            return (
                f"样本数量 {len(rows)} 低于冻结规则最小值 "
                f"{rules.minimum_sample_count}。"
            )
        seen_indexes: set[int] = set()
        for row_number, row in enumerate(rows, start=1):
            missing = [field for field in OBSERVABLE_FIELDS if field not in row]
            if missing:
                return f"第 {row_number} 条 Measurement 缺少字段：{', '.join(missing)}。"
            unavailable = [
                field
                for field in OBSERVABLE_FIELDS
                if not isinstance(row[field], str) or not row[field].strip()
            ]
            if unavailable:
                return (
                    f"第 {row_number} 条 Measurement 字段不可用："
                    f"{', '.join(unavailable)}。"
                )
            try:
                sample_index = int(row["sample_index"])
                if sample_index in seen_indexes:
                    return "sample_index 重复，无法计算持续性。"
                seen_indexes.add(sample_index)
                for field in ("mtf_center", *CORNER_FIELDS):
                    value = Decimal(row[field])
                    if not value.is_finite() or value < 0 or value > 1:
                        return f"第 {row_number} 条 Measurement 的 {field} 无效。"
            except (ValueError, InvalidOperation):
                return f"第 {row_number} 条 Measurement 无法计算持续性。"
        ordered_indexes = sorted(seen_indexes)
        if any(
            current != previous + 1
            for previous, current in zip(ordered_indexes, ordered_indexes[1:])
        ):
            return "sample_index 不连续，无法计算持续性。"
        if detection_input.control_limits.rule_set_version != rules.rule_set_version:
            return "控制限与 SPC 规则版本不一致。"
        return None

    @staticmethod
    def _parse_measurement(row: dict[str, str]) -> dict[str, Decimal]:
        return {
            field: Decimal(row[field])
            for field in ("mtf_center", *CORNER_FIELDS)
        }

    @staticmethod
    def _aggregate(rows: tuple[dict[str, Decimal], ...]) -> AggregateMetrics:
        means = {
            field: sum((row[field] for row in rows), Decimal(0)) / len(rows)
            for field in ("mtf_center", *CORNER_FIELDS)
        }
        corners = tuple(means[field] for field in CORNER_FIELDS)
        return AggregateMetrics(
            mtf_center=_format(means["mtf_center"]),
            mtf_lt=_format(means["mtf_lt"]),
            mtf_rt=_format(means["mtf_rt"]),
            mtf_lb=_format(means["mtf_lb"]),
            mtf_rb=_format(means["mtf_rb"]),
            corner_mtf_min=_format(min(corners)),
            corner_mtf_range=_format(max(corners) - min(corners)),
            corner_mtf_std=_format(statistics.pstdev(corners)),
        )

    @staticmethod
    def _persistence(
        violations: list[bool],
        rules: SpcRuleSnapshot,
    ) -> PersistenceEvidence:
        maximum = 0
        current = 0
        for violation in violations:
            current = current + 1 if violation else 0
            maximum = max(maximum, current)
        count = sum(violations)
        ratio = Decimal(count) / len(violations) if violations else Decimal(0)
        return PersistenceEvidence(
            sample_count=len(violations),
            violating_sample_count=count,
            violation_ratio=_format(ratio),
            maximum_consecutive_violations=maximum,
            minimum_consecutive_violations=rules.minimum_consecutive_violations,
            minimum_violation_ratio=_format(rules.minimum_violation_ratio),
            consecutive_condition_met=(
                maximum >= rules.minimum_consecutive_violations
            ),
            ratio_condition_met=ratio >= rules.minimum_violation_ratio,
        )

    @staticmethod
    def _check(
        rule_id: str,
        passed: bool,
        actual: str | int | None,
        threshold: str | int | None,
        operator: str | None,
        detail: str,
    ) -> RuleCheck:
        return RuleCheck(
            rule_id=rule_id,
            status=RuleCheckStatus.PASSED if passed else RuleCheckStatus.FAILED,
            actual=None if actual is None else str(actual),
            threshold=None if threshold is None else str(threshold),
            operator=operator,
            detail=detail,
        )

    def _evaluated_checks(
        self,
        *,
        metrics: AggregateMetrics,
        limits: ControlLimitSnapshot,
        rules: SpcRuleSnapshot,
        corner_min_hits: list[bool],
        corner_range_hits: list[bool],
        corner_std_hits: list[bool],
        corner_min_values: list[Decimal],
        corner_range_values: list[Decimal],
        corner_std_values: list[Decimal],
        center_gate: bool,
        global_degradation: bool,
        persistence: PersistenceEvidence,
        anomaly_result: AnomalyResult,
    ) -> tuple[RuleCheck, ...]:
        minimum_corner_hit = any(corner_min_hits)
        range_hit = any(corner_range_hits)
        std_hit = any(corner_std_hits)
        corner_signal = minimum_corner_hit or range_hit or std_hit
        persistence_met = (
            persistence.consecutive_condition_met
            or persistence.ratio_condition_met
        )
        return (
            self._check(
                "INPUT_DATA_SUFFICIENT",
                True,
                persistence.sample_count,
                rules.minimum_sample_count,
                ">=",
                "必需 Measurement 字段完整且可计算持续性。",
            ),
            self._check(
                "GLOBAL_DEGRADATION_PROTECTION",
                global_degradation,
                "GLOBAL" if global_degradation else "NOT_GLOBAL",
                "PROTECTED_WHEN_PERSISTENT",
                "==",
                "整体退化优先于四角不对称目标异常。",
            ),
            self._check(
                "CENTER_NOT_CLEARLY_LOW",
                center_gate,
                metrics.mtf_center,
                _format(
                    limits.center_lower_limit
                    - rules.center_clear_degradation_margin
                ),
                ">=",
                "中心 MTF 不明显低于中心控制下限。",
            ),
            self._check(
                "CORNER_MIN_LIMIT",
                minimum_corner_hit,
                _format(min(corner_min_values)),
                _format(limits.corner_lower_limit),
                "<",
                f"{sum(corner_min_hits)} 个样本的最差角低于角落控制下限。",
            ),
            self._check(
                "CORNER_RANGE_LIMIT",
                range_hit,
                _format(max(corner_range_values)),
                _format(limits.asymmetry_limit),
                ">",
                f"{sum(corner_range_hits)} 个样本的四角极差超过不对称限。",
            ),
            self._check(
                "CORNER_STD_LIMIT",
                std_hit,
                _format(max(corner_std_values)),
                _format(limits.corner_std_limit),
                ">",
                f"{sum(corner_std_hits)} 个样本的四角标准差超过离散限。",
            ),
            self._check(
                "CORNER_SIGNAL_PRESENT",
                corner_signal,
                sum(a or b or c for a, b, c in zip(
                    corner_min_hits, corner_range_hits, corner_std_hits
                )),
                1,
                ">=",
                "三项四角信号至少一项成立。",
            ),
            self._check(
                "MINIMUM_CONSECUTIVE_VIOLATIONS",
                persistence.consecutive_condition_met,
                persistence.maximum_consecutive_violations,
                rules.minimum_consecutive_violations,
                ">=",
                "按 sample_index 计算当前路由信号的最大连续越限长度。",
            ),
            self._check(
                "MINIMUM_VIOLATION_RATIO",
                persistence.ratio_condition_met,
                persistence.violation_ratio,
                _format(rules.minimum_violation_ratio),
                ">=",
                "当前路由信号越限样本比例。",
            ),
            self._check(
                "PERSISTENCE_CONDITION",
                persistence_met,
                "CONSECUTIVE_OR_RATIO" if persistence_met else "NOT_MET",
                "CONSECUTIVE_OR_RATIO",
                "==",
                "连续次数或样本比例至少满足一项。",
            ),
            self._check(
                "TARGET_ANOMALY_DECISION",
                anomaly_result is AnomalyResult.TARGET_ANOMALY,
                anomaly_result.value,
                AnomalyResult.TARGET_ANOMALY.value,
                "==",
                "仅目标异常允许任务推进。",
            ),
        )

    def _insufficient(
        self,
        detection_input: DetectionInput,
        reason: str,
    ) -> DetectionDecision:
        rules = detection_input.rule_snapshot
        persistence = PersistenceEvidence(
            sample_count=len(detection_input.measurements),
            violating_sample_count=0,
            violation_ratio="0.000000",
            maximum_consecutive_violations=0,
            minimum_consecutive_violations=rules.minimum_consecutive_violations,
            minimum_violation_ratio=_format(rules.minimum_violation_ratio),
            consecutive_condition_met=False,
            ratio_condition_met=False,
        )
        checks = (
            RuleCheck(
                rule_id="INPUT_DATA_SUFFICIENT",
                status=RuleCheckStatus.FAILED,
                actual=str(len(detection_input.measurements)),
                threshold=str(rules.minimum_sample_count),
                operator=">=",
                detail=reason,
            ),
            *(
                RuleCheck(
                    rule_id=rule_id,
                    status=RuleCheckStatus.NOT_EVALUATED,
                    actual=None,
                    threshold=None,
                    operator=None,
                    detail="输入不足，未执行此规则。",
                )
                for rule_id in (
                    "GLOBAL_DEGRADATION_PROTECTION",
                    "CENTER_NOT_CLEARLY_LOW",
                    "CORNER_MIN_LIMIT",
                    "CORNER_RANGE_LIMIT",
                    "CORNER_STD_LIMIT",
                    "CORNER_SIGNAL_PRESENT",
                    "MINIMUM_CONSECUTIVE_VIOLATIONS",
                    "MINIMUM_VIOLATION_RATIO",
                    "PERSISTENCE_CONDITION",
                    "TARGET_ANOMALY_DECISION",
                )
            ),
        )
        return self._decision(
            detection_input=detection_input,
            anomaly_result=AnomalyResult.INSUFFICIENT_DATA,
            metrics=AggregateMetrics(*(None for _ in range(8))),
            checks=checks,
            persistence=persistence,
        )

    @staticmethod
    def _decision(
        *,
        detection_input: DetectionInput,
        anomaly_result: AnomalyResult,
        metrics: AggregateMetrics,
        checks: tuple[RuleCheck, ...],
        persistence: PersistenceEvidence,
    ) -> DetectionDecision:
        payload = {
            "task_id": detection_input.task_id,
            "batch_id": detection_input.batch_id,
            "anomaly_result": anomaly_result.value,
            "aggregate_metrics": asdict(metrics),
            "control_limits": asdict(
                ControlLimitEvidence(
                    center_lower_limit=_format(
                        detection_input.control_limits.center_lower_limit
                    ),
                    corner_lower_limit=_format(
                        detection_input.control_limits.corner_lower_limit
                    ),
                    asymmetry_limit=_format(
                        detection_input.control_limits.asymmetry_limit
                    ),
                    corner_std_limit=_format(
                        detection_input.control_limits.corner_std_limit
                    ),
                )
            ),
            "rule_checks": [asdict(check) for check in checks],
            "persistence_evidence": asdict(persistence),
            "control_limit_snapshot_version": (
                detection_input.control_limits.snapshot_version
            ),
            "rule_set_version": detection_input.rule_snapshot.rule_set_version,
            "rule_snapshot_version": (
                detection_input.rule_snapshot.snapshot_version
            ),
            "input_data_version": detection_input.input_data_version,
            "input_hash": detection_input.input_hash,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return DetectionDecision(
            task_id=detection_input.task_id,
            batch_id=detection_input.batch_id,
            aggregate_metrics=metrics,
            control_limits=ControlLimitEvidence(
                center_lower_limit=_format(
                    detection_input.control_limits.center_lower_limit
                ),
                corner_lower_limit=_format(
                    detection_input.control_limits.corner_lower_limit
                ),
                asymmetry_limit=_format(
                    detection_input.control_limits.asymmetry_limit
                ),
                corner_std_limit=_format(
                    detection_input.control_limits.corner_std_limit
                ),
            ),
            rule_checks=checks,
            persistence_evidence=persistence,
            anomaly_result=anomaly_result,
            control_limit_snapshot_version=(
                detection_input.control_limits.snapshot_version
            ),
            rule_set_version=detection_input.rule_snapshot.rule_set_version,
            rule_snapshot_version=detection_input.rule_snapshot.snapshot_version,
            input_data_version=detection_input.input_data_version,
            input_hash=detection_input.input_hash,
            result_hash=hashlib.sha256(canonical).hexdigest(),
        )
