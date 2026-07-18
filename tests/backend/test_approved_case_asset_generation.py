from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from tools.generate_approved_case_index import (
    _build_case,
    _sha256,
    _source_content_payload,
    build_approved_index,
    fit_retrieval_scaler,
    generate,
)
from tunewise.diagnostic_contract import CLASS_ORDER, FEATURE_NAMES


def file_hashes(root):
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def test_fixed_training_source_generates_deterministic_approved_case_bundle(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"

    first_manifest = generate(first_root, seed=20260718)
    second_manifest = generate(second_root, seed=20260718)

    assert file_hashes(first_root) == file_hashes(second_root)
    assert first_manifest == second_manifest

    approved_cases = json.loads(
        (first_root / "approved-cases.json").read_text(encoding="utf-8")
    )["cases"]
    assert len(approved_cases) == 60
    assert {case["status"] for case in approved_cases} == {"APPROVED"}
    assert {case["source_partition"] for case in approved_cases} == {"TRAIN"}
    assert {case["station_type"] for case in approved_cases} == {"AA"}
    assert {case["product_model"] for case in approved_cases} == {
        "TW-AA-PROTOTYPE-V1"
    }
    assert {case["reviewed_root_cause"] for case in approved_cases} == {
        "PLANE_TILT",
        "XY_DECENTER",
        "PLATFORM_INSTABILITY",
        "REFERENCE_DRIFT",
        "Z_DEFOCUS_CONDITIONAL",
    }
    assert len({case["case_id"] for case in approved_cases}) == 60
    assert len({case["case_content_hash"] for case in approved_cases}) == 60
    required_case_fields = {
        "case_id",
        "status",
        "source_batch_id",
        "source_partition",
        "source_partition_id",
        "station_type",
        "product_model",
        "reviewed_root_cause",
        "parameter_family",
        "inspection_action",
        "observable_feature_vector",
        "historical_action",
        "historical_simulated_result",
        "applicability_conditions",
        "source_dataset_version",
        "feature_definition_version",
        "rule_set_version",
        "retrieval_rule_version",
        "case_schema_version",
        "source_content_hash",
        "case_content_hash",
        "review_metadata",
    }
    assert all(set(case) == required_case_fields for case in approved_cases)
    assert all(
        tuple(case["observable_feature_vector"]["feature_names"]) == FEATURE_NAMES
        and len(case["observable_feature_vector"]["values"]) == len(FEATURE_NAMES)
        for case in approved_cases
    )
    serialized_cases = json.dumps(approved_cases).lower()
    for forbidden in (
        "faulttruth",
        "fault_truth",
        "scenario_ref",
        "simulator_coefficient",
        "hidden_scenario",
    ):
        assert forbidden not in serialized_cases

    index = json.loads((first_root / "index.json").read_text(encoding="utf-8"))
    assert index["ordered_case_ids"] == sorted(index["ordered_case_ids"])
    assert len(index["ordered_case_ids"]) == 60
    assert index["approved_only"] is True
    assert index["ordered_case_ids"] == [
        case["case_id"] for case in sorted(approved_cases, key=lambda item: item["case_id"])
    ]

    scaler = json.loads((first_root / "scaler.json").read_text(encoding="utf-8"))
    assert scaler["artifact_type"] == "StandardScaler"
    assert scaler["scaler_version"] == "tw-case-retrieval-scaler-v1"
    assert scaler["feature_names"] == list(FEATURE_NAMES)
    assert len(scaler["mean"]) == len(scaler["scale"]) == 50
    assert scaler["fit_case_count"] == 60
    assert scaler["fit_status"] == "APPROVED"
    assert scaler["fit_source_partition"] == "TRAIN"
    assert scaler["zero_variance_policy"] == "SCALE_TO_ONE"

    compatibility = json.loads(
        (first_root / "compatibility-rules.json").read_text(encoding="utf-8")
    )
    assert compatibility["read_only"] is True
    assert compatibility["compatible_products"] == {
        "TW-AA-PROTOTYPE-V1": ["TW-AA-PROTOTYPE-V1"]
    }
    assert first_manifest["source_partition"] == "diagnostic-dev-train-v1"
    assert first_manifest["case_count"] == 60
    assert first_manifest["root_cause_distribution"] == {
        root_cause: 12 for root_cause in CLASS_ORDER
    }
    assert set(first_manifest["files"]) == {
        "approved-cases.json",
        "compatibility-rules.json",
        "index.json",
        "scaler.json",
    }
    assert first_manifest["distance_feature_names"] == list(FEATURE_NAMES)
    assert {
        "FaultTruth",
        "reviewed_root_cause",
        "historical_action",
        "historical_simulated_result",
        "case_id",
        "batch_id",
        "task_id",
        "source_partition",
        "scenario_ref",
        "adjusted_result",
    }.issubset(first_manifest["distance_excluded_fields"])
    assert first_manifest["excluded_partitions"] == [
        "VALIDATION",
        "TEST",
        "BLIND_TEST",
        "DEMO",
        "PENDING_REVIEW",
        "RUNTIME_SUBMISSION",
    ]


def test_checked_in_case_assets_and_windows_command_match_the_generator(tmp_path):
    generated = tmp_path / "generated"
    generate(generated, seed=20260718)
    repository_root = Path(__file__).parents[2]
    checked_in = repository_root / "assets" / "cases" / "tw-approved-case-index-v1"

    assert file_hashes(generated) == file_hashes(checked_in)
    command = (repository_root / "generate-approved-case-index.cmd").read_text(
        encoding="utf-8"
    )
    assert "tools.generate_approved_case_index" in command
    assert "assets\\cases\\tw-approved-case-index-v1" in command
    assert "--seed 20260718" in command


def test_index_and_scaler_reject_pending_non_train_and_incompatible_sources(tmp_path):
    root = tmp_path / "source"
    generate(root, seed=20260718)
    approved = json.loads(
        (root / "approved-cases.json").read_text(encoding="utf-8")
    )["cases"]
    baseline_scaler = fit_retrieval_scaler(approved)

    pollutants = []
    for suffix, field, value in (
        ("pending", "status", "PENDING_REVIEW"),
        ("validation", "source_partition", "VALIDATION"),
        ("test", "source_partition", "TEST"),
        ("blind", "source_partition", "BLIND_TEST"),
        ("demo", "source_partition", "DEMO"),
        ("runtime", "source_partition", "RUNTIME_SUBMISSION"),
        ("station", "station_type", "OTHER"),
        ("product", "product_model", "OTHER-PRODUCT"),
        ("schema", "case_schema_version", "future-schema"),
        ("dataset-version", "source_dataset_version", "future-dataset"),
        ("rule-version", "rule_set_version", "future-rules"),
        ("source-hash", "source_content_hash", "0" * 64),
        ("case-hash", "case_content_hash", "0" * 64),
        ("historical-action", "historical_action", None),
        ("historical-result", "historical_simulated_result", []),
        ("review-metadata", "review_metadata", "invalid"),
    ):
        polluted = deepcopy(approved[0])
        polluted["case_id"] = f"polluted-{suffix}"
        polluted[field] = value
        polluted["observable_feature_vector"]["values"] = ["999.000000000000"] * 50
        if suffix not in {"source-hash", "case-hash"}:
            polluted["source_content_hash"] = _sha256(
                _source_content_payload(polluted)
            )
            polluted["case_content_hash"] = _sha256(
                {
                    key: item
                    for key, item in polluted.items()
                    if key != "case_content_hash"
                }
            )
        pollutants.append(polluted)
    non_finite = deepcopy(approved[0])
    non_finite["case_id"] = "polluted-non-finite"
    non_finite["observable_feature_vector"]["values"][0] = "NaN"
    non_finite["source_content_hash"] = _sha256(
        _source_content_payload(non_finite)
    )
    non_finite["case_content_hash"] = _sha256(
        {
            key: item
            for key, item in non_finite.items()
            if key != "case_content_hash"
        }
    )
    pollutants.append(non_finite)

    mixed = [*approved, *pollutants]
    index = build_approved_index(mixed)
    scaler = fit_retrieval_scaler(mixed)

    assert index["ordered_case_ids"] == sorted(case["case_id"] for case in approved)
    assert scaler["fit_case_count"] == 60
    assert scaler["fit_case_ids_hash"] == baseline_scaler["fit_case_ids_hash"]
    assert scaler["mean"] == baseline_scaler["mean"]
    assert scaler["scale"] == baseline_scaler["scale"]


def test_scaler_zero_variance_features_use_deterministic_unit_scale(tmp_path):
    root = tmp_path / "source"
    generate(root, seed=20260718)
    identical = []
    for index in range(3):
        identical.append(
            _build_case(
                index=index,
                source_batch_id=f"{index + 1:064x}",
                feature_row=[2.0] * 50,
                reviewed_root_cause="PLANE_TILT",
            )
        )

    scaler = fit_retrieval_scaler(identical)

    assert scaler["mean"] == ["2.000000000000"] * 50
    assert scaler["scale"] == ["1.000000000000"] * 50
    assert scaler["zero_variance_policy"] == "SCALE_TO_ONE"
