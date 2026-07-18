from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

from tools.generate_approved_case_index import generate
from tunewise.case_retrieval import (
    ApprovedCaseAssetLoader,
    CaseRetrievalGuardError,
    StructuredCaseRetriever,
    record_case_retrieval,
)
from tunewise.diagnosis import DerivedFeatureSet
from tunewise.diagnostic_contract import FEATURE_DEFINITION_VERSION, FEATURE_NAMES


def load_assets(tmp_path):
    root = tmp_path / "cases"
    generate(root, seed=20260718)
    manifest_hash = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    return ApprovedCaseAssetLoader(root, manifest_hash).load()


def query_for(case):
    return DerivedFeatureSet(
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        feature_names=FEATURE_NAMES,
        values=tuple(float(value) for value in case.feature_values),
        input_feature_hash="a" * 64,
    )


def restricted_assets(assets, cases):
    return replace(
        assets,
        cases=tuple(cases),
        index_case_ids=tuple(sorted(case.case_id for case in cases)),
    )


def canonical_bytes(payload):
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def content_hash(payload):
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def trust_mutated_file(root, name, mutate):
    path = root / name
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_bytes(canonical_bytes(payload))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["files"][name] = file_hash
    if name == "approved-cases.json":
        manifest["case_collection_hash"] = file_hash
    manifest_path.write_bytes(canonical_bytes(manifest))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def trust_resigned_scaler(root):
    scaler_path = root / "scaler.json"
    scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
    scaler["mean"][0] = "999.000000000000"
    fingerprint_payload = {
        key: value for key, value in scaler.items() if key != "scaler_fingerprint"
    }
    scaler["scaler_fingerprint"] = content_hash(fingerprint_payload)
    scaler_path.write_bytes(canonical_bytes(scaler))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["scaler.json"] = hashlib.sha256(
        scaler_path.read_bytes()
    ).hexdigest()
    manifest["scaler_fingerprint"] = scaler["scaler_fingerprint"]
    manifest_path.write_bytes(canonical_bytes(manifest))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def trust_resigned_case_contract(root, mutate):
    cases_path = root / "approved-cases.json"
    collection = json.loads(cases_path.read_text(encoding="utf-8"))
    mutate(collection["cases"][0])
    case = collection["cases"][0]
    case["case_content_hash"] = content_hash(
        {key: value for key, value in case.items() if key != "case_content_hash"}
    )
    cases_path.write_bytes(canonical_bytes(collection))
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_file_hash = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    manifest["files"]["approved-cases.json"] = case_file_hash
    manifest["case_collection_hash"] = case_file_hash
    manifest_path.write_bytes(canonical_bytes(manifest))
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def test_exact_observable_query_returns_three_stage_one_cases_with_stable_evidence(tmp_path):
    assets = load_assets(tmp_path)
    exact_case = assets.cases[0]
    query = query_for(exact_case)

    result = StructuredCaseRetriever(assets).retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=3,
    )

    assert result.retrieval_status == "CASES_FOUND"
    assert result.returned_count == 3
    assert result.requested_count == 3
    assert [case.rank for case in result.ordered_cases] == [1, 2, 3]
    assert {case.retrieval_stage for case in result.ordered_cases} == {
        "TOP3_ROOT_CAUSE"
    }
    assert result.ordered_cases[0].case_id == exact_case.case_id
    assert result.ordered_cases[0].distance == "0.000000"
    assert result.ordered_cases[0].similarity_display_value == "1.000000"
    assert [
        item.feature_index
        for item in result.ordered_cases[0].key_feature_differences
    ] == [0, 1, 2, 3, 4]
    assert all(
        len(case.key_feature_differences) == 5 for case in result.ordered_cases
    )
    assert result.case_index_version == "tw-approved-case-index-v1"
    assert result.scaler_version == "tw-case-retrieval-scaler-v1"
    assert result.feature_definition_version == "tw-feature-definition-v1"


def test_stage_two_only_fills_shortfall_and_never_reorders_stage_one(tmp_path):
    assets = load_assets(tmp_path)
    first_stage = (assets.cases[0], assets.cases[1])
    fallback = assets.cases[24]
    limited = restricted_assets(assets, (*first_stage, fallback))

    result = StructuredCaseRetriever(limited).retrieve(
        query_features=query_for(fallback),
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=3,
    )

    assert [case.retrieval_stage for case in result.ordered_cases] == [
        "TOP3_ROOT_CAUSE",
        "TOP3_ROOT_CAUSE",
        "COMPATIBLE_FALLBACK",
    ]
    assert result.ordered_cases[2].case_id == fallback.case_id
    assert result.ordered_cases[2].distance == "0.000000"
    assert len({case.case_id for case in result.ordered_cases}) == 3


def test_equal_fixed_precision_distance_uses_case_id_not_input_order(tmp_path):
    assets = load_assets(tmp_path)
    first, second = assets.cases[0], assets.cases[1]
    midpoint = tuple(
        float((left + right) / 2)
        for left, right in zip(first.feature_values, second.feature_values, strict=True)
    )
    query = DerivedFeatureSet(
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        feature_names=FEATURE_NAMES,
        values=midpoint,
        input_feature_hash="b" * 64,
    )
    reversed_assets = restricted_assets(assets, (second, first))

    result = StructuredCaseRetriever(reversed_assets).retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=2,
    )

    assert result.ordered_cases[0].distance == result.ordered_cases[1].distance
    assert [case.case_id for case in result.ordered_cases] == sorted(
        (first.case_id, second.case_id)
    )


def test_standardized_euclidean_distance_uses_only_fixed_feature_vector(tmp_path):
    assets = load_assets(tmp_path)
    original = assets.cases[0]
    values = ["0.000000000000"] * 50
    values[0] = "3.000000000000"
    values[1] = "4.000000000000"
    payload = deepcopy(original.payload)
    payload["observable_feature_vector"]["values"] = values
    source_payload = {
        "source_batch_id": payload["source_batch_id"],
        "source_partition": payload["source_partition"],
        "source_partition_id": payload["source_partition_id"],
        "source_dataset_version": payload["source_dataset_version"],
        "feature_definition_version": payload["feature_definition_version"],
        "observable_feature_vector": payload["observable_feature_vector"],
        "reviewed_root_cause": payload["reviewed_root_cause"],
    }
    payload["source_content_hash"] = content_hash(source_payload)
    case_payload = {
        key: value for key, value in payload.items() if key != "case_content_hash"
    }
    payload["case_content_hash"] = content_hash(case_payload)
    custom_case = replace(
        original,
        feature_values=tuple(Decimal(value) for value in values),
        source_content_hash=payload["source_content_hash"],
        case_content_hash=payload["case_content_hash"],
        payload=payload,
    )
    unit_assets = replace(
        restricted_assets(assets, (custom_case,)),
        scaler_mean=(Decimal(0),) * 50,
        scaler_scale=(Decimal(1),) * 50,
    )
    query = DerivedFeatureSet(
        feature_definition_version=FEATURE_DEFINITION_VERSION,
        feature_names=FEATURE_NAMES,
        values=(0.0,) * 50,
        input_feature_hash="c" * 64,
    )

    result = StructuredCaseRetriever(unit_assets).retrieve(
        query_features=query,
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=1,
    )

    assert result.ordered_cases[0].distance == "5.000000"
    assert [
        (difference.feature_index, difference.standardized_absolute_difference)
        for difference in result.ordered_cases[0].key_feature_differences[:2]
    ] == [(1, "4.000000"), (0, "3.000000")]


def test_query_reapplies_approved_station_product_partition_and_version_filters(tmp_path):
    assets = load_assets(tmp_path)
    cases = (
        replace(assets.cases[0], status="PENDING_REVIEW"),
        replace(assets.cases[1], station_type="OTHER"),
        replace(assets.cases[2], product_model="OTHER-PRODUCT"),
        replace(assets.cases[3], source_partition="VALIDATION"),
        replace(assets.cases[4], case_schema_version="future-schema"),
        replace(assets.cases[5], rule_set_version="future-rules"),
        assets.cases[6],
    )
    mixed = restricted_assets(assets, cases)

    result = StructuredCaseRetriever(mixed).retrieve(
        query_features=query_for(assets.cases[0]),
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=3,
    )

    assert result.retrieval_status == "PARTIAL_RESULTS"
    assert result.returned_count == 1
    assert [case.case_id for case in result.ordered_cases] == [assets.cases[6].case_id]


def test_no_approved_compatible_case_is_a_non_error_empty_decision(tmp_path):
    assets = load_assets(tmp_path)
    pending = restricted_assets(
        assets,
        tuple(replace(case, status="PENDING_REVIEW") for case in assets.cases[:3]),
    )

    result = StructuredCaseRetriever(pending).retrieve(
        query_features=query_for(assets.cases[0]),
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=3,
    )

    assert result.retrieval_status == "NO_RELEVANT_CASE_AVAILABLE"
    assert result.ordered_cases == ()
    assert result.returned_count == 0
    assert result.shortfall_message == "暂无兼容已审核案例。"


def test_missing_and_non_finite_query_features_are_structurally_rejected(tmp_path):
    assets = load_assets(tmp_path)
    retriever = StructuredCaseRetriever(assets)
    valid = query_for(assets.cases[0])
    invalid_queries = (
        (
            replace(valid, values=valid.values[:-1]),
            "CASE_QUERY_FEATURE_MISSING",
        ),
        (
            replace(valid, values=(float("nan"), *valid.values[1:])),
            "CASE_QUERY_FEATURE_NON_FINITE",
        ),
    )

    for query, expected_code in invalid_queries:
        try:
            retriever.retrieve(
                query_features=query,
                product_model="TW-AA-PROTOTYPE-V1",
                top3_root_causes=(
                    "PLANE_TILT",
                    "XY_DECENTER",
                    "REFERENCE_DRIFT",
                ),
                top_k=3,
            )
        except CaseRetrievalGuardError as error:
            assert error.code == expected_code
        else:
            raise AssertionError(f"expected {expected_code}")


def test_missing_or_tampered_case_assets_are_structurally_rejected(tmp_path):
    mutations = (
        (
            "missing-scaler",
            "scaler.json",
            None,
            "CASE_SCALER_MISSING",
        ),
        (
            "tampered-case",
            "approved-cases.json",
            lambda payload: payload["cases"][0]["historical_action"].__setitem__(
                "summary", "tampered"
            ),
            "CASE_CONTENT_HASH_MISMATCH",
        ),
        (
            "tampered-scaler",
            "scaler.json",
            lambda payload: payload["mean"].__setitem__(0, "999.000000000000"),
            "CASE_SCALER_INVALID",
        ),
        (
            "tampered-index",
            "index.json",
            lambda payload: payload["ordered_case_ids"].reverse(),
            "CASE_INDEX_INVALID",
        ),
        (
            "tampered-compatibility",
            "compatibility-rules.json",
            lambda payload: payload.__setitem__("read_only", False),
            "CASE_COMPATIBILITY_RULES_INVALID",
        ),
    )
    for directory, filename, mutate, expected_code in mutations:
        root = tmp_path / directory
        generate(root, seed=20260718)
        if mutate is None:
            expected_hash = hashlib.sha256(
                (root / "manifest.json").read_bytes()
            ).hexdigest()
            (root / filename).unlink()
        else:
            expected_hash = trust_mutated_file(root, filename, mutate)
        try:
            ApprovedCaseAssetLoader(root, expected_hash).load()
        except Exception as error:
            assert getattr(error, "code", None) == expected_code
        else:
            raise AssertionError(f"expected {expected_code}")


def test_retrieval_result_hash_excludes_timestamp_and_derived_record_id(tmp_path):
    assets = load_assets(tmp_path)
    decision = StructuredCaseRetriever(assets).retrieve(
        query_features=query_for(assets.cases[0]),
        product_model="TW-AA-PROTOTYPE-V1",
        top3_root_causes=("PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"),
        top_k=3,
    )
    common = {
        "decision": decision,
        "task_id": "task-a",
        "diagnostic_result_id": "diagnostic-a",
        "ordered_top3_root_causes": (
            "PLANE_TILT",
            "XY_DECENTER",
            "REFERENCE_DRIFT",
        ),
    }

    first = record_case_retrieval(
        created_at="2026-01-01T00:00:00Z", **common
    )
    second = record_case_retrieval(
        created_at="2030-01-01T00:00:00Z", **common
    )

    assert first.created_at != second.created_at
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash
    assert first.retrieval_result_id == second.retrieval_result_id
    assert first.ordered_cases == decision.ordered_cases


def test_resigned_scaler_is_rejected_when_statistics_do_not_match_allowed_cases(tmp_path):
    root = tmp_path / "resigned-scaler"
    generate(root, seed=20260718)
    expected_hash = trust_resigned_scaler(root)

    try:
        ApprovedCaseAssetLoader(root, expected_hash).load()
    except Exception as error:
        assert getattr(error, "code", None) == "CASE_SCALER_SOURCE_MISMATCH"
    else:
        raise AssertionError("expected CASE_SCALER_SOURCE_MISMATCH")


def test_resigned_non_aa_case_is_rejected_before_it_can_enter_runtime_assets(tmp_path):
    root = tmp_path / "resigned-case"
    generate(root, seed=20260718)
    expected_hash = trust_resigned_case_contract(
        root,
        lambda case: case.__setitem__("station_type", "OTHER"),
    )

    try:
        ApprovedCaseAssetLoader(root, expected_hash).load()
    except Exception as error:
        assert getattr(error, "code", None) == "CASE_INDEX_ILLEGAL_ENTRY"
    else:
        raise AssertionError("expected CASE_INDEX_ILLEGAL_ENTRY")


def test_resigned_malformed_case_knowledge_fields_are_structurally_rejected(tmp_path):
    mutations = (
        lambda case: case.__setitem__("historical_action", None),
        lambda case: case.__setitem__("historical_simulated_result", []),
        lambda case: case.__setitem__("review_metadata", "invalid"),
    )
    for index, mutate in enumerate(mutations):
        root = tmp_path / f"malformed-knowledge-{index}"
        generate(root, seed=20260718)
        expected_hash = trust_resigned_case_contract(root, mutate)

        try:
            ApprovedCaseAssetLoader(root, expected_hash).load()
        except Exception as error:
            assert getattr(error, "code", None) == "CASE_KNOWLEDGE_PAYLOAD_INVALID"
        else:
            raise AssertionError("expected CASE_KNOWLEDGE_PAYLOAD_INVALID")


def test_resigned_string_applicability_is_not_split_into_display_conditions(tmp_path):
    root = tmp_path / "malformed-applicability"
    generate(root, seed=20260718)
    expected_hash = trust_resigned_case_contract(
        root,
        lambda case: case.__setitem__("applicability_conditions", "AA"),
    )

    try:
        ApprovedCaseAssetLoader(root, expected_hash).load()
    except Exception as error:
        assert getattr(error, "code", None) == "CASE_APPLICABILITY_INVALID"
    else:
        raise AssertionError("expected CASE_APPLICABILITY_INVALID")
