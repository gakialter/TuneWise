from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .assets import AssetIntegrityError, PublicAssetLoader
from .case_retrieval import (
    ApprovedCase,
    ApprovedCaseAssetLoader,
    CaseRetrievalAssets,
)
from .detection import ControlLimitRegistry, canonical_measurement_hash
from .diagnosis import DiagnosticAssetLoader, FeatureEngineer, RootCauseDiagnoser
from .diagnostic_contract import DIAGNOSTIC_RESULT_VERSION, FEATURE_NAMES, PARAMETER_FIELDS
from .importing import DemoDatasetImporter, ImportedDataset
from .parameter_planning import (
    DirectionEvidenceGenerator,
    HistoricalCaseAction,
    ParameterConstraintSnapshot,
    ParameterPlanCandidate,
    ParameterPlanGenerator,
    ParameterPlanningAssetLoader,
    ParameterSafetyValidator,
)
from .process_aware_retrieval import (
    ProcessAwareCaseRetrievalDecision,
    ProcessAwareCaseRetriever,
    ProcessAwareParameterPlanGenerator,
)
from .process_context import (
    CaseProcessProfile,
    ProcessContext,
    ProcessContextValidationError,
    case_process_profile_from_payload,
    process_context_from_payload,
)


PROCESS_AWARE_DEMO_VERSION = "tw-process-aware-demo-v1"
PROCESS_AWARE_FIXTURE_VERSION = "tw-process-aware-demo-fixture-v1"
PROCESS_AWARE_FIXTURE_FILE = "process-aware-demo.json"
SYNTHETIC_SOURCE_KIND = "SYNTHETIC_TEST_FIXTURE"
PROCESS_AWARE_DEMO_TITLE = "Process-aware Decision Demo"
FACTS_BOUNDARY = (
    "Synthetic process-context demonstration.\n"
    "Demonstrates deterministic context-sensitive evidence selection.\n"
    "Does not represent Sunny Optical SOP or validated production tuning accuracy."
)
ABSTRACTION_NOTE = (
    "TuneWise process-context abstractions; not industry-standard states."
)

_EXPECTED_ASSET_BINDINGS = {
    "dataset": {
        "asset_id": "tw-aa-demo-v1",
        "manifest_hash": (
            "d66077f880e6d4c470772be30a771ca20d26520ab39c08fc4f4340fa4e31950c"
        ),
        "measurement_hash": (
            "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668"
        ),
        "query_feature_hash": (
            "7fa3c96138dbeb938466fcd12b00b2b8c1a9fcb61ee78dcad77f29a545462040"
        ),
    },
    "diagnostic": {
        "manifest_hash": (
            "d2d287fcd830771c3b8c6e91f41152d950ea2a02820107c1ca802fb268b5ed4b"
        ),
        "model_version": "tw-model-v1",
        "preprocessing_version": "tw-preprocessing-v1",
        "feature_definition_version": "tw-feature-definition-v1",
        "ordered_top3_root_causes": [
            "PLANE_TILT",
            "XY_DECENTER",
            "REFERENCE_DRIFT",
        ],
    },
    "cases": {
        "manifest_hash": (
            "3259575b170a617a9314a7c6883d829b64df9a022be7a90529bf7e50db7acb81"
        ),
        "approved_case_count": 60,
        "case_index_hash": (
            "a97ecb3790741390f6eb87ba3e47af863090338d48dfbb641dfd6a1593661755"
        ),
        "scaler_version": "tw-case-retrieval-scaler-v1",
    },
    "planning": {
        "manifest_hash": (
            "fc73d61a29bcfbe89ab3b8f34cd0cf7436ff10c0716c59be8882b21be2881f4b"
        ),
        "planning_rule_version": "tw-parameter-planning-v1",
        "safety_rule_version": "tw-parameter-safety-v1",
    },
}
_EXPECTED_CONTEXT_HASHES = (
    "125937228baf4e3a145e343309ef9e9cc7d6aeb20d0b717ebad3031daeab28f6",
    "765e6d2af105ef6e9429654125b95385f8b2788d457fb12cd5744852ad99c7e0",
)
_EXPECTED_PROFILE_HASHES = (
    "d32cb2acd5026f587d79e61b8e6829740076832a509e0d7154c364c1a86b06c6",
    "3fd8dd44abb6b65e2eabba02443ec996dee6171d501d1095463fff20f8bd4e05",
)
_EXPECTED_ELIGIBLE_CASES = {"A": "tw-aa-approved-011", "B": "tw-aa-approved-003"}
_STAGE_DISPLAYS = {
    "INITIAL_ASSESSMENT": {"zh": "初始评估", "en": "Initial Assessment"},
    "POST_ADJUSTMENT_EVALUATION": {
        "zh": "调整后评估",
        "en": "Post-adjustment Evaluation",
    },
}
_OUTCOME_DISPLAYS = {
    "NO_MATERIAL_IMPROVEMENT": {
        "zh": "未观察到显著改善",
        "en": "No Material Improvement",
    }
}


class ProcessAwareDemoAssetError(AssetIntegrityError):
    """Fails the optional demonstration closed on any fixture drift."""


@dataclass(frozen=True, slots=True)
class ProcessAwareDemoFixture:
    title: str
    facts_boundary: str
    abstraction_note: str
    asset_bindings: dict[str, Any]
    scenarios: tuple[tuple[str, ProcessContext], ...]
    profiles: tuple[CaseProcessProfile, ...]
    manifest_hash: str


class ProcessAwareDemoFixtureLoader:
    def __init__(self, root: Path, expected_manifest_hash: str) -> None:
        self._root = root.resolve()
        self._expected_manifest_hash = expected_manifest_hash

    def load(self) -> ProcessAwareDemoFixture:
        manifest_bytes = self._read("manifest.json")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != self._expected_manifest_hash:
            self._raise(
                "PROCESS_AWARE_DEMO_MANIFEST_HASH_MISMATCH",
                "Process-aware demo fixture manifest does not match the trusted hash.",
            )
        manifest = self._json(manifest_bytes, "manifest.json")
        if (
            set(manifest)
            != {
                "manifest_version",
                "demo_version",
                "fixture_version",
                "source_kind",
                "synthetic",
                "files",
            }
            or manifest["manifest_version"] != "1"
            or manifest["demo_version"] != PROCESS_AWARE_DEMO_VERSION
            or manifest["fixture_version"] != PROCESS_AWARE_FIXTURE_VERSION
            or manifest["source_kind"] != SYNTHETIC_SOURCE_KIND
            or manifest["synthetic"] is not True
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != {PROCESS_AWARE_FIXTURE_FILE}
            or not self._is_hash(manifest["files"][PROCESS_AWARE_FIXTURE_FILE])
        ):
            self._raise(
                "PROCESS_AWARE_DEMO_MANIFEST_INVALID",
                "Process-aware demo fixture manifest is invalid or unsupported.",
            )

        fixture_bytes = self._read(PROCESS_AWARE_FIXTURE_FILE)
        if (
            hashlib.sha256(fixture_bytes).hexdigest()
            != manifest["files"][PROCESS_AWARE_FIXTURE_FILE]
        ):
            self._raise(
                "PROCESS_AWARE_DEMO_ASSET_HASH_MISMATCH",
                "Process-aware demo fixture content does not match its manifest.",
            )
        payload = self._json(fixture_bytes, PROCESS_AWARE_FIXTURE_FILE)
        self._validate_fixture_header(payload)

        try:
            raw_contexts = payload["contexts"]
            raw_profiles = payload["case_process_profiles"]
            if not isinstance(raw_contexts, list) or not isinstance(raw_profiles, list):
                raise TypeError
            scenarios = tuple(
                (
                    str(item["scenario_id"]),
                    process_context_from_payload(
                        {key: value for key, value in item.items() if key != "scenario_id"}
                    ),
                )
                for item in raw_contexts
                if isinstance(item, Mapping)
            )
            profiles = tuple(
                case_process_profile_from_payload(item)
                for item in raw_profiles
                if isinstance(item, Mapping)
            )
        except (KeyError, TypeError, ValueError, ProcessContextValidationError) as error:
            self._raise(
                "PROCESS_AWARE_DEMO_FIXTURE_INVALID",
                "Process-aware demo contexts or process profiles are invalid.",
                error,
            )
        self._validate_contexts_and_profiles(scenarios, profiles)
        return ProcessAwareDemoFixture(
            title=payload["title"],
            facts_boundary=payload["facts_boundary"],
            abstraction_note=payload["abstraction_note"],
            asset_bindings=dict(payload["asset_bindings"]),
            scenarios=scenarios,
            profiles=profiles,
            manifest_hash=manifest_hash,
        )

    def _read(self, relative_path: str) -> bytes:
        pure = PurePosixPath(relative_path)
        path = (self._root / Path(*pure.parts)).resolve()
        if pure.is_absolute() or ".." in pure.parts or not path.is_relative_to(self._root):
            self._raise(
                "PROCESS_AWARE_DEMO_ASSET_PATH_FORBIDDEN",
                "Process-aware demo assets must remain inside the configured root.",
            )
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            self._raise(
                "PROCESS_AWARE_DEMO_ASSET_MISSING",
                f"Process-aware demo asset is missing: {relative_path}.",
                error,
            )

    def _json(self, content: bytes, name: str) -> dict[str, Any]:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._raise(
                "PROCESS_AWARE_DEMO_ASSET_INVALID",
                f"Process-aware demo asset is not valid JSON: {name}.",
                error,
            )
        if not isinstance(payload, dict):
            self._raise(
                "PROCESS_AWARE_DEMO_ASSET_INVALID",
                f"Process-aware demo asset must be a JSON object: {name}.",
            )
        return payload

    def _validate_fixture_header(self, payload: dict[str, Any]) -> None:
        if (
            set(payload)
            != {
                "fixture_version",
                "demo_version",
                "title",
                "facts_boundary",
                "abstraction_note",
                "source_kind",
                "synthetic",
                "asset_bindings",
                "contexts",
                "case_process_profiles",
            }
            or payload["fixture_version"] != PROCESS_AWARE_FIXTURE_VERSION
            or payload["demo_version"] != PROCESS_AWARE_DEMO_VERSION
            or payload["title"] != PROCESS_AWARE_DEMO_TITLE
            or payload["facts_boundary"] != FACTS_BOUNDARY
            or payload["abstraction_note"] != ABSTRACTION_NOTE
            or payload["source_kind"] != SYNTHETIC_SOURCE_KIND
            or payload["synthetic"] is not True
            or payload["asset_bindings"] != _EXPECTED_ASSET_BINDINGS
        ):
            self._raise(
                "PROCESS_AWARE_DEMO_FIXTURE_BINDING_MISMATCH",
                "Process-aware demo fixture header or fixed asset bindings changed.",
            )

    def _validate_contexts_and_profiles(
        self,
        scenarios: tuple[tuple[str, ProcessContext], ...],
        profiles: tuple[CaseProcessProfile, ...],
    ) -> None:
        if (
            tuple(scenario_id for scenario_id, _context in scenarios) != ("A", "B")
            or tuple(context.context_hash for _scenario_id, context in scenarios)
            != _EXPECTED_CONTEXT_HASHES
            or not all(context.is_synthetic for _scenario_id, context in scenarios)
            or tuple(profile.case_id for profile in profiles)
            != ("tw-aa-approved-011", "tw-aa-approved-003")
            or tuple(profile.profile_hash for profile in profiles)
            != _EXPECTED_PROFILE_HASHES
            or not all(profile.is_synthetic for profile in profiles)
        ):
            self._raise(
                "PROCESS_AWARE_DEMO_FIXTURE_BINDING_MISMATCH",
                "Process-aware demo A/B context or case profile bindings changed.",
            )

    @staticmethod
    def _is_hash(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _raise(code: str, message: str, cause: Exception | None = None) -> None:
        error = ProcessAwareDemoAssetError(code, message)
        if cause is None:
            raise error
        raise error from cause


class ProcessAwareDemoService:
    """Pure, read-only assembly of a fixed process-context A/B demonstration."""

    def __init__(
        self,
        *,
        public_asset_loader: PublicAssetLoader,
        fixture_root: Path,
        expected_fixture_manifest_hash: str,
        demo_asset_root: Path,
        expected_dataset_manifest_hash: str,
        diagnostic_asset_root: Path,
        expected_diagnostic_manifest_hash: str,
        case_asset_root: Path,
        expected_case_manifest_hash: str,
        planning_asset_root: Path,
        expected_planning_manifest_hash: str,
    ) -> None:
        self._public_asset_loader = public_asset_loader
        self._fixture_loader = ProcessAwareDemoFixtureLoader(
            fixture_root, expected_fixture_manifest_hash
        )
        self._demo_asset_root = demo_asset_root
        self._expected_dataset_manifest_hash = expected_dataset_manifest_hash
        self._diagnostic_asset_root = diagnostic_asset_root
        self._expected_diagnostic_manifest_hash = expected_diagnostic_manifest_hash
        self._case_asset_root = case_asset_root
        self._expected_case_manifest_hash = expected_case_manifest_hash
        self._planning_asset_root = planning_asset_root
        self._expected_planning_manifest_hash = expected_planning_manifest_hash

    def get_demo(self) -> dict[str, Any]:
        fixture = self._fixture_loader.load()
        self._validate_configured_bindings(fixture)
        public_assets = self._public_asset_loader.load()
        imported = DemoDatasetImporter(
            self._demo_asset_root,
            self._expected_dataset_manifest_hash,
            public_assets.versions,
        ).load("tw-aa-demo-v1")
        measurement_hash = canonical_measurement_hash(imported.measurements)
        features = FeatureEngineer().derive(imported.measurements)
        diagnostic_assets = DiagnosticAssetLoader(
            self._diagnostic_asset_root,
            self._expected_diagnostic_manifest_hash,
        ).load()
        diagnosis = RootCauseDiagnoser(diagnostic_assets).diagnose(
            features,
            ControlLimitRegistry.snapshot_for(public_assets.versions.rule_set_version),
        )
        case_assets = ApprovedCaseAssetLoader(
            self._case_asset_root,
            self._expected_case_manifest_hash,
        ).load()
        planning_assets = ParameterPlanningAssetLoader(
            self._planning_asset_root,
            self._expected_planning_manifest_hash,
        ).load()
        self._validate_computed_bindings(
            fixture=fixture,
            imported=imported,
            measurement_hash=measurement_hash,
            query_feature_hash=features.input_feature_hash,
            feature_count=len(features.values),
            diagnostic_assets=diagnostic_assets,
            diagnosis=diagnosis,
            case_assets=case_assets,
            planning_assets=planning_assets,
            public_versions=public_assets.versions,
        )

        top3 = tuple(item.root_cause for item in diagnosis.ordered_top3)
        retriever = ProcessAwareCaseRetriever(case_assets, fixture.profiles)
        retrievals: dict[str, ProcessAwareCaseRetrievalDecision] = {}
        for scenario_id, context in fixture.scenarios:
            decision = retriever.retrieve(
                query_features=features,
                product_model=imported.summary.product_model,
                top3_root_causes=top3,
                top_k=3,
                process_context=context,
            )
            if not isinstance(decision, ProcessAwareCaseRetrievalDecision):
                self._fail("Process-aware retrieval unexpectedly used the legacy path.")
            expected_case_id = _EXPECTED_ELIGIBLE_CASES[scenario_id]
            if (
                decision.eligible_case_ids != (expected_case_id,)
                or len(decision.ordered_cases) != 1
                or decision.ordered_cases[0].case_id != expected_case_id
                or decision.query_feature_hash != features.input_feature_hash
                or decision.ordered_top3_root_causes != top3
                or decision.case_index_hash != case_assets.index_file_hash
            ):
                self._fail("Process-aware retrieval A/B evidence binding changed.")
            retrievals[scenario_id] = decision

        snapshot = ParameterConstraintSnapshot.from_payload(
            imported.parameter_constraints
        )
        current_values = self._current_values(imported)
        feature_values = {
            name: f"{value:.12f}"
            for name, value in zip(
                features.feature_names, features.values, strict=True
            )
        }
        direction = DirectionEvidenceGenerator(planning_assets.direction_rules).generate(
            root_cause=top3[0],
            current_values=current_values,
            features=feature_values,
            snapshot=snapshot,
            diagnostic_result_version=DIAGNOSTIC_RESULT_VERSION,
            feature_definition_version=diagnosis.feature_definition_version,
            z_gate_passed=diagnosis.z_gate_result.passed,
        )
        if tuple(item.parameter_name for item in direction.usable_evidence) != (
            "pitch",
        ):
            self._fail("Fixed demo direction evidence no longer isolates pitch.")

        historical_cases = tuple(
            self._historical_case(case) for case in case_assets.cases
        )
        generator = ProcessAwareParameterPlanGenerator(
            ParameterPlanGenerator(
                validator=ParameterSafetyValidator(planning_assets.safety_policy),
                planning_policy=planning_assets.planning_policy,
            )
        )
        parameter_family = planning_assets.safety_policy.family_for_root_cause(top3[0])
        if parameter_family is None:
            self._fail("Fixed demo Top-1 no longer maps to a safe parameter family.")
        plans = {
            scenario_id: generator.generate(
                retrieval=retrievals[scenario_id],
                root_cause=top3[0],
                parameter_family=parameter_family,
                current_values=current_values,
                direction_evidence=direction.usable_evidence,
                snapshot=snapshot,
                diagnostic_result_version=DIAGNOSTIC_RESULT_VERSION,
                cases=historical_cases,
                feature_definition_version=diagnosis.feature_definition_version,
                product_model=imported.summary.product_model,
            )
            for scenario_id, _context in fixture.scenarios
        }
        candidates = {
            scenario_id: {
                generation_type: self._candidate(plan.ordered_candidates, generation_type)
                for generation_type in ("CONSERVATIVE", "STANDARD", "CASE_GUIDED")
            }
            for scenario_id, plan in plans.items()
        }
        self._validate_candidate_invariants(candidates)

        profiles = {profile.case_id: profile for profile in fixture.profiles}
        scenarios = [
            self._scenario_payload(
                scenario_id=scenario_id,
                context=context,
                profile=profiles[_EXPECTED_ELIGIBLE_CASES[scenario_id]],
                retrieval=retrievals[scenario_id],
                case_guided=candidates[scenario_id]["CASE_GUIDED"],
            )
            for scenario_id, context in fixture.scenarios
        ]
        conservative = candidates["A"]["CONSERVATIVE"]
        standard = candidates["A"]["STANDARD"]
        check_summary = self._validation_checks(conservative)
        return {
            "demo_version": PROCESS_AWARE_DEMO_VERSION,
            "title": fixture.title,
            "facts_boundary": fixture.facts_boundary,
            "abstraction_note": fixture.abstraction_note,
            "synthetic": True,
            "provenance": {
                "source_kind": SYNTHETIC_SOURCE_KIND,
                "fixture_version": PROCESS_AWARE_FIXTURE_VERSION,
                "fixture_manifest_hash": fixture.manifest_hash,
                "demo_dataset_asset_id": imported.summary.preset_asset_id,
            },
            "shared_evidence": {
                "measurement_evidence_label": "Same measurement evidence",
                "measurement_hash": measurement_hash,
                "query_feature_hash": features.input_feature_hash,
                "feature_dimension": len(FEATURE_NAMES),
                "feature_definition_version": diagnosis.feature_definition_version,
                "diagnostic_model_version": diagnosis.model_version,
                "preprocessing_version": diagnosis.preprocessing_version,
                "scaler_version": case_assets.scaler_version,
                "case_index_hash": case_assets.index_file_hash,
                "ordered_root_causes": [
                    {"rank": item.rank, "root_cause": item.root_cause}
                    for item in diagnosis.ordered_top3
                ],
                "top1_root_cause": diagnosis.ordered_top3[0].root_cause,
                "same_across_scenarios": True,
            },
            "scenarios": scenarios,
            "unchanged_controls": {
                "identical_across_scenarios": True,
                "conservative_candidate": self._candidate_summary(conservative),
                "standard_candidate": self._candidate_summary(standard),
                "scenario_candidate_hashes": {
                    scenario_id: {
                        generation_type: candidates[scenario_id][
                            generation_type
                        ].candidate_hash
                        for generation_type in ("CONSERVATIVE", "STANDARD")
                    }
                    for scenario_id in ("A", "B")
                },
                "safety_validator": {
                    "unchanged_across_scenarios": True,
                    "safety_rule_version": conservative.safety_rule_version,
                    "status": "PASSED",
                    "validation_checks": check_summary,
                },
            },
        }

    def _validate_configured_bindings(
        self, fixture: ProcessAwareDemoFixture
    ) -> None:
        configured = {
            "dataset": self._expected_dataset_manifest_hash,
            "diagnostic": self._expected_diagnostic_manifest_hash,
            "cases": self._expected_case_manifest_hash,
            "planning": self._expected_planning_manifest_hash,
        }
        if any(
            configured[name] != fixture.asset_bindings[name]["manifest_hash"]
            for name in configured
        ):
            self._fail("Configured source asset hashes do not match the demo fixture.")

    def _validate_computed_bindings(
        self,
        *,
        fixture: ProcessAwareDemoFixture,
        imported: ImportedDataset,
        measurement_hash: str,
        query_feature_hash: str,
        feature_count: int,
        diagnostic_assets: Any,
        diagnosis: Any,
        case_assets: CaseRetrievalAssets,
        planning_assets: Any,
        public_versions: Any,
    ) -> None:
        bindings = fixture.asset_bindings
        top3 = [item.root_cause for item in diagnosis.ordered_top3]
        snapshot_content = (
            json.dumps(
                imported.parameter_constraints,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        if (
            imported.summary.preset_asset_id != bindings["dataset"]["asset_id"]
            or imported.summary.product_model != "TW-AA-PROTOTYPE-V1"
            or measurement_hash != bindings["dataset"]["measurement_hash"]
            or measurement_hash
            != imported.summary.hashes.canonical_observation_hash
            or query_feature_hash != bindings["dataset"]["query_feature_hash"]
            or feature_count != len(FEATURE_NAMES)
            or len(FEATURE_NAMES) != 50
            or diagnostic_assets.model["model_version"]
            != bindings["diagnostic"]["model_version"]
            or diagnostic_assets.preprocessing["preprocessing_version"]
            != bindings["diagnostic"]["preprocessing_version"]
            or diagnosis.feature_definition_version
            != bindings["diagnostic"]["feature_definition_version"]
            or top3 != bindings["diagnostic"]["ordered_top3_root_causes"]
            or diagnosis.model_version != public_versions.model_version
            or diagnosis.preprocessing_version
            != public_versions.preprocessing_version
            or diagnosis.evidence_status != "SUFFICIENT_EVIDENCE"
            or len(case_assets.cases) != bindings["cases"]["approved_case_count"]
            or case_assets.index_file_hash != bindings["cases"]["case_index_hash"]
            or case_assets.scaler_version != bindings["cases"]["scaler_version"]
            or case_assets.manifest.get("rule_set_version")
            != public_versions.rule_set_version
            or planning_assets.planning_policy.planning_rule_version
            != bindings["planning"]["planning_rule_version"]
            or planning_assets.safety_policy.safety_rule_version
            != bindings["planning"]["safety_rule_version"]
            or planning_assets.safety_policy.rule_set_version
            != public_versions.rule_set_version
            or hashlib.sha256(snapshot_content).hexdigest()
            != planning_assets.expected_parameter_constraint_snapshot_hash
        ):
            self._fail("Computed frozen evidence no longer matches the demo fixture.")

    @staticmethod
    def _current_values(imported: ImportedDataset) -> dict[str, str]:
        current: dict[str, str] = {}
        for name in PARAMETER_FIELDS:
            try:
                values = {Decimal(row[name]) for row in imported.measurements}
            except (KeyError, InvalidOperation, TypeError) as error:
                raise ProcessAwareDemoAssetError(
                    "PROCESS_AWARE_DEMO_SOURCE_BINDING_MISMATCH",
                    "Fixed demo current parameter values are invalid.",
                ) from error
            if len(values) != 1:
                raise ProcessAwareDemoAssetError(
                    "PROCESS_AWARE_DEMO_SOURCE_BINDING_MISMATCH",
                    "Fixed demo does not contain one deterministic parameter baseline.",
                )
            current[name] = f"{next(iter(values)):.6f}"
        return current

    @staticmethod
    def _historical_case(case: ApprovedCase) -> HistoricalCaseAction:
        action = case.historical_action
        result = case.historical_simulated_result
        return HistoricalCaseAction(
            case_id=case.case_id,
            status=case.status,
            source_partition=case.source_partition,
            source_partition_id=case.source_partition_id,
            station_type=case.station_type,
            product_model=case.product_model,
            reviewed_root_cause=case.reviewed_root_cause,
            parameter_family=case.parameter_family or "",
            parameter_delta_ticks=dict(action["parameter_delta_ticks"]),
            action_version=action["action_version"],
            historical_safety_status=action["historical_safety_status"],
            historical_safety_rule_version=action[
                "historical_safety_rule_version"
            ],
            historical_simulated_result_status=result["status"],
            center_within_tolerance=result["center_within_tolerance"],
            feature_definition_version=case.feature_definition_version,
            rule_set_version=case.rule_set_version,
            retrieval_rule_version=case.retrieval_rule_version,
            case_schema_version=case.case_schema_version,
        )

    @staticmethod
    def _candidate(
        candidates: tuple[ParameterPlanCandidate, ...], generation_type: str
    ) -> ParameterPlanCandidate:
        matches = tuple(
            candidate
            for candidate in candidates
            if candidate.generation_type == generation_type
        )
        if len(matches) != 1:
            raise ProcessAwareDemoAssetError(
                "PROCESS_AWARE_DEMO_SOURCE_BINDING_MISMATCH",
                f"Fixed demo candidate is missing or ambiguous: {generation_type}.",
            )
        return matches[0]

    def _validate_candidate_invariants(
        self, candidates: dict[str, dict[str, ParameterPlanCandidate]]
    ) -> None:
        if (
            candidates["A"]["CONSERVATIVE"]
            != candidates["B"]["CONSERVATIVE"]
            or candidates["A"]["STANDARD"] != candidates["B"]["STANDARD"]
            or candidates["A"]["CASE_GUIDED"].delta_ticks != {"pitch": -3}
            or candidates["B"]["CASE_GUIDED"].delta_ticks != {"pitch": -4}
            or candidates["A"]["CASE_GUIDED"].supporting_case_ids
            != ("tw-aa-approved-011",)
            or candidates["B"]["CASE_GUIDED"].supporting_case_ids
            != ("tw-aa-approved-003",)
        ):
            self._fail("Fixed demo candidate A/B invariants changed.")
        all_candidates = tuple(
            candidate
            for scenario in ("A", "B")
            for candidate in candidates[scenario].values()
        )
        signatures = {
            tuple(
                (check.check_code, check.status)
                for check in candidate.validation_checks
            )
            for candidate in all_candidates
        }
        if (
            any(candidate.validation_status != "PASSED" for candidate in all_candidates)
            or len(signatures) != 1
            or any(
                check.status != "PASSED"
                for candidate in all_candidates
                for check in candidate.validation_checks
            )
        ):
            self._fail("ParameterSafetyValidator evidence changed across A/B.")

    def _scenario_payload(
        self,
        *,
        scenario_id: str,
        context: ProcessContext,
        profile: CaseProcessProfile,
        retrieval: ProcessAwareCaseRetrievalDecision,
        case_guided: ParameterPlanCandidate,
    ) -> dict[str, Any]:
        eligible_case_id = _EXPECTED_ELIGIBLE_CASES[scenario_id]
        evaluation = next(
            item
            for item in retrieval.case_evaluations
            if item.case_id == eligible_case_id
        )
        retrieved = retrieval.ordered_cases[0]
        if (
            evaluation.reason_code != "CONTEXT_MATCH"
            or not evaluation.profile_is_synthetic
            or profile.profile_hash != evaluation.profile_hash
        ):
            self._fail("Eligible case compatibility evidence is not a synthetic match.")
        action = context.previous_action
        outcome = (
            None
            if context.previous_action_outcome is None
            else context.previous_action_outcome.value
        )
        return {
            "scenario_id": scenario_id,
            "process_context": {
                "process_stage": context.process_stage.value,
                "process_stage_display": dict(
                    _STAGE_DISPLAYS[context.process_stage.value]
                ),
                "iteration_index": context.iteration_index,
                "previous_action": (
                    None
                    if action is None
                    else {
                        "parameter_name": action.parameter_name,
                        "before_value": action.before_value,
                        "after_value": action.after_value,
                        "delta_ticks": action.delta_ticks,
                        "action_version": action.action_version,
                    }
                ),
                "previous_action_outcome": outcome,
                "previous_action_outcome_display": (
                    None if outcome is None else dict(_OUTCOME_DISPLAYS[outcome])
                ),
                "source_kind": context.provenance.source_kind.value,
                "synthetic": context.is_synthetic,
                "context_hash": context.context_hash,
            },
            "eligible_case": {
                "case_id": retrieved.case_id,
                "distance": retrieved.distance,
                "compatibility": {
                    "reason_code": evaluation.reason_code,
                    "explanation": evaluation.explanation,
                },
                "process_profile": {
                    "compatible_process_stage": profile.compatible_process_stage.value,
                    "previous_action_parameter": profile.previous_action_parameter,
                    "previous_action_outcome": (
                        None
                        if profile.previous_action_outcome is None
                        else profile.previous_action_outcome.value
                    ),
                    "minimum_iteration": profile.minimum_iteration,
                    "maximum_iteration": profile.maximum_iteration,
                    "source_kind": profile.profile_provenance.source_kind.value,
                    "synthetic": profile.is_synthetic,
                    "profile_hash": profile.profile_hash,
                },
                "historical_action": {
                    "parameter_delta_ticks": dict(
                        retrieved.historical_action["parameter_delta_ticks"]
                    ),
                    "action_version": retrieved.historical_action["action_version"],
                    "historical_safety_status": retrieved.historical_action[
                        "historical_safety_status"
                    ],
                },
            },
            "case_guided_candidate": self._candidate_summary(case_guided),
        }

    @staticmethod
    def _candidate_summary(candidate: ParameterPlanCandidate) -> dict[str, Any]:
        parameters = tuple(sorted(candidate.delta_ticks))
        if len(parameters) != 1:
            raise ProcessAwareDemoAssetError(
                "PROCESS_AWARE_DEMO_SOURCE_BINDING_MISMATCH",
                "Process-aware demo candidate must adjust exactly one parameter.",
            )
        parameter = parameters[0]
        return {
            "candidate_id": candidate.candidate_id,
            "candidate_hash": candidate.candidate_hash,
            "generation_type": candidate.generation_type,
            "parameter_name": parameter,
            "current_value": candidate.current_values[parameter],
            "proposed_value": candidate.proposed_values[parameter],
            "delta_value": candidate.deltas[parameter],
            "delta_ticks": candidate.delta_ticks[parameter],
            "supporting_case_ids": list(candidate.supporting_case_ids),
            "validation_status": candidate.validation_status,
            "safety_rule_version": candidate.safety_rule_version,
            "validation_checks": ProcessAwareDemoService._validation_checks(
                candidate
            ),
        }

    @staticmethod
    def _validation_checks(
        candidate: ParameterPlanCandidate,
    ) -> list[dict[str, str]]:
        return [
            {"check_code": check.check_code, "status": check.status}
            for check in candidate.validation_checks
        ]

    @staticmethod
    def _fail(message: str) -> None:
        raise ProcessAwareDemoAssetError(
            "PROCESS_AWARE_DEMO_SOURCE_BINDING_MISMATCH", message
        )
