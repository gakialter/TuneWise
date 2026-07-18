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
