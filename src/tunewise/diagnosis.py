from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any

from .diagnostic_contract import (
    CALCULATION_VERSION,
    CLASS_ORDER,
    DIAGNOSTIC_RESULT_VERSION,
    EVIDENCE_RULE_VERSION,
    FEATURE_DEFINITION_VERSION,
    FEATURE_NAMES,
    MTF_FIELDS,
    MODEL_VERSION,
    PARAMETER_FIELDS,
    PLATFORM_FIELDS,
    PREPROCESSING_VERSION,
)
from .detection import ControlLimitSnapshot
from .importing import OBSERVABLE_FIELDS


class FeatureEngineeringError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DiagnosticAssetError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class DiagnosticGuardError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DerivedFeatureSet:
    feature_definition_version: str
    feature_names: tuple[str, ...]
    values: tuple[float, ...]
    input_feature_hash: str


@dataclass(frozen=True, slots=True)
class DiagnosticAssets:
    manifest: dict[str, Any]
    feature_definition: dict[str, Any]
    preprocessing: dict[str, Any]
    model: dict[str, Any]
    class_order: tuple[str, ...]
    evidence_rules: dict[str, Any]
    input_asset_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class StructuredEvidence:
    rule_id: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class KeyObservation:
    feature_name: str
    value: str
    summary: str


@dataclass(frozen=True, slots=True)
class LogitContribution:
    feature_name: str
    feature_index: int
    standardized_feature_value: str
    class_coefficient: str
    contribution: str
    description: str = "该特征对当前类别 logit 的贡献"


@dataclass(frozen=True, slots=True)
class RootCauseCandidate:
    rank: int
    root_cause: str
    normalized_score: str
    raw_logit: str
    adjustability: str
    matched_explicit_rules: tuple[StructuredEvidence, ...]
    key_observations: tuple[KeyObservation, ...]
    positive_logit_contributions: tuple[LogitContribution, ...]
    conflict_evidence: tuple[StructuredEvidence, ...]
    model_version: str
    preprocessing_version: str
    feature_definition_version: str


@dataclass(frozen=True, slots=True)
class ZGateResult:
    status: str
    passed: bool
    checks: tuple[StructuredEvidence, ...]
    removed_category: str | None


@dataclass(frozen=True, slots=True)
class DiagnosisDecision:
    ordered_top3: tuple[RootCauseCandidate, ...]
    evidence_status: str
    evidence_checks: tuple[StructuredEvidence, ...]
    z_gate_result: ZGateResult
    model_version: str
    preprocessing_version: str
    feature_definition_version: str
    evidence_rule_version: str
    input_asset_hashes: dict[str, str]
    parameter_candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class DiagnosticResultRecord:
    diagnostic_result_version: str
    diagnostic_result_id: str
    task_id: str
    detection_result_id: str
    input_data_version: str
    input_feature_hash: str
    anomaly_result: str
    ordered_top3: tuple[RootCauseCandidate, ...]
    evidence_status: str
    evidence_checks: tuple[StructuredEvidence, ...]
    z_gate_result: ZGateResult
    model_version: str
    preprocessing_version: str
    feature_definition_version: str
    evidence_rule_version: str
    input_asset_hashes: dict[str, str]
    result_hash: str
    created_at: str
    parameter_candidate_count: int = 0


def record_diagnosis(
    decision: DiagnosisDecision,
    *,
    task_id: str,
    detection_result_id: str,
    input_data_version: str,
    input_feature_hash: str,
    anomaly_result: str,
    created_at: str,
) -> DiagnosticResultRecord:
    business_payload = {
        "diagnostic_result_version": DIAGNOSTIC_RESULT_VERSION,
        "task_id": task_id,
        "detection_result_id": detection_result_id,
        "input_data_version": input_data_version,
        "input_feature_hash": input_feature_hash,
        "anomaly_result": anomaly_result,
        "ordered_top3": [asdict(candidate) for candidate in decision.ordered_top3],
        "evidence_status": decision.evidence_status,
        "evidence_checks": [asdict(check) for check in decision.evidence_checks],
        "z_gate_result": asdict(decision.z_gate_result),
        "model_version": decision.model_version,
        "preprocessing_version": decision.preprocessing_version,
        "feature_definition_version": decision.feature_definition_version,
        "evidence_rule_version": decision.evidence_rule_version,
        "input_asset_hashes": decision.input_asset_hashes,
        "parameter_candidate_count": 0,
    }
    canonical = json.dumps(
        business_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    result_hash = hashlib.sha256(canonical).hexdigest()
    return DiagnosticResultRecord(
        diagnostic_result_version=DIAGNOSTIC_RESULT_VERSION,
        diagnostic_result_id=f"tw-diagnostic-{result_hash[:16]}",
        task_id=task_id,
        detection_result_id=detection_result_id,
        input_data_version=input_data_version,
        input_feature_hash=input_feature_hash,
        anomaly_result=anomaly_result,
        ordered_top3=decision.ordered_top3,
        evidence_status=decision.evidence_status,
        evidence_checks=decision.evidence_checks,
        z_gate_result=decision.z_gate_result,
        model_version=decision.model_version,
        preprocessing_version=decision.preprocessing_version,
        feature_definition_version=decision.feature_definition_version,
        evidence_rule_version=decision.evidence_rule_version,
        input_asset_hashes=dict(decision.input_asset_hashes),
        result_hash=result_hash,
        created_at=created_at,
        parameter_candidate_count=0,
    )


def deserialize_diagnostic_result(payload: dict[str, Any]) -> DiagnosticResultRecord:
    def evidence(item: dict[str, Any]) -> StructuredEvidence:
        return StructuredEvidence(**item)

    def candidate(item: dict[str, Any]) -> RootCauseCandidate:
        return RootCauseCandidate(
            rank=item["rank"],
            root_cause=item["root_cause"],
            normalized_score=item["normalized_score"],
            raw_logit=item["raw_logit"],
            adjustability=item["adjustability"],
            matched_explicit_rules=tuple(evidence(value) for value in item["matched_explicit_rules"]),
            key_observations=tuple(KeyObservation(**value) for value in item["key_observations"]),
            positive_logit_contributions=tuple(
                LogitContribution(**value)
                for value in item["positive_logit_contributions"]
            ),
            conflict_evidence=tuple(evidence(value) for value in item["conflict_evidence"]),
            model_version=item["model_version"],
            preprocessing_version=item["preprocessing_version"],
            feature_definition_version=item["feature_definition_version"],
        )

    z_payload = payload["z_gate_result"]
    return DiagnosticResultRecord(
        diagnostic_result_version=payload["diagnostic_result_version"],
        diagnostic_result_id=payload["diagnostic_result_id"],
        task_id=payload["task_id"],
        detection_result_id=payload["detection_result_id"],
        input_data_version=payload["input_data_version"],
        input_feature_hash=payload["input_feature_hash"],
        anomaly_result=payload["anomaly_result"],
        ordered_top3=tuple(candidate(value) for value in payload["ordered_top3"]),
        evidence_status=payload["evidence_status"],
        evidence_checks=tuple(evidence(value) for value in payload["evidence_checks"]),
        z_gate_result=ZGateResult(
            status=z_payload["status"],
            passed=z_payload["passed"],
            checks=tuple(evidence(value) for value in z_payload["checks"]),
            removed_category=z_payload["removed_category"],
        ),
        model_version=payload["model_version"],
        preprocessing_version=payload["preprocessing_version"],
        feature_definition_version=payload["feature_definition_version"],
        evidence_rule_version=payload["evidence_rule_version"],
        input_asset_hashes=payload["input_asset_hashes"],
        result_hash=payload["result_hash"],
        created_at=payload["created_at"],
        parameter_candidate_count=payload.get("parameter_candidate_count", 0),
    )


class DiagnosticAssetLoader:
    REQUIRED_FILES = (
        "class-order.json",
        "evidence-rules.json",
        "feature-definition.json",
        "model.json",
        "preprocessing.json",
    )
    EVIDENCE_NUMERIC_RULES = (
        "top1_score_minimum",
        "top1_top2_margin_minimum",
        "plane_tilt_spatial_support_minimum",
        "xy_parameter_support_minimum",
        "platform_vibration_mean_minimum",
        "platform_repeat_error_mean_minimum",
        "reference_residual_mean_minimum",
        "z_center_near_limit_margin",
        "z_corner_mean_margin",
        "z_asymmetry_maximum",
        "z_corner_std_maximum",
    )

    def __init__(self, root: Path, expected_manifest_hash: str) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash

    def _read(self, relative_path: str) -> bytes:
        pure = PurePosixPath(relative_path)
        path = (self._root / Path(*pure.parts)).resolve()
        if pure.is_absolute() or ".." in pure.parts or not path.is_relative_to(self._root):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_ASSET_PATH_FORBIDDEN",
                "诊断运行时只能读取固定诊断资产目录。",
            )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            code = {
                "model.json": "DIAGNOSTIC_MODEL_MISSING",
                "preprocessing.json": "DIAGNOSTIC_PREPROCESSING_MISSING",
                "feature-definition.json": "DIAGNOSTIC_FEATURE_DEFINITION_MISSING",
                "evidence-rules.json": "DIAGNOSTIC_EVIDENCE_RULE_MISSING",
            }.get(relative_path, "DIAGNOSTIC_ASSET_MISSING")
            raise DiagnosticAssetError(code, f"缺失诊断资产：{relative_path}") from error

    @staticmethod
    def _json(content: bytes, name: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_ASSET_INVALID", f"诊断资产格式无效：{name}"
            ) from error
        if not isinstance(payload, dict):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_ASSET_INVALID", f"诊断资产格式无效：{name}"
            )
        return payload

    def load(self) -> DiagnosticAssets:
        manifest_bytes = self._read("manifest.json")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != self._expected_manifest_hash:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_MANIFEST_HASH_MISMATCH", "诊断资产清单已被篡改。"
            )
        manifest = self._json(manifest_bytes, "manifest.json")
        files = manifest.get("files")
        if manifest.get("manifest_version") != "1" or not isinstance(files, dict):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_ASSET_INVALID", "诊断资产清单格式无效。"
            )
        payloads: dict[str, dict[str, Any]] = {}
        actual_hashes: dict[str, str] = {"manifest.json": manifest_hash}
        for name in self.REQUIRED_FILES:
            content = self._read(name)
            actual_hash = hashlib.sha256(content).hexdigest()
            if files.get(name) != actual_hash:
                raise DiagnosticAssetError(
                    "DIAGNOSTIC_ASSET_HASH_MISMATCH", f"诊断资产内容哈希不匹配：{name}"
                )
            payloads[name] = self._json(content, name)
            actual_hashes[name] = actual_hash
        class_order = tuple(payloads["class-order.json"].get("class_order", ()))
        if (
            class_order != CLASS_ORDER
            or tuple(payloads["model.json"].get("class_order", ())) != CLASS_ORDER
            or tuple(manifest.get("class_order", ())) != CLASS_ORDER
            or payloads["class-order.json"].get("model_version") != MODEL_VERSION
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_MODEL_CLASS_ORDER_MISMATCH", "模型类别顺序与冻结类别顺序不一致。"
            )
        version_bindings = (
            ("feature_definition_version", FEATURE_DEFINITION_VERSION, payloads["feature-definition.json"]),
            ("preprocessing_version", PREPROCESSING_VERSION, payloads["preprocessing.json"]),
            ("model_version", MODEL_VERSION, payloads["model.json"]),
            ("evidence_rule_version", EVIDENCE_RULE_VERSION, payloads["evidence-rules.json"]),
        )
        if any(
            manifest.get(key) != expected or payload.get(key) != expected
            for key, expected, payload in version_bindings
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_ASSET_VERSION_MISMATCH",
                "诊断资产版本绑定与冻结版本不一致。",
            )
        definitions = payloads["feature-definition.json"].get("features")
        if not isinstance(definitions, list) or any(
            not isinstance(item, dict) for item in definitions
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_FEATURE_DEFINITION_INVALID",
                "特征定义资产格式无效。",
            )
        expected_features = tuple(item.get("feature_name") for item in definitions)
        if expected_features != FEATURE_NAMES:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_FEATURE_ORDER_MISMATCH", "特征定义顺序与冻结顺序不一致。"
            )
        if any(
            item.get("feature_index") != index
            or item.get("calculation_version") != CALCULATION_VERSION
            or item.get("missing_value_policy") != "REJECT_BATCH"
            or not isinstance(item.get("expected_unit"), str)
            or not item.get("expected_unit")
            or not isinstance(item.get("allowed_source_fields"), list)
            or not item.get("allowed_source_fields")
            or any(source not in OBSERVABLE_FIELDS for source in item["allowed_source_fields"])
            for index, item in enumerate(definitions)
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_FEATURE_DEFINITION_INVALID",
                "特征定义元数据与冻结计算边界不一致。",
            )
        if tuple(payloads["preprocessing.json"].get("feature_names", ())) != FEATURE_NAMES or tuple(payloads["model.json"].get("feature_names", ())) != FEATURE_NAMES:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_FEATURE_ORDER_MISMATCH", "预处理器或模型特征顺序不一致。"
            )
        preprocessing = payloads["preprocessing.json"]
        means = preprocessing.get("mean")
        scales = preprocessing.get("scale")
        if (
            preprocessing.get("artifact_type") != "StandardScaler"
            or not isinstance(means, list)
            or not isinstance(scales, list)
            or len(means) != len(FEATURE_NAMES)
            or len(scales) != len(FEATURE_NAMES)
            or not self._all_finite(means)
            or not self._all_finite(scales)
            or any(float(scale) <= 0 for scale in scales)
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_PREPROCESSING_INVALID",
                "StandardScaler 资产维度或数值无效。",
            )
        model = payloads["model.json"]
        normalized_model_fingerprint = hashlib.sha256(
            (
                json.dumps(
                    model,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        if manifest.get("model_fingerprint") != normalized_model_fingerprint:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_MODEL_FINGERPRINT_MISMATCH",
                "逻辑回归模型规范化指纹不匹配。",
            )
        coefficients = model.get("coefficient")
        intercept = model.get("intercept")
        if (
            model.get("artifact_type") != "multinomial_logistic_regression"
            or model.get("solver") != "deterministic_full_batch_gradient_descent"
            or model.get("random_seed") != manifest.get("random_seed")
            or not isinstance(coefficients, list)
            or len(coefficients) != len(CLASS_ORDER)
            or any(
                not isinstance(row, list) or len(row) != len(FEATURE_NAMES)
                for row in coefficients
            )
            or not isinstance(intercept, list)
            or len(intercept) != len(CLASS_ORDER)
            or not all(self._all_finite(row) for row in coefficients)
            or not self._all_finite(intercept)
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_MODEL_INVALID", "逻辑回归模型维度无效。"
            )
        evidence_rules = payloads["evidence-rules.json"]
        rule_values = [evidence_rules.get(name) for name in self.EVIDENCE_NUMERIC_RULES]
        if (
            evidence_rules.get("validation_partition")
            != manifest.get("validation_partition")
            or not self._all_finite(rule_values)
            or any(float(value) < 0 for value in rule_values)
        ):
            raise DiagnosticAssetError(
                "DIAGNOSTIC_EVIDENCE_RULE_INVALID",
                "证据规则阈值缺失或包含无效数值。",
            )
        return DiagnosticAssets(
            manifest=manifest,
            feature_definition=payloads["feature-definition.json"],
            preprocessing=payloads["preprocessing.json"],
            model=model,
            class_order=class_order,
            evidence_rules=payloads["evidence-rules.json"],
            input_asset_hashes=actual_hashes,
        )

    @staticmethod
    def _all_finite(values: object) -> bool:
        if not isinstance(values, (list, tuple)):
            return False
        try:
            return all(math.isfinite(float(value)) for value in values)
        except (TypeError, ValueError, OverflowError):
            return False


class FeatureEngineer:
    def derive(self, measurements: tuple[dict[str, str], ...]) -> DerivedFeatureSet:
        if not measurements:
            raise FeatureEngineeringError(
                "DIAGNOSTIC_FEATURE_MISSING",
                "当前 Batch 缺少 Measurement，无法生成诊断特征。",
            )
        parsed: list[tuple[int, dict[str, float]]] = []
        numeric_fields = (*PARAMETER_FIELDS, *PLATFORM_FIELDS, *MTF_FIELDS)
        for row_number, row in enumerate(measurements, start=1):
            missing = [field for field in OBSERVABLE_FIELDS if field not in row]
            if missing:
                raise FeatureEngineeringError(
                    "DIAGNOSTIC_FEATURE_MISSING",
                    f"第 {row_number} 条 Measurement 缺少字段：{', '.join(missing)}。",
                )
            try:
                sample_index = int(row["sample_index"])
                values = {field: float(Decimal(row[field])) for field in numeric_fields}
            except (InvalidOperation, TypeError, ValueError) as error:
                raise FeatureEngineeringError(
                    "DIAGNOSTIC_FEATURE_NON_FINITE",
                    f"第 {row_number} 条 Measurement 包含不可计算数值。",
                ) from error
            if not all(math.isfinite(value) for value in values.values()):
                raise FeatureEngineeringError(
                    "DIAGNOSTIC_FEATURE_NON_FINITE",
                    f"第 {row_number} 条 Measurement 包含非有限数值。",
                )
            parsed.append((sample_index, values))
        parsed.sort(key=lambda item: item[0])
        if len({sample_index for sample_index, _ in parsed}) != len(parsed):
            raise FeatureEngineeringError(
                "DIAGNOSTIC_FEATURE_INVALID",
                "sample_index 重复，无法生成稳定趋势特征。",
            )

        feature_values: dict[str, float] = {}
        for field in (*MTF_FIELDS, *PARAMETER_FIELDS, *PLATFORM_FIELDS):
            series = [row[field] for _, row in parsed]
            feature_values[f"{field}_mean"] = statistics.fmean(series)
            feature_values[f"{field}_std"] = statistics.pstdev(series)
            feature_values[f"{field}_trend"] = self._trend(
                [sample_index for sample_index, _ in parsed], series
            )
        corner_means = [
            feature_values[f"{field}_mean"]
            for field in ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
        ]
        lt, rt, lb, rb = corner_means
        corner_mean = statistics.fmean(corner_means)
        feature_values.update(
            {
                "corner_mtf_mean": corner_mean,
                "corner_mtf_min": min(corner_means),
                "corner_mtf_range": max(corner_means) - min(corner_means),
                "corner_mtf_std": statistics.pstdev(corner_means),
                "left_right_difference": ((lt + lb) - (rt + rb)) / 2,
                "top_bottom_difference": ((lt + rt) - (lb + rb)) / 2,
                "diagonal_difference": ((lt + rb) - (rt + lb)) / 2,
                "center_corner_gap": feature_values["mtf_center_mean"] - corner_mean,
            }
        )
        ordered = tuple(feature_values[name] for name in FEATURE_NAMES)
        canonical = json.dumps(
            {
                "feature_definition_version": FEATURE_DEFINITION_VERSION,
                "feature_names": FEATURE_NAMES,
                "values": [f"{value:.12f}" for value in ordered],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return DerivedFeatureSet(
            feature_definition_version=FEATURE_DEFINITION_VERSION,
            feature_names=FEATURE_NAMES,
            values=ordered,
            input_feature_hash=hashlib.sha256(canonical).hexdigest(),
        )

    @staticmethod
    def _trend(indexes: list[int], values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        index_mean = statistics.fmean(indexes)
        value_mean = statistics.fmean(values)
        denominator = sum((index - index_mean) ** 2 for index in indexes)
        if denominator == 0:
            return 0.0
        return sum(
            (index - index_mean) * (value - value_mean)
            for index, value in zip(indexes, values)
        ) / denominator


class RootCauseDiagnoser:
    OBSERVATION_FEATURES = {
        "PLANE_TILT": (
            "top_bottom_difference",
            "left_right_difference",
            "diagonal_difference",
            "pitch_mean",
            "roll_mean",
        ),
        "XY_DECENTER": (
            "x_offset_mean",
            "y_offset_mean",
            "left_right_difference",
            "top_bottom_difference",
        ),
        "PLATFORM_INSTABILITY": (
            "vibration_rms_mean",
            "vibration_rms_std",
            "repeat_position_error_mean",
            "repeat_position_error_std",
        ),
        "REFERENCE_DRIFT": (
            "calibration_residual_x_mean",
            "calibration_residual_y_mean",
            "calibration_residual_x_trend",
            "calibration_residual_y_trend",
        ),
        "Z_DEFOCUS_CONDITIONAL": (
            "mtf_center_mean",
            "corner_mtf_mean",
            "corner_mtf_range",
            "corner_mtf_std",
        ),
    }
    ADJUSTABILITY = {
        "PLANE_TILT": "ADJUSTABLE",
        "XY_DECENTER": "ADJUSTABLE",
        "PLATFORM_INSTABILITY": "INSPECTION_ONLY",
        "REFERENCE_DRIFT": "INSPECTION_ONLY",
        "Z_DEFOCUS_CONDITIONAL": "ADJUSTABLE",
    }

    def __init__(self, assets: DiagnosticAssets) -> None:
        self._assets = assets

    def diagnose(
        self,
        features: DerivedFeatureSet,
        control_limits: ControlLimitSnapshot,
    ) -> DiagnosisDecision:
        if features.feature_names != FEATURE_NAMES:
            raise DiagnosticAssetError(
                "DIAGNOSTIC_FEATURE_ORDER_MISMATCH",
                "当前 DerivedFeatureSet 特征顺序与模型不一致。",
            )
        return self.diagnose_values(list(features.values), control_limits)

    def diagnose_values(
        self,
        values: list[float],
        control_limits: ControlLimitSnapshot,
    ) -> DiagnosisDecision:
        if len(values) != len(FEATURE_NAMES) or not all(math.isfinite(value) for value in values):
            raise FeatureEngineeringError(
                "DIAGNOSTIC_FEATURE_NON_FINITE", "诊断特征数量错误或包含非有限数值。"
            )
        preprocessing = self._assets.preprocessing
        means = preprocessing["mean"]
        scales = preprocessing["scale"]
        standardized = [
            (value - float(means[index])) / float(scales[index])
            for index, value in enumerate(values)
        ]
        model = self._assets.model
        logits = [
            float(bias)
            + sum(float(weight) * value for weight, value in zip(weights, standardized))
            for weights, bias in zip(model["coefficient"], model["intercept"])
        ]
        probabilities = self._softmax(logits)
        raw = dict(zip(FEATURE_NAMES, values))
        z_gate = self._z_gate(raw, control_limits)
        visible_indexes = list(range(len(CLASS_ORDER)))
        if not z_gate.passed:
            visible_indexes.remove(CLASS_ORDER.index("Z_DEFOCUS_CONDITIONAL"))
        visible_total = sum(probabilities[index] for index in visible_indexes)
        normalized = {
            index: probabilities[index] / visible_total for index in visible_indexes
        }
        ranked = sorted(
            visible_indexes,
            key=lambda index: (-round(normalized[index], 6), index),
        )[:3]
        candidates = tuple(
            self._candidate(
                rank,
                class_index,
                normalized[class_index],
                logits[class_index],
                raw,
                standardized,
                z_gate,
            )
            for rank, class_index in enumerate(ranked, start=1)
        )
        evidence_status, evidence_checks = self._evidence(candidates, z_gate)
        return DiagnosisDecision(
            ordered_top3=candidates,
            evidence_status=evidence_status,
            evidence_checks=evidence_checks,
            z_gate_result=z_gate,
            model_version=model["model_version"],
            preprocessing_version=preprocessing["preprocessing_version"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
            evidence_rule_version=self._assets.evidence_rules["evidence_rule_version"],
            input_asset_hashes=self._assets.input_asset_hashes,
        )

    def _candidate(
        self,
        rank: int,
        class_index: int,
        score: float,
        logit: float,
        raw: dict[str, float],
        standardized: list[float],
        z_gate: ZGateResult,
    ) -> RootCauseCandidate:
        root_cause = CLASS_ORDER[class_index]
        coefficient = self._assets.model["coefficient"][class_index]
        positive: list[LogitContribution] = []
        for index, (standard_value, weight) in enumerate(zip(standardized, coefficient)):
            contribution = standard_value * float(weight)
            if contribution > 0:
                positive.append(
                    LogitContribution(
                        feature_name=FEATURE_NAMES[index],
                        feature_index=index,
                        standardized_feature_value=f"{standard_value:.12f}",
                        class_coefficient=f"{float(weight):.12f}",
                        contribution=f"{contribution:.6f}",
                    )
                )
        positive.sort(
            key=lambda item: (-round(float(item.contribution), 6), item.feature_index)
        )
        if len(positive) < 3:
            raise DiagnosticGuardError(
                "DIAGNOSTIC_EXPLANATION_INSUFFICIENT",
                f"{root_cause} 缺少至少三项正向 logit 贡献，诊断结果未创建。",
            )
        matched, conflicts = self._rules_for(root_cause, raw, z_gate)
        observations = tuple(
            KeyObservation(
                feature_name=name,
                value=f"{raw[name]:.6f}",
                summary=f"观测特征 {name} = {raw[name]:.6f}",
            )
            for name in self.OBSERVATION_FEATURES[root_cause]
        )
        return RootCauseCandidate(
            rank=rank,
            root_cause=root_cause,
            normalized_score=f"{score:.6f}",
            raw_logit=f"{logit:.6f}",
            adjustability=self.ADJUSTABILITY[root_cause],
            matched_explicit_rules=matched,
            key_observations=observations,
            positive_logit_contributions=tuple(positive[:5]),
            conflict_evidence=conflicts,
            model_version=self._assets.model["model_version"],
            preprocessing_version=self._assets.preprocessing["preprocessing_version"],
            feature_definition_version=FEATURE_DEFINITION_VERSION,
        )

    def _rules_for(
        self,
        root_cause: str,
        raw: dict[str, float],
        z_gate: ZGateResult,
    ) -> tuple[tuple[StructuredEvidence, ...], tuple[StructuredEvidence, ...]]:
        rules = self._assets.evidence_rules
        spatial = max(
            abs(raw["left_right_difference"]),
            abs(raw["top_bottom_difference"]),
            abs(raw["diagonal_difference"]),
        )
        tests = {
            "PLANE_TILT": (
                spatial >= float(rules["plane_tilt_spatial_support_minimum"]),
                "PLANE_TILT_SPATIAL_PATTERN",
                "稳定空间不对称达到倾斜支持阈值。",
            ),
            "XY_DECENTER": (
                max(abs(raw["x_offset_mean"]), abs(raw["y_offset_mean"]))
                >= float(rules["xy_parameter_support_minimum"]),
                "XY_DECENTER_PARAMETER_STATE",
                "X/Y 当前参数状态达到偏心支持阈值。",
            ),
            "PLATFORM_INSTABILITY": (
                raw["vibration_rms_mean"] >= float(rules["platform_vibration_mean_minimum"])
                or raw["repeat_position_error_mean"] >= float(rules["platform_repeat_error_mean_minimum"]),
                "PLATFORM_VARIATION_HIGH",
                "振动或重复定位误差达到平台排查阈值。",
            ),
            "REFERENCE_DRIFT": (
                max(
                    abs(raw["calibration_residual_x_mean"]),
                    abs(raw["calibration_residual_y_mean"]),
                )
                >= float(rules["reference_residual_mean_minimum"]),
                "REFERENCE_RESIDUAL_PERSISTENT",
                "标定残差达到基准漂移排查阈值。",
            ),
            "Z_DEFOCUS_CONDITIONAL": (
                z_gate.passed,
                "Z_DEFOCUS_GATE_PASSED",
                "Z 条件性门控的三项检查均通过。",
            ),
        }
        passed, rule_id, detail = tests[root_cause]
        evidence = StructuredEvidence(
            rule_id=rule_id,
            status="PASSED" if passed else "FAILED",
            detail=detail if passed else f"未命中：{detail}",
        )
        return ((evidence,), ()) if passed else ((), (evidence,))

    def _z_gate(
        self,
        raw: dict[str, float],
        controls: ControlLimitSnapshot,
    ) -> ZGateResult:
        rules = self._assets.evidence_rules
        checks = (
            StructuredEvidence(
                "Z_CENTER_NEAR_LOWER_LIMIT",
                "PASSED"
                if raw["mtf_center_mean"]
                <= float(controls.center_lower_limit)
                + float(rules["z_center_near_limit_margin"])
                else "FAILED",
                "中心 MTF 接近或低于中心下限。",
            ),
            StructuredEvidence(
                "Z_CORNERS_GLOBAL_LOW",
                "PASSED"
                if max(
                    raw["mtf_lt_mean"],
                    raw["mtf_rt_mean"],
                    raw["mtf_lb_mean"],
                    raw["mtf_rb_mean"],
                )
                <= float(controls.corner_lower_limit)
                + float(rules["z_corner_mean_margin"])
                else "FAILED",
                "四角整体同向下降。",
            ),
            StructuredEvidence(
                "Z_ASYMMETRY_NOT_DOMINANT",
                "PASSED"
                if raw["corner_mtf_range"] <= float(rules["z_asymmetry_maximum"])
                and raw["corner_mtf_std"] <= float(rules["z_corner_std_maximum"])
                else "FAILED",
                "四角不对称不是主导特征。",
            ),
        )
        passed = all(check.status == "PASSED" for check in checks)
        return ZGateResult(
            status="PASSED" if passed else "REMOVED",
            passed=passed,
            checks=checks,
            removed_category=None if passed else "Z_DEFOCUS_CONDITIONAL",
        )

    def _evidence(
        self,
        candidates: tuple[RootCauseCandidate, ...],
        z_gate: ZGateResult,
    ) -> tuple[str, tuple[StructuredEvidence, ...]]:
        rules = self._assets.evidence_rules
        top1 = float(candidates[0].normalized_score)
        margin = top1 - float(candidates[1].normalized_score)
        checks = (
            StructuredEvidence(
                "TOP1_SCORE_MINIMUM",
                "PASSED" if top1 >= float(rules["top1_score_minimum"]) else "FAILED",
                f"Top-1 相对分数 {top1:.6f}。",
            ),
            StructuredEvidence(
                "TOP1_TOP2_MARGIN_MINIMUM",
                "PASSED" if margin >= float(rules["top1_top2_margin_minimum"]) else "FAILED",
                f"Top-1 与 Top-2 分差 {margin:.6f}。",
            ),
            StructuredEvidence(
                "TOP1_COMPATIBLE_RULE",
                "PASSED" if candidates[0].matched_explicit_rules else "FAILED",
                "Top-1 具有兼容显式规则证据。",
            ),
            StructuredEvidence(
                "MODEL_RULE_CONFLICT",
                "PASSED" if not candidates[0].conflict_evidence else "FAILED",
                "Top-1 模型输出与硬规则无冲突。",
            ),
            StructuredEvidence(
                "ASSET_AND_FEATURE_INTEGRITY",
                "PASSED",
                "模型、预处理器、特征和规则资产完整有效。",
            ),
            StructuredEvidence(
                "Z_GATE_CONSISTENCY",
                "PASSED"
                if candidates[0].root_cause != "Z_DEFOCUS_CONDITIONAL" or z_gate.passed
                else "FAILED",
                (
                    "Z 条件性类别已通过硬门控。"
                    if z_gate.passed
                    else "Z 条件性类别已从展示候选移除并重新归一化。"
                ),
            ),
        )
        status = (
            "SUFFICIENT_EVIDENCE"
            if all(check.status == "PASSED" for check in checks)
            else "INSUFFICIENT_EVIDENCE"
        )
        return status, checks

    @staticmethod
    def _softmax(logits: list[float]) -> list[float]:
        maximum = max(logits)
        exponents = [math.exp(value - maximum) for value in logits]
        total = sum(exponents)
        return [value / total for value in exponents]
