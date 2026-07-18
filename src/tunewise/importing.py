from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import (
    DataImportSummary,
    ImportHashSummary,
    ImportSnapshotVersions,
    ImportValidationSummary,
    MtfSummary,
    ParameterSummary,
    PlatformSummary,
    VersionSnapshot,
)


OBSERVABLE_FIELDS: tuple[str, ...] = (
    "sample_index",
    "timestamp",
    "x_offset",
    "y_offset",
    "pitch",
    "roll",
    "z_offset",
    "vibration_rms",
    "repeat_position_error",
    "calibration_residual_x",
    "calibration_residual_y",
    "mtf_center",
    "mtf_lt",
    "mtf_rt",
    "mtf_lb",
    "mtf_rb",
)

CANONICAL_PRECISION = Decimal("0.000001")
SAMPLE_INDEX_PATTERN = re.compile(r"0|[1-9][0-9]*")


class ObservationValidationError(ValueError):
    pass


class ImportValidationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CanonicalObservations:
    content: bytes
    sha256: str


class ObservableCanonicalizer:
    version = "tw-canonicalizer-v1"

    def canonicalize_csv(self, csv_bytes: bytes) -> CanonicalObservations:
        try:
            csv_text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ObservationValidationError("CSV 必须使用 UTF-8 编码。") from error
        reader = csv.reader(io.StringIO(csv_text, newline=""))
        try:
            header = next(reader)
        except StopIteration as error:
            raise ObservationValidationError("CSV 内容为空。") from error
        if tuple(header) != OBSERVABLE_FIELDS:
            raise ObservationValidationError("CSV 字段必须与冻结可观测字段完全一致。")

        records: list[tuple[int, list[str]]] = []
        seen_indexes: set[int] = set()
        for line_number, row in enumerate(reader, start=2):
            if len(row) != len(OBSERVABLE_FIELDS):
                raise ObservationValidationError(f"CSV 第 {line_number} 行字段数量无效。")
            canonical_row = self._canonicalize_row(row, line_number)
            sample_index = int(canonical_row[0])
            if sample_index in seen_indexes:
                raise ObservationValidationError("sample_index 不得重复。")
            seen_indexes.add(sample_index)
            records.append((sample_index, canonical_row))
        if not records:
            raise ObservationValidationError("CSV 至少需要一条观测记录。")

        payload = {
            "canonicalizer_version": self.version,
            "fields": list(OBSERVABLE_FIELDS),
            "records": [record for _, record in sorted(records, key=lambda item: item[0])],
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return CanonicalObservations(
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def _canonicalize_row(self, row: list[str], line_number: int) -> list[str]:
        values = dict(zip(OBSERVABLE_FIELDS, row, strict=True))
        sample_index = values["sample_index"]
        if not SAMPLE_INDEX_PATTERN.fullmatch(sample_index):
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 sample_index 无效。"
            )
        timestamp = self._canonical_timestamp(values["timestamp"], line_number)
        result = [str(int(sample_index)), timestamp]
        for field in OBSERVABLE_FIELDS[2:]:
            result.append(self._canonical_decimal(values[field], field, line_number))
        return result

    @staticmethod
    def _canonical_timestamp(value: str, line_number: int) -> str:
        if not value:
            raise ObservationValidationError(f"CSV 第 {line_number} 行 timestamp 为空。")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 timestamp 无效。"
            ) from error
        if parsed.tzinfo is None:
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 timestamp 必须包含时区。"
            )
        return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _canonical_decimal(
        value: str,
        field: str,
        line_number: int,
    ) -> str:
        if not value:
            raise ObservationValidationError(f"CSV 第 {line_number} 行 {field} 为空。")
        try:
            parsed = Decimal(value)
        except InvalidOperation as error:
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 {field} 不是合法数值。"
            ) from error
        if not parsed.is_finite():
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 {field} 不是有限数值。"
            )
        try:
            quantized = parsed.quantize(
                CANONICAL_PRECISION,
                rounding=ROUND_HALF_EVEN,
            )
        except InvalidOperation as error:
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 {field} 数值精度无效。"
            ) from error
        if parsed != quantized:
            raise ObservationValidationError(
                f"CSV 第 {line_number} 行 {field} 数值精度超过 6 位。"
            )
        return format(quantized, "f")


@dataclass(frozen=True, slots=True)
class ImportedDataset:
    summary: DataImportSummary
    manifest: dict[str, Any]
    batch: dict[str, Any]
    measurements: tuple[dict[str, str], ...]
    control_limits: dict[str, Any]
    parameter_constraints: dict[str, Any]
    replay_evaluation_rules: dict[str, Any]


class DemoDatasetImporter:
    def __init__(
        self,
        root: Path,
        expected_manifest_hash: str,
        versions: VersionSnapshot,
    ) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash
        self._versions = versions

    def load(self, preset_asset_id: str) -> ImportedDataset:
        if preset_asset_id != "tw-aa-demo-v1":
            raise ImportValidationError("PRESET_ASSET_NOT_FOUND", "预置 AA 批次不存在。", 404)
        manifest_bytes = self._read_bytes("dataset-manifest.json")
        if hashlib.sha256(manifest_bytes).hexdigest() != self._expected_manifest_hash:
            raise ImportValidationError(
                "DATASET_MANIFEST_HASH_MISMATCH",
                "DatasetManifest 内容哈希不匹配。",
                409,
            )
        manifest = self._parse_manifest(manifest_bytes)
        self._validate_manifest(manifest, preset_asset_id)
        rules_bytes = self._read_bytes(manifest["rules_file"])
        if hashlib.sha256(rules_bytes).hexdigest() != manifest["rules_file_hash"]:
            raise ImportValidationError(
                "RULE_ASSET_HASH_MISMATCH",
                "导入规则资产哈希与 DatasetManifest 不匹配。",
                409,
            )
        rules = self._parse_rules(rules_bytes, manifest["product_model"])
        csv_bytes = self._read_bytes(manifest["csv_file"])
        raw_hash = hashlib.sha256(csv_bytes).hexdigest()
        if raw_hash != manifest["raw_file_hash"]:
            raise ImportValidationError(
                "RAW_FILE_HASH_MISMATCH",
                "CSV 原始文件哈希与 DatasetManifest 不匹配。",
                409,
            )
        try:
            canonical = ObservableCanonicalizer().canonicalize_csv(csv_bytes)
        except ObservationValidationError as error:
            raise ImportValidationError("CSV_VALIDATION_FAILED", str(error)) from error
        if canonical.sha256 != manifest["canonical_observation_hash"]:
            raise ImportValidationError(
                "CANONICAL_OBSERVATION_HASH_MISMATCH",
                "规范化观测哈希与 DatasetManifest 不匹配。",
                409,
            )
        measurements = self._measurements(canonical.content)
        self._validate_measurements(measurements)
        summary = self._summary(manifest, measurements, rules)
        persisted_manifest = {
            key: value
            for key, value in manifest.items()
            if key != "scenario_ref"
        }
        persisted_manifest["dataset_manifest_hash"] = self._expected_manifest_hash
        return ImportedDataset(
            summary=summary,
            manifest=persisted_manifest,
            batch={
                "station_id": manifest["station_id"],
                "batch_id": manifest["batch_id"],
                "product_model": manifest["product_model"],
                "initial_parameters": asdict(summary.parameter_summary),
                "derived_observation_metrics": self._derived_observation_metrics(
                    measurements,
                    rules["control_limits"],
                ),
            },
            measurements=measurements,
            control_limits=rules["control_limits"],
            parameter_constraints=rules["parameter_constraints"],
            replay_evaluation_rules=rules["replay_evaluation_rules"],
        )

    def _read_bytes(self, relative_path: str) -> bytes:
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ImportValidationError("DATASET_ASSET_PATH_FORBIDDEN", "演示资产路径无效。")
        path = (self._root / Path(*pure_path.parts)).resolve()
        if not path.is_relative_to(self._root):
            raise ImportValidationError("DATASET_ASSET_PATH_FORBIDDEN", "演示资产路径无效。")
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise ImportValidationError("DATASET_ASSET_MISSING", "预置演示资产缺失。", 409) from error

    @staticmethod
    def _parse_manifest(content: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 格式无效。") from error
        if not isinstance(payload, dict):
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 格式无效。")
        return payload

    def _validate_manifest(self, manifest: dict[str, Any], preset_asset_id: str) -> None:
        required = {
            "manifest_version",
            "asset_id",
            "station_id",
            "batch_id",
            "product_model",
            "csv_file",
            "rules_file",
            "random_seed",
            "versions",
            "raw_file_hash",
            "rules_file_hash",
            "canonical_observation_hash",
            "scenario_ref",
            "scenario_ref_hash",
        }
        if set(manifest) != required:
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 字段无效。")
        string_fields = required - {"random_seed", "versions"}
        if not all(
            isinstance(manifest[field], str) and manifest[field]
            for field in string_fields
        ):
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 字段类型无效。")
        if not isinstance(manifest["random_seed"], int) or isinstance(
            manifest["random_seed"], bool
        ):
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 固定种子无效。")
        if not isinstance(manifest["versions"], dict):
            raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 版本字段无效。")
        for field in (
            "raw_file_hash",
            "rules_file_hash",
            "canonical_observation_hash",
            "scenario_ref_hash",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", manifest[field]):
                raise ImportValidationError("DATASET_MANIFEST_INVALID", "DatasetManifest 哈希字段无效。")
        if manifest["manifest_version"] != "1" or manifest["asset_id"] != preset_asset_id:
            raise ImportValidationError("DATASET_MANIFEST_MISMATCH", "DatasetManifest 与预置资产不匹配。", 409)
        if manifest["station_id"] != "AA":
            raise ImportValidationError("STATION_NOT_ALLOWED", "仅允许导入 AA 工站数据。")
        expected_versions = {
            "canonicalizer_version": self._versions.canonicalizer_version,
            "dataset_version": self._versions.dataset_version,
            "evaluation_rule_version": self._versions.evaluation_rule_version,
            "generator_version": self._versions.generator_version,
            "model_version": self._versions.model_version,
            "preprocessing_version": self._versions.preprocessing_version,
            "rule_set_version": self._versions.rule_set_version,
            "schema_version": self._versions.schema_version,
        }
        if manifest["versions"] != expected_versions:
            raise ImportValidationError("DATASET_VERSION_MISMATCH", "DatasetManifest 版本与任务快照不匹配。", 409)
        if manifest["random_seed"] != 20260718:
            raise ImportValidationError("DATASET_VERSION_MISMATCH", "DatasetManifest 固定种子不匹配。", 409)
        scenario_ref = manifest["scenario_ref"]
        if not isinstance(scenario_ref, str) or not re.fullmatch(r"scn_[0-9a-f]{32}", scenario_ref):
            raise ImportValidationError("SCENARIO_REFERENCE_INVALID", "场景引用格式无效。", 409)
        if hashlib.sha256(scenario_ref.encode("utf-8")).hexdigest() != manifest["scenario_ref_hash"]:
            raise ImportValidationError("SCENARIO_REFERENCE_HASH_MISMATCH", "场景引用哈希不匹配。", 409)

    def _parse_rules(self, content: bytes, product_model: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ImportValidationError("RULE_ASSET_INVALID", "导入规则资产格式无效。") from error
        if not isinstance(payload, dict) or set(payload) != {
            "control_limits",
            "parameter_constraints",
            "replay_evaluation_rules",
        }:
            raise ImportValidationError("RULE_ASSET_INVALID", "导入规则资产格式无效。")
        expected = self._expected_rules(product_model)
        if payload != expected:
            raise ImportValidationError("RULE_ASSET_VERSION_MISMATCH", "导入规则资产与冻结版本不匹配。", 409)
        return payload

    @staticmethod
    def _measurements(canonical_content: bytes) -> tuple[dict[str, str], ...]:
        payload = json.loads(canonical_content)
        return tuple(
            dict(zip(OBSERVABLE_FIELDS, record, strict=True))
            for record in payload["records"]
        )

    @staticmethod
    def _validate_measurements(measurements: tuple[dict[str, str], ...]) -> None:
        mtf_fields = ("mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
        parameter_fields = ("x_offset", "y_offset", "pitch", "roll", "z_offset")
        for measurement in measurements:
            for field in mtf_fields:
                value = Decimal(measurement[field])
                if value < 0 or value > 1:
                    raise ImportValidationError("MTF_OUT_OF_RANGE", f"{field} 必须位于 0 到 1。")
            for field in parameter_fields:
                value = Decimal(measurement[field])
                if value < -1 or value > 1 or value % Decimal("0.05") != 0:
                    raise ImportValidationError("PARAMETER_VALUE_INVALID", f"{field} 超出范围或不在 0.05 网格。")
            for field in ("vibration_rms", "repeat_position_error"):
                if Decimal(measurement[field]) < 0:
                    raise ImportValidationError("PLATFORM_VALUE_INVALID", f"{field} 不得小于 0。")

    @staticmethod
    def _mean(measurements: tuple[dict[str, str], ...], field: str) -> Decimal:
        return sum((Decimal(item[field]) for item in measurements), Decimal(0)) / len(measurements)

    @staticmethod
    def _format(value: Decimal) -> str:
        return format(value.quantize(CANONICAL_PRECISION, rounding=ROUND_HALF_EVEN), "f")

    def _summary(
        self,
        manifest: dict[str, Any],
        measurements: tuple[dict[str, str], ...],
        rules: dict[str, Any],
    ) -> DataImportSummary:
        means = {
            field: self._mean(measurements, field)
            for field in (
                "mtf_center",
                "mtf_lt",
                "mtf_rt",
                "mtf_lb",
                "mtf_rb",
                "vibration_rms",
                "repeat_position_error",
                "calibration_residual_x",
                "calibration_residual_y",
            )
        }
        corners = [means[field] for field in ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")]
        current = measurements[-1]
        return DataImportSummary(
            preset_asset_id=manifest["asset_id"],
            batch_id=manifest["batch_id"],
            station_id=manifest["station_id"],
            product_model=manifest["product_model"],
            sample_count=len(measurements),
            validation_summary=ImportValidationSummary(
                canonical_observation_hash="PASSED",
                csv_schema="PASSED",
                manifest="PASSED",
                raw_file_hash="PASSED",
                versions="PASSED",
            ),
            hashes=ImportHashSummary(
                raw_file_hash=manifest["raw_file_hash"],
                canonical_observation_hash=manifest["canonical_observation_hash"],
                scenario_ref_hash=manifest["scenario_ref_hash"],
            ),
            mtf_summary=MtfSummary(
                mtf_center=self._format(means["mtf_center"]),
                mtf_lt=self._format(means["mtf_lt"]),
                mtf_rt=self._format(means["mtf_rt"]),
                mtf_lb=self._format(means["mtf_lb"]),
                mtf_rb=self._format(means["mtf_rb"]),
                corner_mtf_min=self._format(min(corners)),
                corner_mtf_range=self._format(max(corners) - min(corners)),
                corner_mtf_std=self._format(statistics.pstdev(corners)),
            ),
            parameter_summary=ParameterSummary(
                **{field: current[field] for field in ("x_offset", "y_offset", "pitch", "roll", "z_offset")}
            ),
            platform_summary=PlatformSummary(
                **{
                    field: self._format(means[field])
                    for field in (
                        "vibration_rms",
                        "repeat_position_error",
                        "calibration_residual_x",
                        "calibration_residual_y",
                    )
                }
            ),
            snapshot_versions=ImportSnapshotVersions(
                control_limit_snapshot=rules["control_limits"]["snapshot_version"],
                parameter_constraint_snapshot=rules["parameter_constraints"]["snapshot_version"],
                replay_evaluation_rule_snapshot=rules["replay_evaluation_rules"]["snapshot_version"],
            ),
        )

    def _derived_observation_metrics(
        self,
        measurements: tuple[dict[str, str], ...],
        control_limits: dict[str, Any],
    ) -> dict[str, Any]:
        center_limit = Decimal(control_limits["center_lower_limit"])
        corner_limit = Decimal(control_limits["corner_lower_limit"])
        range_limit = Decimal(control_limits["asymmetry_limit"])
        std_limit = Decimal(control_limits["corner_std_limit"])
        history: dict[str, list[Decimal]] = {
            "mtf_center": [],
            "corner_mtf_min": [],
            "corner_mtf_range": [],
            "corner_mtf_std": [],
        }
        series: list[dict[str, Any]] = []
        for measurement in measurements:
            corners = [
                Decimal(measurement[field])
                for field in ("mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb")
            ]
            values = {
                "mtf_center": Decimal(measurement["mtf_center"]),
                "corner_mtf_min": min(corners),
                "corner_mtf_range": max(corners) - min(corners),
                "corner_mtf_std": statistics.pstdev(corners),
            }
            for field, value in values.items():
                history[field].append(value)
            within_limits = (
                values["mtf_center"] >= center_limit
                and values["corner_mtf_min"] >= corner_limit
                and values["corner_mtf_range"] <= range_limit
                and values["corner_mtf_std"] <= std_limit
            )
            series.append(
                {
                    "sample_index": measurement["sample_index"],
                    "values": {
                        field: self._format(value)
                        for field, value in values.items()
                    },
                    "control_limit_deviations": {
                        "mtf_center": self._format(values["mtf_center"] - center_limit),
                        "corner_mtf_min": self._format(
                            values["corner_mtf_min"] - corner_limit
                        ),
                        "corner_mtf_range": self._format(
                            values["corner_mtf_range"] - range_limit
                        ),
                        "corner_mtf_std": self._format(
                            values["corner_mtf_std"] - std_limit
                        ),
                    },
                    "rolling": {
                        field: {
                            "mean": self._format(
                                sum(field_history, Decimal(0))
                                / len(field_history)
                            ),
                            "std": self._format(statistics.pstdev(field_history)),
                        }
                        for field, field_history in history.items()
                    },
                    "control_limit_status": (
                        "WITHIN_LIMITS" if within_limits else "OUTSIDE_LIMITS"
                    ),
                }
            )
        return {
            "rolling_method": "EXPANDING",
            "series": series,
            "final_control_limit_status": series[-1]["control_limit_status"],
        }

    def _expected_rules(self, product_model: str) -> dict[str, Any]:
        constraints = {}
        for field in ("x_offset", "y_offset", "pitch", "roll", "z_offset"):
            constraints[field] = {
                "nominal_value": "0.000000",
                "minimum": "-1.000000",
                "maximum": "1.000000",
                "step": "0.050000",
                "maximum_single_plan_delta": "0.100000" if field == "z_offset" else "0.200000",
            }
        return {
            "control_limits": {
                "snapshot_version": "tw-control-limits-v1",
                "rule_set_version": self._versions.rule_set_version,
                "center_lower_limit": "0.720000",
                "corner_lower_limit": "0.620000",
                "asymmetry_limit": "0.120000",
                "corner_std_limit": "0.050000",
            },
            "parameter_constraints": {
                "snapshot_version": "tw-parameter-constraints-v1",
                "product_model": product_model,
                "rule_set_version": self._versions.rule_set_version,
                "constraints": constraints,
            },
            "replay_evaluation_rules": {
                "snapshot_version": self._versions.evaluation_rule_version,
                "evaluation_rule_version": self._versions.evaluation_rule_version,
                "center_regression_tolerance": "0.010000",
                "minimum_corner_min_improvement": "0.020000",
                "minimum_range_reduction": "0.020000",
                "minimum_std_reduction": "0.010000",
                "center_lower_limit": "0.720000",
                "corner_lower_limit": "0.620000",
                "asymmetry_limit": "0.120000",
            },
        }
