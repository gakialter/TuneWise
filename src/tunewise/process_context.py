from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from .parameter_planning import (
    DEFAULT_SAFETY_POLICY,
    TICK_SIZE,
    _decimal,
    _format_decimal,
)
from .plan_confirmation import FrozenDict


PROCESS_CONTEXT_SCHEMA_VERSION = "tw-process-context-v1"
CASE_PROCESS_PROFILE_SCHEMA_VERSION = "tw-case-process-profile-v1"
CONTEXT_COMPATIBILITY_RULE_VERSION = "tw-context-compatibility-v1"
PARAMETER_VOCABULARY = frozenset(
    parameter
    for _family, parameters in DEFAULT_SAFETY_POLICY.parameter_families
    for parameter in parameters
)


class ProcessContextValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ProcessStage(StrEnum):
    INITIAL_ASSESSMENT = "INITIAL_ASSESSMENT"
    POST_ADJUSTMENT_EVALUATION = "POST_ADJUSTMENT_EVALUATION"


class PreviousActionOutcome(StrEnum):
    IMPROVED = "IMPROVED"
    NO_MATERIAL_IMPROVEMENT = "NO_MATERIAL_IMPROVEMENT"
    REGRESSED = "REGRESSED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class ProcessContextSource(StrEnum):
    BOUND_RUNTIME_EVIDENCE = "BOUND_RUNTIME_EVIDENCE"
    DECLARED_OPERATOR_CONTEXT = "DECLARED_OPERATOR_CONTEXT"
    SYNTHETIC_TEST_FIXTURE = "SYNTHETIC_TEST_FIXTURE"


class ContextCompatibilityReason(StrEnum):
    CONTEXT_MATCH = "CONTEXT_MATCH"
    PROCESS_STAGE_MISMATCH = "PROCESS_STAGE_MISMATCH"
    PREVIOUS_ACTION_PARAMETER_MISMATCH = "PREVIOUS_ACTION_PARAMETER_MISMATCH"
    PREVIOUS_OUTCOME_MISMATCH = "PREVIOUS_OUTCOME_MISMATCH"
    ITERATION_OUT_OF_RANGE = "ITERATION_OUT_OF_RANGE"
    CASE_CONTEXT_UNAVAILABLE = "CASE_CONTEXT_UNAVAILABLE"
    PROCESS_CONTEXT_NOT_PROVIDED = "PROCESS_CONTEXT_NOT_PROVIDED"
    INVALID_CONTEXT = "INVALID_CONTEXT"


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _required_text(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProcessContextValidationError(
            "PROCESS_CONTEXT_FIELD_INVALID",
            f"{field_name} must be a non-empty string.",
        )


def _evidence_value(evidence: object, name: str) -> Any:
    if isinstance(evidence, Mapping):
        return evidence.get(name)
    return getattr(evidence, name, None)


@dataclass(frozen=True, slots=True)
class ProcessContextProvenance:
    source_kind: ProcessContextSource
    source_refs: tuple[str, ...]
    source_hashes: tuple[str, ...]
    actor_id: str
    recorded_at: str

    def __post_init__(self) -> None:
        try:
            source_kind = ProcessContextSource(self.source_kind)
        except ValueError as error:
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_SOURCE_INVALID",
                "Unsupported process context provenance source.",
            ) from error
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        object.__setattr__(self, "source_hashes", tuple(self.source_hashes))
        if not self.source_refs or len(self.source_refs) != len(self.source_hashes):
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_PROVENANCE_INCOMPLETE",
                "Provenance references and hashes must be non-empty paired values.",
            )
        if any(not isinstance(ref, str) or not ref.strip() for ref in self.source_refs):
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_PROVENANCE_INCOMPLETE",
                "Provenance references must be non-empty strings.",
            )
        if any(not _is_hash(value) for value in self.source_hashes):
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_PROVENANCE_HASH_INVALID",
                "Provenance hashes must be lowercase SHA-256 values.",
            )
        _required_text(self.actor_id, "actor_id")
        _required_text(self.recorded_at, "recorded_at")
        try:
            recorded_at = datetime.fromisoformat(self.recorded_at)
        except ValueError as error:
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_RECORDED_AT_INVALID",
                "recorded_at must be ISO-8601.",
            ) from error
        if recorded_at.tzinfo is None:
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_RECORDED_AT_INVALID",
                "recorded_at must include an explicit timezone.",
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind.value,
            "source_refs": list(self.source_refs),
            "source_hashes": list(self.source_hashes),
            "actor_id": self.actor_id,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class PreviousParameterAction:
    parameter_name: str
    before_value: str
    after_value: str
    delta_ticks: int
    action_version: str
    confirmed_plan_id: str | None = None
    confirmed_plan_hash: str | None = None
    execution_receipt_id: str | None = None
    execution_receipt_hash: str | None = None

    def __post_init__(self) -> None:
        if self.parameter_name not in PARAMETER_VOCABULARY:
            raise ProcessContextValidationError(
                "PREVIOUS_ACTION_PARAMETER_INVALID",
                "Previous action parameter is outside the TuneWise vocabulary.",
            )
        before = _decimal(self.before_value)
        after = _decimal(self.after_value)
        if before is None or after is None:
            raise ProcessContextValidationError(
                "PREVIOUS_ACTION_VALUE_INVALID",
                "Previous action values must use TuneWise fixed Decimal precision.",
            )
        if (
            not isinstance(self.delta_ticks, int)
            or isinstance(self.delta_ticks, bool)
            or self.delta_ticks == 0
        ):
            raise ProcessContextValidationError(
                "PREVIOUS_ACTION_DELTA_INVALID",
                "Previous action delta_ticks must be a non-zero integer.",
            )
        if after - before != Decimal(self.delta_ticks) * TICK_SIZE:
            raise ProcessContextValidationError(
                "PREVIOUS_ACTION_DELTA_MISMATCH",
                "Previous action before/after values do not match delta_ticks.",
            )
        _required_text(self.action_version, "action_version")
        self._validate_pair(
            self.confirmed_plan_id,
            self.confirmed_plan_hash,
            "confirmed plan",
        )
        self._validate_pair(
            self.execution_receipt_id,
            self.execution_receipt_hash,
            "execution receipt",
        )
        object.__setattr__(self, "before_value", _format_decimal(before))
        object.__setattr__(self, "after_value", _format_decimal(after))

    @staticmethod
    def _validate_pair(identifier: str | None, content_hash: str | None, label: str) -> None:
        if (identifier is None) != (content_hash is None):
            raise ProcessContextValidationError(
                "PREVIOUS_ACTION_EVIDENCE_PAIR_INCOMPLETE",
                f"{label} ID and hash must be supplied together.",
            )
        if identifier is not None:
            _required_text(identifier, f"{label} ID")
            if not _is_hash(content_hash):
                raise ProcessContextValidationError(
                    "PREVIOUS_ACTION_EVIDENCE_HASH_INVALID",
                    f"{label} hash must be a lowercase SHA-256 value.",
                )

    def verify_runtime_evidence(
        self,
        *,
        confirmed_plan: object | None = None,
        execution_receipt: object | None = None,
    ) -> None:
        if confirmed_plan is not None:
            expected = {
                "confirmed_plan_id": _evidence_value(confirmed_plan, "confirmed_plan_id"),
                "confirmed_plan_hash": _evidence_value(confirmed_plan, "confirmed_plan_hash"),
            }
            current_values = _evidence_value(confirmed_plan, "current_values")
            proposed_values = _evidence_value(confirmed_plan, "proposed_values")
            delta_ticks = _evidence_value(confirmed_plan, "delta_ticks")
            if (
                self.confirmed_plan_id != expected["confirmed_plan_id"]
                or self.confirmed_plan_hash != expected["confirmed_plan_hash"]
                or not isinstance(current_values, Mapping)
                or not isinstance(proposed_values, Mapping)
                or not isinstance(delta_ticks, Mapping)
                or current_values.get(self.parameter_name) != self.before_value
                or proposed_values.get(self.parameter_name) != self.after_value
                or delta_ticks.get(self.parameter_name) != self.delta_ticks
            ):
                raise ProcessContextValidationError(
                    "PREVIOUS_ACTION_RUNTIME_EVIDENCE_MISMATCH",
                    "Declared previous action conflicts with ConfirmedPlan evidence.",
                )
        if execution_receipt is not None:
            before = _evidence_value(execution_receipt, "actual_before_value")
            if before is None:
                before = _evidence_value(execution_receipt, "expected_before_value")
            after = _evidence_value(execution_receipt, "actual_after_value")
            if after is None:
                after = _evidence_value(execution_receipt, "requested_after_value")
            if (
                self.execution_receipt_id
                != _evidence_value(execution_receipt, "device_execution_id")
                or self.execution_receipt_hash
                != _evidence_value(execution_receipt, "receipt_hash")
                or self.parameter_name
                != _evidence_value(execution_receipt, "parameter_name")
                or self.before_value != before
                or self.after_value != after
                or self.delta_ticks != _evidence_value(execution_receipt, "tick_delta")
            ):
                raise ProcessContextValidationError(
                    "PREVIOUS_ACTION_RUNTIME_EVIDENCE_MISMATCH",
                    "Declared previous action conflicts with execution receipt evidence.",
                )

    def to_payload(self) -> dict[str, object]:
        return {
            "parameter_name": self.parameter_name,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "delta_ticks": self.delta_ticks,
            "action_version": self.action_version,
            "confirmed_plan_id": self.confirmed_plan_id,
            "confirmed_plan_hash": self.confirmed_plan_hash,
            "execution_receipt_id": self.execution_receipt_id,
            "execution_receipt_hash": self.execution_receipt_hash,
        }


@dataclass(frozen=True, slots=True)
class ProcessContext:
    process_stage: ProcessStage
    iteration_index: int
    previous_measurement_hash: str | None
    previous_action: PreviousParameterAction | None
    previous_action_outcome: PreviousActionOutcome | None
    outcome_rule_version: str | None
    provenance: ProcessContextProvenance
    schema_version: str = PROCESS_CONTEXT_SCHEMA_VERSION
    context_hash: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PROCESS_CONTEXT_SCHEMA_VERSION:
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_SCHEMA_VERSION_INVALID",
                "Unsupported ProcessContext schema version.",
            )
        try:
            stage = ProcessStage(self.process_stage)
            outcome = (
                None
                if self.previous_action_outcome is None
                else PreviousActionOutcome(self.previous_action_outcome)
            )
        except ValueError as error:
            raise ProcessContextValidationError(
                "INVALID_CONTEXT", "Unsupported ProcessContext enum value."
            ) from error
        object.__setattr__(self, "process_stage", stage)
        object.__setattr__(self, "previous_action_outcome", outcome)
        if not isinstance(self.iteration_index, int) or isinstance(
            self.iteration_index, bool
        ):
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_ITERATION_INVALID",
                "iteration_index must be an integer.",
            )
        if stage is ProcessStage.INITIAL_ASSESSMENT:
            if (
                self.iteration_index != 0
                or self.previous_measurement_hash is not None
                or self.previous_action is not None
                or outcome is not None
                or self.outcome_rule_version is not None
            ):
                raise ProcessContextValidationError(
                    "INITIAL_PROCESS_CONTEXT_INVALID",
                    "Initial assessment cannot contain fabricated previous state.",
                )
        else:
            if (
                self.iteration_index < 1
                or not _is_hash(self.previous_measurement_hash)
                or self.previous_action is None
                or outcome is None
            ):
                raise ProcessContextValidationError(
                    "POST_ADJUSTMENT_PROCESS_CONTEXT_INVALID",
                    "Post-adjustment context requires bound previous state.",
                )
            evaluable = outcome is not PreviousActionOutcome.NOT_EVALUABLE
            if evaluable and not self.outcome_rule_version:
                raise ProcessContextValidationError(
                    "OUTCOME_RULE_VERSION_REQUIRED",
                    "Evaluated previous outcomes require a versioned outcome rule.",
                )
            if not evaluable and self.outcome_rule_version is not None:
                raise ProcessContextValidationError(
                    "NOT_EVALUABLE_OUTCOME_RULE_FORBIDDEN",
                    "NOT_EVALUABLE must not claim a versioned evaluated outcome.",
                )
            if (
                self.provenance.source_kind
                is ProcessContextSource.BOUND_RUNTIME_EVIDENCE
                and self.previous_action.confirmed_plan_id is None
                and self.previous_action.execution_receipt_id is None
            ):
                raise ProcessContextValidationError(
                    "BOUND_RUNTIME_EVIDENCE_MISSING",
                    "Runtime-bound process context requires a bound plan or receipt.",
                )
        expected_hash = _canonical_hash(self.business_payload())
        if self.context_hash and self.context_hash != expected_hash:
            raise ProcessContextValidationError(
                "PROCESS_CONTEXT_HASH_MISMATCH",
                "ProcessContext hash does not match canonical business content.",
            )
        object.__setattr__(self, "context_hash", expected_hash)

    @property
    def is_synthetic(self) -> bool:
        return (
            self.provenance.source_kind
            is ProcessContextSource.SYNTHETIC_TEST_FIXTURE
        )

    def business_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "process_stage": self.process_stage.value,
            "iteration_index": self.iteration_index,
            "previous_measurement_hash": self.previous_measurement_hash,
            "previous_action": (
                None if self.previous_action is None else self.previous_action.to_payload()
            ),
            "previous_action_outcome": (
                None
                if self.previous_action_outcome is None
                else self.previous_action_outcome.value
            ),
            "outcome_rule_version": self.outcome_rule_version,
            "provenance": self.provenance.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.business_payload(), "context_hash": self.context_hash}

    def canonical_json(self) -> str:
        return _canonical_bytes(self.to_payload()).decode("utf-8")

    def verify_runtime_evidence(
        self,
        *,
        confirmed_plan: object | None = None,
        execution_receipt: object | None = None,
    ) -> None:
        if self.previous_action is None:
            if confirmed_plan is not None or execution_receipt is not None:
                raise ProcessContextValidationError(
                    "PREVIOUS_ACTION_RUNTIME_EVIDENCE_MISMATCH",
                    "Initial assessment cannot bind previous runtime action evidence.",
                )
            return
        self.previous_action.verify_runtime_evidence(
            confirmed_plan=confirmed_plan,
            execution_receipt=execution_receipt,
        )


@dataclass(frozen=True, slots=True)
class CaseProcessProfile:
    case_id: str
    compatible_process_stage: ProcessStage
    previous_action_parameter: str | None
    previous_action_outcome: PreviousActionOutcome | None
    minimum_iteration: int
    maximum_iteration: int | None
    profile_provenance: ProcessContextProvenance
    process_profile_schema_version: str = CASE_PROCESS_PROFILE_SCHEMA_VERSION
    profile_hash: str = ""

    def __post_init__(self) -> None:
        _required_text(self.case_id, "case_id")
        if self.process_profile_schema_version != CASE_PROCESS_PROFILE_SCHEMA_VERSION:
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_VERSION_INVALID",
                "Unsupported CaseProcessProfile schema version.",
            )
        try:
            stage = ProcessStage(self.compatible_process_stage)
            outcome = (
                None
                if self.previous_action_outcome is None
                else PreviousActionOutcome(self.previous_action_outcome)
            )
        except ValueError as error:
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_INVALID",
                "Unsupported CaseProcessProfile enum value.",
            ) from error
        object.__setattr__(self, "compatible_process_stage", stage)
        object.__setattr__(self, "previous_action_outcome", outcome)
        if (
            not isinstance(self.minimum_iteration, int)
            or isinstance(self.minimum_iteration, bool)
            or self.minimum_iteration < 0
            or (
                self.maximum_iteration is not None
                and (
                    not isinstance(self.maximum_iteration, int)
                    or isinstance(self.maximum_iteration, bool)
                    or self.maximum_iteration < self.minimum_iteration
                )
            )
        ):
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_ITERATION_INVALID",
                "Case process profile iteration range is invalid.",
            )
        if stage is ProcessStage.INITIAL_ASSESSMENT:
            if (
                self.previous_action_parameter is not None
                or outcome is not None
                or self.minimum_iteration != 0
                or self.maximum_iteration not in (None, 0)
            ):
                raise ProcessContextValidationError(
                    "CASE_PROCESS_PROFILE_INVALID",
                    "Initial profiles cannot claim previous action facts.",
                )
        else:
            if self.minimum_iteration < 1:
                raise ProcessContextValidationError(
                    "CASE_PROCESS_PROFILE_INVALID",
                    "Post-adjustment profiles must start at iteration one or later.",
                )
            if self.previous_action_parameter is not None:
                if self.previous_action_parameter not in PARAMETER_VOCABULARY:
                    raise ProcessContextValidationError(
                        "CASE_PROCESS_PROFILE_INVALID",
                        "Profile previous-action parameter is outside the TuneWise vocabulary.",
                    )
        expected_hash = _canonical_hash(self.business_payload())
        if self.profile_hash and self.profile_hash != expected_hash:
            raise ProcessContextValidationError(
                "CASE_PROCESS_PROFILE_HASH_MISMATCH",
                "CaseProcessProfile hash does not match canonical business content.",
            )
        object.__setattr__(self, "profile_hash", expected_hash)

    @property
    def is_synthetic(self) -> bool:
        return (
            self.profile_provenance.source_kind
            is ProcessContextSource.SYNTHETIC_TEST_FIXTURE
        )

    def business_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "process_profile_schema_version": self.process_profile_schema_version,
            "compatible_process_stage": self.compatible_process_stage.value,
            "previous_action_parameter": self.previous_action_parameter,
            "previous_action_outcome": (
                None
                if self.previous_action_outcome is None
                else self.previous_action_outcome.value
            ),
            "minimum_iteration": self.minimum_iteration,
            "maximum_iteration": self.maximum_iteration,
            "profile_provenance": self.profile_provenance.to_payload(),
        }

    def to_payload(self) -> dict[str, object]:
        return {**self.business_payload(), "profile_hash": self.profile_hash}


@dataclass(frozen=True, slots=True)
class ContextCompatibilityDecision:
    eligible: bool
    reason_code: ContextCompatibilityReason
    reason_details: FrozenDict
    explanation: str
    compatibility_rule_version: str = CONTEXT_COMPATIBILITY_RULE_VERSION


class ContextCompatibilityEvaluator:
    _EXPLANATIONS = {
        ContextCompatibilityReason.CONTEXT_MATCH: "Case process profile matches the supplied process context.",
        ContextCompatibilityReason.PROCESS_STAGE_MISMATCH: "Case process stage does not match the supplied process stage.",
        ContextCompatibilityReason.PREVIOUS_ACTION_PARAMETER_MISMATCH: "Case previous-action parameter does not match the supplied previous action.",
        ContextCompatibilityReason.PREVIOUS_OUTCOME_MISMATCH: "Case previous outcome does not match the supplied previous outcome.",
        ContextCompatibilityReason.ITERATION_OUT_OF_RANGE: "Process iteration is outside the case profile range.",
        ContextCompatibilityReason.CASE_CONTEXT_UNAVAILABLE: "Case has no process-labelled profile and is informational only.",
        ContextCompatibilityReason.PROCESS_CONTEXT_NOT_PROVIDED: "No process context was supplied; legacy v1 eligibility applies.",
        ContextCompatibilityReason.INVALID_CONTEXT: "Process context is invalid.",
    }

    def evaluate(
        self,
        context: ProcessContext | None,
        profile: CaseProcessProfile | None,
    ) -> ContextCompatibilityDecision:
        if context is None:
            return self._decision(
                True,
                ContextCompatibilityReason.PROCESS_CONTEXT_NOT_PROVIDED,
                {"legacy_behavior": True},
            )
        if not isinstance(context, ProcessContext):
            return self._decision(
                False,
                ContextCompatibilityReason.INVALID_CONTEXT,
                {"expected_schema_version": PROCESS_CONTEXT_SCHEMA_VERSION},
            )
        if profile is None:
            return self._decision(
                False,
                ContextCompatibilityReason.CASE_CONTEXT_UNAVAILABLE,
                {"context_hash": context.context_hash},
            )
        if profile.compatible_process_stage is not context.process_stage:
            return self._decision(
                False,
                ContextCompatibilityReason.PROCESS_STAGE_MISMATCH,
                {
                    "actual": context.process_stage.value,
                    "expected": profile.compatible_process_stage.value,
                },
            )
        if not (
            profile.minimum_iteration <= context.iteration_index
            and (
                profile.maximum_iteration is None
                or context.iteration_index <= profile.maximum_iteration
            )
        ):
            return self._decision(
                False,
                ContextCompatibilityReason.ITERATION_OUT_OF_RANGE,
                {
                    "actual": context.iteration_index,
                    "minimum": profile.minimum_iteration,
                    "maximum": profile.maximum_iteration,
                },
            )
        actual_parameter = (
            None
            if context.previous_action is None
            else context.previous_action.parameter_name
        )
        if (
            profile.previous_action_parameter is not None
            and profile.previous_action_parameter != actual_parameter
        ):
            return self._decision(
                False,
                ContextCompatibilityReason.PREVIOUS_ACTION_PARAMETER_MISMATCH,
                {
                    "actual": actual_parameter,
                    "expected": profile.previous_action_parameter,
                },
            )
        if (
            profile.previous_action_outcome is not None
            and profile.previous_action_outcome is not context.previous_action_outcome
        ):
            return self._decision(
                False,
                ContextCompatibilityReason.PREVIOUS_OUTCOME_MISMATCH,
                {
                    "actual": (
                        None
                        if context.previous_action_outcome is None
                        else context.previous_action_outcome.value
                    ),
                    "expected": profile.previous_action_outcome.value,
                },
            )
        return self._decision(
            True,
            ContextCompatibilityReason.CONTEXT_MATCH,
            {
                "case_id": profile.case_id,
                "context_hash": context.context_hash,
                "profile_hash": profile.profile_hash,
            },
        )

    def _decision(
        self,
        eligible: bool,
        reason_code: ContextCompatibilityReason,
        details: dict[str, object],
    ) -> ContextCompatibilityDecision:
        return ContextCompatibilityDecision(
            eligible=eligible,
            reason_code=reason_code,
            reason_details=FrozenDict(sorted(details.items())),
            explanation=self._EXPLANATIONS[reason_code],
        )


def provenance_from_payload(payload: Mapping[str, object]) -> ProcessContextProvenance:
    try:
        return ProcessContextProvenance(
            source_kind=ProcessContextSource(str(payload["source_kind"])),
            source_refs=tuple(str(item) for item in payload["source_refs"]),
            source_hashes=tuple(str(item) for item in payload["source_hashes"]),
            actor_id=str(payload["actor_id"]),
            recorded_at=str(payload["recorded_at"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ProcessContextValidationError):
            raise
        raise ProcessContextValidationError(
            "PROCESS_CONTEXT_PROVENANCE_INVALID",
            "Process context provenance payload is invalid.",
        ) from error


def process_context_from_payload(payload: Mapping[str, object]) -> ProcessContext:
    try:
        action_payload = payload.get("previous_action")
        action = (
            None
            if action_payload is None
            else PreviousParameterAction(**dict(action_payload))
        )
        return ProcessContext(
            schema_version=str(payload["schema_version"]),
            process_stage=ProcessStage(str(payload["process_stage"])),
            iteration_index=payload["iteration_index"],
            previous_measurement_hash=payload.get("previous_measurement_hash"),
            previous_action=action,
            previous_action_outcome=(
                None
                if payload.get("previous_action_outcome") is None
                else PreviousActionOutcome(str(payload["previous_action_outcome"]))
            ),
            outcome_rule_version=payload.get("outcome_rule_version"),
            provenance=provenance_from_payload(dict(payload["provenance"])),
            context_hash=str(payload.get("context_hash", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ProcessContextValidationError):
            raise
        raise ProcessContextValidationError(
            "INVALID_CONTEXT", "ProcessContext payload is invalid."
        ) from error


def case_process_profile_from_payload(
    payload: Mapping[str, object],
) -> CaseProcessProfile:
    try:
        return CaseProcessProfile(
            case_id=str(payload["case_id"]),
            process_profile_schema_version=str(
                payload["process_profile_schema_version"]
            ),
            compatible_process_stage=ProcessStage(
                str(payload["compatible_process_stage"])
            ),
            previous_action_parameter=payload.get("previous_action_parameter"),
            previous_action_outcome=(
                None
                if payload.get("previous_action_outcome") is None
                else PreviousActionOutcome(str(payload["previous_action_outcome"]))
            ),
            minimum_iteration=payload["minimum_iteration"],
            maximum_iteration=payload.get("maximum_iteration"),
            profile_provenance=provenance_from_payload(
                dict(payload["profile_provenance"])
            ),
            profile_hash=str(payload.get("profile_hash", "")),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ProcessContextValidationError):
            raise
        raise ProcessContextValidationError(
            "CASE_PROCESS_PROFILE_INVALID",
            "CaseProcessProfile payload is invalid.",
        ) from error
