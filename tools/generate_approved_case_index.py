from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from tools.generate_diagnostic_assets import (
    TRAINING_SEED_OFFSET,
    build_partition,
    canonical_bytes,
)
from tunewise.diagnostic_contract import CLASS_ORDER, FEATURE_DEFINITION_VERSION, FEATURE_NAMES


ASSET_VERSION = "tw-approved-case-assets-v1"
CASE_SCHEMA_VERSION = "tw-approved-case-schema-v1"
CASE_INDEX_VERSION = "tw-approved-case-index-v1"
SCALER_VERSION = "tw-case-retrieval-scaler-v1"
COMPATIBILITY_RULE_VERSION = "tw-product-compatibility-v1"
RETRIEVAL_RULE_VERSION = "tw-case-retrieval-rules-v1"
CASE_ACTION_VERSION = "tw-approved-case-action-v1"
SAFETY_RULE_VERSION = "tw-parameter-safety-v1"
RULE_SET_VERSION = "tw-rules-v1"
SOURCE_DATASET_VERSION = "tw-diagnostic-dev-dataset-v1"
SOURCE_GENERATOR_VERSION = "tw-diagnostic-synthetic-source-v1"
SOURCE_PARTITION = "TRAIN"
SOURCE_PARTITION_ID = "diagnostic-dev-train-v1"
PRODUCT_MODEL = "TW-AA-PROTOTYPE-V1"
STATION_TYPE = "AA"
ROWS_PER_CLASS = 12
EXCLUDED_PARTITIONS = (
    "VALIDATION",
    "TEST",
    "BLIND_TEST",
    "DEMO",
    "PENDING_REVIEW",
    "RUNTIME_SUBMISSION",
)
CASE_FIELDS = {
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


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _source_batch_ids(seed: int, count: int) -> list[str]:
    return [
        hashlib.sha256(
            f"{seed}:{SOURCE_PARTITION_ID}:batch:{index}".encode("ascii")
        ).hexdigest()
        for index in range(count)
    ]


def _source_partition_manifest(
    seed: int,
    rows: list[list[float]],
    labels: list[str],
) -> dict[str, object]:
    batch_ids = _source_batch_ids(seed, len(rows))
    batch_id_manifest_hash = _sha256(
        {"partition": SOURCE_PARTITION_ID, "batch_ids": batch_ids}
    )
    observations_hash = _sha256(
        {
            "feature_names": FEATURE_NAMES,
            "rows": [[f"{value:.12f}" for value in row] for row in rows],
        }
    )
    labels_hash = _sha256(labels)
    partition_payload = {
        "partition": SOURCE_PARTITION_ID,
        "random_seed": seed,
        "batch_count": len(rows),
        "batch_id_manifest_hash": batch_id_manifest_hash,
        "observations_hash": observations_hash,
        "labels_hash": labels_hash,
    }
    return {
        **partition_payload,
        "partition_manifest_hash": _sha256(partition_payload),
    }


def _case_knowledge(root_cause: str) -> dict[str, Any]:
    values = {
        "PLANE_TILT": {
            "parameter_family": "PITCH_ROLL",
            "inspection_action": None,
            "historical_action": "历史案例在规则约束模拟环境中校正 Pitch/Roll 参数族。",
            "applicability": "稳定空间不对称且倾斜证据与当前参数状态一致。",
        },
        "XY_DECENTER": {
            "parameter_family": "XY_OFFSET",
            "inspection_action": None,
            "historical_action": "历史案例在规则约束模拟环境中校正 X/Y 偏心参数族。",
            "applicability": "X/Y 参数状态与空间下降方向共同支持偏心排查。",
        },
        "PLATFORM_INSTABILITY": {
            "parameter_family": None,
            "inspection_action": "检查 AA 平台重复定位、回差与振动状态。",
            "historical_action": "历史案例执行平台重复定位与振动排查，未直接调整光学参数。",
            "applicability": "时间序列波动或重复定位误差达到平台排查阈值。",
        },
        "REFERENCE_DRIFT": {
            "parameter_family": None,
            "inspection_action": "检查夹具基准与设备标定状态。",
            "historical_action": "历史案例复核夹具基准与标定残差，未直接调整光学参数。",
            "applicability": "持续标定残差支持基准或设备标定漂移排查。",
        },
        "Z_DEFOCUS_CONDITIONAL": {
            "parameter_family": "Z_OFFSET",
            "inspection_action": None,
            "historical_action": "历史案例在条件门控通过后校正 Z Offset 参数族。",
            "applicability": "中心接近下限、四角整体偏低且不对称不是主导特征。",
        },
    }
    return values[root_cause]


def _build_case(
    *,
    index: int,
    source_batch_id: str,
    feature_row: list[float],
    reviewed_root_cause: str,
) -> dict[str, Any]:
    vector = {
        "feature_names": list(FEATURE_NAMES),
        "values": [f"{value:.12f}" for value in feature_row],
    }
    source_payload = {
        "source_batch_id": source_batch_id,
        "source_partition": SOURCE_PARTITION,
        "source_partition_id": SOURCE_PARTITION_ID,
        "source_dataset_version": SOURCE_DATASET_VERSION,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "observable_feature_vector": vector,
        "reviewed_root_cause": reviewed_root_cause,
    }
    knowledge = _case_knowledge(reviewed_root_cause)
    parameter_names = {
        "PLANE_TILT": ("pitch", "roll"),
        "XY_DECENTER": ("x_offset", "y_offset"),
        "Z_DEFOCUS_CONDITIONAL": ("z_offset",),
    }.get(reviewed_root_cause, ())
    parameter_delta_ticks = {}
    for parameter_name in parameter_names:
        current_value = feature_row[FEATURE_NAMES.index(f"{parameter_name}_mean")]
        if current_value != 0:
            magnitude = min(2 + (index % 3), 2 if parameter_name == "z_offset" else 4)
            parameter_delta_ticks[parameter_name] = -magnitude if current_value > 0 else magnitude
    case = {
        "case_id": f"tw-aa-approved-{index + 1:03d}",
        "status": "APPROVED",
        "source_batch_id": source_batch_id,
        "source_partition": SOURCE_PARTITION,
        "source_partition_id": SOURCE_PARTITION_ID,
        "station_type": STATION_TYPE,
        "product_model": PRODUCT_MODEL,
        "reviewed_root_cause": reviewed_root_cause,
        "parameter_family": knowledge["parameter_family"],
        "inspection_action": knowledge["inspection_action"],
        "observable_feature_vector": vector,
        "historical_action": {
            "context": "VERSIONED_APPROVED_OFFLINE_CASE",
            "summary": knowledge["historical_action"],
            "action_version": CASE_ACTION_VERSION,
            "parameter_delta_ticks": parameter_delta_ticks,
            "historical_safety_status": "PASSED" if parameter_delta_ticks else "NOT_APPLICABLE",
            "historical_safety_rule_version": SAFETY_RULE_VERSION,
        },
        "historical_simulated_result": {
            "context_label": "规则约束模拟环境中的历史案例结果",
            "status": "SUCCESS",
            "summary": "该历史案例在固定规则与版本的模拟环境中达到准入条件。",
            "center_mtf_change": "-0.003000",
            "center_regression_tolerance": "0.010000",
            "center_within_tolerance": True,
        },
        "applicability_conditions": [
            "仅适用于 AA 工站与兼容产品型号。",
            knowledge["applicability"],
        ],
        "source_dataset_version": SOURCE_DATASET_VERSION,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "rule_set_version": RULE_SET_VERSION,
        "retrieval_rule_version": RETRIEVAL_RULE_VERSION,
        "case_schema_version": CASE_SCHEMA_VERSION,
        "source_content_hash": _sha256(source_payload),
        "review_metadata": {
            "approval_origin": "VERSIONED_OFFLINE_ASSET",
            "review_record_version": "tw-approved-case-review-record-v1",
            "runtime_state_transition": False,
        },
    }
    return {**case, "case_content_hash": _sha256(case)}


def _source_content_payload(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_batch_id": case["source_batch_id"],
        "source_partition": case["source_partition"],
        "source_partition_id": case["source_partition_id"],
        "source_dataset_version": case["source_dataset_version"],
        "feature_definition_version": case["feature_definition_version"],
        "observable_feature_vector": case["observable_feature_vector"],
        "reviewed_root_cause": case["reviewed_root_cause"],
    }


def _knowledge_payload_valid(case: dict[str, Any]) -> bool:
    historical_action = case.get("historical_action")
    historical_result = case.get("historical_simulated_result")
    review_metadata = case.get("review_metadata")
    applicability = case.get("applicability_conditions")
    return (
        isinstance(historical_action, dict)
        and set(historical_action)
        == {
            "context",
            "summary",
            "action_version",
            "parameter_delta_ticks",
            "historical_safety_status",
            "historical_safety_rule_version",
        }
        and historical_action.get("context") == "VERSIONED_APPROVED_OFFLINE_CASE"
        and isinstance(historical_action.get("summary"), str)
        and bool(historical_action["summary"])
        and historical_action.get("action_version") == CASE_ACTION_VERSION
        and isinstance(historical_action.get("parameter_delta_ticks"), dict)
        and all(
            name in {"x_offset", "y_offset", "pitch", "roll", "z_offset"}
            and isinstance(delta, int)
            and delta != 0
            for name, delta in historical_action["parameter_delta_ticks"].items()
        )
        and historical_action.get("historical_safety_status")
        in {"PASSED", "NOT_APPLICABLE"}
        and historical_action.get("historical_safety_rule_version")
        == SAFETY_RULE_VERSION
        and isinstance(historical_result, dict)
        and set(historical_result)
        == {
            "context_label",
            "status",
            "summary",
            "center_mtf_change",
            "center_regression_tolerance",
            "center_within_tolerance",
        }
        and historical_result.get("context_label")
        == "规则约束模拟环境中的历史案例结果"
        and all(
            isinstance(historical_result.get(key), str)
            and bool(historical_result[key])
        for key in ("status", "summary")
        )
        and historical_result.get("center_within_tolerance") is True
        and isinstance(review_metadata, dict)
        and set(review_metadata)
        == {"approval_origin", "review_record_version", "runtime_state_transition"}
        and review_metadata.get("approval_origin") == "VERSIONED_OFFLINE_ASSET"
        and review_metadata.get("review_record_version")
        == "tw-approved-case-review-record-v1"
        and review_metadata.get("runtime_state_transition") is False
        and isinstance(applicability, list)
        and bool(applicability)
        and all(isinstance(item, str) and item for item in applicability)
    )


def _eligible_source_case(case: dict[str, Any]) -> bool:
    vector = case.get("observable_feature_vector")
    if not (
        set(case) == CASE_FIELDS
        and case.get("status") == "APPROVED"
        and case.get("source_partition") == SOURCE_PARTITION
        and case.get("source_partition_id") == SOURCE_PARTITION_ID
        and case.get("station_type") == STATION_TYPE
        and case.get("product_model") == PRODUCT_MODEL
        and case.get("reviewed_root_cause") in CLASS_ORDER
        and case.get("source_dataset_version") == SOURCE_DATASET_VERSION
        and case.get("case_schema_version") == CASE_SCHEMA_VERSION
        and case.get("feature_definition_version") == FEATURE_DEFINITION_VERSION
        and case.get("rule_set_version") == RULE_SET_VERSION
        and case.get("retrieval_rule_version") == RETRIEVAL_RULE_VERSION
        and _knowledge_payload_valid(case)
        and isinstance(vector, dict)
        and set(vector) == {"feature_names", "values"}
        and vector.get("feature_names") == list(FEATURE_NAMES)
        and isinstance(vector.get("values"), list)
        and len(vector["values"]) == len(FEATURE_NAMES)
    ):
        return False
    try:
        values = [Decimal(value) for value in vector["values"]]
        source_hash_valid = case["source_content_hash"] == _sha256(
            _source_content_payload(case)
        )
        case_payload = {
            key: value for key, value in case.items() if key != "case_content_hash"
        }
        case_hash_valid = case["case_content_hash"] == _sha256(case_payload)
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False
    return all(value.is_finite() for value in values) and source_hash_valid and case_hash_valid


def build_approved_index(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    eligible = [case for case in cases if _eligible_source_case(case)]
    ordered_case_ids = sorted(case["case_id"] for case in eligible)
    payload = {
        "case_index_version": CASE_INDEX_VERSION,
        "case_schema_version": CASE_SCHEMA_VERSION,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "retrieval_rule_version": RETRIEVAL_RULE_VERSION,
        "scaler_version": SCALER_VERSION,
        "compatibility_rule_version": COMPATIBILITY_RULE_VERSION,
        "approved_only": True,
        "source_partition": SOURCE_PARTITION,
        "source_partition_id": SOURCE_PARTITION_ID,
        "ordered_case_ids": ordered_case_ids,
    }
    return {**payload, "index_content_hash": _sha256(payload)}


def fit_retrieval_scaler(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    approved_cases = [case for case in cases if _eligible_source_case(case)]
    rows = [
        [Decimal(value) for value in case["observable_feature_vector"]["values"]]
        for case in approved_cases
    ]
    if not rows:
        raise ValueError("检索标准化器至少需要一个允许的 APPROVED TRAIN 案例。")
    means = [sum(column, Decimal(0)) / len(rows) for column in zip(*rows)]
    scales: list[Decimal] = []
    for feature_index, mean in enumerate(means):
        variance = (
            sum(
                (row[feature_index] - mean) ** 2
                for row in rows
            )
            / len(rows)
        )
        scales.append(variance.sqrt() if variance else Decimal(1))
    source_ids = sorted(case["case_id"] for case in approved_cases)
    payload = {
        "artifact_type": "StandardScaler",
        "scaler_version": SCALER_VERSION,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "mean": [f"{value:.12f}" for value in means],
        "scale": [f"{value:.12f}" for value in scales],
        "zero_variance_policy": "SCALE_TO_ONE",
        "fit_case_count": len(approved_cases),
        "fit_status": "APPROVED",
        "fit_source_partition": SOURCE_PARTITION,
        "fit_source_partition_id": SOURCE_PARTITION_ID,
        "fit_case_ids_hash": _sha256(source_ids),
    }
    return {**payload, "scaler_fingerprint": _sha256(payload)}


def _compatibility_rules() -> dict[str, Any]:
    return {
        "compatibility_rule_version": COMPATIBILITY_RULE_VERSION,
        "read_only": True,
        "station_type": STATION_TYPE,
        "compatible_products": {PRODUCT_MODEL: [PRODUCT_MODEL]},
        "compatible_case_schema_versions": [CASE_SCHEMA_VERSION],
        "compatible_feature_definition_versions": [FEATURE_DEFINITION_VERSION],
        "compatible_retrieval_rule_versions": [RETRIEVAL_RULE_VERSION],
    }


def _load_diagnostic_training_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("固定 TW-04 训练来源 Manifest 缺失或无效。") from error
    if not isinstance(payload, dict):
        raise ValueError("固定 TW-04 训练来源 Manifest 无效。")
    return payload


def generate(
    output: Path,
    seed: int = 20260718,
    diagnostic_manifest_path: Path | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    training_seed = seed + TRAINING_SEED_OFFSET
    rows, labels = build_partition(training_seed, "TRAIN", ROWS_PER_CLASS)
    source_manifest = _source_partition_manifest(training_seed, rows, labels)
    if diagnostic_manifest_path is None:
        diagnostic_manifest_path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "diagnostic"
            / "tw-diagnostic-v1"
            / "manifest.json"
        )
    diagnostic_manifest = _load_diagnostic_training_manifest(
        diagnostic_manifest_path
    )
    if (
        diagnostic_manifest.get("source_generator_version")
        != SOURCE_GENERATOR_VERSION
        or diagnostic_manifest.get("training_partition") != SOURCE_PARTITION_ID
        or diagnostic_manifest.get("source_assets", {}).get("training")
        != source_manifest
    ):
        raise ValueError("案例来源与固定 TW-04 允许训练分区不一致。")

    source_batch_ids = _source_batch_ids(training_seed, len(rows))
    cases = [
        _build_case(
            index=index,
            source_batch_id=source_batch_id,
            feature_row=row,
            reviewed_root_cause=label,
        )
        for index, (source_batch_id, row, label) in enumerate(
            zip(source_batch_ids, rows, labels, strict=True)
        )
    ]
    case_payload = {
        "asset_version": ASSET_VERSION,
        "case_schema_version": CASE_SCHEMA_VERSION,
        "source_partition": SOURCE_PARTITION,
        "source_partition_id": SOURCE_PARTITION_ID,
        "cases": cases,
    }
    artifacts = {
        "approved-cases.json": case_payload,
        "compatibility-rules.json": _compatibility_rules(),
        "index.json": build_approved_index(cases),
        "scaler.json": fit_retrieval_scaler(cases),
    }
    files: dict[str, str] = {}
    for name, payload in artifacts.items():
        content = canonical_bytes(payload)
        (output / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()

    scaler = artifacts["scaler.json"]
    index = artifacts["index.json"]
    manifest = {
        "manifest_version": "1",
        "asset_version": ASSET_VERSION,
        "generator_version": "tw-approved-case-index-generator-v1",
        "random_seed": seed,
        "case_schema_version": CASE_SCHEMA_VERSION,
        "case_index_version": CASE_INDEX_VERSION,
        "scaler_version": SCALER_VERSION,
        "compatibility_rule_version": COMPATIBILITY_RULE_VERSION,
        "retrieval_rule_version": RETRIEVAL_RULE_VERSION,
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "rule_set_version": RULE_SET_VERSION,
        "source_dataset_version": SOURCE_DATASET_VERSION,
        "source_generator_version": SOURCE_GENERATOR_VERSION,
        "source_partition": SOURCE_PARTITION_ID,
        "source_partition_kind": SOURCE_PARTITION,
        "source_partition_manifest_hash": source_manifest[
            "partition_manifest_hash"
        ],
        "source_observations_hash": source_manifest["observations_hash"],
        "source_batch_id_manifest_hash": source_manifest[
            "batch_id_manifest_hash"
        ],
        "case_count": len(cases),
        "approved_case_count": len(cases),
        "root_cause_distribution": dict(Counter(labels)),
        "excluded_partitions": list(EXCLUDED_PARTITIONS),
        "distance_feature_names": list(FEATURE_NAMES),
        "distance_excluded_fields": [
            "FaultTruth",
            "reviewed_root_cause",
            "status",
            "historical_action",
            "historical_simulated_result",
            "applicability_conditions",
            "case_id",
            "batch_id",
            "task_id",
            "source_partition",
            "file_name",
            "random_seed",
            "scenario_ref",
            "adjusted_result",
        ],
        "case_collection_hash": files["approved-cases.json"],
        "scaler_fingerprint": scaler["scaler_fingerprint"],
        "index_content_hash": index["index_content_hash"],
        "dependency_summary": {
            "implementation": "python-standard-library",
            "serialization": "canonical-json-v1",
            "network": "none",
        },
        "files": files,
    }
    (output / "manifest.json").write_bytes(canonical_bytes(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从允许训练分区生成 TuneWise APPROVED-only 案例索引。"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260718)
    parser.add_argument("--diagnostic-manifest", type=Path)
    arguments = parser.parse_args()
    manifest = generate(
        arguments.output,
        seed=arguments.seed,
        diagnostic_manifest_path=arguments.diagnostic_manifest,
    )
    sys.stdout.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
