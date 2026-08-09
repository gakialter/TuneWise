from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType

import pytest

from tunewise.importing import ObservableCanonicalizer
from tunewise.shadow_data import (
    SHADOW_STORAGE_PARTITION,
    ShadowDataAdapter,
    ShadowDataImportError,
    ShadowDataStatus,
    ShadowEvaluationStatus,
    ShadowSourceType,
)
from tunewise.shadow_analysis import ShadowAnalysisContract, ShadowAnalysisRunner


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "shadow-data"
CSV_PATH = FIXTURE_ROOT / "synthetic-contract-observations.csv"
MANIFEST_PATH = FIXTURE_ROOT / "synthetic-contract-mapping-v1.json"
ANALYSIS_CONTRACT_PATH = FIXTURE_ROOT / "synthetic-contract-analysis-v1.json"
REPOSITORY_ROOT = Path(__file__).parents[2]


def fixture_payload() -> tuple[bytes, dict]:
    return CSV_PATH.read_bytes(), json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def import_fixture():
    csv_bytes, manifest = fixture_payload()
    return ShadowDataAdapter().import_csv(csv_bytes, manifest)


def analysis_contract_payload(csv_bytes: bytes | None = None) -> dict:
    payload = json.loads(ANALYSIS_CONTRACT_PATH.read_text(encoding="utf-8"))
    if csv_bytes is not None:
        payload["raw_file_sha256"] = hashlib.sha256(csv_bytes).hexdigest()
    return payload


def run_analysis(dataset, contract_payload: dict | None = None):
    contract = ShadowAnalysisContract.from_payload(
        contract_payload or analysis_contract_payload()
    )
    return ShadowAnalysisRunner(
        diagnostic_asset_root=(
            REPOSITORY_ROOT / "assets" / "diagnostic" / "tw-diagnostic-v1"
        ),
        planning_asset_root=(
            REPOSITORY_ROOT
            / "assets"
            / "planning"
            / "tw-parameter-planning-v1"
        ),
    ).run(dataset, contract)


def rewrite_csv(csv_bytes: bytes, mutate) -> bytes:
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"), newline="")))
    mutate(rows)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def trust_raw_hash(manifest: dict, csv_bytes: bytes) -> None:
    manifest["expected_raw_file_sha256"] = hashlib.sha256(csv_bytes).hexdigest()


def test_contract_fixture_import_is_explicitly_synthetic_and_versioned():
    dataset = import_fixture()

    assert dataset.source_type is ShadowSourceType.CONTRACT_FIXTURE
    assert dict(dataset.source_metadata)["data_reality"] == "SYNTHETIC_CONTRACT_FIXTURE"
    assert "not real device or production data" in dict(dataset.source_metadata)[
        "provenance_statement"
    ]
    assert dataset.mapping_version == "tw-shadow-contract-fixture-mapping-v1"
    assert dataset.quality_report.mapping_version == dataset.mapping_version
    assert dataset.quality_report.sample_count == 8
    assert dataset.quality_report.schema_mapping_complete is True
    assert dataset.quality_report.required_fields_present is True
    assert dataset.quality_report.units_explicit is True
    assert dataset.quality_report.analysis_contract_bound is False
    assert dataset.quality_report.diagnostic_runnable is False
    assert dataset.quality_report.safety_recommendation_runnable is False
    assert dataset.measurements[0]["mtf_center"] == "0.800000"
    assert dataset.measurements[0]["pitch"] == "0.250000"
    assert isinstance(dataset.measurements[0], MappingProxyType)


def test_missing_required_canonical_mapping_is_rejected():
    csv_bytes, manifest = fixture_payload()
    manifest["column_mappings"] = [
        mapping
        for mapping in manifest["column_mappings"]
        if mapping["canonical_field"] != "mtf_rb"
    ]

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "一一覆盖" in caught.value.message


def test_unknown_unit_is_rejected_instead_of_guessed():
    csv_bytes, manifest = fixture_payload()
    pitch = next(
        mapping
        for mapping in manifest["column_mappings"]
        if mapping["canonical_field"] == "pitch"
    )
    pitch["source_unit"] = "DEGREE"

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert caught.value.code == "UNIT_UNKNOWN"
    assert "未在版本化适配契约中定义" in caught.value.message


def test_unmapped_external_column_is_rejected():
    csv_bytes, manifest = fixture_payload()
    changed = rewrite_csv(
        csv_bytes,
        lambda rows: (
            rows[0].append("mystery_device_signal"),
            [row.append("42") for row in rows[1:]],
        ),
    )
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "未显式映射" in caught.value.message


def test_invalid_numeric_value_is_rejected_with_quality_evidence():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("pitch_normalized")
        rows[3][column] = "not-a-number"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "FEATURE_UNAVAILABLE"
    report = caught.value.quality_report
    assert report is not None
    assert report.numeric_types_valid is False
    assert report.invalid_numeric_values[0].field == "pitch"
    assert report.diagnostic_runnable is False
    assert report.safety_recommendation_runnable is False


def test_non_finite_value_is_rejected_without_silent_fill():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("mtf_center_percent")
        rows[2][column] = "NaN"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert report is not None
    assert report.non_finite_values[0].field == "mtf_center"


def test_missing_required_value_is_reported_and_rejected_without_fill():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("mtf_rb_percent")
        rows[2][column] = ""

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert report is not None
    assert report.required_fields_present is False
    assert report.missing_values[0].field == "mtf_rb"


def test_out_of_range_value_is_reported_and_rejected():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("mtf_center_percent")
        rows[2][column] = "150"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert report is not None
    assert report.range_violations[0].field == "mtf_center"
    assert report.range_violations[0].constraint == "0 <= value <= 1"


def test_duplicate_sample_is_reported_and_rejected_before_canonical_import():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("sample_no")
        rows[4][column] = rows[3][column]

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert report is not None
    assert report.duplicate_record_count == 1
    assert report.features_computable is False


def test_discontinuous_sample_index_is_rejected_before_detection():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("sample_no")
        rows[-1][column] = "8"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert report is not None
    assert report.sample_indexes_contiguous is False
    assert report.diagnostic_runnable is False


def test_out_of_order_timestamp_is_reported_and_rejected():
    csv_bytes, manifest = fixture_payload()

    def mutate(rows):
        column = rows[0].index("event_time")
        rows[5][column] = "2026-07-17T23:59:59Z"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    report = caught.value.quality_report
    assert report is not None
    assert report.timestamps_in_order is False
    assert report.diagnostic_runnable is False


def test_too_few_samples_imports_as_insufficient_data_not_as_valid_evaluation():
    csv_bytes, manifest = fixture_payload()
    canonical_full = import_fixture().canonical_csv_bytes
    shortened = rewrite_csv(csv_bytes, lambda rows: rows.pop())
    canonical_shortened = rewrite_csv(canonical_full, lambda rows: rows.pop())
    trust_raw_hash(manifest, shortened)
    manifest["expected_canonical_observation_sha256"] = (
        ObservableCanonicalizer().canonicalize_csv(canonical_shortened).sha256
    )

    dataset = ShadowDataAdapter().import_csv(shortened, manifest)

    assert dataset.quality_report.status is ShadowDataStatus.INSUFFICIENT_DATA
    assert dataset.quality_report.sample_count == 7
    assert dataset.quality_report.spc_minimum_sample_met is False
    assert dataset.quality_report.features_computable is True
    assert dataset.quality_report.diagnostic_runnable is False
    assert dataset.quality_report.safety_recommendation_runnable is False


def test_zero_samples_are_structurally_rejected_as_insufficient_data():
    csv_bytes, manifest = fixture_payload()
    empty = rewrite_csv(csv_bytes, lambda rows: rows.__delitem__(slice(1, None)))
    trust_raw_hash(manifest, empty)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(empty, manifest)

    report = caught.value.quality_report
    assert caught.value.code == "INSUFFICIENT_DATA"
    assert report is not None
    assert report.status is ShadowDataStatus.INSUFFICIENT_DATA
    assert report.sample_count == 0


def test_declared_real_source_without_labels_is_not_evaluable_or_verified():
    csv_bytes, manifest = fixture_payload()
    manifest["source_type"] = "REAL_DEVICE_SHADOW_DECLARED"
    manifest["source_metadata"].update(
        {
            "provenance_statement": "Operator declares this input as an authorized real-device shadow export; TuneWise has not verified that claim.",
            "device_model_declared": "OPERATOR_DECLARED_MODEL_X",
            "authorization_reference": "OPERATOR_DECLARED_AUTHORIZATION_REF",
            "data_reality": "OPERATOR_DECLARED_REAL_DEVICE_SHADOW_NOT_VERIFIED",
        }
    )

    dataset = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    analysis = run_analysis(dataset)

    assert dataset.source_type is ShadowSourceType.REAL_DEVICE_SHADOW_DECLARED
    assert dataset.source_authenticity_status == "OPERATOR_DECLARED_NOT_VERIFIED"
    assert dataset.quality_report.status is ShadowDataStatus.NOT_EVALUABLE
    assert dataset.quality_report.diagnostic_runnable is False
    assert analysis.quality_report.diagnostic_runnable is True
    assert analysis.quality_report.safety_recommendation_runnable is True
    assert analysis.evaluation.status is ShadowEvaluationStatus.NOT_EVALUABLE
    assert analysis.evaluation.top1_reviewed_label_consistency is None
    assert "不得计算一致率" in analysis.evaluation.message


def test_source_declaration_must_match_reality_marker():
    csv_bytes, manifest = fixture_payload()
    manifest["source_type"] = "REAL_DEVICE_SHADOW_DECLARED"

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "data_reality" in caught.value.message


def test_shadow_import_is_read_only_isolated_and_cannot_retrain_or_approve_cases():
    protected_paths = (
        Path("assets/demo/tw-aa-demo-v1/dataset-manifest.json"),
        Path("assets/diagnostic/tw-diagnostic-v1/model.json"),
        Path("assets/cases/tw-approved-case-index-v1/approved-cases.json"),
    )
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected_paths
    }

    dataset = import_fixture()

    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected_paths
    }
    assert before == after
    assert dataset.storage_partition == SHADOW_STORAGE_PARTITION
    assert dataset.eligible_for_training is False
    assert dataset.eligible_for_approved_case_library is False
    assert dataset.automatic_retraining_allowed is False
    assert dataset.fixed_demo_asset_mutation_allowed is False


def test_raw_and_canonical_hashes_are_recomputable_with_existing_canonicalizer():
    csv_bytes, manifest = fixture_payload()
    dataset = ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert dataset.raw_file_sha256 == hashlib.sha256(csv_bytes).hexdigest()
    assert dataset.raw_file_sha256 == manifest["expected_raw_file_sha256"]
    assert dataset.canonical_observation_sha256 == (
        ObservableCanonicalizer()
        .canonicalize_csv(dataset.canonical_csv_bytes)
        .sha256
    )
    assert (
        dataset.canonical_observation_sha256
        == manifest["expected_canonical_observation_sha256"]
    )


def test_raw_file_tampering_is_rejected_by_manifest_hash():
    csv_bytes, manifest = fixture_payload()
    changed = csv_bytes.replace(b"80.000000", b"81.000000", 1)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "原始影子 CSV 哈希" in caught.value.message


def test_canonical_hash_mismatch_is_rejected_after_mapping():
    csv_bytes, manifest = fixture_payload()
    manifest["expected_canonical_observation_sha256"] = "f" * 64

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "规范化影子观测哈希" in caught.value.message


def reviewed_fixture() -> tuple[bytes, dict]:
    csv_bytes, manifest = fixture_payload()

    def add_reviewed_columns(rows):
        rows[0].extend(
            [
                "expert_review_status",
                "expert_anomaly",
                "expert_root_cause",
                "expert_parameter_direction",
            ]
        )
        for row in rows[1:]:
            row.extend(["REVIEWED", "TARGET_ANOMALY", "PLANE_TILT", "DECREASE"])

    reviewed_csv = rewrite_csv(csv_bytes, add_reviewed_columns)
    manifest["reviewed_outcome_mappings"] = [
        {
            "external_column": "expert_review_status",
            "canonical_field": "reviewed_status",
            "required": True,
        },
        {
            "external_column": "expert_anomaly",
            "canonical_field": "reviewed_anomaly",
            "required": True,
        },
        {
            "external_column": "expert_root_cause",
            "canonical_field": "reviewed_root_cause",
            "required": True,
        },
        {
            "external_column": "expert_parameter_direction",
            "canonical_field": "reviewed_parameter_direction",
            "required": True,
        },
    ]
    manifest["review_contract"] = {
        "contract_version": "tw-shadow-review-contract-v1",
        "reviewer_id": "synthetic-reviewer-001",
        "reviewer_role": "SYNTHETIC_FIXTURE_REVIEWER",
        "reviewed_at": "2026-08-04T12:00:00+00:00",
        "review_protocol_version": "synthetic-review-protocol-v1",
        "label_source": "REVIEWED_DECLARED",
        "dataset_batch_reference": "synthetic-contract-batch-001",
        "reviewed_outcome_version": "synthetic-reviewed-outcome-v1",
        "provenance_declaration": "SYNTHETIC contract fixture; not externally verified.",
    }
    trust_raw_hash(manifest, reviewed_csv)
    return reviewed_csv, manifest


def test_reviewed_outcomes_enable_only_offline_consistency_metrics():
    csv_bytes, manifest = reviewed_fixture()
    dataset = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    analysis = run_analysis(
        dataset,
        analysis_contract_payload(csv_bytes),
    )
    report = analysis.evaluation

    assert dataset.quality_report.status is ShadowDataStatus.READY
    assert dataset.quality_report.reviewed_labels_available is True
    assert report.status is ShadowEvaluationStatus.EVALUATED_DECLARED_REVIEW
    assert report.detection_coverage.ratio == "1.000000"
    assert report.top1_reviewed_label_consistency.ratio == "1.000000"
    assert report.top3_reviewed_label_consistency.ratio == "1.000000"
    assert report.safety_candidate_pass_rate.evidence_kind == "RULE_CHECK_OUTPUT"
    assert report.parameter_direction_reviewed_consistency.ratio == "1.000000"
    assert "REAL_YIELD_IMPROVEMENT" in report.excluded_claims
    assert "CAUSAL_PARAMETER_EFFECT" in report.excluded_claims
    serialized = asdict(report)
    assert "yield_improvement" not in serialized
    assert "tuning_time_reduction" not in serialized


def test_partial_reviewed_mapping_is_rejected_instead_of_silently_ignored():
    csv_bytes, manifest = fixture_payload()
    manifest["reviewed_outcome_mappings"] = [
        {
            "external_column": "expert_review_status",
            "canonical_field": "reviewed_status",
            "required": False,
        }
    ]

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert caught.value.code == "MAPPING_INVALID"
    assert "完整映射四个审核字段" in caught.value.message


@pytest.mark.parametrize("status", ["", "UNKNOWN", "APPROVED"])
def test_invalid_or_missing_reviewed_status_is_rejected(status: str):
    csv_bytes, manifest = reviewed_fixture()

    def mutate(rows):
        column = rows[0].index("expert_review_status")
        rows[1][column] = status

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "FEATURE_UNAVAILABLE"


def test_canonical_measurements_are_immutable_after_hashing():
    dataset = import_fixture()

    with pytest.raises(TypeError):
        dataset.measurements[0]["pitch"] = "0.999999"

    assert dataset.measurements[0]["pitch"] == "0.250000"
    assert (
        dataset.canonical_observation_sha256
        == "aca64480cbef2a9da8f919d5a70df5d0718c5dbb6d8a8d496ff66af386c44c2f"
    )


def test_invalid_reviewed_root_cause_is_rejected_not_inferred():
    csv_bytes, manifest = reviewed_fixture()

    def mutate(rows):
        column = rows[0].index("expert_root_cause")
        for row in rows[1:]:
            row[column] = "OPERATOR_FREE_TEXT_CAUSE"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)

    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert "冻结诊断标签集" in caught.value.message


@pytest.mark.parametrize(
    ("column", "replacement"),
    [
        ("expert_anomaly", "NORMAL"),
        ("expert_root_cause", "REFERENCE_DRIFT"),
        ("expert_parameter_direction", "INCREASE"),
    ],
)
def test_reviewed_outcome_tampering_changes_bound_hashes(column: str, replacement: str):
    csv_bytes, manifest = reviewed_fixture()
    original = ShadowDataAdapter().import_csv(csv_bytes, manifest)

    def mutate(rows):
        index = rows[0].index(column)
        for row in rows[1:]:
            row[index] = replacement
        if column == "expert_anomaly" and replacement == "NORMAL":
            root = rows[0].index("expert_root_cause")
            direction = rows[0].index("expert_parameter_direction")
            for row in rows[1:]:
                row[root] = "NOT_APPLICABLE"
                row[direction] = "NOT_APPLICABLE"

    changed_csv = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed_csv)
    changed = ShadowDataAdapter().import_csv(changed_csv, manifest)

    assert changed.canonical_observation_sha256 == original.canonical_observation_sha256
    assert changed.reviewed_outcome_hash != original.reviewed_outcome_hash
    assert changed.evidence_bundle_hash != original.evidence_bundle_hash


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("reviewer_id", "synthetic-reviewer-002"),
        ("reviewed_at", "2026-08-04T12:00:01+00:00"),
        ("review_protocol_version", "synthetic-review-protocol-v2"),
    ],
)
def test_reviewer_contract_tampering_changes_provenance_and_bundle_hash(
    field: str,
    replacement: str,
):
    csv_bytes, manifest = reviewed_fixture()
    original = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    manifest["review_contract"][field] = replacement

    changed = ShadowDataAdapter().import_csv(csv_bytes, manifest)

    assert changed.provenance_hash != original.provenance_hash
    assert changed.evidence_bundle_hash != original.evidence_bundle_hash


def test_source_metadata_and_context_tampering_change_their_bound_hashes():
    csv_bytes, manifest = reviewed_fixture()
    original = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    changed_manifest = json.loads(json.dumps(manifest))
    changed_manifest["source_metadata"]["declared_by"] = "synthetic-declarer-002"
    changed_source = ShadowDataAdapter().import_csv(csv_bytes, changed_manifest)
    assert changed_source.provenance_hash != original.provenance_hash
    assert changed_source.evidence_bundle_hash != original.evidence_bundle_hash

    def mutate_context(rows):
        column = rows[0].index("batch_code")
        for row in rows[1:]:
            row[column] = "synthetic-batch-tampered"

    changed_csv = rewrite_csv(csv_bytes, mutate_context)
    trust_raw_hash(manifest, changed_csv)
    changed_context = ShadowDataAdapter().import_csv(changed_csv, manifest)
    assert changed_context.context_hash != original.context_hash
    assert changed_context.evidence_bundle_hash != original.evidence_bundle_hash


def test_reviewed_labels_without_valid_review_contract_remain_not_evaluable():
    csv_bytes, manifest = reviewed_fixture()
    manifest.pop("review_contract")
    missing = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    assert missing.quality_report.status is ShadowDataStatus.NOT_EVALUABLE
    assert missing.quality_report.reviewed_labels_available is False

    manifest["review_contract"] = {"reviewer_id": "incomplete"}
    invalid = ShadowDataAdapter().import_csv(csv_bytes, manifest)
    assert invalid.quality_report.status is ShadowDataStatus.NOT_EVALUABLE
    assert invalid.quality_report.reviewed_labels_available is False


def test_normal_review_cannot_claim_tuning_root_cause_or_direction():
    csv_bytes, manifest = reviewed_fixture()

    def mutate(rows):
        anomaly = rows[0].index("expert_anomaly")
        for row in rows[1:]:
            row[anomaly] = "NORMAL"

    changed = rewrite_csv(csv_bytes, mutate)
    trust_raw_hash(manifest, changed)
    with pytest.raises(ShadowDataImportError) as caught:
        ShadowDataAdapter().import_csv(changed, manifest)

    assert caught.value.code == "FEATURE_UNAVAILABLE"
    assert "不得同时声明" in caught.value.message
