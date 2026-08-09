export type Actor = {
  actor_id: string;
  actor_role: string;
  display_name: string;
};

export type VersionSnapshot = {
  public_asset_version: string;
  application_version: string;
  dataset_version: string;
  schema_version: string;
  generator_version: string;
  rule_set_version: string;
  model_version: string;
  preprocessing_version: string;
  evaluation_rule_version: string;
  canonicalizer_version: string;
};

export type WorkflowStage = {
  code: string;
  label: string;
  availability: "completed" | "current" | "locked";
};

export type Task = {
  task_id: string;
  status: string;
  actor: Actor;
  versions: VersionSnapshot;
  stages: WorkflowStage[];
  data_import?: DataImportSummary | null;
  anomaly_detection?: AnomalyDetectionResult | null;
  diagnostic_result?: DiagnosticResult | null;
  parameter_planning_result?: ParameterPlanningResult | null;
  confirmed_plan?: ConfirmedPlan | null;
  replay_result?: ReplayResult | null;
};

export type DiagnosticEvidence = {
  rule_id: string;
  status: "PASSED" | "FAILED";
  detail: string;
};

export type DiagnosticCandidate = {
  rank: number;
  root_cause: string;
  normalized_score: string;
  raw_logit: string;
  adjustability: "ADJUSTABLE" | "INSPECTION_ONLY";
  matched_explicit_rules: DiagnosticEvidence[];
  key_observations: { feature_name: string; value: string; summary: string }[];
  positive_logit_contributions: {
    feature_name: string;
    feature_index: number;
    standardized_feature_value: string;
    class_coefficient: string;
    contribution: string;
    description: string;
  }[];
  conflict_evidence: DiagnosticEvidence[];
  model_version: string;
  preprocessing_version: string;
  feature_definition_version: string;
};

export type DiagnosticResult = {
  diagnostic_result_version: string;
  diagnostic_result_id: string;
  task_id: string;
  detection_result_id: string;
  input_data_version: string;
  input_feature_hash: string;
  anomaly_result: "TARGET_ANOMALY";
  ordered_top3: DiagnosticCandidate[];
  evidence_status: "SUFFICIENT_EVIDENCE" | "INSUFFICIENT_EVIDENCE";
  evidence_checks: DiagnosticEvidence[];
  z_gate_result: {
    status: "PASSED" | "REMOVED";
    passed: boolean;
    checks: DiagnosticEvidence[];
    removed_category: string | null;
  };
  model_version: string;
  preprocessing_version: string;
  feature_definition_version: string;
  evidence_rule_version: string;
  input_asset_hashes: Record<string, string>;
  result_hash: string;
  created_at: string;
  parameter_candidate_count: number;
};

export type DiagnosisResponse = {
  task: Task;
  diagnostic: DiagnosticResult;
};

export type KeyFeatureDifference = {
  feature_name: string;
  feature_index: number;
  standardized_absolute_difference: string;
  query_value: string;
  case_value: string;
};

export type RetrievedApprovedCase = {
  rank: number;
  case_id: string;
  retrieval_stage: "TOP3_ROOT_CAUSE" | "COMPATIBLE_FALLBACK";
  distance: string;
  similarity_display_value: string;
  key_feature_differences: KeyFeatureDifference[];
  reviewed_root_cause: string;
  historical_action: {
    context: string;
    summary: string;
    action_version?: string;
    parameter_delta_ticks?: Record<string, number>;
    historical_safety_status?: string;
    historical_safety_rule_version?: string;
  };
  historical_simulated_result: {
    context_label: string;
    status: string;
    summary: string;
    center_mtf_change?: string;
    center_regression_tolerance?: string;
    center_within_tolerance?: boolean;
  };
  applicability_conditions: string[];
  product_model: string;
  source_version_summary: Record<string, string>;
  case_content_hash: string;
  case_index_version: string;
};

export type CaseRetrievalResult = {
  retrieval_result_version: string;
  retrieval_result_id: string;
  task_id: string;
  diagnostic_result_id: string;
  query_feature_hash: string;
  ordered_top3_root_causes: string[];
  ordered_cases: RetrievedApprovedCase[];
  retrieval_status:
    | "CASES_FOUND"
    | "PARTIAL_RESULTS"
    | "NO_RELEVANT_CASE_AVAILABLE";
  requested_count: number;
  returned_count: number;
  shortfall_message: string | null;
  case_index_version: string;
  case_index_hash: string;
  scaler_version: string;
  feature_definition_version: string;
  compatibility_rule_version: string;
  retrieval_rule_version: string;
  input_hash: string;
  result_hash: string;
  created_at: string;
};

export type CaseRetrievalResponse = {
  retrieval: CaseRetrievalResult;
};

export type ParameterConstraint = {
  parameter_name: string;
  nominal_value: string;
  minimum: string;
  maximum: string;
  step: string;
  maximum_single_plan_delta: string;
};

export type ParameterDirectionEvidence = {
  parameter_name: string;
  current_value: string;
  current_tick: number | null;
  nominal_value: string;
  nominal_tick: number;
  recommended_direction: "INCREASE" | "DECREASE";
  supporting_features: string[];
  supporting_rules: string[];
  conflicting_features: string[];
  conflict_status: "NO_CONFLICT" | "CONFLICT" | "INSUFFICIENT_SUPPORT";
  diagnostic_result_version: string;
  feature_definition_version: string;
  direction_rule_version: string;
  evidence_hash: string;
};

export type ParameterValidationCheck = {
  check_code: string;
  status: "PASSED" | "FAILED";
  detail: string;
};

export type ParameterPlanCandidate = {
  candidate_id: string;
  generation_type: "CONSERVATIVE" | "STANDARD" | "CASE_GUIDED";
  generation_sources: string[];
  root_cause: string;
  parameter_family: string;
  current_values: Record<string, string>;
  proposed_values: Record<string, string>;
  current_ticks: Record<string, number | null>;
  proposed_ticks: Record<string, number | null>;
  deltas: Record<string, string>;
  delta_ticks: Record<string, number | null>;
  total_absolute_delta_ticks: number;
  direction_evidence: ParameterDirectionEvidence[];
  supporting_case_ids: string[];
  supporting_case_count: number;
  constraint_snapshot_version: string;
  rule_set_version: string;
  direction_rule_version: string;
  safety_rule_version: string;
  diagnostic_result_version: string;
  case_retrieval_result_version: string | null;
  validation_checks: ParameterValidationCheck[];
  validation_status: "PASSED" | "REJECTED";
  rejection_reasons: string[];
  candidate_hash: string;
};

export type ParameterPlanningResult = {
  planning_result_version: string;
  planning_result_id: string;
  task_id: string;
  diagnostic_result_id: string;
  case_retrieval_result_id: string | null;
  top1_root_cause: string;
  direction_evidence: ParameterDirectionEvidence[];
  ordered_candidates: ParameterPlanCandidate[];
  parameter_constraints: ParameterConstraint[];
  planning_status: "CANDIDATES_AVAILABLE" | "PARAMETER_RECOMMENDATION_REFUSED";
  refusal_code: string | null;
  refusal_message: string | null;
  supporting_evidence: string[];
  recommended_inspection_actions: string[];
  case_guidance_status: string;
  input_hash: string;
  result_hash: string;
  created_at: string;
  constraint_snapshot_version: string;
  rule_set_version: string;
  direction_rule_version: string;
  safety_rule_version: string;
  planning_rule_version: string;
  feature_definition_version: string;
  diagnostic_result_version: string;
  case_retrieval_result_version: string | null;
  planning_asset_manifest_hash: string;
};

export type ParameterPlanningResponse = {
  task: Task;
  planning: ParameterPlanningResult;
};

export type ConfirmedPlan = {
  confirmed_plan_id: string;
  confirmed_plan_version: string;
  confirmed_plan_hash: string;
  task_id: string;
  planning_result_id: string;
  planning_result_version: string;
  candidate_id: string;
  candidate_hash: string;
  current_values: Record<string, string>;
  proposed_values: Record<string, string>;
  deltas: Record<string, string>;
  delta_ticks: Record<string, number | null>;
  parameter_family: string;
  root_cause: string;
  generation_type: string;
  supporting_case_ids: string[];
  direction_evidence_hashes: string[];
  actor_id: string;
  actor_role: string;
  display_name: string;
  confirmed_at: string;
  status: "VALID" | "STALE";
  stale_reason_codes: string[];
  freshness_rule_version: string;
  input_data_version: string;
  input_measurement_hash: string;
  current_parameter_hash: string;
  detection_result_id: string;
  detection_result_version: string;
  diagnostic_result_id: string;
  diagnostic_result_version: string;
  case_retrieval_result_id: string | null;
  case_retrieval_result_version: string | null;
  control_limit_snapshot_version: string;
  control_limit_snapshot_hash: string;
  parameter_constraint_snapshot_version: string;
  parameter_constraint_snapshot_hash: string;
  direction_rule_version: string;
  safety_rule_version: string;
  planning_rule_version: string;
  rule_set_version: string;
  feature_definition_version: string;
  model_version: string;
  preprocessing_version: string;
  approved_case_index_version: string | null;
  source_asset_hashes: Record<string, string>;
  created_at: string;
};

export type PlanConfirmationResponse = {
  task: Task;
  confirmed_plan: ConfirmedPlan;
};

export type ReplayMetrics = {
  sample_count: number;
  mtf_center_mean: string;
  mtf_center_std: string;
  mtf_lt_mean: string;
  mtf_rt_mean: string;
  mtf_lb_mean: string;
  mtf_rb_mean: string;
  corner_mtf_mean: string;
  corner_mtf_min: string;
  corner_mtf_range: string;
  corner_mtf_std: string;
  center_corner_gap: string;
  control_limit_pass: boolean;
  target_anomaly_triggered: boolean;
  parameter_summary: Record<string, string>;
  metric_definition_version: string;
  standard_deviation_method: "POPULATION";
};

export type ReplayEvaluationCheck = {
  check_id: string;
  metric: string;
  before_value: string | boolean;
  after_value: string | boolean;
  delta: string;
  threshold: string | null;
  tolerance: string | null;
  status: "PASSED" | "FAILED";
  rule_version: string;
  explanation_template_key: string;
};

export type ReplayResult = {
  replay_result_id: string;
  replay_result_version: string;
  task_id: string;
  confirmed_plan_id: string;
  confirmed_plan_hash: string;
  candidate_id: string;
  candidate_hash: string;
  request_idempotency_key_hash: string;
  replay_status: "SUCCESS" | "PARTIAL_IMPROVEMENT" | "NO_IMPROVEMENT" | "REGRESSION";
  attempt_count: number;
  dataset_version: string;
  schema_version: string;
  generator_version: string;
  rule_set_version: string;
  model_version: string;
  simulator_version: string;
  replay_scenario_schema_version: string;
  scenario_mapping_version: string;
  scenario_ref_hash: string;
  disturbance_sequence_hash: string;
  replay_seed_hash: string;
  baseline_input_hash: string;
  intervention_input_hash: string;
  canonicalizer_version: string;
  replay_result_canonicalizer_version: string;
  imported_baseline_canonical_hash: string;
  simulated_baseline_canonical_hash: string;
  baseline_reproduction_status: "PASSED";
  baseline_metrics: ReplayMetrics;
  intervention_metrics: ReplayMetrics;
  metric_deltas: Record<string, string>;
  evaluation_checks: ReplayEvaluationCheck[];
  replay_evaluation_rule_version: string;
  input_asset_hashes: Record<string, string>;
  pairing_invariants: Record<string, string>;
  before_observation_hash: string;
  after_observation_hash: string;
  baseline_output_hash: string;
  intervention_output_hash: string;
  result_hash: string;
  created_at: string;
  completed_at: string;
  disclaimer_version: string;
  disclaimer: string;
  no_device_write_notice: string;
};

export type ReplayResponse = {
  task: Task;
  replay_result: ReplayResult;
};

export type DeviceExecutionEligibility = {
  eligible: boolean;
  code: string;
  message: string;
  execution_mode: string;
  gateway_version: string;
  node_mapping_version: string;
  endpoint_local_id: string;
  endpoint_fingerprint: string;
  observed_server_identity_hash: string | null;
  observed_application_uri: string | null;
  security_profile: string | null;
  device_connected: boolean;
  device_status: string;
  safety_gate_status: string;
  replay_status: string | null;
  parameter_name: string | null;
  node_id: string | null;
  expected_before_value: string | null;
  actual_before_value: string | null;
  requested_after_value: string | null;
  tick_delta: number | null;
  disclaimer: string;
};

export type DeviceExecutionReceipt = {
  receipt_version: string;
  receipt_canonicalizer_version: string;
  state_machine_version: string;
  device_execution_id: string;
  task_id: string;
  confirmed_plan_id: string;
  confirmed_plan_hash: string;
  replay_result_id: string | null;
  replay_result_hash: string | null;
  execution_mode: string;
  gateway_version: string;
  namespace_uri: string;
  node_mapping_version: string;
  endpoint_local_id: string;
  endpoint_fingerprint: string;
  observed_server_identity_hash: string | null;
  observed_application_uri: string | null;
  security_profile: string | null;
  certificate_fingerprint: string | null;
  parameter_name: string | null;
  node_id: string | null;
  expected_before_value: string | null;
  actual_before_value: string | null;
  requested_after_value: string | null;
  actual_after_value: string | null;
  tick_delta: number | null;
  safety_validator_version: string | null;
  validation_result: string;
  execution_status:
    | "REJECTED"
    | "FAILED_DEFINITE"
    | "UNKNOWN_OUTCOME"
    | "RECONCILIATION_REQUIRED"
    | "SUCCEEDED";
  failure_stage: string | null;
  failure_code: string | null;
  message: string;
  device_status: string | null;
  actor_id: string;
  actor_role: string;
  display_name: string;
  started_at: string;
  completed_at: string;
  idempotency_key: string;
  attempt_count: number;
  internal_retry_count: number;
  write_attempt_count: number;
  state_trace: string[];
  disclaimer: string;
  receipt_hash: string;
};

export type DeviceExecutionResponse = {
  device_execution: DeviceExecutionReceipt;
  idempotent_replay: boolean;
};

export type RuleCheck = {
  rule_id: string;
  status: "PASSED" | "FAILED" | "NOT_EVALUATED";
  actual: string | null;
  threshold: string | null;
  operator: string | null;
  detail: string;
};

export type AnomalyDetectionResult = {
  detection_result_id: string;
  task_id: string;
  batch_id: string;
  anomaly_result:
    | "TARGET_ANOMALY"
    | "NORMAL"
    | "NON_TARGET_GLOBAL_DEGRADATION"
    | "INSUFFICIENT_DATA";
  aggregate_metrics: {
    mtf_center: string | null;
    mtf_lt: string | null;
    mtf_rt: string | null;
    mtf_lb: string | null;
    mtf_rb: string | null;
    corner_mtf_min: string | null;
    corner_mtf_range: string | null;
    corner_mtf_std: string | null;
  };
  control_limits: {
    center_lower_limit: string;
    corner_lower_limit: string;
    asymmetry_limit: string;
    corner_std_limit: string;
  };
  rule_checks: RuleCheck[];
  persistence_evidence: {
    sample_count: number;
    violating_sample_count: number;
    violation_ratio: string;
    maximum_consecutive_violations: number;
    minimum_consecutive_violations: number;
    minimum_violation_ratio: string;
    consecutive_condition_met: boolean;
    ratio_condition_met: boolean;
  };
  control_limit_snapshot_version: string;
  rule_set_version: string;
  rule_snapshot_version: string;
  input_data_version: string;
  input_hash: string;
  result_hash: string;
  created_at: string;
};

export type DetectionResponse = {
  task: Task;
  detection: AnomalyDetectionResult;
};

export type DataImportSummary = {
  preset_asset_id: string;
  batch_id: string;
  station_id: string;
  product_model: string;
  sample_count: number;
  validation_summary: Record<string, string>;
  hashes: {
    raw_file_hash: string;
    canonical_observation_hash: string;
    scenario_ref_hash: string;
  };
  mtf_summary: {
    mtf_center: string;
    mtf_lt: string;
    mtf_rt: string;
    mtf_lb: string;
    mtf_rb: string;
    corner_mtf_min: string;
    corner_mtf_range: string;
    corner_mtf_std: string;
  };
  parameter_summary: Record<string, string>;
  platform_summary: Record<string, string>;
  snapshot_versions: Record<string, string>;
};

type ErrorPayload = {
  error?: {
    code?: string;
    message?: string;
  };
};

export class TaskCreationError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}
export async function createInitialTask(): Promise<Task> {
  const response = await fetch("/api/tasks/initial", { method: "POST" });
  const payload = (await response.json()) as Task | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "TASK_CREATION_FAILED",
      error?.message ?? "无法创建本地调机任务。",
    );
  }
  return payload as Task;
}

export async function importPresetAsset(taskId: string): Promise<Task> {
  const response = await fetch(`/api/tasks/${taskId}/imports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ preset_asset_id: "tw-aa-demo-v1" }),
  });
  const payload = (await response.json()) as Task | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "DATA_IMPORT_FAILED",
      error?.message ?? "无法导入预置 AA 批次。",
    );
  }
  return payload as Task;
}

export async function runAnomalyDetection(
  taskId: string,
  inputDataVersion: string,
): Promise<DetectionResponse> {
  const response = await fetch(`/api/tasks/${taskId}/detections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input_data_version: inputDataVersion }),
  });
  const payload = (await response.json()) as DetectionResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "ANOMALY_DETECTION_FAILED",
      error?.message ?? "无法运行异常检测。",
    );
  }
  return payload as DetectionResponse;
}

export async function runRootCauseDiagnosis(
  taskId: string,
  detectionResultId: string,
): Promise<DiagnosisResponse> {
  const response = await fetch(`/api/tasks/${taskId}/diagnoses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ detection_result_id: detectionResultId }),
  });
  const payload = (await response.json()) as DiagnosisResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "ROOT_CAUSE_DIAGNOSIS_FAILED",
      error?.message ?? "无法运行根因诊断。",
    );
  }
  return payload as DiagnosisResponse;
}

export async function retrieveApprovedCases(
  taskId: string,
  diagnosticResultId: string,
): Promise<CaseRetrievalResponse> {
  const response = await fetch(`/api/tasks/${taskId}/case-retrievals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ diagnostic_result_id: diagnosticResultId, top_k: 3 }),
  });
  const payload = (await response.json()) as CaseRetrievalResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "APPROVED_CASE_RETRIEVAL_FAILED",
      error?.message ?? "无法检索已审核相似案例。",
    );
  }
  return payload as CaseRetrievalResponse;
}

export async function generateParameterPlans(
  taskId: string,
  diagnosticResultId: string,
  caseRetrievalResultId: string | null,
): Promise<ParameterPlanningResponse> {
  const response = await fetch(`/api/tasks/${taskId}/parameter-plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      diagnostic_result_id: diagnosticResultId,
      case_retrieval_result_id: caseRetrievalResultId,
    }),
  });
  const payload = (await response.json()) as ParameterPlanningResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "PARAMETER_PLANNING_FAILED",
      error?.message ?? "无法生成安全参数候选。",
    );
  }
  return payload as ParameterPlanningResponse;
}

export async function confirmParameterPlan(
  taskId: string,
  candidateId: string,
  candidateHash: string,
): Promise<PlanConfirmationResponse> {
  const response = await fetch(`/api/tasks/${taskId}/confirmed-plans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      candidate_id: candidateId,
      candidate_hash: candidateHash,
    }),
  });
  const payload = (await response.json()) as PlanConfirmationResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "PLAN_CONFIRMATION_FAILED",
      error?.message ?? "无法人工确认候选方案。",
    );
  }
  return payload as PlanConfirmationResponse;
}

export async function runPairedReplay(
  taskId: string,
  confirmedPlanId: string,
  confirmedPlanHash: string,
): Promise<ReplayResponse> {
  const response = await fetch(`/api/tasks/${taskId}/replays`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      task_id: taskId,
      confirmed_plan_id: confirmedPlanId,
      confirmed_plan_hash: confirmedPlanHash,
      request_idempotency_key: `tw-replay-${confirmedPlanId}`,
    }),
  });
  const payload = (await response.json()) as ReplayResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "PAIRED_REPLAY_FAILED",
      error?.message ?? "无法运行确定性配对模拟干预回放。",
    );
  }
  return payload as ReplayResponse;
}

export async function getDeviceExecutionEligibility(
  taskId: string,
  confirmedPlanId: string,
  confirmedPlanHash: string,
): Promise<DeviceExecutionEligibility> {
  const query = new URLSearchParams({
    confirmed_plan_id: confirmedPlanId,
    confirmed_plan_hash: confirmedPlanHash,
  });
  const response = await fetch(
    `/api/tasks/${taskId}/device-executions/eligibility?${query.toString()}`,
  );
  const payload = (await response.json()) as DeviceExecutionEligibility | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "DEVICE_EXECUTION_ELIGIBILITY_FAILED",
      error?.message ?? "无法检查本地模拟设备执行资格。",
    );
  }
  return payload as DeviceExecutionEligibility;
}

export async function executeControlledDeviceWrite(
  taskId: string,
  confirmedPlanId: string,
  confirmedPlanHash: string,
): Promise<DeviceExecutionResponse> {
  const response = await fetch(`/api/tasks/${taskId}/device-executions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      confirmed_plan_id: confirmedPlanId,
      confirmed_plan_hash: confirmedPlanHash,
      execution_mode: "OPCUA_SANDBOX",
      sandbox_execution_acknowledged: true,
    }),
  });
  const payload = (await response.json()) as DeviceExecutionResponse | ErrorPayload;
  if (!response.ok) {
    const error = (payload as ErrorPayload).error;
    throw new TaskCreationError(
      error?.code ?? "DEVICE_EXECUTION_FAILED",
      error?.message ?? "本地模拟设备受控下发失败。",
    );
  }
  return payload as DeviceExecutionResponse;
}
