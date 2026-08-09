from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from tunewise.shadow_analysis import (
    SHADOW_ANALYSIS_DISCLAIMER,
    SHADOW_CASE_LIBRARY_MODE,
    ShadowAnalysisContract,
    ShadowAnalysisError,
    ShadowAnalysisRunner,
    shadow_analysis_result_hash,
)
from tunewise.diagnosis import DiagnosticGuardError, RootCauseDiagnoser
from tunewise.importing import ObservableCanonicalizer
from tunewise.shadow_data import (
    ShadowDataAdapter,
    ShadowDataStatus,
    ShadowEvaluationStatus,
)


REPOSITORY_ROOT = Path(__file__).parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "shadow-data"
CSV_PATH = FIXTURE_ROOT / "synthetic-contract-observations.csv"
MAPPING_PATH = FIXTURE_ROOT / "synthetic-contract-mapping-v1.json"
CONTRACT_PATH = FIXTURE_ROOT / "synthetic-contract-analysis-v1.json"
DIAGNOSTIC_ROOT = REPOSITORY_ROOT / "assets" / "diagnostic" / "tw-diagnostic-v1"
PLANNING_ROOT = (
    REPOSITORY_ROOT / "assets" / "planning" / "tw-parameter-planning-v1"
)


def imported_dataset():
    return ShadowDataAdapter().import_csv(
        CSV_PATH.read_bytes(),
        json.loads(MAPPING_PATH.read_text(encoding="utf-8")),
    )


def contract_payload() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def runner() -> ShadowAnalysisRunner:
    return ShadowAnalysisRunner(
        diagnostic_asset_root=DIAGNOSTIC_ROOT,
        planning_asset_root=PLANNING_ROOT,
    )


def rewrite_csv(csv_bytes: bytes, mutate) -> bytes:
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"), newline="")))
    mutate(rows)
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue().encode("utf-8")


def imported_changed_dataset(
    external_csv: bytes,
    canonical_csv: bytes,
    mapping_payload: dict,
):
    mapping_payload["expected_raw_file_sha256"] = hashlib.sha256(
        external_csv
    ).hexdigest()
    canonical_hash = ObservableCanonicalizer().canonicalize_csv(
        canonical_csv
    ).sha256
    mapping_payload["expected_canonical_observation_sha256"] = canonical_hash
    dataset = ShadowDataAdapter().import_csv(external_csv, mapping_payload)
    analysis_payload = contract_payload()
    analysis_payload["raw_file_sha256"] = mapping_payload[
        "expected_raw_file_sha256"
    ]
    analysis_payload["canonical_observation_sha256"] = canonical_hash
    return dataset, ShadowAnalysisContract.from_payload(analysis_payload)


def run_fixture():
    return runner().run(
        imported_dataset(),
        ShadowAnalysisContract.from_payload(contract_payload()),
    )


def test_runner_executes_real_detection_diagnosis_and_safety_chain():
    result = run_fixture()

    assert result.qualification.eligible is True
    assert result.quality_report.analysis_contract_bound is True
    assert result.quality_report.diagnostic_runnable is True
    assert result.quality_report.safety_recommendation_runnable is True
    assert result.case_library_mode == SHADOW_CASE_LIBRARY_MODE
    assert result.storage_partition == "SHADOW_READ_ONLY"
    assert result.eligible_for_training is False
    assert result.eligible_for_approved_case_library is False
    assert result.automatic_retraining_allowed is False
    assert result.fixed_demo_asset_mutation_allowed is False
    assert result.evaluation.status is ShadowEvaluationStatus.NOT_EVALUABLE
    group = result.group_results[0]
    assert group.detection_status == "EVALUATED"
    assert group.predicted_anomaly == "TARGET_ANOMALY"
    assert group.ranked_root_causes == (
        "PLANE_TILT",
        "REFERENCE_DRIFT",
        "XY_DECENTER",
    )
    assert group.safety_candidate_status == "PASSED"
    assert group.predicted_parameter_direction == "DECREASE"
    assert [candidate.generation_type for candidate in group.safety_candidates] == [
        "CONSERVATIVE",
        "STANDARD",
    ]
    assert group.safety_candidates[0].delta_ticks == (("pitch", -1),)
    assert group.safety_candidates[0].proposed_values == (("pitch", "0.200000"),)
    assert group.safety_candidates[1].delta_ticks == (("pitch", -2),)
    assert result.disclaimer == SHADOW_ANALYSIS_DISCLAIMER


def test_runner_output_and_hash_are_deterministic_and_recomputable():
    first = run_fixture()
    second = run_fixture()

    assert first == second
    assert first.analysis_result_hash == shadow_analysis_result_hash(first)
    assert first.analysis_result_id == (
        f"tw-shadow-analysis-{first.analysis_result_hash[:16]}"
    )

    tampered = replace(first, disclaimer="tampered")
    assert shadow_analysis_result_hash(tampered) != first.analysis_result_hash


def test_shadow_evidence_bundle_binds_context_and_rebuilds_quality_report():
    dataset = imported_dataset()
    assert len(dataset.evidence_bundle_hash) == 64
    assert len(dataset.context_hash) == 64
    assert len(dataset.reviewed_outcome_hash) == 64
    assert len(dataset.provenance_hash) == 64

    context = dataset.observation_contexts[0]
    tampered_contexts = (
        replace(context, batch_id="tampered-batch"),
        *dataset.observation_contexts[1:],
    )
    stale_report = replace(
        dataset.quality_report,
        reviewed_labels_available=True,
        reviewed_group_count=999,
    )
    tampered = replace(
        dataset,
        observation_contexts=tampered_contexts,
        quality_report=stale_report,
    )

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(tampered, ShadowAnalysisContract.from_payload(contract_payload()))

    assert caught.value.code == "ANALYSIS_EVIDENCE_BUNDLE_MISMATCH"


def test_contract_must_bind_current_raw_and_canonical_data_hashes():
    payload = contract_payload()
    payload["raw_file_sha256"] = "f" * 64
    contract = ShadowAnalysisContract.from_payload(payload)

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(imported_dataset(), contract)

    assert caught.value.code == "ANALYSIS_CONTRACT_DATA_MISMATCH"


def test_runner_recomputes_hash_from_actual_measurements():
    dataset = imported_dataset()
    changed_measurements = tuple(
        MappingProxyType(
            {
                **dict(measurement),
                "pitch": "0.200000",
            }
        )
        for measurement in dataset.measurements
    )
    tampered = replace(dataset, measurements=changed_measurements)

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(
            tampered,
            ShadowAnalysisContract.from_payload(contract_payload()),
        )

    assert caught.value.code == "ANALYSIS_EVIDENCE_BUNDLE_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage_partition", "TRAIN"),
        ("eligible_for_training", True),
        ("eligible_for_approved_case_library", True),
        ("automatic_retraining_allowed", True),
        ("fixed_demo_asset_mutation_allowed", True),
    ],
)
def test_runner_rechecks_all_shadow_isolation_flags(field: str, value):
    dataset = replace(imported_dataset(), **{field: value})

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(
            dataset,
            ShadowAnalysisContract.from_payload(contract_payload()),
        )

    assert caught.value.code == "ANALYSIS_ISOLATION_VIOLATION"


def test_safety_runnable_is_false_when_group_parameter_state_is_inconsistent():
    source = CSV_PATH.read_bytes()
    canonical = imported_dataset().canonical_csv_bytes

    def change_external(rows):
        rows[2][rows[0].index("pitch_normalized")] = "0.200000"

    def change_canonical(rows):
        rows[2][rows[0].index("pitch")] = "0.200000"

    changed_source = rewrite_csv(source, change_external)
    changed_canonical = rewrite_csv(canonical, change_canonical)
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    dataset, contract = imported_changed_dataset(
        changed_source,
        changed_canonical,
        mapping,
    )

    result = runner().run(dataset, contract)

    assert result.qualification.diagnostic_runnable is True
    assert result.qualification.safety_recommendation_runnable is False
    assert result.quality_report.safety_recommendation_runnable is False
    assert result.group_results[0].safety_candidate_status == "REJECTED"
    assert result.group_results[0].refusal_code == (
        "CURRENT_PARAMETER_STATE_INCONSISTENT"
    )


def test_insufficient_reviewed_group_produces_rejection_rate_without_diagnosis():
    source = CSV_PATH.read_bytes()
    canonical = imported_dataset().canonical_csv_bytes

    def add_reviews_and_shorten(rows):
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
        rows.pop()

    shortened_source = rewrite_csv(source, add_reviews_and_shorten)
    shortened_canonical = rewrite_csv(canonical, lambda rows: rows.pop())
    mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    mapping["reviewed_outcome_mappings"] = [
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
    mapping["review_contract"] = {
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
    dataset, contract = imported_changed_dataset(
        shortened_source,
        shortened_canonical,
        mapping,
    )

    result = runner().run(dataset, contract)

    assert dataset.quality_report.status is ShadowDataStatus.INSUFFICIENT_DATA
    assert result.qualification.diagnostic_runnable is False
    assert result.qualification.insufficient_group_count == 1
    assert result.group_results[0].detection_status == "INSUFFICIENT_DATA"
    assert result.group_results[0].diagnostic_status == "NOT_RUN"
    assert result.evaluation.status is ShadowEvaluationStatus.EVALUATED_DECLARED_REVIEW
    assert result.evaluation.insufficient_data_rejection_rate.ratio == "1.000000"


def test_diagnostic_guard_is_converted_to_structured_group_refusal(monkeypatch):
    def reject_diagnosis(*_args, **_kwargs):
        raise DiagnosticGuardError(
            "TEST_DIAGNOSTIC_GUARD",
            "structured diagnostic refusal",
        )

    monkeypatch.setattr(RootCauseDiagnoser, "diagnose", reject_diagnosis)

    result = run_fixture()

    assert result.group_results[0].diagnostic_status == "REJECTED"
    assert result.group_results[0].refusal_code == "TEST_DIAGNOSTIC_GUARD"
    assert result.group_results[0].safety_candidate_status == "NOT_RUN"


def test_control_limits_cannot_change_under_an_existing_rule_version():
    payload = contract_payload()
    payload["control_limits"]["corner_lower_limit"] = "0.610000"
    contract = ShadowAnalysisContract.from_payload(payload)

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(imported_dataset(), contract)

    assert caught.value.code == "ANALYSIS_ASSET_VERSION_MISMATCH"


def test_diagnostic_asset_manifest_hash_is_enforced():
    payload = contract_payload()
    payload["diagnostic_asset_manifest_sha256"] = "f" * 64
    contract = ShadowAnalysisContract.from_payload(payload)

    with pytest.raises(ShadowAnalysisError) as caught:
        runner().run(imported_dataset(), contract)

    assert caught.value.code == "ANALYSIS_ASSET_VALIDATION_FAILED"


def test_parameter_constraint_snapshot_hash_is_enforced():
    payload = contract_payload()
    payload["parameter_constraints"]["constraints"]["pitch"]["maximum"] = (
        "0.950000"
    )

    with pytest.raises(ShadowAnalysisError) as caught:
        ShadowAnalysisContract.from_payload(payload)

    assert caught.value.code == "ANALYSIS_CONTRACT_INVALID"
    assert "参数约束快照哈希" in caught.value.message


def test_runner_does_not_mutate_training_case_or_demo_assets():
    protected_paths = (
        REPOSITORY_ROOT / "assets" / "demo" / "tw-aa-demo-v1" / "aa-demo-batch.csv",
        REPOSITORY_ROOT / "assets" / "diagnostic" / "tw-diagnostic-v1" / "model.json",
        REPOSITORY_ROOT
        / "assets"
        / "cases"
        / "tw-approved-case-index-v1"
        / "approved-cases.json",
    )
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected_paths
    }

    result = run_fixture()

    after = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected_paths
    }
    assert result.case_library_mode == "DISABLED_SHADOW_ISOLATION"
    assert before == after


def test_cli_runs_bound_shadow_analysis_without_exposing_observations():
    completed = _run_cli(
        "--csv",
        str(CSV_PATH),
        "--manifest",
        str(MAPPING_PATH),
        "--analysis-contract",
        str(CONTRACT_PATH),
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["status"] == "NOT_EVALUABLE"
    assert payload["quality_report"]["analysis_contract_bound"] is True
    assert payload["analysis_result"]["group_results"][0]["predicted_anomaly"] == (
        "TARGET_ANOMALY"
    )
    assert "measurements" not in payload["analysis_result"]


@pytest.mark.parametrize("failure_kind", ["missing_csv", "invalid_manifest_json"])
def test_cli_file_and_json_failures_are_structured_without_traceback(
    tmp_path: Path,
    failure_kind: str,
):
    invalid_manifest = tmp_path / "invalid-manifest.json"
    invalid_manifest.write_text("{not-json", encoding="utf-8")
    csv_path = CSV_PATH if failure_kind != "missing_csv" else tmp_path / "missing.csv"
    manifest_path = (
        invalid_manifest
        if failure_kind == "invalid_manifest_json"
        else MAPPING_PATH
    )

    completed = _run_cli(
        "--csv",
        str(csv_path),
        "--manifest",
        str(manifest_path),
    )

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "MAPPING_INVALID"
    assert payload["quality_report"] is None


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "tools.validate_shadow_data", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
