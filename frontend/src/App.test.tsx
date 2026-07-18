import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "./App";

const stages = [
  ["CREATED", "任务创建", "current"],
  ["DATA_IMPORTED", "数据导入", "locked"],
  ["ANOMALY_DETECTED", "异常检测", "locked"],
  ["DIAGNOSED", "根因诊断", "locked"],
  ["PLAN_READY", "候选方案", "locked"],
  ["PLAN_CONFIRMED", "人工确认", "locked"],
  ["REPLAYING", "回放执行", "locked"],
  ["REPLAYED", "回放结果", "locked"],
  ["CLOSED", "复盘关闭", "locked"],
  ["CASE_SUBMITTED", "案例提交", "locked"],
].map(([code, label, availability]) => ({ code, label, availability }));

const taskResponse = {
  task_id: "tw-demo-task-001",
  status: "CREATED",
  actor: {
    actor_id: "demo-aa-engineer",
    actor_role: "AA_PROCESS_ENGINEER",
    display_name: "AA工艺工程师",
  },
  versions: {
    public_asset_version: "tw-public-v1",
    application_version: "0.1.0",
    dataset_version: "tw-dataset-v1",
    schema_version: "tw-schema-v1",
    generator_version: "tw-generator-v1",
    rule_set_version: "tw-rules-v1",
    model_version: "tw-model-v1",
    preprocessing_version: "tw-preprocessing-v1",
    evaluation_rule_version: "tw-evaluation-v1",
    canonicalizer_version: "tw-canonicalizer-v1",
  },
  stages,
};

const importedTaskResponse = {
  ...taskResponse,
  status: "DATA_IMPORTED",
  stages: stages.map((stage, index) => ({
    ...stage,
    availability: index === 0 ? "completed" : index === 1 ? "current" : "locked",
  })),
  data_import: {
    preset_asset_id: "tw-aa-demo-v1",
    batch_id: "tw-aa-demo-batch-001",
    station_id: "AA",
    product_model: "TW-AA-PROTOTYPE-V1",
    sample_count: 24,
    validation_summary: {
      canonical_observation_hash: "PASSED",
      csv_schema: "PASSED",
      manifest: "PASSED",
      raw_file_hash: "PASSED",
      versions: "PASSED",
    },
    hashes: {
      raw_file_hash: "a7f13e1cf537f0a78c6adb482abd49a0b88e0a5fd96eeb33c0c3cef5957619b3",
      canonical_observation_hash:
        "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668",
      scenario_ref_hash: "5c210f78b07a053aebb4ddf1875f1d975d5725e9c9bf028aecedc6677796808a",
    },
    mtf_summary: {
      mtf_center: "0.831003",
      mtf_lt: "0.714968",
      mtf_rt: "0.752520",
      mtf_lb: "0.633978",
      mtf_rb: "0.567683",
      corner_mtf_min: "0.567683",
      corner_mtf_range: "0.184837",
      corner_mtf_std: "0.071709",
    },
    parameter_summary: {
      x_offset: "0.100000",
      y_offset: "-0.050000",
      pitch: "0.250000",
      roll: "-0.200000",
      z_offset: "0.000000",
    },
    platform_summary: {
      vibration_rms: "0.017882",
      repeat_position_error: "0.014082",
      calibration_residual_x: "0.005973",
      calibration_residual_y: "-0.004003",
    },
    snapshot_versions: {
      control_limit_snapshot: "tw-control-limits-v1",
      parameter_constraint_snapshot: "tw-parameter-constraints-v1",
      replay_evaluation_rule_snapshot: "tw-evaluation-v1",
    },
  },
};

const targetDetectionResult = {
  detection_result_id: "tw-detection-fixed",
  task_id: "tw-demo-task-001",
  batch_id: "tw-aa-demo-batch-001",
  anomaly_result: "TARGET_ANOMALY",
  aggregate_metrics: {
    mtf_center: "0.831003",
    mtf_lt: "0.714968",
    mtf_rt: "0.752520",
    mtf_lb: "0.633978",
    mtf_rb: "0.567683",
    corner_mtf_min: "0.567683",
    corner_mtf_range: "0.184837",
    corner_mtf_std: "0.071709",
  },
  control_limits: {
    center_lower_limit: "0.720000",
    corner_lower_limit: "0.620000",
    asymmetry_limit: "0.120000",
    corner_std_limit: "0.050000",
  },
  rule_checks: [
    {
      rule_id: "INPUT_DATA_SUFFICIENT",
      status: "PASSED",
      actual: "24",
      threshold: "8",
      operator: ">=",
      detail: "必需 Measurement 字段完整且可计算持续性。",
    },
    {
      rule_id: "GLOBAL_DEGRADATION_PROTECTION",
      status: "FAILED",
      actual: "NOT_GLOBAL",
      threshold: "PROTECTED_WHEN_PERSISTENT",
      operator: "==",
      detail: "整体退化优先于四角不对称目标异常。",
    },
    {
      rule_id: "CORNER_RANGE_LIMIT",
      status: "PASSED",
      actual: "0.184837",
      threshold: "0.120000",
      operator: ">",
      detail: "24 个样本的四角极差超过不对称限。",
    },
  ],
  persistence_evidence: {
    sample_count: 24,
    violating_sample_count: 24,
    violation_ratio: "1.000000",
    maximum_consecutive_violations: 24,
    minimum_consecutive_violations: 3,
    minimum_violation_ratio: "0.250000",
    consecutive_condition_met: true,
    ratio_condition_met: true,
  },
  control_limit_snapshot_version: "tw-control-limits-v1",
  rule_set_version: "tw-rules-v1",
  rule_snapshot_version: "tw-spc-detection-v1",
  input_data_version: "tw-dataset-v1",
  input_hash: "c74206387e06287d6c11ee8a4c6cc46cae867e6967f0c790f5dfe2f5ef940668",
  result_hash: "2".repeat(64),
  created_at: "2026-07-18T08:00:00.000000Z",
};

function detectionResponse(anomalyResult: string) {
  const target = anomalyResult === "TARGET_ANOMALY";
  const detection = {
    ...targetDetectionResult,
    anomaly_result: anomalyResult,
    aggregate_metrics:
      anomalyResult === "INSUFFICIENT_DATA"
        ? Object.fromEntries(
            Object.keys(targetDetectionResult.aggregate_metrics).map((key) => [key, null]),
          )
        : targetDetectionResult.aggregate_metrics,
    rule_checks:
      anomalyResult === "INSUFFICIENT_DATA"
        ? [
            {
              ...targetDetectionResult.rule_checks[0],
              status: "FAILED",
              actual: "7",
              detail: "样本数量 7 低于冻结规则最小值 8。",
            },
          ]
        : targetDetectionResult.rule_checks,
  };
  const task = {
    ...importedTaskResponse,
    status: target ? "ANOMALY_DETECTED" : "DATA_IMPORTED",
    stages: stages.map((stage, index) => ({
      ...stage,
      availability: target
        ? index < 2
          ? "completed"
          : index === 2
            ? "current"
            : "locked"
        : index === 0
          ? "completed"
          : index === 1
            ? "current"
            : "locked",
    })),
    anomaly_detection: detection,
  };
  return { task, detection };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders backend task identity versions and complete locked workflow", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(taskResponse), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  render(<App />);

  expect(await screen.findAllByText("AA工艺工程师")).toHaveLength(2);
  expect(screen.getByText("demo-aa-engineer")).toBeTruthy();
  expect(screen.getAllByText("AA_PROCESS_ENGINEER")).toHaveLength(2);
  expect(screen.getAllByText("CREATED")).toHaveLength(2);
  expect(screen.getByText("tw-rules-v1")).toBeTruthy();
  expect(screen.getAllByRole("listitem", { name: /阶段/ })).toHaveLength(10);
  expect(screen.getAllByText("未开放")).toHaveLength(9);
  expect(screen.queryByText(/登录|注册|权限管理|规则编辑/)).toBeNull();
});

test("provides keyboard and landmark structure for the task workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(taskResponse), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  render(<App />);

  const skipLink = await screen.findByRole("link", { name: "跳到主要内容" });
  expect(skipLink.getAttribute("href")).toBe("#workspace");
  expect(screen.getByRole("region", { name: "任务概览" })).toBeTruthy();
  expect(screen.getByRole("navigation", { name: "任务阶段" })).toBeTruthy();
});

test("renders the task status supplied by the backend response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...taskResponse, status: "SERVER_STATE" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  render(<App />);

  expect(await screen.findByText("SERVER_STATE")).toBeTruthy();
});

test("shows a clear backend asset integrity error instead of a usable task", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "PUBLIC_ASSET_HASH_MISMATCH",
            message: "公共版本资产内容哈希不匹配。",
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    ),
  );

  render(<App />);

  await waitFor(() => {
    expect(screen.getByText("公共版本资产内容哈希不匹配。")).toBeTruthy();
  });
  expect(screen.queryByText("tw-demo-task-001")).toBeNull();
});

test("imports the preset batch and renders verified metrics and hashes", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(taskResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(importedTaskResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );

  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "导入预置 AA 异常批次" }),
  );

  expect(await screen.findByText("CSV 与 Manifest 校验通过")).toBeTruthy();
  expect(screen.getAllByText("DATA_IMPORTED")).toHaveLength(2);
  expect(screen.getByText("0.831003")).toBeTruthy();
  expect(screen.getAllByText("0.567683")).toHaveLength(2);
  expect(screen.getByText("0.184837")).toBeTruthy();
  expect(screen.getByText("0.071709")).toBeTruthy();
  expect(screen.getByText("c74206387e06")).toBeTruthy();
  expect(screen.getByText("24 条观测")).toBeTruthy();
  expect(screen.getByText("已完成")).toBeTruthy();
});

test("shows an accessible loading state while import validation is pending", async () => {
  let resolveImport: (response: Response) => void = () => undefined;
  const pendingImport = new Promise<Response>((resolve) => {
    resolveImport = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(taskResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockReturnValueOnce(pendingImport),
  );

  render(<App />);
  const button = await screen.findByRole("button", { name: "导入预置 AA 异常批次" });
  fireEvent.click(button);

  expect(await screen.findByText("正在校验 CSV、Manifest 与内容哈希…")).toBeTruthy();
  expect((button as HTMLButtonElement).disabled).toBe(true);
  resolveImport(
    new Response(JSON.stringify(importedTaskResponse), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(await screen.findByText("CSV 与 Manifest 校验通过")).toBeTruthy();
});

test("renders structured import errors inline without window alert", async () => {
  const alert = vi.fn();
  vi.stubGlobal("alert", alert);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(taskResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "RAW_FILE_HASH_MISMATCH",
              message: "CSV 原始文件哈希与 DatasetManifest 不匹配。",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  fireEvent.click(
    await screen.findByRole("button", { name: "导入预置 AA 异常批次" }),
  );

  expect(
    await screen.findByText("CSV 原始文件哈希与 DatasetManifest 不匹配。"),
  ).toBeTruthy();
  expect(screen.getByText("RAW_FILE_HASH_MISMATCH")).toBeTruthy();
  expect(screen.getAllByText("CREATED")).toHaveLength(2);
  expect(alert).not.toHaveBeenCalled();
});

test.each([
  ["TARGET_ANOMALY", "检测到四角 MTF 不对称下降"],
  ["NORMAL", "未超过原型控制限"],
  ["NON_TARGET_GLOBAL_DEGRADATION", "非目标整体退化场景"],
  ["INSUFFICIENT_DATA", "数据不足，检测已保护停止"],
])("renders backend %s detection evidence and routing copy", async (result, heading) => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(importedTaskResponse), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(detectionResponse(result)), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "运行异常检测" }));

  expect(await screen.findByRole("heading", { name: heading })).toBeTruthy();
  expect(screen.getByText(result)).toBeTruthy();
  expect(screen.getByText("中心 MTF")).toBeTruthy();
  expect(screen.getByText("0.720000", { exact: false })).toBeTruthy();
  expect(screen.getByText("越限样本数量")).toBeTruthy();
  expect(screen.getByText("最大连续越限")).toBeTruthy();
  expect(screen.getByText("tw-rules-v1")).toBeTruthy();
  expect(screen.getByText("c74206387e06")).toBeTruthy();
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/tasks/tw-demo-task-001/detections",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_data_version: "tw-dataset-v1" }),
    },
  );
  if (result === "TARGET_ANOMALY") {
    expect(screen.getAllByText("ANOMALY_DETECTED")).toHaveLength(2);
  } else {
    expect(screen.getByText("主流程已停止")).toBeTruthy();
    expect(screen.getByText("不生成根因诊断或参数建议。")).toBeTruthy();
    expect(screen.getAllByText("DATA_IMPORTED")).toHaveLength(2);
  }
});

test("shows accessible detection loading and disables duplicate action", async () => {
  let resolveDetection: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    resolveDetection = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(importedTaskResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockReturnValueOnce(pending),
  );

  render(<App />);
  const action = await screen.findByRole("button", { name: "运行异常检测" });
  fireEvent.click(action);

  expect(await screen.findByText("正在执行版本化 SPC 规则…")).toBeTruthy();
  expect((action as HTMLButtonElement).disabled).toBe(true);
  resolveDetection(
    new Response(JSON.stringify(detectionResponse("TARGET_ANOMALY")), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(
    await screen.findByRole("heading", { name: "检测到四角 MTF 不对称下降" }),
  ).toBeTruthy();
});

test("renders structured detection errors inline without window alert", async () => {
  const alert = vi.fn();
  vi.stubGlobal("alert", alert);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(importedTaskResponse), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "DETECTION_INPUT_HASH_MISMATCH",
              message: "持久化 Measurement 与导入输入哈希不一致。",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "运行异常检测" }));

  expect(
    await screen.findByText("持久化 Measurement 与导入输入哈希不一致。"),
  ).toBeTruthy();
  expect(screen.getByText("DETECTION_INPUT_HASH_MISMATCH")).toBeTruthy();
  expect(alert).not.toHaveBeenCalled();
});
