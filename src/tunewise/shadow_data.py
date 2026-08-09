from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .diagnostic_contract import CLASS_ORDER
from .detection import DetectionGuardError, canonical_measurement_hash
from .importing import (
    CANONICAL_PRECISION,
    OBSERVABLE_FIELDS,
    ObservableCanonicalizer,
    ObservationValidationError,
)
from .parameter_planning import TICK_SIZE


SHADOW_MAPPING_MANIFEST_VERSION = "tw-shadow-mapping-manifest-v1"
SHADOW_CANONICAL_SCHEMA_VERSION = "tw-schema-v1"
SHADOW_QUALITY_POLICY_VERSION = "tw-shadow-quality-v1"
SHADOW_STORAGE_PARTITION = "SHADOW_READ_ONLY"
SHADOW_EVIDENCE_BUNDLE_VERSION = "tw-shadow-evidence-bundle-v1"
SHADOW_EVIDENCE_CANONICALIZER_VERSION = "tw-shadow-evidence-canonical-json-v1"
SHADOW_REVIEW_CONTRACT_VERSION = "tw-shadow-review-contract-v1"
MINIMUM_SPC_SAMPLE_COUNT = 8
HASH_PATTERN = re.compile(r"[0-9a-f]{64}")

PARAMETER_FIELDS = frozenset(
    {"x_offset", "y_offset", "pitch", "roll", "z_offset"}
)
MTF_FIELDS = frozenset({"mtf_center", "mtf_lt", "mtf_rt", "mtf_lb", "mtf_rb"})
NON_NEGATIVE_FIELDS = frozenset({"vibration_rms", "repeat_position_error"})
REVIEWED_OUTCOME_FIELDS = frozenset(
    {
        "reviewed_status",
        "reviewed_anomaly",
        "reviewed_root_cause",
        "reviewed_parameter_direction",
    }
)


class ShadowSourceType(StrEnum):
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"
    CONTRACT_FIXTURE = "CONTRACT_FIXTURE"
    REAL_DEVICE_SHADOW_DECLARED = "REAL_DEVICE_SHADOW_DECLARED"


class ShadowDataStatus(StrEnum):
    READY = "READY"
    MAPPING_INVALID = "MAPPING_INVALID"
    UNIT_UNKNOWN = "UNIT_UNKNOWN"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FEATURE_UNAVAILABLE = "FEATURE_UNAVAILABLE"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class FieldClassification(StrEnum):
    IDENTIFIER = "IDENTIFIER"
    TIMESTAMP = "TIMESTAMP"
    PARAMETER = "PARAMETER"
    OBSERVATION = "OBSERVATION"


class ConversionKind(StrEnum):
    INTEGER_IDENTITY = "INTEGER_IDENTITY"
    TIMESTAMP_ISO8601 = "TIMESTAMP_ISO8601"
    DECIMAL_AFFINE = "DECIMAL_AFFINE"


class ShadowEvaluationStatus(StrEnum):
    EVALUATED_DECLARED_REVIEW = "EVALUATED_DECLARED_REVIEW"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class ShadowDataImportError(RuntimeError):
    def __init__(
        self,
        code: ShadowDataStatus | str,
        message: str,
        *,
        quality_report: ShadowDataQualityReport | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.quality_report = quality_report


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    external_column: str
    canonical_field: str
    classification: FieldClassification
    required: bool
    source_unit: str
    canonical_unit: str
    conversion_kind: ConversionKind
    scale: Decimal
    offset: Decimal


@dataclass(frozen=True, slots=True)
class ContextMapping:
    external_column: str
    canonical_field: str
    required: bool


@dataclass(frozen=True, slots=True)
class ReviewedOutcomeMapping:
    external_column: str
    canonical_field: str
    required: bool


@dataclass(frozen=True, slots=True)
class ShadowReviewContract:
    contract_version: str
    reviewer_id: str
    reviewer_role: str
    reviewed_at: str
    review_protocol_version: str
    label_source: str
    dataset_batch_reference: str
    reviewed_outcome_version: str
    provenance_declaration: str


@dataclass(frozen=True, slots=True)
class ShadowEvidenceBundle:
    bundle_schema_version: str
    canonicalizer_version: str
    raw_file_sha256: str
    mapping_manifest_hash: str
    canonical_measurements_hash: str
    mapping_version: str
    unit_mapping: tuple[tuple[str, str, str, str], ...]
    observation_contexts: tuple[ObservationContext, ...]
    reviewed_outcomes: tuple[ReviewedOutcome, ...]
    source_type: str
    source_metadata: tuple[tuple[str, str], ...]
    review_contract: ShadowReviewContract | None
    review_contract_declaration_hash: str
    context_hash: str
    reviewed_outcome_hash: str
    provenance_hash: str
    evidence_bundle_hash: str


@dataclass(frozen=True, slots=True)
class ShadowMappingManifest:
    manifest_version: str
    mapping_version: str
    canonical_schema_version: str
    canonicalizer_version: str
    source_type: ShadowSourceType
    source_metadata: tuple[tuple[str, str], ...]
    column_mappings: tuple[ColumnMapping, ...]
    context_mappings: tuple[ContextMapping, ...]
    reviewed_outcome_mappings: tuple[ReviewedOutcomeMapping, ...]
    ignored_columns: tuple[str, ...]
    expected_raw_file_sha256: str
    expected_canonical_observation_sha256: str
    review_contract: ShadowReviewContract | None
    review_contract_declaration_hash: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ShadowMappingManifest:
        expected_keys = {
            "manifest_version",
            "mapping_version",
            "canonical_schema_version",
            "canonicalizer_version",
            "source_type",
            "source_metadata",
            "column_mappings",
            "context_mappings",
            "reviewed_outcome_mappings",
            "ignored_columns",
            "expected_raw_file_sha256",
            "expected_canonical_observation_sha256",
        }
        if not isinstance(payload, Mapping) or not set(payload).issubset(
            expected_keys | {"review_contract"}
        ) or not expected_keys.issubset(payload):
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子数据 mapping manifest 字段不完整或包含未定义字段。",
            )
        if payload["manifest_version"] != SHADOW_MAPPING_MANIFEST_VERSION:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子数据 mapping manifest 版本不受支持。",
            )
        if payload["canonical_schema_version"] != SHADOW_CANONICAL_SCHEMA_VERSION:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子数据 canonical schema 版本不受支持。",
            )
        if payload["canonicalizer_version"] != ObservableCanonicalizer.version:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "mapping manifest 与当前 canonicalizer 版本不一致。",
            )
        mapping_version = payload["mapping_version"]
        if not isinstance(mapping_version, str) or not mapping_version.strip():
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "mapping_version 必须是非空版本标识。",
            )
        try:
            source_type = ShadowSourceType(payload["source_type"])
        except (TypeError, ValueError) as error:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子数据来源类型不受支持。",
            ) from error
        source_metadata = _parse_source_metadata(payload["source_metadata"], source_type)
        column_mappings = _parse_column_mappings(payload["column_mappings"])
        context_mappings = _parse_context_mappings(payload["context_mappings"])
        reviewed_mappings = _parse_reviewed_mappings(
            payload["reviewed_outcome_mappings"]
        )
        ignored_columns = _parse_ignored_columns(payload["ignored_columns"])
        expected_raw_hash = _required_hash(
            payload["expected_raw_file_sha256"], "expected_raw_file_sha256"
        )
        expected_canonical_hash = _required_hash(
            payload["expected_canonical_observation_sha256"],
            "expected_canonical_observation_sha256",
        )
        review_payload = payload.get("review_contract")
        review_contract = _parse_review_contract(review_payload, source_type)
        review_contract_declaration_hash = _evidence_hash(review_payload)
        all_external = [item.external_column for item in column_mappings]
        all_external.extend(item.external_column for item in context_mappings)
        all_external.extend(item.external_column for item in reviewed_mappings)
        all_external.extend(ignored_columns)
        if len(set(all_external)) != len(all_external):
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "同一外部列不得映射到多个字段或同时被忽略。",
            )
        return cls(
            manifest_version=payload["manifest_version"],
            mapping_version=mapping_version,
            canonical_schema_version=payload["canonical_schema_version"],
            canonicalizer_version=payload["canonicalizer_version"],
            source_type=source_type,
            source_metadata=source_metadata,
            column_mappings=column_mappings,
            context_mappings=context_mappings,
            reviewed_outcome_mappings=reviewed_mappings,
            ignored_columns=ignored_columns,
            expected_raw_file_sha256=expected_raw_hash,
            expected_canonical_observation_sha256=expected_canonical_hash,
            review_contract=review_contract,
            review_contract_declaration_hash=review_contract_declaration_hash,
        )

    def source_metadata_dict(self) -> dict[str, str]:
        return dict(self.source_metadata)


@dataclass(frozen=True, slots=True)
class FieldIssueCount:
    field: str
    count: int


@dataclass(frozen=True, slots=True)
class ValueRangeViolation:
    row_number: int
    field: str
    value: str
    constraint: str


@dataclass(frozen=True, slots=True)
class ShadowDataQualityReport:
    status: ShadowDataStatus
    policy_version: str
    mapping_version: str
    schema_mapping_complete: bool
    required_fields_present: bool
    units_explicit: bool
    sample_count: int
    analysis_group_count: int
    minimum_group_sample_count: int
    missing_values: tuple[FieldIssueCount, ...]
    duplicate_record_count: int
    sample_indexes_contiguous: bool
    timestamps_in_order: bool
    numeric_types_valid: bool
    invalid_numeric_values: tuple[FieldIssueCount, ...]
    non_finite_values: tuple[FieldIssueCount, ...]
    range_violations: tuple[ValueRangeViolation, ...]
    features_computable: bool
    spc_minimum_sample_count: int
    spc_minimum_sample_met: bool
    analysis_contract_bound: bool
    diagnostic_runnable: bool
    safety_recommendation_runnable: bool
    reviewed_labels_available: bool
    reviewed_group_count: int
    messages: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservationContext:
    sample_index: str
    batch_id: str | None
    lot_id: str | None


@dataclass(frozen=True, slots=True)
class ReviewedOutcome:
    batch_id: str | None
    lot_id: str | None
    reviewed_anomaly: str
    reviewed_root_cause: str
    reviewed_parameter_direction: str

    @property
    def group_key(self) -> tuple[str | None, str | None]:
        return self.batch_id, self.lot_id


@dataclass(frozen=True, slots=True)
class ImportedShadowDataset:
    source_type: ShadowSourceType
    source_metadata: tuple[tuple[str, str], ...]
    source_authenticity_status: str
    mapping_version: str
    canonical_schema_version: str
    canonicalizer_version: str
    raw_file_sha256: str
    canonical_observation_sha256: str
    canonical_csv_bytes: bytes
    measurements: tuple[Mapping[str, str], ...]
    observation_contexts: tuple[ObservationContext, ...]
    reviewed_outcomes: tuple[ReviewedOutcome, ...]
    quality_report: ShadowDataQualityReport
    evidence_bundle: ShadowEvidenceBundle
    storage_partition: str = SHADOW_STORAGE_PARTITION
    eligible_for_training: bool = False
    eligible_for_approved_case_library: bool = False
    automatic_retraining_allowed: bool = False
    fixed_demo_asset_mutation_allowed: bool = False

    @property
    def context_hash(self) -> str:
        return self.evidence_bundle.context_hash

    @property
    def reviewed_outcome_hash(self) -> str:
        return self.evidence_bundle.reviewed_outcome_hash

    @property
    def provenance_hash(self) -> str:
        return self.evidence_bundle.provenance_hash

    @property
    def evidence_bundle_hash(self) -> str:
        return self.evidence_bundle.evidence_bundle_hash


@dataclass(frozen=True, slots=True)
class ShadowPrediction:
    batch_id: str | None
    lot_id: str | None
    detection_status: str
    predicted_anomaly: str | None
    ranked_root_causes: tuple[str, ...]
    safety_candidate_status: str
    predicted_parameter_direction: str | None

    @property
    def group_key(self) -> tuple[str | None, str | None]:
        return self.batch_id, self.lot_id


@dataclass(frozen=True, slots=True)
class EvaluationMetric:
    numerator: int
    denominator: int
    ratio: str | None
    evidence_kind: str


@dataclass(frozen=True, slots=True)
class ShadowEvaluationReport:
    status: ShadowEvaluationStatus
    source_type: ShadowSourceType
    source_authenticity_status: str
    reviewed_group_count: int
    detection_coverage: EvaluationMetric | None
    evidence_level: str
    top1_reviewed_label_consistency: EvaluationMetric | None
    top3_reviewed_label_consistency: EvaluationMetric | None
    indeterminate_ratio: EvaluationMetric | None
    safety_candidate_pass_rate: EvaluationMetric | None
    insufficient_data_rejection_rate: EvaluationMetric | None
    parameter_direction_reviewed_consistency: EvaluationMetric | None
    excluded_claims: tuple[str, ...]
    message: str


CANONICAL_UNITS: dict[str, str] = {
    "sample_index": "COUNT",
    "timestamp": "ISO8601",
    "x_offset": "NORMALIZED_OFFSET_UNIT",
    "y_offset": "NORMALIZED_OFFSET_UNIT",
    "pitch": "NORMALIZED_ANGULAR_UNIT",
    "roll": "NORMALIZED_ANGULAR_UNIT",
    "z_offset": "NORMALIZED_OFFSET_UNIT",
    "vibration_rms": "NORMALIZED_PROTOTYPE_UNIT",
    "repeat_position_error": "NORMALIZED_PROTOTYPE_UNIT",
    "calibration_residual_x": "NORMALIZED_PROTOTYPE_UNIT",
    "calibration_residual_y": "NORMALIZED_PROTOTYPE_UNIT",
    "mtf_center": "NORMALIZED_MTF",
    "mtf_lt": "NORMALIZED_MTF",
    "mtf_rt": "NORMALIZED_MTF",
    "mtf_lb": "NORMALIZED_MTF",
    "mtf_rb": "NORMALIZED_MTF",
}

EXPECTED_CLASSIFICATIONS: dict[str, FieldClassification] = {
    "sample_index": FieldClassification.IDENTIFIER,
    "timestamp": FieldClassification.TIMESTAMP,
    **{field: FieldClassification.PARAMETER for field in PARAMETER_FIELDS},
    **{
        field: FieldClassification.OBSERVATION
        for field in set(OBSERVABLE_FIELDS) - PARAMETER_FIELDS - {"sample_index", "timestamp"}
    },
}

# Conversions are intentionally closed. Physical-to-normalized calibration is device
# specific and must be added as a reviewed contract instead of supplied ad hoc.
ALLOWED_DECIMAL_CONVERSIONS: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("NORMALIZED_OFFSET_UNIT", "NORMALIZED_OFFSET_UNIT"): (Decimal("1"), Decimal("0")),
    ("NORMALIZED_ANGULAR_UNIT", "NORMALIZED_ANGULAR_UNIT"): (Decimal("1"), Decimal("0")),
    ("NORMALIZED_PROTOTYPE_UNIT", "NORMALIZED_PROTOTYPE_UNIT"): (Decimal("1"), Decimal("0")),
    ("NORMALIZED_MTF", "NORMALIZED_MTF"): (Decimal("1"), Decimal("0")),
    ("PERCENT", "NORMALIZED_MTF"): (Decimal("0.01"), Decimal("0")),
}


class ShadowDataAdapter:
    def import_csv(
        self,
        csv_bytes: bytes,
        manifest_payload: Mapping[str, Any] | ShadowMappingManifest,
    ) -> ImportedShadowDataset:
        manifest = (
            manifest_payload
            if isinstance(manifest_payload, ShadowMappingManifest)
            else ShadowMappingManifest.from_payload(manifest_payload)
        )
        raw_hash = hashlib.sha256(csv_bytes).hexdigest()
        if raw_hash != manifest.expected_raw_file_sha256:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "原始影子 CSV 哈希与 mapping manifest 不一致。",
            )
        header, source_rows = self._read_csv(csv_bytes)
        self._validate_header(header, manifest)

        canonical_rows: list[list[str]] = []
        contexts: list[ObservationContext] = []
        row_review_values: list[tuple[tuple[str | None, str | None], dict[str, str]]] = []
        missing: dict[str, int] = {}
        invalid_numeric: dict[str, int] = {}
        non_finite: dict[str, int] = {}
        range_violations: list[ValueRangeViolation] = []
        parsed_timestamps: list[datetime] = []
        sample_indexes: list[tuple[tuple[str | None, str | None], str]] = []
        group_sample_counts: dict[tuple[str | None, str | None], int] = {}

        mappings_by_field = {
            mapping.canonical_field: mapping for mapping in manifest.column_mappings
        }
        context_by_field = {
            mapping.canonical_field: mapping for mapping in manifest.context_mappings
        }
        review_by_field = {
            mapping.canonical_field: mapping
            for mapping in manifest.reviewed_outcome_mappings
        }
        for row_number, source_row in enumerate(source_rows, start=2):
            canonical_values: dict[str, str] = {}
            for field in OBSERVABLE_FIELDS:
                mapping = mappings_by_field[field]
                value = source_row.get(mapping.external_column, "")
                if not value.strip():
                    missing[field] = missing.get(field, 0) + 1
                    continue
                converted = self._convert(
                    value,
                    mapping,
                    row_number,
                    invalid_numeric,
                    non_finite,
                )
                if converted is not None:
                    canonical_values[field] = converted
                    self._range_check(
                        converted,
                        field,
                        row_number,
                        range_violations,
                    )
            batch_id = self._context_value(
                source_row, context_by_field.get("batch_id"), missing, "batch_id"
            )
            lot_id = self._context_value(
                source_row, context_by_field.get("lot_id"), missing, "lot_id"
            )
            if "timestamp" in canonical_values:
                try:
                    parsed_timestamp = datetime.fromisoformat(
                        canonical_values["timestamp"].replace("Z", "+00:00")
                    )
                    if parsed_timestamp.tzinfo is None:
                        raise ValueError("timestamp must contain timezone")
                    parsed_timestamps.append(parsed_timestamp.astimezone(UTC))
                except ValueError:
                    invalid_numeric["timestamp"] = invalid_numeric.get("timestamp", 0) + 1
            if "sample_index" in canonical_values:
                group_key = (batch_id, lot_id)
                sample_indexes.append((group_key, canonical_values["sample_index"]))
                group_sample_counts[group_key] = group_sample_counts.get(group_key, 0) + 1
            if len(canonical_values) == len(OBSERVABLE_FIELDS):
                canonical_rows.append(
                    [canonical_values[field] for field in OBSERVABLE_FIELDS]
                )
                contexts.append(
                    ObservationContext(
                        sample_index=canonical_values["sample_index"],
                        batch_id=batch_id,
                        lot_id=lot_id,
                    )
                )
            row_review_values.append(
                (
                    (batch_id, lot_id),
                    {
                        field: source_row.get(mapping.external_column, "").strip()
                        for field, mapping in review_by_field.items()
                    },
                )
            )

        index_values = [value for _group_key, value in sample_indexes]
        duplicate_count = len(index_values) - len(set(index_values))
        timestamps_in_order = all(
            current >= previous
            for previous, current in zip(parsed_timestamps, parsed_timestamps[1:])
        ) and len(parsed_timestamps) == len(source_rows)
        reviewed_outcomes = self._reviewed_outcomes(row_review_values)
        preliminary = self._quality_report(
            manifest=manifest,
            sample_count=len(source_rows),
            group_sample_counts=group_sample_counts,
            missing=missing,
            duplicate_count=duplicate_count,
            sample_indexes_contiguous=self._sample_indexes_contiguous(
                sample_indexes,
                len(source_rows),
            ),
            timestamps_in_order=timestamps_in_order,
            invalid_numeric=invalid_numeric,
            non_finite=non_finite,
            range_violations=range_violations,
            reviewed_outcomes=reviewed_outcomes,
        )
        if preliminary.status is ShadowDataStatus.FEATURE_UNAVAILABLE:
            raise ShadowDataImportError(
                ShadowDataStatus.FEATURE_UNAVAILABLE,
                "影子数据质量不足，未进入只读影子评估。",
                quality_report=preliminary,
            )
        if not source_rows:
            raise ShadowDataImportError(
                ShadowDataStatus.INSUFFICIENT_DATA,
                "影子数据没有观测记录，未达到 SPC 最小样本条件。",
                quality_report=preliminary,
            )

        canonical_csv = self._canonical_csv(canonical_rows)
        try:
            canonical = ObservableCanonicalizer().canonicalize_csv(canonical_csv)
        except ObservationValidationError as error:
            failed_report = self._replace_quality_status(
                preliminary,
                ShadowDataStatus.FEATURE_UNAVAILABLE,
                (*preliminary.messages, str(error)),
            )
            raise ShadowDataImportError(
                ShadowDataStatus.FEATURE_UNAVAILABLE,
                str(error),
                quality_report=failed_report,
            ) from error
        if canonical.sha256 != manifest.expected_canonical_observation_sha256:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "规范化影子观测哈希与 mapping manifest 不一致。",
                quality_report=preliminary,
            )
        measurements = self._measurements(canonical.content)
        ordered_contexts = tuple(
            sorted(contexts, key=lambda item: int(item.sample_index))
        )
        evidence_bundle = build_shadow_evidence_bundle(
            manifest=manifest,
            raw_file_sha256=raw_hash,
            canonical_measurements_hash=canonical.sha256,
            observation_contexts=ordered_contexts,
            reviewed_outcomes=reviewed_outcomes,
        )
        return ImportedShadowDataset(
            source_type=manifest.source_type,
            source_metadata=manifest.source_metadata,
            source_authenticity_status=(
                "OPERATOR_DECLARED_NOT_VERIFIED"
                if manifest.source_type is ShadowSourceType.REAL_DEVICE_SHADOW_DECLARED
                else "SYNTHETIC"
            ),
            mapping_version=manifest.mapping_version,
            canonical_schema_version=manifest.canonical_schema_version,
            canonicalizer_version=manifest.canonicalizer_version,
            raw_file_sha256=raw_hash,
            canonical_observation_sha256=canonical.sha256,
            canonical_csv_bytes=canonical_csv,
            measurements=measurements,
            observation_contexts=ordered_contexts,
            reviewed_outcomes=reviewed_outcomes,
            quality_report=preliminary,
            evidence_bundle=evidence_bundle,
        )

    @staticmethod
    def _read_csv(csv_bytes: bytes) -> tuple[tuple[str, ...], list[dict[str, str]]]:
        try:
            text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子 CSV 必须使用 UTF-8 编码。",
            ) from error
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子 CSV 缺少表头。",
            )
        header = tuple(reader.fieldnames)
        if any(not field for field in header) or len(set(header)) != len(header):
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "影子 CSV 表头包含空列名或重复列名。",
            )
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ShadowDataImportError(
                    ShadowDataStatus.MAPPING_INVALID,
                    f"影子 CSV 第 {row_number} 行字段数量超过表头。",
                )
            rows.append({key: value or "" for key, value in row.items()})
        return header, rows

    @staticmethod
    def _validate_header(
        header: tuple[str, ...], manifest: ShadowMappingManifest
    ) -> None:
        declared = {
            mapping.external_column for mapping in manifest.column_mappings
        }
        declared.update(
            mapping.external_column for mapping in manifest.context_mappings
        )
        declared.update(
            mapping.external_column
            for mapping in manifest.reviewed_outcome_mappings
        )
        declared.update(manifest.ignored_columns)
        required = {
            mapping.external_column
            for mapping in (
                *manifest.column_mappings,
                *manifest.context_mappings,
                *manifest.reviewed_outcome_mappings,
            )
            if mapping.required
        }
        missing = sorted(required - set(header))
        unmapped = sorted(set(header) - declared)
        if missing or unmapped:
            detail = []
            if missing:
                detail.append(f"缺少必填列：{', '.join(missing)}")
            if unmapped:
                detail.append(f"存在未显式映射列：{', '.join(unmapped)}")
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "；".join(detail) + "。",
            )

    @staticmethod
    def _convert(
        value: str,
        mapping: ColumnMapping,
        row_number: int,
        invalid_numeric: dict[str, int],
        non_finite: dict[str, int],
    ) -> str | None:
        if mapping.conversion_kind is ConversionKind.TIMESTAMP_ISO8601:
            return value.strip()
        if mapping.conversion_kind is ConversionKind.INTEGER_IDENTITY:
            stripped = value.strip()
            if not re.fullmatch(r"0|[1-9][0-9]*", stripped):
                invalid_numeric[mapping.canonical_field] = (
                    invalid_numeric.get(mapping.canonical_field, 0) + 1
                )
                return None
            return str(int(stripped))
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            invalid_numeric[mapping.canonical_field] = (
                invalid_numeric.get(mapping.canonical_field, 0) + 1
            )
            return None
        if not parsed.is_finite():
            non_finite[mapping.canonical_field] = (
                non_finite.get(mapping.canonical_field, 0) + 1
            )
            return None
        converted = parsed * mapping.scale + mapping.offset
        if not converted.is_finite():
            non_finite[mapping.canonical_field] = (
                non_finite.get(mapping.canonical_field, 0) + 1
            )
            return None
        return format(converted, "f")

    @staticmethod
    def _context_value(
        row: Mapping[str, str],
        mapping: ContextMapping | None,
        missing: dict[str, int],
        canonical_field: str,
    ) -> str | None:
        if mapping is None:
            return None
        value = row.get(mapping.external_column, "").strip()
        if not value and mapping.required:
            missing[canonical_field] = missing.get(canonical_field, 0) + 1
        return value or None

    @staticmethod
    def _range_check(
        value: str,
        field: str,
        row_number: int,
        violations: list[ValueRangeViolation],
    ) -> None:
        if field in {"sample_index", "timestamp"}:
            return
        parsed = Decimal(value)
        if field in PARAMETER_FIELDS:
            if parsed < Decimal("-1") or parsed > Decimal("1"):
                violations.append(
                    ValueRangeViolation(row_number, field, value, "-1 <= value <= 1")
                )
            elif parsed % TICK_SIZE != 0:
                violations.append(
                    ValueRangeViolation(
                        row_number,
                        field,
                        value,
                        f"value on {format(TICK_SIZE, 'f')} tick grid",
                    )
                )
        elif field in MTF_FIELDS and (parsed < 0 or parsed > 1):
            violations.append(
                ValueRangeViolation(row_number, field, value, "0 <= value <= 1")
            )
        elif field in NON_NEGATIVE_FIELDS and parsed < 0:
            violations.append(
                ValueRangeViolation(row_number, field, value, "value >= 0")
            )

    @staticmethod
    def _reviewed_outcomes(
        rows: Sequence[
            tuple[tuple[str | None, str | None], dict[str, str]]
        ],
    ) -> tuple[ReviewedOutcome, ...]:
        by_group: dict[tuple[str | None, str | None], ReviewedOutcome] = {}
        for group_key, values in rows:
            if not values or not any(values.values()):
                continue
            if set(values) != REVIEWED_OUTCOME_FIELDS:
                raise ShadowDataImportError(
                    ShadowDataStatus.MAPPING_INVALID,
                    "审核结果映射不完整，不能静默丢弃标签。",
                )
            reviewed_status = values["reviewed_status"]
            if reviewed_status == "NOT_REVIEWED":
                if any(
                    values[field]
                    for field in REVIEWED_OUTCOME_FIELDS - {"reviewed_status"}
                ):
                    raise ShadowDataImportError(
                        ShadowDataStatus.FEATURE_UNAVAILABLE,
                        "NOT_REVIEWED 行不得包含审核标签值。",
                    )
                continue
            if reviewed_status != "REVIEWED":
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "reviewed_status 只能是 REVIEWED 或 NOT_REVIEWED。",
                )
            if not all(values[field] for field in REVIEWED_OUTCOME_FIELDS):
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "审核结果字段不完整，不能猜测缺失标签。",
                )
            anomaly = values["reviewed_anomaly"]
            root_cause = values["reviewed_root_cause"]
            direction = values["reviewed_parameter_direction"]
            if anomaly not in {
                "TARGET_ANOMALY",
                "NORMAL",
                "NON_TARGET_GLOBAL_DEGRADATION",
            }:
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "审核异常标签不属于受支持的显式标签集。",
                )
            if root_cause not in {*CLASS_ORDER, "NOT_APPLICABLE"}:
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "审核根因标签不属于冻结诊断标签集。",
                )
            if direction not in {"INCREASE", "DECREASE", "NO_CHANGE", "NOT_APPLICABLE"}:
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "审核参数方向不属于显式方向标签集。",
                )
            if anomaly != "TARGET_ANOMALY" and (
                root_cause != "NOT_APPLICABLE" or direction != "NOT_APPLICABLE"
            ):
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "NORMAL/非目标异常不得同时声明调参根因或方向结果。",
                )
            if anomaly == "TARGET_ANOMALY" and (
                root_cause == "NOT_APPLICABLE"
                or direction in {"NOT_APPLICABLE", "NO_CHANGE"}
            ):
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "目标异常的根因与调整方向 review 必须同时有效。",
                )
            if (root_cause == "NOT_APPLICABLE") != (
                direction == "NOT_APPLICABLE"
            ):
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "review root cause 与 adjustment direction 不兼容。",
                )
            outcome = ReviewedOutcome(
                batch_id=group_key[0],
                lot_id=group_key[1],
                reviewed_anomaly=anomaly,
                reviewed_root_cause=root_cause,
                reviewed_parameter_direction=direction,
            )
            current = by_group.get(group_key)
            if current is not None and current != outcome:
                raise ShadowDataImportError(
                    ShadowDataStatus.FEATURE_UNAVAILABLE,
                    "同一 batch/lot 的审核结果不一致。",
                )
            by_group[group_key] = outcome
        return tuple(by_group[key] for key in sorted(by_group, key=_group_sort_key))

    @staticmethod
    def _quality_report(
        *,
        manifest: ShadowMappingManifest,
        sample_count: int,
        group_sample_counts: Mapping[tuple[str | None, str | None], int],
        missing: Mapping[str, int],
        duplicate_count: int,
        sample_indexes_contiguous: bool,
        timestamps_in_order: bool,
        invalid_numeric: Mapping[str, int],
        non_finite: Mapping[str, int],
        range_violations: Sequence[ValueRangeViolation],
        reviewed_outcomes: tuple[ReviewedOutcome, ...],
    ) -> ShadowDataQualityReport:
        required_present = not missing
        numeric_valid = not invalid_numeric and not non_finite
        features_computable = (
            sample_count > 0
            and required_present
            and numeric_valid
            and duplicate_count == 0
            and sample_indexes_contiguous
            and timestamps_in_order
            and not range_violations
        )
        minimum_group_sample_count = min(group_sample_counts.values(), default=0)
        spc_ready = (
            bool(group_sample_counts)
            and minimum_group_sample_count >= MINIMUM_SPC_SAMPLE_COUNT
        )
        if not spc_ready and (
            sample_count == 0
            or (
                required_present
                and numeric_valid
                and duplicate_count == 0
                and sample_indexes_contiguous
                and timestamps_in_order
                and not range_violations
            )
        ):
            status = ShadowDataStatus.INSUFFICIENT_DATA
        elif not features_computable:
            status = ShadowDataStatus.FEATURE_UNAVAILABLE
        elif not reviewed_outcomes or manifest.review_contract is None:
            status = ShadowDataStatus.NOT_EVALUABLE
        else:
            status = ShadowDataStatus.READY
        messages: list[str] = []
        if missing:
            messages.append("存在缺失的必填字段。")
        if duplicate_count:
            messages.append("sample_index 存在重复记录。")
        if not sample_indexes_contiguous:
            messages.append("sample_index 缺失或不连续，无法计算持续性。")
        if not timestamps_in_order:
            messages.append("时间戳缺失、无效或未按采集顺序排列。")
        if invalid_numeric:
            messages.append("存在无法按显式映射解析的数值。")
        if non_finite:
            messages.append("存在非有限数值。")
        if range_violations:
            messages.append("存在超出当前数据质量/参数配置边界的数值。")
        if not spc_ready:
            messages.append(
                f"样本数低于 SPC 最小条件 {MINIMUM_SPC_SAMPLE_COUNT}。"
            )
        if not reviewed_outcomes:
            messages.append("没有审核标签，评估状态必须保持 NOT_EVALUABLE。")
        elif manifest.review_contract is None:
            messages.append("缺少合法 review contract，声明标签不得用于评估。")
        if features_computable and spc_ready:
            messages.append(
                "尚未绑定版本化分析契约、控制限、模型与安全规则，不能运行影子分析。"
            )
        return ShadowDataQualityReport(
            status=status,
            policy_version=SHADOW_QUALITY_POLICY_VERSION,
            mapping_version=manifest.mapping_version,
            schema_mapping_complete=True,
            required_fields_present=required_present,
            units_explicit=True,
            sample_count=sample_count,
            analysis_group_count=len(group_sample_counts),
            minimum_group_sample_count=minimum_group_sample_count,
            missing_values=_issue_counts(missing),
            duplicate_record_count=duplicate_count,
            sample_indexes_contiguous=sample_indexes_contiguous,
            timestamps_in_order=timestamps_in_order,
            numeric_types_valid=numeric_valid,
            invalid_numeric_values=_issue_counts(invalid_numeric),
            non_finite_values=_issue_counts(non_finite),
            range_violations=tuple(range_violations),
            features_computable=features_computable,
            spc_minimum_sample_count=MINIMUM_SPC_SAMPLE_COUNT,
            spc_minimum_sample_met=spc_ready,
            analysis_contract_bound=False,
            diagnostic_runnable=False,
            safety_recommendation_runnable=False,
            reviewed_labels_available=bool(reviewed_outcomes and manifest.review_contract),
            reviewed_group_count=(
                len(reviewed_outcomes) if manifest.review_contract is not None else 0
            ),
            messages=tuple(messages),
        )

    @staticmethod
    def _replace_quality_status(
        report: ShadowDataQualityReport,
        status: ShadowDataStatus,
        messages: tuple[str, ...],
    ) -> ShadowDataQualityReport:
        return ShadowDataQualityReport(
            status=status,
            policy_version=report.policy_version,
            mapping_version=report.mapping_version,
            schema_mapping_complete=report.schema_mapping_complete,
            required_fields_present=report.required_fields_present,
            units_explicit=report.units_explicit,
            sample_count=report.sample_count,
            analysis_group_count=report.analysis_group_count,
            minimum_group_sample_count=report.minimum_group_sample_count,
            missing_values=report.missing_values,
            duplicate_record_count=report.duplicate_record_count,
            sample_indexes_contiguous=report.sample_indexes_contiguous,
            timestamps_in_order=report.timestamps_in_order,
            numeric_types_valid=report.numeric_types_valid,
            invalid_numeric_values=report.invalid_numeric_values,
            non_finite_values=report.non_finite_values,
            range_violations=report.range_violations,
            features_computable=False,
            spc_minimum_sample_count=report.spc_minimum_sample_count,
            spc_minimum_sample_met=report.spc_minimum_sample_met,
            analysis_contract_bound=report.analysis_contract_bound,
            diagnostic_runnable=False,
            safety_recommendation_runnable=False,
            reviewed_labels_available=report.reviewed_labels_available,
            reviewed_group_count=report.reviewed_group_count,
            messages=messages,
        )

    @staticmethod
    def _canonical_csv(rows: Sequence[Sequence[str]]) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(OBSERVABLE_FIELDS)
        writer.writerows(rows)
        return output.getvalue().encode("utf-8")

    @staticmethod
    def _measurements(content: bytes) -> tuple[Mapping[str, str], ...]:
        payload = json.loads(content)
        return tuple(
            MappingProxyType(dict(zip(OBSERVABLE_FIELDS, record, strict=True)))
            for record in payload["records"]
        )

    @staticmethod
    def _sample_indexes_contiguous(
        sample_indexes: Sequence[
            tuple[tuple[str | None, str | None], str]
        ],
        sample_count: int,
    ) -> bool:
        if len(sample_indexes) != sample_count:
            return False
        grouped: dict[tuple[str | None, str | None], list[int]] = {}
        for group_key, value in sample_indexes:
            grouped.setdefault(group_key, []).append(int(value))
        return all(
            all(
                current == previous + 1
                for previous, current in zip(indexes, indexes[1:])
            )
            for indexes in (sorted(values) for values in grouped.values())
        )


def _evidence_plain(value: Any) -> Any:
    if is_dataclass(value):
        return _evidence_plain(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {
            str(key): _evidence_plain(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_evidence_plain(item) for item in value]
    return value


def _evidence_hash(value: Any) -> str:
    envelope = {
        "canonicalizer_version": SHADOW_EVIDENCE_CANONICALIZER_VERSION,
        "business_content": _evidence_plain(value),
    }
    return hashlib.sha256(
        json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _manifest_hash(manifest: ShadowMappingManifest) -> str:
    return _evidence_hash(
        {
            "manifest_version": manifest.manifest_version,
            "mapping_version": manifest.mapping_version,
            "canonical_schema_version": manifest.canonical_schema_version,
            "canonicalizer_version": manifest.canonicalizer_version,
            "source_type": manifest.source_type,
            "source_metadata": manifest.source_metadata,
            "column_mappings": manifest.column_mappings,
            "context_mappings": manifest.context_mappings,
            "reviewed_outcome_mappings": manifest.reviewed_outcome_mappings,
            "ignored_columns": manifest.ignored_columns,
            "expected_raw_file_sha256": manifest.expected_raw_file_sha256,
            "expected_canonical_observation_sha256": (
                manifest.expected_canonical_observation_sha256
            ),
            "review_contract": manifest.review_contract,
            "review_contract_declaration_hash": (
                manifest.review_contract_declaration_hash
            ),
        }
    )


def _assemble_evidence_bundle(
    *,
    raw_file_sha256: str,
    mapping_manifest_hash: str,
    canonical_measurements_hash: str,
    mapping_version: str,
    unit_mapping: tuple[tuple[str, str, str, str], ...],
    observation_contexts: tuple[ObservationContext, ...],
    reviewed_outcomes: tuple[ReviewedOutcome, ...],
    source_type: str,
    source_metadata: tuple[tuple[str, str], ...],
    review_contract: ShadowReviewContract | None,
    review_contract_declaration_hash: str,
) -> ShadowEvidenceBundle:
    context_hash = _evidence_hash(observation_contexts)
    outcome_hash = _evidence_hash(reviewed_outcomes)
    provenance_payload = {
        "source_type": source_type,
        "source_metadata": source_metadata,
        "review_contract": review_contract,
        "review_contract_declaration_hash": review_contract_declaration_hash,
    }
    provenance_hash = _evidence_hash(provenance_payload)
    content = {
        "bundle_schema_version": SHADOW_EVIDENCE_BUNDLE_VERSION,
        "canonicalizer_version": SHADOW_EVIDENCE_CANONICALIZER_VERSION,
        "raw_file_sha256": raw_file_sha256,
        "mapping_manifest_hash": mapping_manifest_hash,
        "canonical_measurements_hash": canonical_measurements_hash,
        "mapping_version": mapping_version,
        "unit_mapping": unit_mapping,
        "observation_contexts": observation_contexts,
        "reviewed_outcomes": reviewed_outcomes,
        "source_type": source_type,
        "source_metadata": source_metadata,
        "review_contract": review_contract,
        "review_contract_declaration_hash": review_contract_declaration_hash,
        "context_hash": context_hash,
        "reviewed_outcome_hash": outcome_hash,
        "provenance_hash": provenance_hash,
    }
    return ShadowEvidenceBundle(
        **content,
        evidence_bundle_hash=_evidence_hash(content),
    )


def build_shadow_evidence_bundle(
    *,
    manifest: ShadowMappingManifest,
    raw_file_sha256: str,
    canonical_measurements_hash: str,
    observation_contexts: tuple[ObservationContext, ...],
    reviewed_outcomes: tuple[ReviewedOutcome, ...],
) -> ShadowEvidenceBundle:
    unit_mapping = tuple(
        sorted(
            (
                item.canonical_field,
                item.source_unit,
                item.canonical_unit,
                item.conversion_kind.value,
            )
            for item in manifest.column_mappings
        )
    )
    return _assemble_evidence_bundle(
        raw_file_sha256=raw_file_sha256,
        mapping_manifest_hash=_manifest_hash(manifest),
        canonical_measurements_hash=canonical_measurements_hash,
        mapping_version=manifest.mapping_version,
        unit_mapping=unit_mapping,
        observation_contexts=observation_contexts,
        reviewed_outcomes=reviewed_outcomes,
        source_type=manifest.source_type.value,
        source_metadata=manifest.source_metadata,
        review_contract=manifest.review_contract,
        review_contract_declaration_hash=manifest.review_contract_declaration_hash,
    )


def recompute_shadow_evidence_bundle(
    dataset: ImportedShadowDataset,
) -> ShadowEvidenceBundle:
    current = dataset.evidence_bundle
    return _assemble_evidence_bundle(
        raw_file_sha256=dataset.raw_file_sha256,
        mapping_manifest_hash=current.mapping_manifest_hash,
        canonical_measurements_hash=canonical_measurement_hash(
            tuple(dict(item) for item in dataset.measurements)
        ),
        mapping_version=dataset.mapping_version,
        unit_mapping=current.unit_mapping,
        observation_contexts=dataset.observation_contexts,
        reviewed_outcomes=dataset.reviewed_outcomes,
        source_type=dataset.source_type.value,
        source_metadata=dataset.source_metadata,
        review_contract=current.review_contract,
        review_contract_declaration_hash=current.review_contract_declaration_hash,
    )


def validate_shadow_evidence_bundle(dataset: ImportedShadowDataset) -> None:
    try:
        recomputed = recompute_shadow_evidence_bundle(dataset)
    except (DetectionGuardError, KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "ShadowEvidenceBundle 无法从当前 measurements 重新计算。"
        ) from error
    if recomputed != dataset.evidence_bundle:
        raise ValueError("ShadowEvidenceBundle 与当前上下文、标签或来源内容不一致。")


def rebuild_shadow_quality_report(
    dataset: ImportedShadowDataset,
) -> ShadowDataQualityReport:
    validate_shadow_evidence_bundle(dataset)
    indexes = [int(item["sample_index"]) for item in dataset.measurements]
    contexts = {item.sample_index: item for item in dataset.observation_contexts}
    group_counts: dict[tuple[str | None, str | None], int] = {}
    timestamps: list[datetime] = []
    for measurement in dataset.measurements:
        sample_index = measurement["sample_index"]
        context = contexts.get(sample_index)
        if context is None:
            raise ValueError("ShadowEvidenceBundle context 未覆盖 canonical measurement。")
        key = (context.batch_id, context.lot_id)
        group_counts[key] = group_counts.get(key, 0) + 1
        parsed = datetime.fromisoformat(measurement["timestamp"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("canonical timestamp 缺少时区。")
        timestamps.append(parsed.astimezone(UTC))
    contiguous = sorted(indexes) == list(range(min(indexes), max(indexes) + 1))
    ordered = all(b >= a for a, b in zip(timestamps, timestamps[1:]))
    minimum = min(group_counts.values(), default=0)
    spc_ready = minimum >= MINIMUM_SPC_SAMPLE_COUNT
    review_valid = dataset.evidence_bundle.review_contract is not None
    status = (
        ShadowDataStatus.INSUFFICIENT_DATA
        if not spc_ready
        else ShadowDataStatus.READY
        if dataset.reviewed_outcomes and review_valid
        else ShadowDataStatus.NOT_EVALUABLE
    )
    messages = [
        "质量报告由绑定后的 ShadowEvidenceBundle 重新生成。",
        "尚未绑定版本化分析契约、控制限、模型与安全规则，不能运行影子分析。",
    ]
    if not review_valid:
        messages.append("缺少合法 review contract，声明标签不得用于评估。")
    return ShadowDataQualityReport(
        status=status,
        policy_version=SHADOW_QUALITY_POLICY_VERSION,
        mapping_version=dataset.mapping_version,
        schema_mapping_complete=True,
        required_fields_present=True,
        units_explicit=bool(dataset.evidence_bundle.unit_mapping),
        sample_count=len(dataset.measurements),
        analysis_group_count=len(group_counts),
        minimum_group_sample_count=minimum,
        missing_values=(),
        duplicate_record_count=len(indexes) - len(set(indexes)),
        sample_indexes_contiguous=contiguous,
        timestamps_in_order=ordered,
        numeric_types_valid=True,
        invalid_numeric_values=(),
        non_finite_values=(),
        range_violations=(),
        features_computable=bool(indexes and contiguous and ordered),
        spc_minimum_sample_count=MINIMUM_SPC_SAMPLE_COUNT,
        spc_minimum_sample_met=spc_ready,
        analysis_contract_bound=False,
        diagnostic_runnable=False,
        safety_recommendation_runnable=False,
        reviewed_labels_available=bool(dataset.reviewed_outcomes and review_valid),
        reviewed_group_count=len(dataset.reviewed_outcomes) if review_valid else 0,
        messages=tuple(messages),
    )


def evaluate_shadow_dataset(
    dataset: ImportedShadowDataset,
    predictions: Sequence[ShadowPrediction],
) -> ShadowEvaluationReport:
    excluded = (
        "REAL_YIELD_IMPROVEMENT",
        "REAL_TUNING_TIME_REDUCTION",
        "CAUSAL_PARAMETER_EFFECT",
        "PARAMETER_EFFECTIVENESS_CLAIM",
    )
    validate_shadow_evidence_bundle(dataset)
    review_contract = dataset.evidence_bundle.review_contract
    if not dataset.reviewed_outcomes or review_contract is None:
        return ShadowEvaluationReport(
            status=ShadowEvaluationStatus.NOT_EVALUABLE,
            source_type=dataset.source_type,
            source_authenticity_status=dataset.source_authenticity_status,
            reviewed_group_count=0,
            detection_coverage=None,
            evidence_level="NOT_REVIEWED",
            top1_reviewed_label_consistency=None,
            top3_reviewed_label_consistency=None,
            indeterminate_ratio=None,
            safety_candidate_pass_rate=None,
            insufficient_data_rejection_rate=None,
            parameter_direction_reviewed_consistency=None,
            excluded_claims=excluded,
            message="没有合法 review contract；不得计算一致率或宣称荐参有效。",
        )
    by_group: dict[tuple[str | None, str | None], ShadowPrediction] = {}
    for prediction in predictions:
        if prediction.group_key in by_group:
            raise ValueError("同一 batch/lot 只能提供一条影子预测。")
        by_group[prediction.group_key] = prediction
    outcomes = dataset.reviewed_outcomes
    paired = [(outcome, by_group.get(outcome.group_key)) for outcome in outcomes]
    coverage = sum(
        prediction is not None and prediction.predicted_anomaly is not None
        for _, prediction in paired
    )
    indeterminate = sum(
        prediction is None
        or prediction.detection_status in {"NOT_EVALUABLE", "INDETERMINATE"}
        or prediction.predicted_anomaly is None
        for _, prediction in paired
    )
    root_pairs = [
        (outcome, prediction)
        for outcome, prediction in paired
        if outcome.reviewed_root_cause != "NOT_APPLICABLE"
        and prediction is not None
        and prediction.ranked_root_causes
    ]
    direction_pairs = [
        (outcome, prediction)
        for outcome, prediction in paired
        if outcome.reviewed_parameter_direction != "NOT_APPLICABLE"
        and prediction is not None
        and prediction.predicted_parameter_direction is not None
    ]
    safety_passes = sum(
        prediction is not None and prediction.safety_candidate_status == "PASSED"
        for _, prediction in paired
    )
    insufficient = sum(
        prediction is not None and prediction.detection_status == "INSUFFICIENT_DATA"
        for _, prediction in paired
    )
    return ShadowEvaluationReport(
        status=ShadowEvaluationStatus.EVALUATED_DECLARED_REVIEW,
        source_type=dataset.source_type,
        source_authenticity_status=dataset.source_authenticity_status,
        reviewed_group_count=len(outcomes),
        evidence_level=review_contract.label_source,
        detection_coverage=_metric(
            coverage, len(outcomes), "DESCRIPTIVE_MODEL_OUTPUT_COVERAGE"
        ),
        top1_reviewed_label_consistency=_metric(
            sum(
                prediction.ranked_root_causes[0] == outcome.reviewed_root_cause
                for outcome, prediction in root_pairs
            ),
            len(root_pairs),
            "MODEL_OUTPUT_VS_DECLARED_REVIEW_LABEL",
        ),
        top3_reviewed_label_consistency=_metric(
            sum(
                outcome.reviewed_root_cause in prediction.ranked_root_causes[:3]
                for outcome, prediction in root_pairs
            ),
            len(root_pairs),
            "MODEL_OUTPUT_VS_DECLARED_REVIEW_LABEL",
        ),
        indeterminate_ratio=_metric(
            indeterminate, len(outcomes), "DESCRIPTIVE_MODEL_OUTPUT_STATUS"
        ),
        safety_candidate_pass_rate=_metric(
            safety_passes, len(outcomes), "RULE_CHECK_OUTPUT"
        ),
        insufficient_data_rejection_rate=_metric(
            insufficient, len(outcomes), "RULE_CHECK_OUTPUT"
        ),
        parameter_direction_reviewed_consistency=_metric(
            sum(
                prediction.predicted_parameter_direction
                == outcome.reviewed_parameter_direction
                for outcome, prediction in direction_pairs
            ),
            len(direction_pairs),
            "MODEL_OUTPUT_VS_DECLARED_REVIEW_LABEL",
        ),
        excluded_claims=excluded,
        message=(
            "报告仅比较离线模型输出、规则检查与已声明审核标签；"
            "标签未经过 TuneWise 外部验证，不包含真实干预或因果收益。"
        ),
    )


def _parse_review_contract(
    payload: Any,
    source_type: ShadowSourceType,
) -> ShadowReviewContract | None:
    fields = {
        "contract_version",
        "reviewer_id",
        "reviewer_role",
        "reviewed_at",
        "review_protocol_version",
        "label_source",
        "dataset_batch_reference",
        "reviewed_outcome_version",
        "provenance_declaration",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        return None
    if not all(isinstance(payload[field], str) and payload[field].strip() for field in fields):
        return None
    if payload["contract_version"] != SHADOW_REVIEW_CONTRACT_VERSION:
        return None
    if payload["label_source"] not in {"OPERATOR_DECLARED", "REVIEWED_DECLARED"}:
        return None
    try:
        reviewed_at = datetime.fromisoformat(
            payload["reviewed_at"].replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if reviewed_at.tzinfo is None:
        return None
    declaration = payload["provenance_declaration"].upper()
    if source_type in {ShadowSourceType.SYNTHETIC_DEMO, ShadowSourceType.CONTRACT_FIXTURE}:
        if "SYNTHETIC" not in declaration:
            return None
    return ShadowReviewContract(**{field: payload[field].strip() for field in fields})


def _parse_source_metadata(
    payload: Any, source_type: ShadowSourceType
) -> tuple[tuple[str, str], ...]:
    required = {
        "declared_by",
        "declared_at",
        "provenance_statement",
        "device_model_declared",
        "authorization_reference",
        "data_reality",
    }
    if not isinstance(payload, Mapping) or not required.issubset(payload):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "source_metadata 缺少来源声明字段。",
        )
    if not all(
        isinstance(key, str)
        and isinstance(value, str)
        and key.strip()
        and value.strip()
        for key, value in payload.items()
    ):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "source_metadata 只能包含非空字符串声明。",
        )
    expected_reality = {
        ShadowSourceType.SYNTHETIC_DEMO: "SYNTHETIC_DEMO",
        ShadowSourceType.CONTRACT_FIXTURE: "SYNTHETIC_CONTRACT_FIXTURE",
        ShadowSourceType.REAL_DEVICE_SHADOW_DECLARED: (
            "OPERATOR_DECLARED_REAL_DEVICE_SHADOW_NOT_VERIFIED"
        ),
    }[source_type]
    if payload["data_reality"] != expected_reality:
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "data_reality 与来源类型不一致。",
        )
    return tuple(sorted((str(key), str(value)) for key, value in payload.items()))


def _parse_column_mappings(payload: Any) -> tuple[ColumnMapping, ...]:
    if not isinstance(payload, list):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "column_mappings 必须是数组。"
        )
    mappings: list[ColumnMapping] = []
    expected_keys = {
        "external_column",
        "canonical_field",
        "classification",
        "required",
        "source_unit",
        "canonical_unit",
        "conversion",
    }
    for item in payload:
        if not isinstance(item, Mapping) or set(item) != expected_keys:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "column mapping 字段无效。"
            )
        external = item["external_column"]
        canonical = item["canonical_field"]
        if not isinstance(external, str) or not external or canonical not in OBSERVABLE_FIELDS:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "外部列或 canonical 字段无效。"
            )
        if item["required"] is not True:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "冻结 canonical observation 字段必须全部显式标为 required。",
            )
        try:
            classification = FieldClassification(item["classification"])
        except (TypeError, ValueError) as error:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "字段分类无效。"
            ) from error
        if classification is not EXPECTED_CLASSIFICATIONS[canonical]:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                f"{canonical} 的参数/观测分类不匹配。",
            )
        conversion = item["conversion"]
        if not isinstance(conversion, Mapping) or set(conversion) != {
            "kind",
            "scale",
            "offset",
        }:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "单位转换声明无效。"
            )
        try:
            kind = ConversionKind(conversion["kind"])
            if not isinstance(conversion["scale"], str) or not isinstance(
                conversion["offset"], str
            ):
                raise TypeError("conversion Decimal values must be strings")
            scale = Decimal(conversion["scale"])
            offset = Decimal(conversion["offset"])
        except (TypeError, ValueError, InvalidOperation) as error:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "单位转换数值无效。"
            ) from error
        if not scale.is_finite() or not offset.is_finite():
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "单位转换必须使用有限 Decimal。"
            )
        source_unit = item["source_unit"]
        canonical_unit = item["canonical_unit"]
        if not isinstance(source_unit, str) or not isinstance(canonical_unit, str):
            raise ShadowDataImportError(
                ShadowDataStatus.UNIT_UNKNOWN, "单位声明必须是字符串。"
            )
        _validate_unit_conversion(
            canonical,
            source_unit,
            canonical_unit,
            kind,
            scale,
            offset,
        )
        mappings.append(
            ColumnMapping(
                external_column=external,
                canonical_field=canonical,
                classification=classification,
                required=True,
                source_unit=source_unit,
                canonical_unit=canonical_unit,
                conversion_kind=kind,
                scale=scale,
                offset=offset,
            )
        )
    canonical_fields = [mapping.canonical_field for mapping in mappings]
    external_fields = [mapping.external_column for mapping in mappings]
    if set(canonical_fields) != set(OBSERVABLE_FIELDS) or len(canonical_fields) != len(
        OBSERVABLE_FIELDS
    ):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "column_mappings 必须一一覆盖冻结 canonical observation 字段。",
        )
    if len(set(external_fields)) != len(external_fields):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "外部列映射不得重复。"
        )
    return tuple(sorted(mappings, key=lambda item: OBSERVABLE_FIELDS.index(item.canonical_field)))


def _validate_unit_conversion(
    field: str,
    source_unit: str,
    canonical_unit: str,
    kind: ConversionKind,
    scale: Decimal,
    offset: Decimal,
) -> None:
    if canonical_unit != CANONICAL_UNITS[field]:
        raise ShadowDataImportError(
            ShadowDataStatus.UNIT_UNKNOWN,
            f"{field} 的 canonical unit 不受支持。",
        )
    if field == "sample_index":
        valid = (
            kind is ConversionKind.INTEGER_IDENTITY
            and source_unit == canonical_unit == "COUNT"
            and scale == 1
            and offset == 0
        )
    elif field == "timestamp":
        valid = (
            kind is ConversionKind.TIMESTAMP_ISO8601
            and source_unit == canonical_unit == "ISO8601"
            and scale == 1
            and offset == 0
        )
    else:
        expected = ALLOWED_DECIMAL_CONVERSIONS.get((source_unit, canonical_unit))
        valid = (
            kind is ConversionKind.DECIMAL_AFFINE
            and expected is not None
            and expected == (scale, offset)
        )
    if not valid:
        raise ShadowDataImportError(
            ShadowDataStatus.UNIT_UNKNOWN,
            f"{field} 的单位或转换未在版本化适配契约中定义。",
        )


def _parse_context_mappings(payload: Any) -> tuple[ContextMapping, ...]:
    if not isinstance(payload, list):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "context_mappings 必须是数组。"
        )
    result: list[ContextMapping] = []
    for item in payload:
        if not isinstance(item, Mapping) or set(item) != {
            "external_column",
            "canonical_field",
            "required",
        }:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "context mapping 字段无效。"
            )
        if item["canonical_field"] not in {"batch_id", "lot_id"}:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID,
                "context mapping 只能声明 batch_id 或 lot_id。",
            )
        if not isinstance(item["external_column"], str) or not item["external_column"]:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "context 外部列无效。"
            )
        if not isinstance(item["required"], bool):
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "context required 必须是布尔值。"
            )
        result.append(
            ContextMapping(
                external_column=item["external_column"],
                canonical_field=item["canonical_field"],
                required=item["required"],
            )
        )
    fields = [item.canonical_field for item in result]
    if set(fields) != {"batch_id", "lot_id"} or len(fields) != 2:
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "context_mappings 必须各声明一次 batch_id 与 lot_id。",
        )
    return tuple(sorted(result, key=lambda item: item.canonical_field))


def _parse_reviewed_mappings(payload: Any) -> tuple[ReviewedOutcomeMapping, ...]:
    if not isinstance(payload, list):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "reviewed_outcome_mappings 必须是数组。",
        )
    result: list[ReviewedOutcomeMapping] = []
    for item in payload:
        if not isinstance(item, Mapping) or set(item) != {
            "external_column",
            "canonical_field",
            "required",
        }:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "reviewed outcome mapping 字段无效。"
            )
        if item["canonical_field"] not in REVIEWED_OUTCOME_FIELDS:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "审核结果 canonical 字段无效。"
            )
        if not isinstance(item["external_column"], str) or not item["external_column"]:
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "审核结果外部列无效。"
            )
        if not isinstance(item["required"], bool):
            raise ShadowDataImportError(
                ShadowDataStatus.MAPPING_INVALID, "审核结果 required 必须是布尔值。"
            )
        result.append(
            ReviewedOutcomeMapping(
                external_column=item["external_column"],
                canonical_field=item["canonical_field"],
                required=item["required"],
            )
        )
    fields = [item.canonical_field for item in result]
    if fields and set(fields) != REVIEWED_OUTCOME_FIELDS:
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID,
            "reviewed_outcome_mappings 必须完全不提供或完整映射四个审核字段。",
        )
    if len(set(fields)) != len(fields):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "审核结果映射不得重复。"
        )
    return tuple(sorted(result, key=lambda item: item.canonical_field))


def _parse_ignored_columns(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list) or not all(
        isinstance(item, str) and item for item in payload
    ):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "ignored_columns 必须是列名数组。"
        )
    if len(set(payload)) != len(payload):
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, "ignored_columns 不得重复。"
        )
    return tuple(sorted(payload))


def _required_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise ShadowDataImportError(
            ShadowDataStatus.MAPPING_INVALID, f"{field} 必须是小写 SHA-256。"
        )
    return value


def _issue_counts(values: Mapping[str, int]) -> tuple[FieldIssueCount, ...]:
    return tuple(
        FieldIssueCount(field=field, count=count)
        for field, count in sorted(values.items())
    )


def _group_sort_key(
    key: tuple[str | None, str | None],
) -> tuple[str, str]:
    return key[0] or "", key[1] or ""


def _metric(numerator: int, denominator: int, evidence_kind: str) -> EvaluationMetric:
    ratio = None
    if denominator:
        ratio = format(
            (Decimal(numerator) / Decimal(denominator)).quantize(
                CANONICAL_PRECISION, rounding=ROUND_HALF_EVEN
            ),
            "f",
        )
    return EvaluationMetric(
        numerator=numerator,
        denominator=denominator,
        ratio=ratio,
        evidence_kind=evidence_kind,
    )
