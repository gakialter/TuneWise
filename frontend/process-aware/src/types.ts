export interface ProcessAwareDemoResponse {
  demo_version: string;
  title: string;
  facts_boundary: string;
  abstraction_note: string;
  synthetic: boolean;
  provenance: DemoProvenance;
  shared_evidence: SharedEvidence;
  scenarios: ProcessAwareScenario[];
  unchanged_controls: UnchangedControls;
}

export interface DemoProvenance {
  source_kind: string;
  fixture_version: string;
  fixture_manifest_hash: string;
  demo_dataset_asset_id: string;
}

export interface SharedEvidence {
  measurement_evidence_label: string;
  measurement_hash: string;
  query_feature_hash: string;
  feature_dimension: number;
  feature_definition_version: string;
  diagnostic_model_version: string;
  preprocessing_version: string;
  scaler_version: string;
  case_index_hash: string;
  ordered_root_causes: RankedRootCause[];
  top1_root_cause: string;
  same_across_scenarios: boolean;
}

export interface RankedRootCause {
  rank: number;
  root_cause: string;
}

export interface ProcessAwareScenario {
  scenario_id: string;
  process_context: ProcessContext;
  eligible_case: EligibleCase;
  case_guided_candidate: CandidateSummary;
}

export interface ProcessContext {
  process_stage: string;
  process_stage_display: LocalizedLabel;
  iteration_index: number;
  previous_action: PreviousAction | null;
  previous_action_outcome: string | null;
  previous_action_outcome_display: LocalizedLabel | null;
  source_kind: string;
  synthetic: boolean;
  context_hash: string;
}

export interface LocalizedLabel {
  zh: string;
  en: string;
}

export interface PreviousAction {
  parameter_name: string;
  before_value: string;
  after_value: string;
  delta_ticks: number;
  action_version: string;
}

export interface EligibleCase {
  case_id: string;
  distance: string;
  compatibility: ContextCompatibility;
  process_profile: CaseProcessProfile;
  historical_action: HistoricalAction;
}

export interface ContextCompatibility {
  reason_code: string;
  explanation: string;
}

export interface CaseProcessProfile {
  compatible_process_stage: string;
  previous_action_parameter: string | null;
  previous_action_outcome: string | null;
  minimum_iteration: number;
  maximum_iteration: number | null;
  source_kind: string;
  synthetic: boolean;
  profile_hash: string;
}

export interface HistoricalAction {
  parameter_delta_ticks: Record<string, number>;
  action_version: string;
  historical_safety_status: string;
}

export interface CandidateSummary {
  candidate_id: string;
  candidate_hash: string;
  generation_type: string;
  parameter_name: string;
  current_value: string;
  proposed_value: string;
  delta_value: string;
  delta_ticks: number;
  supporting_case_ids: string[];
  validation_status: string;
  safety_rule_version: string;
  validation_checks: ValidationCheck[];
}

export interface ValidationCheck {
  check_code: string;
  status: string;
}

export interface UnchangedControls {
  identical_across_scenarios: boolean;
  conservative_candidate: CandidateSummary;
  standard_candidate: CandidateSummary;
  safety_validator: SafetyValidatorSummary;
  scenario_candidate_hashes: {
    A: ScenarioControlHashes;
    B: ScenarioControlHashes;
  };
}

export interface ScenarioControlHashes {
  CONSERVATIVE: string;
  STANDARD: string;
}

export interface SafetyValidatorSummary {
  unchanged_across_scenarios: boolean;
  safety_rule_version: string;
  status: string;
  validation_checks: ValidationCheck[];
}
