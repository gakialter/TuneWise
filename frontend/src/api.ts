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
