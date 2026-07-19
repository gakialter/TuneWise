from __future__ import annotations

import statistics
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Mapping, Sequence

from .detection import ControlLimitSnapshot
from .replay_contracts import (
    REPLAY_METRIC_DEFINITION_VERSION,
    BatchReplayMetrics,
    EvaluationCheck,
    ReplayEvaluation,
    ReplayEvaluationRuleSnapshot,
    ReplayGuardError,
    ReplayStatus,
)


PRECISION = Decimal("0.000001")
MTF_FIELDS = ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
CORNER_FIELDS = ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
PARAMETER_FIELDS = ("x_offset", "y_offset", "pitch", "roll", "z_offset")


def decimal_metric(value: str, field: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ReplayGuardError("REPLAY_METRIC_INPUT_INVALID", f"回放指标 {field} 格式无效。") from error
    if not parsed.is_finite():
        raise ReplayGuardError("REPLAY_METRIC_INPUT_INVALID", f"回放指标 {field} 格式无效。")
    return parsed


def fixed_metric(value: Decimal) -> str:
    return format(value.quantize(PRECISION, rounding=ROUND_HALF_EVEN), "f")


def derive_replay_metrics(
    measurements: Sequence[Mapping[str, str]],
    control_limits: ControlLimitSnapshot,
) -> BatchReplayMetrics:
    if not measurements:
        raise ReplayGuardError("REPLAY_MEASUREMENTS_MISSING", "回放可观测结果为空。")
    ordered = sorted(measurements, key=lambda row: int(row["sample_index"]))
    means = {
        field: sum((decimal_metric(row[field], field) for row in ordered), Decimal(0))
        / len(ordered)
        for field in MTF_FIELDS
    }
    center_values = [decimal_metric(row["mtf_center"], "mtf_center") for row in ordered]
    corners = [means[field] for field in CORNER_FIELDS]
    corner_mean = sum(corners, Decimal(0)) / len(corners)
    corner_min = min(corners)
    corner_range = max(corners) - corner_min
    corner_std = statistics.pstdev(corners)
    center_qualified = means["mtf_center"] >= control_limits.center_lower_limit
    target_anomaly = center_qualified and (
        corner_min < control_limits.corner_lower_limit
        or corner_range > control_limits.asymmetry_limit
        or corner_std > control_limits.corner_std_limit
    )
    current = ordered[-1]
    return BatchReplayMetrics(
        sample_count=len(ordered),
        mtf_center_mean=fixed_metric(means["mtf_center"]),
        mtf_center_std=fixed_metric(statistics.pstdev(center_values)),
        mtf_lt_mean=fixed_metric(means["mtf_lt"]),
        mtf_rt_mean=fixed_metric(means["mtf_rt"]),
        mtf_lb_mean=fixed_metric(means["mtf_lb"]),
        mtf_rb_mean=fixed_metric(means["mtf_rb"]),
        corner_mtf_mean=fixed_metric(corner_mean),
        corner_mtf_min=fixed_metric(corner_min),
        corner_mtf_range=fixed_metric(corner_range),
        corner_mtf_std=fixed_metric(corner_std),
        center_corner_gap=fixed_metric(means["mtf_center"] - corner_mean),
        control_limit_pass=(
            center_qualified
            and corner_min >= control_limits.corner_lower_limit
            and corner_range <= control_limits.asymmetry_limit
            and corner_std <= control_limits.corner_std_limit
        ),
        target_anomaly_triggered=target_anomaly,
        parameter_summary={field: current[field] for field in PARAMETER_FIELDS},
        metric_definition_version=REPLAY_METRIC_DEFINITION_VERSION,
        standard_deviation_method="POPULATION",
    )


class ReplayEvaluator:
    @staticmethod
    def _numeric_check(
        *,
        check_id: str,
        metric: str,
        before: str,
        after: str,
        threshold: str | None,
        tolerance: str | None,
        passed: bool,
        rule_version: str,
    ) -> EvaluationCheck:
        return EvaluationCheck(
            check_id=check_id,
            metric=metric,
            before_value=before,
            after_value=after,
            delta=fixed_metric(decimal_metric(after, metric) - decimal_metric(before, metric)),
            threshold=threshold,
            tolerance=tolerance,
            status="PASSED" if passed else "FAILED",
            rule_version=rule_version,
            explanation_template_key=f"replay.check.{check_id.lower()}",
        )

    @staticmethod
    def _boolean_check(
        *,
        check_id: str,
        metric: str,
        before: bool,
        after: bool,
        passed: bool,
        rule_version: str,
    ) -> EvaluationCheck:
        return EvaluationCheck(
            check_id=check_id,
            metric=metric,
            before_value=before,
            after_value=after,
            delta="UNCHANGED" if before == after else f"{before}->{after}",
            threshold="true",
            tolerance=None,
            status="PASSED" if passed else "FAILED",
            rule_version=rule_version,
            explanation_template_key=f"replay.check.{check_id.lower()}",
        )

    def evaluate(
        self,
        before: BatchReplayMetrics,
        after: BatchReplayMetrics,
        rules: ReplayEvaluationRuleSnapshot,
    ) -> ReplayEvaluation:
        center_delta = decimal_metric(after.mtf_center_mean, "mtf_center_mean") - decimal_metric(
            before.mtf_center_mean, "mtf_center_mean"
        )
        corner_delta = decimal_metric(after.corner_mtf_min, "corner_mtf_min") - decimal_metric(
            before.corner_mtf_min, "corner_mtf_min"
        )
        range_reduction = decimal_metric(before.corner_mtf_range, "corner_mtf_range") - decimal_metric(
            after.corner_mtf_range, "corner_mtf_range"
        )
        std_reduction = decimal_metric(before.corner_mtf_std, "corner_mtf_std") - decimal_metric(
            after.corner_mtf_std, "corner_mtf_std"
        )
        center_tolerance = decimal_metric(rules.center_regression_tolerance, "center_regression_tolerance")
        corner_threshold = decimal_metric(
            rules.minimum_corner_min_improvement, "minimum_corner_min_improvement"
        )
        range_threshold = decimal_metric(rules.minimum_range_reduction, "minimum_range_reduction")
        std_threshold = decimal_metric(rules.minimum_std_reduction, "minimum_std_reduction")
        center_guard = center_delta >= -center_tolerance
        corner_guard = corner_delta >= -corner_threshold
        range_guard = range_reduction >= -range_threshold
        std_guard = std_reduction >= -std_threshold
        control_guard = not before.control_limit_pass or after.control_limit_pass
        corner_improved = corner_delta >= corner_threshold
        range_improved = range_reduction >= range_threshold
        std_improved = std_reduction >= std_threshold
        rule_version = rules.evaluation_rule_version
        checks = (
            self._numeric_check(check_id="CENTER_REGRESSION_GUARD", metric="mtf_center_mean", before=before.mtf_center_mean, after=after.mtf_center_mean, threshold=None, tolerance=rules.center_regression_tolerance, passed=center_guard, rule_version=rule_version),
            self._numeric_check(check_id="WORST_CORNER_REGRESSION_GUARD", metric="corner_mtf_min", before=before.corner_mtf_min, after=after.corner_mtf_min, threshold=None, tolerance=rules.minimum_corner_min_improvement, passed=corner_guard, rule_version=rule_version),
            self._numeric_check(check_id="CORNER_RANGE_REGRESSION_GUARD", metric="corner_mtf_range", before=before.corner_mtf_range, after=after.corner_mtf_range, threshold=None, tolerance=rules.minimum_range_reduction, passed=range_guard, rule_version=rule_version),
            self._numeric_check(check_id="CORNER_STD_REGRESSION_GUARD", metric="corner_mtf_std", before=before.corner_mtf_std, after=after.corner_mtf_std, threshold=None, tolerance=rules.minimum_std_reduction, passed=std_guard, rule_version=rule_version),
            self._boolean_check(check_id="CONTROL_LIMIT_REGRESSION_GUARD", metric="control_limit_pass", before=before.control_limit_pass, after=after.control_limit_pass, passed=control_guard, rule_version=rule_version),
            self._numeric_check(check_id="WORST_CORNER_IMPROVEMENT", metric="corner_mtf_min", before=before.corner_mtf_min, after=after.corner_mtf_min, threshold=rules.minimum_corner_min_improvement, tolerance=None, passed=corner_improved, rule_version=rule_version),
            self._numeric_check(check_id="CORNER_RANGE_REDUCTION", metric="corner_mtf_range", before=before.corner_mtf_range, after=after.corner_mtf_range, threshold=rules.minimum_range_reduction, tolerance=None, passed=range_improved, rule_version=rule_version),
            self._numeric_check(check_id="CORNER_STD_REDUCTION", metric="corner_mtf_std", before=before.corner_mtf_std, after=after.corner_mtf_std, threshold=rules.minimum_std_reduction, tolerance=None, passed=std_improved, rule_version=rule_version),
            self._boolean_check(check_id="CONTROL_LIMIT_PASS", metric="control_limit_pass", before=before.control_limit_pass, after=after.control_limit_pass, passed=after.control_limit_pass, rule_version=rule_version),
            self._boolean_check(check_id="TARGET_ANOMALY_CLEARED", metric="target_anomaly_triggered", before=before.target_anomaly_triggered, after=after.target_anomaly_triggered, passed=not after.target_anomaly_triggered, rule_version=rule_version),
        )
        protection_passed = all((center_guard, corner_guard, range_guard, std_guard, control_guard))
        if not protection_passed:
            status = ReplayStatus.REGRESSION
        elif corner_improved and (range_improved or std_improved) and after.control_limit_pass:
            status = ReplayStatus.SUCCESS
        elif corner_improved or range_improved or std_improved:
            status = ReplayStatus.PARTIAL_IMPROVEMENT
        else:
            status = ReplayStatus.NO_IMPROVEMENT
        return ReplayEvaluation(status.value, checks)


def metric_deltas(
    before: BatchReplayMetrics,
    after: BatchReplayMetrics,
) -> dict[str, str]:
    names = (
        "mtf_center_mean",
        "mtf_center_std",
        "mtf_lt_mean",
        "mtf_rt_mean",
        "mtf_lb_mean",
        "mtf_rb_mean",
        "corner_mtf_mean",
        "corner_mtf_min",
        "corner_mtf_range",
        "corner_mtf_std",
        "center_corner_gap",
    )
    return {
        name: fixed_metric(
            decimal_metric(getattr(after, name), name) - decimal_metric(getattr(before, name), name)
        )
        for name in names
    }
