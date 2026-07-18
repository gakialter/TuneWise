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

const diagnosticResult = {
  diagnostic_result_version: "tw-diagnostic-result-v1",
  diagnostic_result_id: "tw-diagnostic-fixed",
  task_id: "tw-demo-task-001",
  detection_result_id: "tw-detection-fixed",
  input_data_version: "tw-dataset-v1",
  input_feature_hash: "3".repeat(64),
  anomaly_result: "TARGET_ANOMALY",
  ordered_top3: [
    ["PLANE_TILT", "0.982100", "ADJUSTABLE"],
    ["XY_DECENTER", "0.012300", "ADJUSTABLE"],
    ["REFERENCE_DRIFT", "0.004200", "INSPECTION_ONLY"],
  ].map(([root_cause, normalized_score, adjustability], index) => ({
    rank: index + 1,
    root_cause,
    normalized_score,
    raw_logit: `${5 - index}.000000`,
    adjustability,
    matched_explicit_rules: [
      { rule_id: `${root_cause}_RULE`, status: "PASSED", detail: "显式规则已命中。" },
    ],
    key_observations: [
      { feature_name: "top_bottom_difference", value: "0.132914", summary: "上下差异达到空间支持阈值。" },
    ],
    positive_logit_contributions: [
      {
        feature_name: "top_bottom_difference",
        feature_index: 48,
        standardized_feature_value: "2.000000000000",
        class_coefficient: "0.500000000000",
        contribution: "1.000000",
        description: "该特征对当前类别 logit 的贡献",
      },
      {
        feature_name: "pitch_mean",
        feature_index: 24,
        standardized_feature_value: "1.500000000000",
        class_coefficient: "0.400000000000",
        contribution: "0.600000",
        description: "该特征对当前类别 logit 的贡献",
      },
      {
        feature_name: "roll_mean",
        feature_index: 27,
        standardized_feature_value: "-1.200000000000",
        class_coefficient: "-0.300000000000",
        contribution: "0.360000",
        description: "该特征对当前类别 logit 的贡献",
      },
    ],
    conflict_evidence: [],
    model_version: "tw-model-v1",
    preprocessing_version: "tw-preprocessing-v1",
    feature_definition_version: "tw-feature-definition-v1",
  })),
  evidence_status: "SUFFICIENT_EVIDENCE",
  evidence_checks: [
    { rule_id: "TOP1_SCORE_MINIMUM", status: "PASSED", detail: "Top-1 相对分数满足阈值。" },
  ],
  z_gate_result: {
    status: "REMOVED",
    passed: false,
    removed_category: "Z_DEFOCUS_CONDITIONAL",
    checks: [
      { rule_id: "Z_CENTER_NEAR_LOWER_LIMIT", status: "FAILED", detail: "中心 MTF 未接近下限。" },
    ],
  },
  model_version: "tw-model-v1",
  preprocessing_version: "tw-preprocessing-v1",
  feature_definition_version: "tw-feature-definition-v1",
  evidence_rule_version: "tw-evidence-rules-v1",
  input_asset_hashes: { "model.json": "4".repeat(64) },
  result_hash: "5".repeat(64),
  created_at: "2026-07-18T08:01:00.000000Z",
  parameter_candidate_count: 0,
};

function diagnosisResponse(evidenceStatus = "SUFFICIENT_EVIDENCE") {
  const diagnostic = { ...diagnosticResult, evidence_status: evidenceStatus };
  return {
    task: {
      ...detectionResponse("TARGET_ANOMALY").task,
      status: "DIAGNOSED",
      stages: stages.map((stage, index) => ({
        ...stage,
        availability: index < 3 ? "completed" : index === 3 ? "current" : "locked",
      })),
      diagnostic_result: diagnostic,
    },
    diagnostic,
  };
}

const retrievedCases = [
  ["tw-aa-approved-011", "PLANE_TILT", "0.424311"],
  ["tw-aa-approved-001", "PLANE_TILT", "0.702145"],
  ["tw-aa-approved-002", "PLANE_TILT", "0.991284"],
].map(([caseId, rootCause, distance], index) => ({
  rank: index + 1,
  case_id: caseId,
  retrieval_stage: "TOP3_ROOT_CAUSE",
  distance,
  similarity_display_value: `${(1 / (1 + Number(distance))).toFixed(6)}`,
  key_feature_differences: Array.from({ length: 5 }, (_, featureIndex) => ({
    feature_name: [
      "pitch_mean",
      "roll_mean",
      "top_bottom_difference",
      "corner_mtf_range",
      "center_corner_gap",
    ][featureIndex],
    feature_index: [21, 24, 47, 44, 49][featureIndex],
    standardized_absolute_difference: `${1.5 - featureIndex * 0.1}00000`,
    query_value: "0.250000000000",
    case_value: "0.210000000000",
  })),
  reviewed_root_cause: rootCause,
  historical_action: {
    context: "VERSIONED_APPROVED_OFFLINE_CASE",
    summary: "历史案例在规则约束模拟环境中校正 Pitch/Roll 参数族。",
  },
  historical_simulated_result: {
    context_label: "规则约束模拟环境中的历史案例结果",
    status: "SUCCESS",
    summary: "该历史案例在固定规则与版本的模拟环境中达到准入条件。",
  },
  applicability_conditions: [
    "仅适用于 AA 工站与兼容产品型号。",
    "稳定空间不对称且倾斜证据与当前参数状态一致。",
  ],
  product_model: "TW-AA-PROTOTYPE-V1",
  source_version_summary: {
    source_dataset_version: "tw-diagnostic-dev-dataset-v1",
    feature_definition_version: "tw-feature-definition-v1",
    rule_set_version: "tw-rules-v1",
    retrieval_rule_version: "tw-case-retrieval-rules-v1",
    case_schema_version: "tw-approved-case-schema-v1",
  },
  case_content_hash: `${index + 6}`.repeat(64),
  case_index_version: "tw-approved-case-index-v1",
}));

function retrievalResponse(
  status = "CASES_FOUND",
  returnedCount = 3,
) {
  const orderedCases = retrievedCases.slice(0, returnedCount);
  return {
    retrieval: {
      retrieval_result_version: "tw-case-retrieval-result-v1",
      retrieval_result_id: "tw-case-retrieval-fixed",
      task_id: "tw-demo-task-001",
      diagnostic_result_id: "tw-diagnostic-fixed",
      query_feature_hash: "3".repeat(64),
      ordered_top3_root_causes: ["PLANE_TILT", "XY_DECENTER", "REFERENCE_DRIFT"],
      ordered_cases: orderedCases,
      retrieval_status: status,
      requested_count: 3,
      returned_count: returnedCount,
      shortfall_message:
        status === "PARTIAL_RESULTS"
          ? `仅找到 ${returnedCount} 个合法兼容已审核案例。`
          : status === "NO_RELEVANT_CASE_AVAILABLE"
            ? "暂无兼容已审核案例。"
            : null,
      case_index_version: "tw-approved-case-index-v1",
      case_index_hash: "a".repeat(64),
      scaler_version: "tw-case-retrieval-scaler-v1",
      feature_definition_version: "tw-feature-definition-v1",
      compatibility_rule_version: "tw-product-compatibility-v1",
      retrieval_rule_version: "tw-case-retrieval-rules-v1",
      input_hash: "b".repeat(64),
      result_hash: "c".repeat(64),
      created_at: "2026-07-18T08:02:00.000000Z",
    },
  };
}

const planningConstraints = ["x_offset", "y_offset", "pitch", "roll", "z_offset"].map(
  (parameterName) => ({
    parameter_name: parameterName,
    nominal_value: "0.000000",
    minimum: "-1.000000",
    maximum: "1.000000",
    step: "0.050000",
    maximum_single_plan_delta: parameterName === "z_offset" ? "0.100000" : "0.200000",
  }),
);

const planningDirectionEvidence = [
  {
    parameter_name: "pitch",
    current_value: "0.250000",
    current_tick: 5,
    nominal_value: "0.000000",
    nominal_tick: 0,
    recommended_direction: "DECREASE",
    supporting_features: ["top_bottom_difference=0.132913"],
    supporting_rules: ["PLANE_TILT_PITCH_SAME_SIGN"],
    conflicting_features: [],
    conflict_status: "NO_CONFLICT",
    diagnostic_result_version: "tw-diagnostic-result-v1",
    feature_definition_version: "tw-feature-definition-v1",
    direction_rule_version: "tw-direction-rules-v1",
    evidence_hash: "d".repeat(64),
  },
  {
    parameter_name: "roll",
    current_value: "-0.200000",
    current_tick: -4,
    nominal_value: "0.000000",
    nominal_tick: 0,
    recommended_direction: "INCREASE",
    supporting_features: [],
    supporting_rules: [],
    conflicting_features: ["left_right_difference=0.014371"],
    conflict_status: "INSUFFICIENT_SUPPORT",
    diagnostic_result_version: "tw-diagnostic-result-v1",
    feature_definition_version: "tw-feature-definition-v1",
    direction_rule_version: "tw-direction-rules-v1",
    evidence_hash: "e".repeat(64),
  },
];

function planningCandidate(
  generationType: string,
  deltaTick: number,
  supportingCaseIds: string[] = [],
) {
  const proposedTick = 5 + deltaTick;
  const proposedPitch = (proposedTick * 0.05).toFixed(6);
  return {
    candidate_id: `tw-parameter-candidate-${generationType.toLowerCase()}`,
    generation_type: generationType,
    generation_sources: [
      generationType === "CASE_GUIDED" ? "CASE_GUIDED_MEDIAN" : `RULE_${generationType}`,
    ],
    root_cause: "PLANE_TILT",
    parameter_family: "PITCH_ROLL",
    current_values: { x_offset: "0.100000", y_offset: "-0.050000", pitch: "0.250000", roll: "-0.200000", z_offset: "0.000000" },
    proposed_values: { x_offset: "0.100000", y_offset: "-0.050000", pitch: proposedPitch, roll: "-0.200000", z_offset: "0.000000" },
    current_ticks: { x_offset: 2, y_offset: -1, pitch: 5, roll: -4, z_offset: 0 },
    proposed_ticks: { x_offset: 2, y_offset: -1, pitch: proposedTick, roll: -4, z_offset: 0 },
    deltas: { pitch: (deltaTick * 0.05).toFixed(6) },
    delta_ticks: { pitch: deltaTick },
    total_absolute_delta_ticks: Math.abs(deltaTick),
    direction_evidence: [planningDirectionEvidence[0]],
    supporting_case_ids: supportingCaseIds,
    supporting_case_count: supportingCaseIds.length,
    constraint_snapshot_version: "tw-parameter-constraints-v1",
    rule_set_version: "tw-rules-v1",
    direction_rule_version: "tw-direction-rules-v1",
    safety_rule_version: "tw-parameter-safety-v1",
    diagnostic_result_version: "tw-diagnostic-result-v1",
    case_retrieval_result_version: "tw-case-retrieval-result-v1",
    validation_checks: [
      { check_code: "CURRENT_VALUE_GRID", status: "PASSED", detail: "当前值位于网格。" },
      { check_code: "MAXIMUM_SINGLE_PLAN_DELTA", status: "PASSED", detail: "单次变化未超过上限。" },
      { check_code: "NOMINAL_NOT_CROSSED", status: "PASSED", detail: "调整未跨过标称值。" },
    ],
    validation_status: "PASSED",
    rejection_reasons: [],
    candidate_hash: `${Math.abs(deltaTick)}`.repeat(64),
  };
}

function planningResponse(refused = false) {
  const planning = {
    planning_result_version: "tw-parameter-planning-result-v1",
    planning_result_id: "tw-parameter-planning-fixed",
    task_id: "tw-demo-task-001",
    diagnostic_result_id: "tw-diagnostic-fixed",
    case_retrieval_result_id: refused ? null : "tw-case-retrieval-fixed",
    top1_root_cause: refused ? "PLATFORM_INSTABILITY" : "PLANE_TILT",
    direction_evidence: refused ? [] : planningDirectionEvidence,
    ordered_candidates: refused
      ? []
      : [
          planningCandidate("CONSERVATIVE", -1),
          planningCandidate("STANDARD", -2),
          planningCandidate("CASE_GUIDED", -3, [
            "tw-aa-approved-001",
            "tw-aa-approved-002",
            "tw-aa-approved-011",
          ]),
        ],
    parameter_constraints: refused ? [] : planningConstraints,
    planning_status: refused
      ? "PARAMETER_RECOMMENDATION_REFUSED"
      : "CANDIDATES_AVAILABLE",
    refusal_code: refused ? "PLATFORM_INSTABILITY_INSPECTION_ONLY" : null,
    refusal_message: refused ? "当前 Top-1 属于不可调故障，仅输出结构化排查建议。" : null,
    supporting_evidence: refused
      ? ["top1_root_cause=PLATFORM_INSTABILITY"]
      : ["usable_direction_evidence=1", "passed_candidate_count=3"],
    recommended_inspection_actions: refused
      ? ["检查重复定位误差", "检查振动或回差证据", "复核平台稳定性"]
      : [],
    case_guidance_status: refused
      ? "NO_COMPATIBLE_APPROVED_CASE"
      : "COMPATIBLE_APPROVED_CASES_USED",
    input_hash: "f".repeat(64),
    result_hash: "a1".repeat(32),
    created_at: "2026-07-18T08:03:00.000000Z",
    constraint_snapshot_version: "tw-parameter-constraints-v1",
    rule_set_version: "tw-rules-v1",
    direction_rule_version: "tw-direction-rules-v1",
    safety_rule_version: "tw-parameter-safety-v1",
    planning_rule_version: "tw-parameter-planning-v1",
    feature_definition_version: "tw-feature-definition-v1",
    diagnostic_result_version: "tw-diagnostic-result-v1",
    case_retrieval_result_version: refused ? null : "tw-case-retrieval-result-v1",
    planning_asset_manifest_hash: "b1".repeat(32),
  };
  return {
    task: {
      ...diagnosisResponse().task,
      status: refused ? "DIAGNOSED" : "PLAN_READY",
      stages: stages.map((stage, index) => ({
        ...stage,
        availability: refused
          ? index < 3
            ? "completed"
            : index === 3
              ? "current"
              : "locked"
          : index < 4
            ? "completed"
            : index === 4
              ? "current"
              : "locked",
      })),
      parameter_planning_result: planning,
    },
    planning,
  };
}

function confirmedPlanResponse(status: "VALID" | "STALE" = "VALID") {
  const planned = planningResponse();
  const candidate = planned.planning.ordered_candidates[0];
  const confirmedPlan = {
    confirmed_plan_id: "tw-confirmed-plan-fixed",
    confirmed_plan_version: "tw-confirmed-plan-v1",
    confirmed_plan_hash: "c".repeat(64),
    task_id: planned.task.task_id,
    planning_result_id: planned.planning.planning_result_id,
    planning_result_version: planned.planning.planning_result_version,
    candidate_id: candidate.candidate_id,
    candidate_hash: candidate.candidate_hash,
    current_values: candidate.current_values,
    proposed_values: candidate.proposed_values,
    deltas: candidate.deltas,
    delta_ticks: candidate.delta_ticks,
    parameter_family: candidate.parameter_family,
    root_cause: candidate.root_cause,
    generation_type: candidate.generation_type,
    supporting_case_ids: candidate.supporting_case_ids,
    direction_evidence_hashes: ["d".repeat(64)],
    actor_id: "demo-aa-engineer",
    actor_role: "AA_PROCESS_ENGINEER",
    display_name: "AA工艺工程师",
    confirmed_at: "2026-07-19T08:04:00.000000Z",
    status,
    stale_reason_codes: status === "STALE" ? ["INPUT_DATA_CHANGED"] : [],
    freshness_rule_version: "tw-confirmed-plan-freshness-v1",
    input_data_version: "tw-dataset-v1",
    input_measurement_hash: "1".repeat(64),
    current_parameter_hash: "2".repeat(64),
    detection_result_id: "tw-detection-fixed",
    detection_result_version: "tw-anomaly-detection-result-v1",
    diagnostic_result_id: "tw-diagnostic-fixed",
    diagnostic_result_version: "tw-diagnostic-result-v1",
    case_retrieval_result_id: "tw-case-retrieval-fixed",
    case_retrieval_result_version: "tw-case-retrieval-result-v1",
    control_limit_snapshot_version: "tw-control-limits-v1",
    control_limit_snapshot_hash: "3".repeat(64),
    parameter_constraint_snapshot_version: "tw-parameter-constraints-v1",
    parameter_constraint_snapshot_hash: "4".repeat(64),
    direction_rule_version: "tw-direction-rules-v1",
    safety_rule_version: "tw-parameter-safety-v1",
    planning_rule_version: "tw-parameter-planning-v1",
    rule_set_version: "tw-rules-v1",
    feature_definition_version: "tw-feature-definition-v1",
    model_version: "tw-model-v1",
    preprocessing_version: "tw-preprocessing-v1",
    approved_case_index_version: "tw-approved-case-index-v1",
    source_asset_hashes: { planning_asset_manifest: "5".repeat(64) },
    created_at: "2026-07-19T08:04:00.000000Z",
  };
  const task = {
    ...planned.task,
    status: "PLAN_CONFIRMED",
    stages: stages.map((stage, index) => ({
      ...stage,
      availability: index < 5 ? "completed" : index === 5 ? "current" : "locked",
    })),
    confirmed_plan: confirmedPlan,
  };
  return { task, confirmed_plan: confirmedPlan };
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

test("runs diagnosis and renders backend Top-3 structured evidence and versions", async () => {
  const detectedTask = detectionResponse("TARGET_ANOMALY").task;
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(detectedTask), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(diagnosisResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "运行根因诊断" }));

  expect(await screen.findByRole("heading", { name: "Top-3 根因排查顺序" })).toBeTruthy();
  expect(screen.getAllByText("PLANE_TILT").length).toBeGreaterThan(0);
  expect(screen.getByText("98.21%")).toBeTruthy();
  expect(screen.getAllByText("可调").length).toBeGreaterThan(0);
  expect(screen.getByText("仅排查")).toBeTruthy();
  expect(screen.getAllByText("该特征对当前类别 logit 的贡献").length).toBeGreaterThan(0);
  expect(screen.getByText("SUFFICIENT_EVIDENCE")).toBeTruthy();
  expect(screen.getByText("tw-feature-definition-v1")).toBeTruthy();
  expect(screen.getByText("tw-evidence-rules-v1")).toBeTruthy();
  expect(screen.getByText(/555555555555/)).toBeTruthy();
  expect(screen.getAllByText("DIAGNOSED")).toHaveLength(2);
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/tasks/tw-demo-task-001/diagnoses",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ detection_result_id: "tw-detection-fixed" }),
    },
  );
});

test("shows accessible diagnosis loading and disables duplicate action", async () => {
  let resolveDiagnosis: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    resolveDiagnosis = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detectionResponse("TARGET_ANOMALY").task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockReturnValueOnce(pending),
  );

  render(<App />);
  const action = await screen.findByRole("button", { name: "运行根因诊断" });
  fireEvent.click(action);

  expect(
    await screen.findByText("正在校验固定诊断资产并计算 Top-3…"),
  ).toBeTruthy();
  expect((action as HTMLButtonElement).disabled).toBe(true);
  resolveDiagnosis(
    new Response(JSON.stringify(diagnosisResponse()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(await screen.findByText("SUFFICIENT_EVIDENCE")).toBeTruthy();
});

test("renders insufficient evidence protection while preserving Top-3", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detectionResponse("TARGET_ANOMALY").task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse("INSUFFICIENT_EVIDENCE")), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "运行根因诊断" }));

  expect(await screen.findByText("INSUFFICIENT_EVIDENCE")).toBeTruthy();
  expect(screen.getByText("诊断证据不足，仅供排查")).toBeTruthy();
  expect(screen.getByText(/参数候选数量固定为 0/)).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Top-3 根因排查顺序" })).toBeTruthy();
  expect(screen.getAllByText("DIAGNOSED")).toHaveLength(2);
  expect(screen.getAllByText("未开放").length).toBeGreaterThan(0);
});

test("renders structured diagnosis errors inline without window alert", async () => {
  const alert = vi.fn();
  vi.stubGlobal("alert", alert);
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(detectionResponse("TARGET_ANOMALY").task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "DIAGNOSTIC_ASSET_HASH_MISMATCH",
              message: "诊断资产内容哈希不匹配：model.json",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "运行根因诊断" }));

  expect(
    await screen.findByText("诊断资产内容哈希不匹配：model.json"),
  ).toBeTruthy();
  expect(screen.getByText("DIAGNOSTIC_ASSET_HASH_MISMATCH")).toBeTruthy();
  expect(alert).not.toHaveBeenCalled();
});

test("retrieves and displays at most three approved cases with neutral evidence", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(diagnosisResponse().task), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(retrievalResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "检索已审核案例" }));

  expect(await screen.findByRole("heading", { name: "相似案例" })).toBeTruthy();
  expect(screen.getByText("仅检索 APPROVED 案例")).toBeTruthy();
  expect(screen.getAllByRole("listitem", { name: /已审核案例/ })).toHaveLength(3);
  expect(screen.getByText("tw-aa-approved-011")).toBeTruthy();
  expect(screen.getAllByText("PLANE_TILT").length).toBeGreaterThan(0);
  expect(screen.getByText("距离 0.424311")).toBeTruthy();
  expect(screen.getAllByText("pitch_mean").length).toBeGreaterThan(0);
  expect(screen.getAllByText("历史处理动作").length).toBeGreaterThan(0);
  expect(
    screen.getAllByText("规则约束模拟环境中的历史案例结果").length,
  ).toBeGreaterThan(0);
  expect(screen.getByText("tw-approved-case-index-v1")).toBeTruthy();
  expect(screen.getByText("tw-case-retrieval-scaler-v1")).toBeTruthy();
  expect(screen.getByText(/不表示根因真实性、因果关系或真实设备适用概率/)).toBeTruthy();
  expect(screen.queryByText(/推荐采用|一键复用|最佳历史方案/)).toBeNull();
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/tasks/tw-demo-task-001/case-retrievals",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diagnostic_result_id: "tw-diagnostic-fixed", top_k: 3 }),
    },
  );
});

test("shows accessible case retrieval loading and disables duplicate action", async () => {
  let resolveRetrieval: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    resolveRetrieval = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockReturnValueOnce(pending),
  );

  render(<App />);
  const action = await screen.findByRole("button", { name: "检索已审核案例" });
  fireEvent.click(action);

  expect(await screen.findByText("正在校验 APPROVED 案例索引并计算结构化距离…")).toBeTruthy();
  expect((action as HTMLButtonElement).disabled).toBe(true);
  resolveRetrieval(
    new Response(JSON.stringify(retrievalResponse()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(await screen.findByText("tw-aa-approved-011")).toBeTruthy();
});

test.each([
  ["PARTIAL_RESULTS", 2, "仅找到 2 个合法兼容已审核案例。"],
  ["NO_RELEVANT_CASE_AVAILABLE", 0, "暂无兼容已审核案例。"],
])("renders %s case retrieval state without filling from invalid cases", async (status, count, message) => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(retrievalResponse(status, count)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "检索已审核案例" }));

  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.queryAllByRole("listitem", { name: /已审核案例/ })).toHaveLength(count);
  expect(screen.getAllByText("DIAGNOSED")).toHaveLength(2);
});

test("renders structured case retrieval errors without replacing diagnosis", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "CASE_ASSET_HASH_MISMATCH",
              message: "案例检索资产内容哈希不匹配：index.json",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "检索已审核案例" }));

  expect(await screen.findByText("案例检索资产内容哈希不匹配：index.json")).toBeTruthy();
  expect(screen.getByText("CASE_ASSET_HASH_MISMATCH")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Top-3 根因排查顺序" })).toBeTruthy();
});

test("generates and displays three read-only safety-constrained candidates", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(diagnosisResponse().task), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(retrievalResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockResolvedValueOnce(
      new Response(JSON.stringify(planningResponse()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "检索已审核案例" }));
  await screen.findByText("tw-aa-approved-011");
  fireEvent.click(screen.getByRole("button", { name: "生成安全参数候选" }));

  expect(
    await screen.findByRole("heading", {
      name: "通过当前证据和安全规则生成的候选方案",
    }),
  ).toBeTruthy();
  expect(screen.getByText("CANDIDATES_AVAILABLE")).toBeTruthy();
  expect(screen.getAllByRole("listitem", { name: /安全参数候选/ })).toHaveLength(3);
  expect(screen.getByText("CONSERVATIVE")).toBeTruthy();
  expect(screen.getByText("STANDARD")).toBeTruthy();
  expect(screen.getByText("CASE_GUIDED")).toBeTruthy();
  expect(screen.getAllByText("0.250000").length).toBeGreaterThan(0);
  expect(screen.getAllByText("0.100000").length).toBeGreaterThan(0);
  expect(screen.getByText("-0.150000 · -3 ticks")).toBeTruthy();
  expect(screen.getAllByText("[-1.000000, 1.000000]").length).toBeGreaterThan(0);
  expect(screen.getAllByText("步长 0.050000").length).toBeGreaterThan(0);
  expect(screen.getAllByText("最大变化 0.200000").length).toBeGreaterThan(0);
  expect(screen.getByText("支持案例 3")).toBeTruthy();
  expect(screen.getAllByText("PASSED").length).toBeGreaterThan(2);
  expect(screen.getByText("tw-direction-rules-v1")).toBeTruthy();
  expect(screen.getByText("tw-parameter-safety-v1")).toBeTruthy();
  expect(screen.getByText("tw-parameter-constraints-v1")).toBeTruthy();
  expect(screen.getAllByText(/候选哈希/)).toHaveLength(3);
  expect(screen.getByText(/结果哈希/)).toBeTruthy();
  expect(screen.queryByText(/最优参数|最佳方案|预测最优|自动写入|已执行/)).toBeNull();
  expect(screen.getByRole("button", { name: "人工确认候选方案" })).toBeTruthy();
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/tasks/tw-demo-task-001/parameter-plans",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        diagnostic_result_id: "tw-diagnostic-fixed",
        case_retrieval_result_id: "tw-case-retrieval-fixed",
      }),
    },
  );
});

test("shows accessible parameter planning loading and disables duplicate action", async () => {
  let resolvePlanning: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    resolvePlanning = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockReturnValueOnce(pending),
  );

  render(<App />);
  const action = await screen.findByRole("button", { name: "生成安全参数候选" });
  fireEvent.click(action);

  expect(await screen.findByText("正在生成方向证据并执行统一安全校验…")).toBeTruthy();
  expect((action as HTMLButtonElement).disabled).toBe(true);
  resolvePlanning(
    new Response(JSON.stringify(planningResponse()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  expect(await screen.findByText("CANDIDATES_AVAILABLE")).toBeTruthy();
});

test("renders structured planning refusal and inspection-only actions", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(planningResponse(true)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "生成安全参数候选" }));

  expect(await screen.findByText("PARAMETER_RECOMMENDATION_REFUSED")).toBeTruthy();
  expect(screen.getByText("PLATFORM_INSTABILITY_INSPECTION_ONLY")).toBeTruthy();
  expect(screen.getByText("检查重复定位误差")).toBeTruthy();
  expect(screen.getByText("检查振动或回差证据")).toBeTruthy();
  expect(screen.getByText("复核平台稳定性")).toBeTruthy();
  expect(screen.queryAllByRole("listitem", { name: /安全参数候选/ })).toHaveLength(0);
  expect(screen.getAllByText("DIAGNOSED").length).toBeGreaterThan(0);
});

test("restores persisted planning as read-only without reopening case retrieval", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(planningResponse().task), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  render(<App />);

  expect(await screen.findByText("CANDIDATES_AVAILABLE")).toBeTruthy();
  const retrieval = screen.getByRole("button", { name: "案例检索已完成" });
  expect((retrieval as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getAllByRole("listitem", { name: /安全参数候选/ })).toHaveLength(3);
});

test("renders structured parameter planning errors without replacing diagnosis", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(diagnosisResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "PLANNING_ASSET_HASH_MISMATCH",
              message: "参数规划规则资产内容哈希不匹配。",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "生成安全参数候选" }));

  expect(await screen.findByText("参数规划规则资产内容哈希不匹配。")).toBeTruthy();
  expect(screen.getByText("PLANNING_ASSET_HASH_MISMATCH")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Top-3 根因排查顺序" })).toBeTruthy();
});

test("selects one passed candidate and confirms only its identity with loading feedback", async () => {
  let resolveConfirmation: (response: Response) => void = () => undefined;
  const pending = new Promise<Response>((resolve) => {
    resolveConfirmation = resolve;
  });
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify(planningResponse().task), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    )
    .mockReturnValueOnce(pending);
  vi.stubGlobal("fetch", fetchMock);

  render(<App />);
  const confirm = await screen.findByRole("button", { name: "人工确认候选方案" });
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  const candidate = screen.getByRole("radio", { name: /CONSERVATIVE/ });
  fireEvent.click(candidate);
  expect((candidate as HTMLInputElement).checked).toBe(true);
  expect((confirm as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(confirm);
  expect(await screen.findByText("正在冻结候选并执行服务端安全复核…")).toBeTruthy();
  expect((confirm as HTMLButtonElement).disabled).toBe(true);
  resolveConfirmation(
    new Response(JSON.stringify(confirmedPlanResponse()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

  expect(await screen.findByText("方案已人工确认并冻结")).toBeTruthy();
  expect(screen.getAllByText("PLAN_CONFIRMED").length).toBeGreaterThan(0);
  expect(screen.getByText(/尚未进行模拟回放/)).toBeTruthy();
  expect(screen.getByText(/未向真实设备写入任何参数/)).toBeTruthy();
  expect(screen.getByText(/确认方案哈希/)).toBeTruthy();
  expect(fetchMock).toHaveBeenLastCalledWith(
    "/api/tasks/tw-demo-task-001/confirmed-plans",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidate_id: "tw-parameter-candidate-conservative",
        candidate_hash: "1".repeat(64),
      }),
    },
  );
});

test("shows structured confirmation tamper or conflict error inline", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(planningResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "CANDIDATE_HASH_MISMATCH",
              message: "请求 candidate_hash 与服务端当前候选不一致。",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  const selected = await screen.findByRole("radio", { name: /STANDARD/ });
  fireEvent.click(selected);
  fireEvent.click(screen.getByRole("button", { name: "人工确认候选方案" }));

  expect(
    await screen.findByText("请求 candidate_hash 与服务端当前候选不一致。"),
  ).toBeTruthy();
  expect(screen.getByText("CANDIDATE_HASH_MISMATCH")).toBeTruthy();
  expect((selected as HTMLInputElement).disabled).toBe(true);
  expect(screen.getByText("该候选已失效")).toBeTruthy();
  expect(
    (screen.getByRole("button", { name: "人工确认候选方案" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test("disables the whole confirmation context after a planning-level stale error", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(planningResponse().task), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "PLANNING_RESULT_STALE",
              message: "当前参数规划结果已过期。",
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
  );

  render(<App />);
  const selected = await screen.findByRole("radio", { name: /STANDARD/ });
  fireEvent.click(selected);
  fireEvent.click(screen.getByRole("button", { name: "人工确认候选方案" }));

  expect(await screen.findByText("当前参数规划结果已过期。")).toBeTruthy();
  for (const radio of screen.getAllByRole("radio")) {
    expect((radio as HTMLInputElement).disabled).toBe(true);
  }
  expect(
    (screen.getByRole("button", { name: "人工确认候选方案" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});

test("renders persisted stale confirmed plan as permanently unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(confirmedPlanResponse("STALE").task), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  render(<App />);

  expect(
    await screen.findByText("方案已过期，需要重新生成并确认"),
  ).toBeTruthy();
  expect(screen.getByText("INPUT_DATA_CHANGED")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "人工确认候选方案" })).toBeNull();
  expect(screen.queryByRole("button", { name: /回放|执行|写入设备/ })).toBeNull();
});
