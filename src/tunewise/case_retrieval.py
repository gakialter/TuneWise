from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from pathlib import Path, PurePosixPath
from typing import Any

from .diagnosis import DerivedFeatureSet
from .diagnostic_contract import CLASS_ORDER, FEATURE_DEFINITION_VERSION, FEATURE_NAMES


CASE_SCHEMA_VERSION = "tw-approved-case-schema-v1"
CASE_INDEX_VERSION = "tw-approved-case-index-v1"
SCALER_VERSION = "tw-case-retrieval-scaler-v1"
COMPATIBILITY_RULE_VERSION = "tw-product-compatibility-v1"
RETRIEVAL_RULE_VERSION = "tw-case-retrieval-rules-v1"
SOURCE_PARTITION = "TRAIN"
SOURCE_PARTITION_ID = "diagnostic-dev-train-v1"
SOURCE_DATASET_VERSION = "tw-diagnostic-dev-dataset-v1"
STATION_TYPE = "AA"
PRODUCT_MODEL = "TW-AA-PROTOTYPE-V1"
RULE_SET_VERSION = "tw-rules-v1"
DISTANCE_PRECISION = Decimal("0.000001")
DISPLAY_DIFFERENCE_COUNT = 5
CASE_RETRIEVAL_RESULT_VERSION = "tw-case-retrieval-result-v1"


class CaseRetrievalAssetError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CaseRetrievalGuardError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ApprovedCase:
    case_id: str
    status: str
    source_batch_id: str
    source_partition: str
    source_partition_id: str
    station_type: str
    product_model: str
    reviewed_root_cause: str
    parameter_family: str | None
    inspection_action: str | None
    feature_values: tuple[Decimal, ...]
    historical_action: dict[str, Any]
    historical_simulated_result: dict[str, Any]
    applicability_conditions: tuple[str, ...]
    source_dataset_version: str
    feature_definition_version: str
    rule_set_version: str
    retrieval_rule_version: str
    case_schema_version: str
    source_content_hash: str
    case_content_hash: str
    review_metadata: dict[str, Any]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CaseRetrievalAssets:
    manifest: dict[str, Any]
    cases: tuple[ApprovedCase, ...]
    index_case_ids: tuple[str, ...]
    scaler_mean: tuple[Decimal, ...]
    scaler_scale: tuple[Decimal, ...]
    compatible_products: dict[str, tuple[str, ...]]
    asset_hashes: dict[str, str]
    manifest_hash: str
    index_file_hash: str
    scaler_fingerprint: str
    case_index_version: str
    scaler_version: str
    compatibility_rule_version: str
    retrieval_rule_version: str
    case_schema_version: str
    feature_definition_version: str


@dataclass(frozen=True, slots=True)
class KeyFeatureDifference:
    feature_name: str
    feature_index: int
    standardized_absolute_difference: str
    query_value: str
    case_value: str


@dataclass(frozen=True, slots=True)
class RetrievedCase:
    rank: int
    case_id: str
    retrieval_stage: str
    distance: str
    similarity_display_value: str
    key_feature_differences: tuple[KeyFeatureDifference, ...]
    reviewed_root_cause: str
    historical_action: dict[str, Any]
    historical_simulated_result: dict[str, Any]
    applicability_conditions: tuple[str, ...]
    product_model: str
    source_version_summary: dict[str, str]
    case_content_hash: str
    case_index_version: str


@dataclass(frozen=True, slots=True)
class CaseRetrievalDecision:
    ordered_cases: tuple[RetrievedCase, ...]
    retrieval_status: str
    requested_count: int
    returned_count: int
    shortfall_message: str | None
    query_feature_hash: str
    case_index_version: str
    case_index_hash: str
    scaler_version: str
    feature_definition_version: str
    compatibility_rule_version: str
    retrieval_rule_version: str


@dataclass(frozen=True, slots=True)
class CaseRetrievalResultRecord:
    retrieval_result_version: str
    retrieval_result_id: str
    task_id: str
    diagnostic_result_id: str
    query_feature_hash: str
    ordered_top3_root_causes: tuple[str, ...]
    ordered_cases: tuple[RetrievedCase, ...]
    retrieval_status: str
    requested_count: int
    returned_count: int
    shortfall_message: str | None
    case_index_version: str
    case_index_hash: str
    scaler_version: str
    feature_definition_version: str
    compatibility_rule_version: str
    retrieval_rule_version: str
    input_hash: str
    result_hash: str
    created_at: str


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def record_case_retrieval(
    decision: CaseRetrievalDecision,
    *,
    task_id: str,
    diagnostic_result_id: str,
    ordered_top3_root_causes: tuple[str, ...],
    created_at: str,
) -> CaseRetrievalResultRecord:
    input_payload = {
        "task_id": task_id,
        "diagnostic_result_id": diagnostic_result_id,
        "query_feature_hash": decision.query_feature_hash,
        "ordered_top3_root_causes": ordered_top3_root_causes,
        "requested_count": decision.requested_count,
        "case_index_version": decision.case_index_version,
        "case_index_hash": decision.case_index_hash,
        "scaler_version": decision.scaler_version,
        "feature_definition_version": decision.feature_definition_version,
        "compatibility_rule_version": decision.compatibility_rule_version,
        "retrieval_rule_version": decision.retrieval_rule_version,
    }
    input_hash = _sha256(input_payload)
    business_payload = {
        "retrieval_result_version": CASE_RETRIEVAL_RESULT_VERSION,
        "task_id": task_id,
        "diagnostic_result_id": diagnostic_result_id,
        "query_feature_hash": decision.query_feature_hash,
        "ordered_top3_root_causes": ordered_top3_root_causes,
        "ordered_cases": [asdict(case) for case in decision.ordered_cases],
        "retrieval_status": decision.retrieval_status,
        "requested_count": decision.requested_count,
        "returned_count": decision.returned_count,
        "shortfall_message": decision.shortfall_message,
        "case_index_version": decision.case_index_version,
        "case_index_hash": decision.case_index_hash,
        "scaler_version": decision.scaler_version,
        "feature_definition_version": decision.feature_definition_version,
        "compatibility_rule_version": decision.compatibility_rule_version,
        "retrieval_rule_version": decision.retrieval_rule_version,
        "input_hash": input_hash,
    }
    result_hash = _sha256(business_payload)
    return CaseRetrievalResultRecord(
        retrieval_result_version=CASE_RETRIEVAL_RESULT_VERSION,
        retrieval_result_id=f"tw-case-retrieval-{result_hash[:16]}",
        task_id=task_id,
        diagnostic_result_id=diagnostic_result_id,
        query_feature_hash=decision.query_feature_hash,
        ordered_top3_root_causes=ordered_top3_root_causes,
        ordered_cases=decision.ordered_cases,
        retrieval_status=decision.retrieval_status,
        requested_count=decision.requested_count,
        returned_count=decision.returned_count,
        shortfall_message=decision.shortfall_message,
        case_index_version=decision.case_index_version,
        case_index_hash=decision.case_index_hash,
        scaler_version=decision.scaler_version,
        feature_definition_version=decision.feature_definition_version,
        compatibility_rule_version=decision.compatibility_rule_version,
        retrieval_rule_version=decision.retrieval_rule_version,
        input_hash=input_hash,
        result_hash=result_hash,
        created_at=created_at,
    )


def deserialize_case_retrieval_result(
    payload: dict[str, Any],
) -> CaseRetrievalResultRecord:
    def retrieved_case(item: dict[str, Any]) -> RetrievedCase:
        return RetrievedCase(
            rank=item["rank"],
            case_id=item["case_id"],
            retrieval_stage=item["retrieval_stage"],
            distance=item["distance"],
            similarity_display_value=item["similarity_display_value"],
            key_feature_differences=tuple(
                KeyFeatureDifference(**difference)
                for difference in item["key_feature_differences"]
            ),
            reviewed_root_cause=item["reviewed_root_cause"],
            historical_action=item["historical_action"],
            historical_simulated_result=item["historical_simulated_result"],
            applicability_conditions=tuple(item["applicability_conditions"]),
            product_model=item["product_model"],
            source_version_summary=item["source_version_summary"],
            case_content_hash=item["case_content_hash"],
            case_index_version=item["case_index_version"],
        )

    try:
        record = CaseRetrievalResultRecord(
            retrieval_result_version=payload["retrieval_result_version"],
            retrieval_result_id=payload["retrieval_result_id"],
            task_id=payload["task_id"],
            diagnostic_result_id=payload["diagnostic_result_id"],
            query_feature_hash=payload["query_feature_hash"],
            ordered_top3_root_causes=tuple(payload["ordered_top3_root_causes"]),
            ordered_cases=tuple(
                retrieved_case(item) for item in payload["ordered_cases"]
            ),
            retrieval_status=payload["retrieval_status"],
            requested_count=payload["requested_count"],
            returned_count=payload["returned_count"],
            shortfall_message=payload["shortfall_message"],
            case_index_version=payload["case_index_version"],
            case_index_hash=payload["case_index_hash"],
            scaler_version=payload["scaler_version"],
            feature_definition_version=payload["feature_definition_version"],
            compatibility_rule_version=payload["compatibility_rule_version"],
            retrieval_rule_version=payload["retrieval_rule_version"],
            input_hash=payload["input_hash"],
            result_hash=payload["result_hash"],
            created_at=payload["created_at"],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CaseRetrievalGuardError(
            "CASE_RETRIEVAL_RESULT_HASH_MISMATCH",
            "已保存案例检索结果的完整性校验失败。",
        ) from error
    expected = record_case_retrieval(
        CaseRetrievalDecision(
            query_feature_hash=record.query_feature_hash,
            ordered_cases=record.ordered_cases,
            retrieval_status=record.retrieval_status,
            requested_count=record.requested_count,
            returned_count=record.returned_count,
            shortfall_message=record.shortfall_message,
            case_index_version=record.case_index_version,
            case_index_hash=record.case_index_hash,
            scaler_version=record.scaler_version,
            feature_definition_version=record.feature_definition_version,
            compatibility_rule_version=record.compatibility_rule_version,
            retrieval_rule_version=record.retrieval_rule_version,
        ),
        task_id=record.task_id,
        diagnostic_result_id=record.diagnostic_result_id,
        ordered_top3_root_causes=record.ordered_top3_root_causes,
        created_at=record.created_at,
    )
    if (
        record.retrieval_result_version != expected.retrieval_result_version
        or record.retrieval_result_id != expected.retrieval_result_id
        or record.input_hash != expected.input_hash
        or record.result_hash != expected.result_hash
    ):
        raise CaseRetrievalGuardError(
            "CASE_RETRIEVAL_RESULT_HASH_MISMATCH",
            "已保存案例检索结果的完整性校验失败。",
        )
    return record


class ApprovedCaseAssetLoader:
    REQUIRED_FILES = (
        "approved-cases.json",
        "compatibility-rules.json",
        "index.json",
        "scaler.json",
    )
    REQUIRED_CASE_FIELDS = {
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
    FORBIDDEN_RUNTIME_KEYS = {
        "fault" + "truth",
        "fault" + "_truth",
        "primary" + "_fault" + "_truth",
        "scenario" + "_ref",
        "hidden" + "_scenario",
        "simulator_coefficient",
        "simulator_coefficients",
    }

    def __init__(self, root: Path, expected_manifest_hash: str) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash

    def _read(self, relative_path: str) -> bytes:
        pure = PurePosixPath(relative_path)
        path = (self._root / Path(*pure.parts)).resolve()
        if pure.is_absolute() or ".." in pure.parts or not path.is_relative_to(self._root):
            raise CaseRetrievalAssetError(
                "CASE_ASSET_PATH_FORBIDDEN",
                "案例检索运行时只能读取固定案例资产目录。",
            )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            code = {
                "manifest.json": "CASE_MANIFEST_MISSING",
                "approved-cases.json": "APPROVED_CASE_ASSET_MISSING",
                "compatibility-rules.json": "CASE_COMPATIBILITY_RULES_MISSING",
                "index.json": "CASE_INDEX_MISSING",
                "scaler.json": "CASE_SCALER_MISSING",
            }.get(relative_path, "CASE_ASSET_MISSING")
            raise CaseRetrievalAssetError(
                code, f"缺失案例检索资产：{relative_path}"
            ) from error

    @staticmethod
    def _json(content: bytes, name: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CaseRetrievalAssetError(
                "CASE_ASSET_INVALID", f"案例检索资产格式无效：{name}"
            ) from error
        if not isinstance(payload, dict):
            raise CaseRetrievalAssetError(
                "CASE_ASSET_INVALID", f"案例检索资产格式无效：{name}"
            )
        return payload

    def load(self) -> CaseRetrievalAssets:
        manifest_bytes = self._read("manifest.json")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != self._expected_manifest_hash:
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_HASH_MISMATCH", "案例索引 Manifest 已被篡改。"
            )
        manifest = self._json(manifest_bytes, "manifest.json")
        files = manifest.get("files")
        if manifest.get("manifest_version") != "1" or not isinstance(files, dict):
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_INVALID", "案例索引 Manifest 格式无效。"
            )
        payloads: dict[str, dict[str, Any]] = {}
        actual_hashes = {"manifest.json": manifest_hash}
        for name in self.REQUIRED_FILES:
            content = self._read(name)
            actual_hash = hashlib.sha256(content).hexdigest()
            if files.get(name) != actual_hash:
                raise CaseRetrievalAssetError(
                    "CASE_ASSET_HASH_MISMATCH", f"案例检索资产内容哈希不匹配：{name}"
                )
            payloads[name] = self._json(content, name)
            actual_hashes[name] = actual_hash

        self._validate_manifest_bindings(manifest, payloads, actual_hashes)
        cases = self._load_cases(payloads["approved-cases.json"])
        index_ids = self._load_index(payloads["index.json"], cases)
        means, scales = self._load_scaler(payloads["scaler.json"], cases)
        compatible_products = self._load_compatibility(
            payloads["compatibility-rules.json"]
        )
        return CaseRetrievalAssets(
            manifest=manifest,
            cases=cases,
            index_case_ids=index_ids,
            scaler_mean=means,
            scaler_scale=scales,
            compatible_products=compatible_products,
            asset_hashes=actual_hashes,
            manifest_hash=manifest_hash,
            index_file_hash=actual_hashes["index.json"],
            scaler_fingerprint=payloads["scaler.json"]["scaler_fingerprint"],
            case_index_version=manifest["case_index_version"],
            scaler_version=manifest["scaler_version"],
            compatibility_rule_version=manifest["compatibility_rule_version"],
            retrieval_rule_version=manifest["retrieval_rule_version"],
            case_schema_version=manifest["case_schema_version"],
            feature_definition_version=manifest["feature_definition_version"],
        )

    @staticmethod
    def _validate_manifest_bindings(
        manifest: dict[str, Any],
        payloads: dict[str, dict[str, Any]],
        hashes: dict[str, str],
    ) -> None:
        expected = {
            "case_index_version": CASE_INDEX_VERSION,
            "case_schema_version": CASE_SCHEMA_VERSION,
            "scaler_version": SCALER_VERSION,
            "compatibility_rule_version": COMPATIBILITY_RULE_VERSION,
            "retrieval_rule_version": RETRIEVAL_RULE_VERSION,
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "source_partition_kind": SOURCE_PARTITION,
            "source_partition": SOURCE_PARTITION_ID,
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise CaseRetrievalAssetError(
                "CASE_ASSET_VERSION_MISMATCH",
                "案例、索引、标准化器或兼容规则版本绑定不一致。",
            )
        if (
            manifest.get("case_collection_hash") != hashes["approved-cases.json"]
            or manifest.get("index_content_hash")
            != payloads["index.json"].get("index_content_hash")
            or manifest.get("scaler_fingerprint")
            != payloads["scaler.json"].get("scaler_fingerprint")
            or manifest.get("distance_feature_names") != list(FEATURE_NAMES)
        ):
            raise CaseRetrievalAssetError(
                "CASE_MANIFEST_BINDING_MISMATCH",
                "案例 Manifest 与案例集合、索引或标准化器不一致。",
            )

    def _load_cases(self, payload: dict[str, Any]) -> tuple[ApprovedCase, ...]:
        raw_cases = payload.get("cases")
        if (
            payload.get("case_schema_version") != CASE_SCHEMA_VERSION
            or payload.get("source_partition") != SOURCE_PARTITION
            or payload.get("source_partition_id") != SOURCE_PARTITION_ID
            or not isinstance(raw_cases, list)
        ):
            raise CaseRetrievalAssetError(
                "APPROVED_CASE_ASSET_INVALID", "预置 APPROVED 案例集合格式无效。"
            )
        cases = tuple(self._load_case(item) for item in raw_cases)
        if len({case.case_id for case in cases}) != len(cases):
            raise CaseRetrievalAssetError(
                "CASE_ID_DUPLICATE", "预置案例包含重复 case_id。"
            )
        return cases

    def _load_case(self, payload: object) -> ApprovedCase:
        if not isinstance(payload, dict) or set(payload) != self.REQUIRED_CASE_FIELDS:
            raise CaseRetrievalAssetError(
                "APPROVED_CASE_INVALID", "预置案例字段与冻结 Case 契约不一致。"
            )
        if self._contains_forbidden_key(payload):
            raise CaseRetrievalAssetError(
                "CASE_RUNTIME_SECRET_FIELD_FORBIDDEN",
                "案例资产包含训练真值、隐藏场景或模拟器内部字段。",
            )
        if payload["status"] != "APPROVED":
            raise CaseRetrievalAssetError(
                "CASE_INDEX_ILLEGAL_STATUS", "案例索引只允许 APPROVED 案例。"
            )
        vector = payload.get("observable_feature_vector")
        if (
            not isinstance(vector, dict)
            or vector.get("feature_names") != list(FEATURE_NAMES)
            or not isinstance(vector.get("values"), list)
            or len(vector["values"]) != len(FEATURE_NAMES)
        ):
            raise CaseRetrievalAssetError(
                "CASE_FEATURE_VECTOR_INVALID", "案例特征向量顺序或维度无效。"
            )
        try:
            values = tuple(Decimal(value) for value in vector["values"])
        except (InvalidOperation, TypeError, ValueError) as error:
            raise CaseRetrievalAssetError(
                "CASE_FEATURE_VECTOR_NON_FINITE", "案例特征向量包含无效数值。"
            ) from error
        if not all(value.is_finite() for value in values):
            raise CaseRetrievalAssetError(
                "CASE_FEATURE_VECTOR_NON_FINITE", "案例特征向量包含非有限数值。"
            )
        source_payload = {
            "source_batch_id": payload["source_batch_id"],
            "source_partition": payload["source_partition"],
            "source_partition_id": payload["source_partition_id"],
            "source_dataset_version": payload["source_dataset_version"],
            "feature_definition_version": payload["feature_definition_version"],
            "observable_feature_vector": vector,
            "reviewed_root_cause": payload["reviewed_root_cause"],
        }
        if payload["source_content_hash"] != _sha256(source_payload):
            raise CaseRetrievalAssetError(
                "CASE_SOURCE_HASH_MISMATCH", "案例训练来源内容哈希不匹配。"
            )
        business_payload = {
            key: value for key, value in payload.items() if key != "case_content_hash"
        }
        if payload["case_content_hash"] != _sha256(business_payload):
            raise CaseRetrievalAssetError(
                "CASE_CONTENT_HASH_MISMATCH", "案例内容哈希不匹配。"
            )
        if payload["reviewed_root_cause"] not in CLASS_ORDER:
            raise CaseRetrievalAssetError(
                "CASE_REVIEWED_ROOT_CAUSE_INVALID", "案例已审核根因不在冻结类别中。"
            )
        historical_action = payload["historical_action"]
        historical_result = payload["historical_simulated_result"]
        review_metadata = payload["review_metadata"]
        if not (
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
            and historical_action.get("action_version")
            == "tw-approved-case-action-v1"
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
            == "tw-parameter-safety-v1"
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
            == {
                "approval_origin",
                "review_record_version",
                "runtime_state_transition",
            }
            and review_metadata.get("approval_origin") == "VERSIONED_OFFLINE_ASSET"
            and review_metadata.get("review_record_version")
            == "tw-approved-case-review-record-v1"
            and review_metadata.get("runtime_state_transition") is False
        ):
            raise CaseRetrievalAssetError(
                "CASE_KNOWLEDGE_PAYLOAD_INVALID",
                "案例历史知识或离线审核元数据格式无效。",
            )
        try:
            if not isinstance(payload["applicability_conditions"], list):
                raise TypeError
            applicability = tuple(payload["applicability_conditions"])
            if not applicability or not all(
                isinstance(item, str) and item for item in applicability
            ):
                raise TypeError
        except TypeError as error:
            raise CaseRetrievalAssetError(
                "CASE_APPLICABILITY_INVALID", "案例适用条件格式无效。"
            ) from error
        return ApprovedCase(
            case_id=payload["case_id"],
            status=payload["status"],
            source_batch_id=payload["source_batch_id"],
            source_partition=payload["source_partition"],
            source_partition_id=payload["source_partition_id"],
            station_type=payload["station_type"],
            product_model=payload["product_model"],
            reviewed_root_cause=payload["reviewed_root_cause"],
            parameter_family=payload["parameter_family"],
            inspection_action=payload["inspection_action"],
            feature_values=values,
            historical_action=historical_action,
            historical_simulated_result=historical_result,
            applicability_conditions=applicability,
            source_dataset_version=payload["source_dataset_version"],
            feature_definition_version=payload["feature_definition_version"],
            rule_set_version=payload["rule_set_version"],
            retrieval_rule_version=payload["retrieval_rule_version"],
            case_schema_version=payload["case_schema_version"],
            source_content_hash=payload["source_content_hash"],
            case_content_hash=payload["case_content_hash"],
            review_metadata=review_metadata,
            payload=dict(payload),
        )

    @classmethod
    def _contains_forbidden_key(cls, value: object) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).lower() in cls.FORBIDDEN_RUNTIME_KEYS
                or cls._contains_forbidden_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_forbidden_key(item) for item in value)
        return False

    @staticmethod
    def _load_index(
        payload: dict[str, Any], cases: tuple[ApprovedCase, ...]
    ) -> tuple[str, ...]:
        content_payload = {
            key: value for key, value in payload.items() if key != "index_content_hash"
        }
        ordered = payload.get("ordered_case_ids")
        if (
            payload.get("case_index_version") != CASE_INDEX_VERSION
            or payload.get("case_schema_version") != CASE_SCHEMA_VERSION
            or payload.get("feature_definition_version") != FEATURE_DEFINITION_VERSION
            or payload.get("retrieval_rule_version") != RETRIEVAL_RULE_VERSION
            or payload.get("scaler_version") != SCALER_VERSION
            or payload.get("compatibility_rule_version")
            != COMPATIBILITY_RULE_VERSION
            or payload.get("approved_only") is not True
            or payload.get("source_partition") != SOURCE_PARTITION
            or payload.get("source_partition_id") != SOURCE_PARTITION_ID
            or payload.get("index_content_hash") != _sha256(content_payload)
            or not isinstance(ordered, list)
            or ordered != sorted(ordered)
            or len(set(ordered)) != len(ordered)
        ):
            raise CaseRetrievalAssetError(
                "CASE_INDEX_INVALID", "案例索引结构、顺序或内容哈希无效。"
            )
        by_id = {case.case_id: case for case in cases}
        if set(ordered) != set(by_id) or any(
            by_id[case_id].status != "APPROVED"
            or by_id[case_id].source_partition != SOURCE_PARTITION
            or by_id[case_id].source_partition_id != SOURCE_PARTITION_ID
            or by_id[case_id].source_dataset_version != SOURCE_DATASET_VERSION
            or by_id[case_id].station_type != STATION_TYPE
            or by_id[case_id].product_model != PRODUCT_MODEL
            or by_id[case_id].case_schema_version != CASE_SCHEMA_VERSION
            or by_id[case_id].feature_definition_version
            != FEATURE_DEFINITION_VERSION
            or by_id[case_id].rule_set_version != RULE_SET_VERSION
            or by_id[case_id].retrieval_rule_version
            != RETRIEVAL_RULE_VERSION
            for case_id in ordered
        ):
            raise CaseRetrievalAssetError(
                "CASE_INDEX_ILLEGAL_ENTRY",
                "案例索引包含 PENDING、非法分区或缺失案例。",
            )
        return tuple(ordered)

    @staticmethod
    def _load_scaler(
        payload: dict[str, Any], cases: tuple[ApprovedCase, ...]
    ) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...]]:
        fingerprint_payload = {
            key: value for key, value in payload.items() if key != "scaler_fingerprint"
        }
        if (
            payload.get("artifact_type") != "StandardScaler"
            or payload.get("scaler_version") != SCALER_VERSION
            or payload.get("feature_definition_version") != FEATURE_DEFINITION_VERSION
            or payload.get("feature_names") != list(FEATURE_NAMES)
            or payload.get("zero_variance_policy") != "SCALE_TO_ONE"
            or payload.get("fit_status") != "APPROVED"
            or payload.get("fit_source_partition") != SOURCE_PARTITION
            or payload.get("fit_source_partition_id") != SOURCE_PARTITION_ID
            or payload.get("fit_case_count") != len(cases)
            or payload.get("scaler_fingerprint") != _sha256(fingerprint_payload)
        ):
            raise CaseRetrievalAssetError(
                "CASE_SCALER_INVALID", "案例检索 StandardScaler 契约无效。"
            )
        try:
            means = tuple(Decimal(value) for value in payload["mean"])
            scales = tuple(Decimal(value) for value in payload["scale"])
        except (KeyError, InvalidOperation, TypeError, ValueError) as error:
            raise CaseRetrievalAssetError(
                "CASE_SCALER_INVALID", "案例检索 StandardScaler 数值无效。"
            ) from error
        if (
            len(means) != len(FEATURE_NAMES)
            or len(scales) != len(FEATURE_NAMES)
            or not all(value.is_finite() for value in (*means, *scales))
            or any(value <= 0 for value in scales)
        ):
            raise CaseRetrievalAssetError(
                "CASE_SCALER_INVALID", "案例检索 StandardScaler 维度或数值无效。"
            )
        expected_ids_hash = _sha256(sorted(case.case_id for case in cases))
        if payload.get("fit_case_ids_hash") != expected_ids_hash:
            raise CaseRetrievalAssetError(
                "CASE_SCALER_SOURCE_MISMATCH",
                "检索标准化器并非只由当前允许案例拟合。",
            )
        fitted_means = tuple(
            sum(column, Decimal(0)) / len(cases)
            for column in zip(
                *(case.feature_values for case in cases),
                strict=True,
            )
        )
        expected_means = tuple(Decimal(f"{mean:.12f}") for mean in fitted_means)
        expected_scales: list[Decimal] = []
        for feature_index, mean in enumerate(fitted_means):
            variance = sum(
                (case.feature_values[feature_index] - mean) ** 2
                for case in cases
            ) / len(cases)
            expected_scales.append(
                Decimal(f"{variance.sqrt() if variance else Decimal(1):.12f}")
            )
        if means != expected_means or scales != tuple(expected_scales):
            raise CaseRetrievalAssetError(
                "CASE_SCALER_SOURCE_MISMATCH",
                "检索标准化器统计量与允许案例特征不一致。",
            )
        return means, scales

    @staticmethod
    def _load_compatibility(payload: dict[str, Any]) -> dict[str, tuple[str, ...]]:
        products = payload.get("compatible_products")
        if (
            payload.get("compatibility_rule_version")
            != COMPATIBILITY_RULE_VERSION
            or payload.get("read_only") is not True
            or payload.get("station_type") != STATION_TYPE
            or payload.get("compatible_case_schema_versions")
            != [CASE_SCHEMA_VERSION]
            or payload.get("compatible_feature_definition_versions")
            != [FEATURE_DEFINITION_VERSION]
            or payload.get("compatible_retrieval_rule_versions")
            != [RETRIEVAL_RULE_VERSION]
            or not isinstance(products, dict)
            or not products
            or any(
                not isinstance(product, str)
                or not isinstance(compatible, list)
                or not compatible
                or not all(isinstance(item, str) and item for item in compatible)
                for product, compatible in products.items()
            )
        ):
            raise CaseRetrievalAssetError(
                "CASE_COMPATIBILITY_RULES_INVALID", "产品兼容规则资产无效。"
            )
        return {
            product: tuple(compatible) for product, compatible in products.items()
        }


class StructuredCaseRetriever:
    def __init__(self, assets: CaseRetrievalAssets) -> None:
        self._assets = assets

    def retrieve(
        self,
        *,
        query_features: DerivedFeatureSet,
        product_model: str,
        top3_root_causes: tuple[str, ...],
        top_k: int,
        eligible_case_ids: frozenset[str] | None = None,
    ) -> CaseRetrievalDecision:
        if top_k < 1 or top_k > 5:
            raise CaseRetrievalGuardError(
                "CASE_TOP_K_INVALID", "案例检索 top_k 必须位于 1 到 5。", 422
            )
        if (
            query_features.feature_definition_version != FEATURE_DEFINITION_VERSION
            or query_features.feature_names != FEATURE_NAMES
        ):
            raise CaseRetrievalGuardError(
                "CASE_FEATURE_DEFINITION_STALE",
                "查询 DerivedFeatureSet 与冻结特征定义版本或顺序不一致。",
            )
        if len(query_features.values) != len(FEATURE_NAMES):
            raise CaseRetrievalGuardError(
                "CASE_QUERY_FEATURE_MISSING",
                "查询缺少固定 50 项可观测批次特征。",
            )
        try:
            query_values = tuple(
                Decimal(f"{value:.12f}") for value in query_features.values
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise CaseRetrievalGuardError(
                "CASE_QUERY_FEATURE_NON_FINITE", "查询特征包含非有限数值。"
            ) from error
        if not all(value.is_finite() for value in query_values):
            raise CaseRetrievalGuardError(
                "CASE_QUERY_FEATURE_NON_FINITE", "查询特征包含非有限数值。"
            )
        if (
            len(top3_root_causes) != 3
            or len(set(top3_root_causes)) != 3
            or any(root_cause not in CLASS_ORDER for root_cause in top3_root_causes)
        ):
            raise CaseRetrievalGuardError(
                "CASE_DIAGNOSTIC_TOP3_INVALID", "当前诊断缺少有效有序 Top-3。"
            )
        compatible_products = self._assets.compatible_products.get(product_model)
        if compatible_products is None:
            raise CaseRetrievalGuardError(
                "CASE_QUERY_PRODUCT_UNSUPPORTED", "当前 Batch 产品型号没有版本化兼容规则。"
            )
        indexed_ids = set(self._assets.index_case_ids)
        compatible: list[ApprovedCase] = []
        for case in self._assets.cases:
            if case.status not in ("APPROVED", "PENDING_REVIEW"):
                raise CaseRetrievalGuardError(
                    "CASE_STATUS_INVALID", "查询案例包含不支持的知识状态。"
                )
            if case.status != "APPROVED":
                continue
            if (
                case.case_id not in indexed_ids
                or (
                    eligible_case_ids is not None
                    and case.case_id not in eligible_case_ids
                )
                or case.station_type != STATION_TYPE
                or case.product_model not in compatible_products
                or case.source_partition != SOURCE_PARTITION
                or case.source_partition_id != SOURCE_PARTITION_ID
                or case.case_schema_version != self._assets.case_schema_version
                or case.feature_definition_version
                != self._assets.feature_definition_version
                or case.rule_set_version
                != self._assets.manifest.get("rule_set_version")
                or case.retrieval_rule_version
                != self._assets.retrieval_rule_version
            ):
                continue
            business_payload = {
                key: value
                for key, value in case.payload.items()
                if key != "case_content_hash"
            }
            if case.case_content_hash != _sha256(business_payload):
                raise CaseRetrievalGuardError(
                    "CASE_CONTENT_HASH_MISMATCH", "查询时检测到案例内容哈希不匹配。"
                )
            compatible.append(case)

        top3_set = set(top3_root_causes)
        stage_one = self._ranked(
            [case for case in compatible if case.reviewed_root_cause in top3_set],
            query_values,
            stage="TOP3_ROOT_CAUSE",
        )
        selected = stage_one[:top_k]
        if len(selected) < top_k:
            selected_ids = {
                case.case_id
                for case, _distance, _differences, _stage in selected
            }
            stage_two = self._ranked(
                [
                    case
                    for case in compatible
                    if case.case_id not in selected_ids
                    and case.reviewed_root_cause not in top3_set
                ],
                query_values,
                stage="COMPATIBLE_FALLBACK",
            )
            selected.extend(stage_two[: top_k - len(selected)])

        ordered_cases = tuple(
            self._view(rank, item)
            for rank, item in enumerate(selected, start=1)
        )
        returned = len(ordered_cases)
        if returned == 0:
            status = "NO_RELEVANT_CASE_AVAILABLE"
            shortfall = "暂无兼容已审核案例。"
        elif returned < top_k:
            status = "PARTIAL_RESULTS"
            shortfall = f"仅找到 {returned} 个合法兼容已审核案例。"
        else:
            status = "CASES_FOUND"
            shortfall = None
        return CaseRetrievalDecision(
            ordered_cases=ordered_cases,
            retrieval_status=status,
            requested_count=top_k,
            returned_count=returned,
            shortfall_message=shortfall,
            query_feature_hash=query_features.input_feature_hash,
            case_index_version=self._assets.case_index_version,
            case_index_hash=self._assets.index_file_hash,
            scaler_version=self._assets.scaler_version,
            feature_definition_version=self._assets.feature_definition_version,
            compatibility_rule_version=self._assets.compatibility_rule_version,
            retrieval_rule_version=self._assets.retrieval_rule_version,
        )

    def _ranked(
        self,
        cases: list[ApprovedCase],
        query_values: tuple[Decimal, ...],
        *,
        stage: str,
    ) -> list[tuple[ApprovedCase, Decimal, tuple[KeyFeatureDifference, ...], str]]:
        ranked = []
        for case in cases:
            differences = tuple(
                abs(query - candidate) / scale
                for query, candidate, scale in zip(
                    query_values,
                    case.feature_values,
                    self._assets.scaler_scale,
                    strict=True,
                )
            )
            distance = sum(
                (difference * difference for difference in differences), Decimal(0)
            ).sqrt().quantize(DISTANCE_PRECISION, rounding=ROUND_HALF_EVEN)
            key_differences = tuple(
                KeyFeatureDifference(
                    feature_name=FEATURE_NAMES[index],
                    feature_index=index,
                    standardized_absolute_difference=f"{difference:.6f}",
                    query_value=f"{query_values[index]:.12f}",
                    case_value=f"{case.feature_values[index]:.12f}",
                )
                for index, difference in sorted(
                    enumerate(differences),
                    key=lambda item: (-item[1], item[0]),
                )[:DISPLAY_DIFFERENCE_COUNT]
            )
            ranked.append((case, distance, key_differences, stage))
        ranked.sort(key=lambda item: (item[1], item[0].case_id))
        return ranked

    def _view(
        self,
        rank: int,
        item: tuple[ApprovedCase, Decimal, tuple[KeyFeatureDifference, ...], str],
    ) -> RetrievedCase:
        case, distance, differences, stage = item
        similarity = (
            Decimal(1) / (Decimal(1) + distance)
        ).quantize(DISTANCE_PRECISION, rounding=ROUND_HALF_EVEN)
        return RetrievedCase(
            rank=rank,
            case_id=case.case_id,
            retrieval_stage=stage,
            distance=f"{distance:.6f}",
            similarity_display_value=f"{similarity:.6f}",
            key_feature_differences=differences,
            reviewed_root_cause=case.reviewed_root_cause,
            historical_action=dict(case.historical_action),
            historical_simulated_result=dict(case.historical_simulated_result),
            applicability_conditions=case.applicability_conditions,
            product_model=case.product_model,
            source_version_summary={
                "source_dataset_version": case.source_dataset_version,
                "feature_definition_version": case.feature_definition_version,
                "rule_set_version": case.rule_set_version,
                "retrieval_rule_version": case.retrieval_rule_version,
                "case_schema_version": case.case_schema_version,
            },
            case_content_hash=case.case_content_hash,
            case_index_version=self._assets.case_index_version,
        )
