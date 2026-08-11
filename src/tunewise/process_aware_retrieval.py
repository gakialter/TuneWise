from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from .case_retrieval import (
    CaseRetrievalAssets,
    CaseRetrievalDecision,
    RetrievedCase,
    StructuredCaseRetriever,
)
from .diagnosis import DerivedFeatureSet
from .parameter_planning import (
    CandidateGenerationDecision,
    HistoricalCaseAction,
    ParameterConstraintSnapshot,
    ParameterDirectionEvidence,
    ParameterPlanCandidate,
    ParameterPlanGenerator,
)
from .plan_confirmation import FrozenDict
from .process_context import (
    CONTEXT_COMPATIBILITY_RULE_VERSION,
    CaseProcessProfile,
    ContextCompatibilityEvaluator,
    ContextCompatibilityReason,
    ProcessContext,
    ProcessContextValidationError,
)


PROCESS_AWARE_RETRIEVAL_RESULT_VERSION = "tw-process-aware-case-retrieval-result-v1"
PROCESS_AWARE_GUIDANCE_RESULT_VERSION = "tw-process-aware-guidance-result-v1"


def _canonical_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextualCaseEvaluation:
    case_id: str
    eligible_for_guidance: bool
    reason_code: str
    reason_details: FrozenDict
    explanation: str
    profile_hash: str | None
    profile_source_kind: str | None
    profile_is_synthetic: bool
    compatibility_rule_version: str


@dataclass(frozen=True, slots=True)
class ProcessAwareCaseRetrievalDecision:
    retrieval_result_version: str
    retrieval_result_id: str
    context_hash: str
    context_source_kind: str
    context_is_synthetic: bool
    profile_set_hash: str
    informational_cases: tuple[RetrievedCase, ...]
    ordered_cases: tuple[RetrievedCase, ...]
    case_evaluations: tuple[ContextualCaseEvaluation, ...]
    eligible_case_ids: tuple[str, ...]
    informational_only_case_ids: tuple[str, ...]
    guidance_status: str
    guidance_reason_code: str
    query_feature_hash: str
    ordered_top3_root_causes: tuple[str, ...]
    product_model: str
    case_index_version: str
    case_index_hash: str
    scaler_version: str
    feature_definition_version: str
    product_compatibility_rule_version: str
    retrieval_rule_version: str
    context_compatibility_rule_version: str
    result_hash: str


class ProcessAwareCaseRetriever:
    """Adds process eligibility without changing the legacy v1 retrieval path."""

    def __init__(
        self,
        assets: CaseRetrievalAssets,
        profiles: tuple[CaseProcessProfile, ...],
        evaluator: ContextCompatibilityEvaluator | None = None,
    ) -> None:
        profile_ids = [profile.case_id for profile in profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_DUPLICATE",
                "Each v1 case may bind at most one process profile.",
            )
        known_case_ids = {case.case_id for case in assets.cases}
        unknown = sorted(set(profile_ids) - known_case_ids)
        if unknown:
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_CASE_UNKNOWN",
                "CaseProcessProfile must bind an existing v1 case_id.",
            )
        self._assets = assets
        self._profiles = {profile.case_id: profile for profile in profiles}
        self._evaluator = evaluator or ContextCompatibilityEvaluator()
        self._legacy_retriever = StructuredCaseRetriever(assets)

    def retrieve(
        self,
        *,
        query_features: DerivedFeatureSet,
        product_model: str,
        top3_root_causes: tuple[str, ...],
        top_k: int,
        process_context: ProcessContext | None,
    ) -> CaseRetrievalDecision | ProcessAwareCaseRetrievalDecision:
        legacy = self._legacy_retriever.retrieve(
            query_features=query_features,
            product_model=product_model,
            top3_root_causes=top3_root_causes,
            top_k=top_k,
        )
        if process_context is None:
            return legacy

        evaluations: list[ContextualCaseEvaluation] = []
        eligible_ids: set[str] = set()
        for case in sorted(self._assets.cases, key=lambda item: item.case_id):
            profile = self._profiles.get(case.case_id)
            decision = self._evaluator.evaluate(process_context, profile)
            if decision.eligible:
                eligible_ids.add(case.case_id)
            evaluations.append(
                ContextualCaseEvaluation(
                    case_id=case.case_id,
                    eligible_for_guidance=decision.eligible,
                    reason_code=decision.reason_code.value,
                    reason_details=decision.reason_details,
                    explanation=decision.explanation,
                    profile_hash=None if profile is None else profile.profile_hash,
                    profile_source_kind=(
                        None
                        if profile is None
                        else profile.profile_provenance.source_kind.value
                    ),
                    profile_is_synthetic=(
                        False if profile is None else profile.is_synthetic
                    ),
                    compatibility_rule_version=decision.compatibility_rule_version,
                )
            )

        contextual = self._legacy_retriever.retrieve(
            query_features=query_features,
            product_model=product_model,
            top3_root_causes=top3_root_causes,
            top_k=top_k,
            eligible_case_ids=frozenset(eligible_ids),
        )
        ordered_eligible_ids = tuple(case.case_id for case in contextual.ordered_cases)
        informational_only = tuple(
            case.case_id
            for case in legacy.ordered_cases
            if case.case_id not in eligible_ids
        )
        guidance_status = (
            "CONTEXT_ELIGIBLE_CASES_FOUND"
            if ordered_eligible_ids
            else "CASE_GUIDED_UNAVAILABLE"
        )
        guidance_reason = (
            ContextCompatibilityReason.CONTEXT_MATCH.value
            if ordered_eligible_ids
            else "CONTEXT_INSUFFICIENT"
        )
        profile_set_hash = _canonical_hash(
            [self._profiles[case_id].to_payload() for case_id in sorted(self._profiles)]
        )
        business_payload = {
            "retrieval_result_version": PROCESS_AWARE_RETRIEVAL_RESULT_VERSION,
            "context_hash": process_context.context_hash,
            "context_source_kind": process_context.provenance.source_kind.value,
            "context_is_synthetic": process_context.is_synthetic,
            "profile_set_hash": profile_set_hash,
            "informational_cases": [asdict(case) for case in legacy.ordered_cases],
            "ordered_cases": [asdict(case) for case in contextual.ordered_cases],
            "case_evaluations": [asdict(item) for item in evaluations],
            "eligible_case_ids": list(ordered_eligible_ids),
            "informational_only_case_ids": list(informational_only),
            "guidance_status": guidance_status,
            "guidance_reason_code": guidance_reason,
            "query_feature_hash": contextual.query_feature_hash,
            "ordered_top3_root_causes": list(top3_root_causes),
            "product_model": product_model,
            "case_index_version": contextual.case_index_version,
            "case_index_hash": contextual.case_index_hash,
            "scaler_version": contextual.scaler_version,
            "feature_definition_version": contextual.feature_definition_version,
            "product_compatibility_rule_version": contextual.compatibility_rule_version,
            "retrieval_rule_version": contextual.retrieval_rule_version,
            "context_compatibility_rule_version": CONTEXT_COMPATIBILITY_RULE_VERSION,
        }
        result_hash = _canonical_hash(business_payload)
        return ProcessAwareCaseRetrievalDecision(
            retrieval_result_version=PROCESS_AWARE_RETRIEVAL_RESULT_VERSION,
            retrieval_result_id=f"tw-process-aware-case-retrieval-{result_hash[:16]}",
            context_hash=process_context.context_hash,
            context_source_kind=process_context.provenance.source_kind.value,
            context_is_synthetic=process_context.is_synthetic,
            profile_set_hash=profile_set_hash,
            informational_cases=legacy.ordered_cases,
            ordered_cases=contextual.ordered_cases,
            case_evaluations=tuple(evaluations),
            eligible_case_ids=ordered_eligible_ids,
            informational_only_case_ids=informational_only,
            guidance_status=guidance_status,
            guidance_reason_code=guidance_reason,
            query_feature_hash=contextual.query_feature_hash,
            ordered_top3_root_causes=top3_root_causes,
            product_model=product_model,
            case_index_version=contextual.case_index_version,
            case_index_hash=contextual.case_index_hash,
            scaler_version=contextual.scaler_version,
            feature_definition_version=contextual.feature_definition_version,
            product_compatibility_rule_version=contextual.compatibility_rule_version,
            retrieval_rule_version=contextual.retrieval_rule_version,
            context_compatibility_rule_version=CONTEXT_COMPATIBILITY_RULE_VERSION,
            result_hash=result_hash,
        )


@dataclass(frozen=True, slots=True)
class ProcessAwareCandidateGenerationDecision:
    guidance_result_version: str
    ordered_candidates: tuple[ParameterPlanCandidate, ...]
    rejected_candidates: tuple[ParameterPlanCandidate, ...]
    case_guidance_status: str
    case_guidance_reason_code: str
    eligible_case_ids: tuple[str, ...]
    supporting_case_ids: tuple[str, ...]
    retrieval_result_hash: str
    result_hash: str


class ProcessAwareParameterPlanGenerator:
    """Restricts only CASE_GUIDED evidence before using the existing generator."""

    def __init__(self, generator: ParameterPlanGenerator | None = None) -> None:
        self._generator = generator or ParameterPlanGenerator()

    def generate(
        self,
        *,
        retrieval: ProcessAwareCaseRetrievalDecision,
        root_cause: str,
        parameter_family: str,
        current_values: dict[str, str],
        direction_evidence: tuple[ParameterDirectionEvidence, ...],
        snapshot: ParameterConstraintSnapshot,
        diagnostic_result_version: str,
        cases: tuple[HistoricalCaseAction, ...],
        feature_definition_version: str,
        product_model: str,
    ) -> ProcessAwareCandidateGenerationDecision:
        eligible_ids = frozenset(retrieval.eligible_case_ids)
        guidance_cases = tuple(
            case for case in cases if case.case_id in eligible_ids
        )
        base = self._generator.generate(
            root_cause=root_cause,
            parameter_family=parameter_family,
            current_values=current_values,
            direction_evidence=direction_evidence,
            snapshot=snapshot,
            diagnostic_result_version=diagnostic_result_version,
            case_retrieval_result_version=PROCESS_AWARE_RETRIEVAL_RESULT_VERSION,
            cases=guidance_cases,
            feature_definition_version=feature_definition_version,
            product_model=product_model,
        )
        if not eligible_ids:
            base = replace(base, case_guidance_status="CONTEXT_INSUFFICIENT")
            reason_code = "CONTEXT_INSUFFICIENT"
        elif base.case_guidance_status == "COMPATIBLE_APPROVED_CASES_USED":
            reason_code = ContextCompatibilityReason.CONTEXT_MATCH.value
        else:
            reason_code = "CONTEXT_ELIGIBLE_CASE_NOT_GUIDING"
        supporting_case_ids = tuple(
            sorted(
                {
                    case_id
                    for candidate in base.ordered_candidates
                    for case_id in candidate.supporting_case_ids
                }
            )
        )
        business_payload = {
            "guidance_result_version": PROCESS_AWARE_GUIDANCE_RESULT_VERSION,
            "ordered_candidates": [asdict(item) for item in base.ordered_candidates],
            "rejected_candidates": [asdict(item) for item in base.rejected_candidates],
            "case_guidance_status": base.case_guidance_status,
            "case_guidance_reason_code": reason_code,
            "eligible_case_ids": sorted(eligible_ids),
            "supporting_case_ids": list(supporting_case_ids),
            "retrieval_result_hash": retrieval.result_hash,
        }
        return ProcessAwareCandidateGenerationDecision(
            guidance_result_version=PROCESS_AWARE_GUIDANCE_RESULT_VERSION,
            ordered_candidates=base.ordered_candidates,
            rejected_candidates=base.rejected_candidates,
            case_guidance_status=base.case_guidance_status,
            case_guidance_reason_code=reason_code,
            eligible_case_ids=tuple(sorted(eligible_ids)),
            supporting_case_ids=supporting_case_ids,
            retrieval_result_hash=retrieval.result_hash,
            result_hash=_canonical_hash(business_payload),
        )
