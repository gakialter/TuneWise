import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import ProcessAwareDemo from "./ProcessAwareDemo";
import type { CandidateSummary, ProcessAwareDemoResponse } from "./types";

const FACTS_BOUNDARY = [
  "Synthetic process-context demonstration.",
  "Demonstrates deterministic context-sensitive evidence selection.",
  "Does not represent Sunny Optical SOP or validated production tuning accuracy.",
].join("\n");

function candidate(
  generationType: string,
  deltaTicks: number,
  supportingCaseIds: string[] = [],
): CandidateSummary {
  const proposedTick = 5 + deltaTicks;
  return {
    candidate_id: `tw-${generationType.toLowerCase()}-${Math.abs(deltaTicks)}`,
    candidate_hash: String(Math.abs(deltaTicks)).repeat(64),
    generation_type: generationType,
    parameter_name: "pitch",
    current_value: "0.250000",
    proposed_value: (proposedTick * 0.05).toFixed(6),
    delta_value: (deltaTicks * 0.05).toFixed(6),
    delta_ticks: deltaTicks,
    supporting_case_ids: supportingCaseIds,
    validation_status: "PASSED",
    safety_rule_version: "tw-parameter-safety-v1",
    validation_checks: [
      { check_code: "CURRENT_VALUE_GRID", status: "PASSED" },
      { check_code: "MAXIMUM_SINGLE_PLAN_DELTA", status: "PASSED" },
      { check_code: "NOMINAL_NOT_CROSSED", status: "PASSED" },
    ],
  };
}

const demoResponse: ProcessAwareDemoResponse = {
  demo_version: "tw-process-aware-demo-v1",
  title: "Process-aware Decision Demo",
  facts_boundary: FACTS_BOUNDARY,
  abstraction_note: "TuneWise process-context abstractions; not industry-standard states.",
  synthetic: true,
  provenance: {
    source_kind: "SYNTHETIC_TEST_FIXTURE",
    fixture_version: "tw-process-aware-test-fixture-v1",
    fixture_manifest_hash: "f".repeat(64),
    demo_dataset_asset_id: "tw-aa-demo-v1",
  },
  shared_evidence: {
    measurement_evidence_label: "Same fixed synthetic measurement batch",
    measurement_hash: "a".repeat(64),
    query_feature_hash: "b".repeat(64),
    feature_dimension: 50,
    feature_definition_version: "tw-feature-definition-v1",
    diagnostic_model_version: "tw-model-v1",
    preprocessing_version: "tw-preprocessing-v1",
    scaler_version: "tw-case-retrieval-scaler-v1",
    case_index_hash: "c".repeat(64),
    ordered_root_causes: [
      { rank: 1, root_cause: "PLANE_TILT" },
      { rank: 2, root_cause: "XY_DECENTER" },
      { rank: 3, root_cause: "REFERENCE_DRIFT" },
    ],
    top1_root_cause: "PLANE_TILT",
    same_across_scenarios: true,
  },
  scenarios: [
    {
      scenario_id: "A",
      process_context: {
        process_stage: "INITIAL_ASSESSMENT",
        process_stage_display: { en: "Initial Assessment", zh: "初始评估" },
        iteration_index: 0,
        previous_action: null,
        previous_action_outcome: null,
        previous_action_outcome_display: null,
        source_kind: "SYNTHETIC_TEST_FIXTURE",
        synthetic: true,
        context_hash: "d".repeat(64),
      },
      eligible_case: {
        case_id: "tw-aa-approved-011",
        distance: "4.442915",
        compatibility: {
          reason_code: "CONTEXT_MATCH",
          explanation: "Initial-assessment profile matches the synthetic process context.",
        },
        process_profile: {
          compatible_process_stage: "INITIAL_ASSESSMENT",
          previous_action_parameter: null,
          previous_action_outcome: null,
          minimum_iteration: 0,
          maximum_iteration: 0,
          source_kind: "SYNTHETIC_TEST_FIXTURE",
          synthetic: true,
          profile_hash: "e".repeat(64),
        },
        historical_action: {
          parameter_delta_ticks: { pitch: -3, roll: 3 },
          action_version: "tw-approved-case-action-v1",
          historical_safety_status: "PASSED",
        },
      },
      case_guided_candidate: candidate("CASE_GUIDED", -3, ["tw-aa-approved-011"]),
    },
    {
      scenario_id: "B",
      process_context: {
        process_stage: "POST_ADJUSTMENT_EVALUATION",
        process_stage_display: { en: "Post-adjustment Evaluation", zh: "调整后评估" },
        iteration_index: 1,
        previous_action: {
          parameter_name: "pitch",
          before_value: "0.250000",
          after_value: "0.200000",
          delta_ticks: -1,
          action_version: "tw-approved-case-action-v1",
        },
        previous_action_outcome: "NO_MATERIAL_IMPROVEMENT",
        previous_action_outcome_display: {
          en: "No Material Improvement",
          zh: "未观察到显著改善",
        },
        source_kind: "SYNTHETIC_TEST_FIXTURE",
        synthetic: true,
        context_hash: "1".repeat(64),
      },
      eligible_case: {
        case_id: "tw-aa-approved-003",
        distance: "4.973548",
        compatibility: {
          reason_code: "CONTEXT_MATCH",
          explanation: "The recorded pitch outcome matches the post-adjustment profile.",
        },
        process_profile: {
          compatible_process_stage: "POST_ADJUSTMENT_EVALUATION",
          previous_action_parameter: "pitch",
          previous_action_outcome: "NO_MATERIAL_IMPROVEMENT",
          minimum_iteration: 1,
          maximum_iteration: 1,
          source_kind: "SYNTHETIC_TEST_FIXTURE",
          synthetic: true,
          profile_hash: "2".repeat(64),
        },
        historical_action: {
          parameter_delta_ticks: { pitch: -4, roll: 4 },
          action_version: "tw-approved-case-action-v1",
          historical_safety_status: "PASSED",
        },
      },
      case_guided_candidate: candidate("CASE_GUIDED", -4, ["tw-aa-approved-003"]),
    },
  ],
  unchanged_controls: {
    identical_across_scenarios: true,
    conservative_candidate: candidate("CONSERVATIVE", -1),
    standard_candidate: candidate("STANDARD", -2),
    safety_validator: {
      unchanged_across_scenarios: true,
      safety_rule_version: "tw-parameter-safety-v1",
      status: "PASSED",
      validation_checks: [
        { check_code: "CURRENT_VALUE_GRID", status: "PASSED" },
        { check_code: "MAXIMUM_SINGLE_PLAN_DELTA", status: "PASSED" },
        { check_code: "NOMINAL_NOT_CROSSED", status: "PASSED" },
      ],
    },
    scenario_candidate_hashes: {
      A: { CONSERVATIVE: "3".repeat(64), STANDARD: "4".repeat(64) },
      B: { CONSERVATIVE: "3".repeat(64), STANDARD: "4".repeat(64) },
    },
  },
};

function mockSuccessfulFetch() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(demoResponse),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ProcessAwareDemo", () => {
  test("provides an accessible loading state and fixed page title", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<ProcessAwareDemo />);

    expect(screen.getByRole("heading", { level: 1, name: "结合调机步骤的决策演示" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("正在加载场景对比");
    expect(screen.getByRole("link", { name: "返回固定端到端演示" }).getAttribute("href")).toBe("/");
  });

  test("provides an accessible API error and retry control", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    render(<ProcessAwareDemo />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("暂时无法加载调机过程对比");
    expect(alert.textContent).toContain("HTTP 503");
    expect(within(alert).getByRole("button", { name: "重新加载" })).toBeTruthy();
  });

  test("shows the exact facts boundary and shared deterministic evidence", async () => {
    const fetchMock = mockSuccessfulFetch();
    render(<ProcessAwareDemo />);

    await screen.findByText("这是合成调机过程演示。");
    expect(screen.getByText("当前演示用于证明 TuneWise 能根据不同调机过程信息选择不同的历史参考案例。")).toBeTruthy();
    expect(document.querySelector(".boundary-english")?.textContent).toContain(
      demoResponse.facts_boundary,
    );
    expect(
      screen.getByText("TuneWise process-context abstractions; not industry-standard states."),
    ).toBeTruthy();

    expect(screen.getByText("测量数据")).toBeTruthy();
    expect(screen.getByText("根因判断")).toBeTruthy();
    expect(screen.getAllByText("PLANE_TILT").length).toBeGreaterThan(0);
    expect(screen.getByText("Top-1")).toBeTruthy();
    expect(screen.getByText("50 维")).toBeTruthy();
    expect(screen.getByText("tw-feature-definition-v1")).toBeTruthy();
    expect(screen.getByLabelText("标准化器版本: tw-case-retrieval-scaler-v1")).toBeTruthy();
    expect(screen.getByLabelText(`检索特征哈希: ${"b".repeat(64)}`)).toBeTruthy();
    expect(screen.getByLabelText(`案例索引哈希: ${"c".repeat(64)}`)).toBeTruthy();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/demos/process-aware",
      expect.objectContaining({ method: "GET", headers: { Accept: "application/json" } }),
    );
  });

  test("renders A and B together with context-eligible cases and distinct CASE_GUIDED deltas", async () => {
    mockSuccessfulFetch();
    render(<ProcessAwareDemo />);

    const comparison = await screen.findByTestId("scenario-comparison");
    expect(comparison.querySelectorAll(".scenario-card")).toHaveLength(2);

    const scenarioAHeading = within(comparison).getByRole("heading", {
      level: 3,
      name: "初始评估 / Initial Assessment",
    });
    const scenarioBHeading = within(comparison).getByRole("heading", {
      level: 3,
      name: "调整后评估 / Post-adjustment Evaluation",
    });
    const scenarioA = scenarioAHeading.closest("article");
    const scenarioB = scenarioBHeading.closest("article");
    expect(scenarioA).not.toBeNull();
    expect(scenarioB).not.toBeNull();

    const a = within(scenarioA as HTMLElement);
    expect(a.getAllByText("INITIAL_ASSESSMENT").length).toBeGreaterThan(0);
    expect(a.getByText("无")).toBeTruthy();
    expect(a.getByText("tw-aa-approved-011")).toBeTruthy();
    expect(a.getByText("CASE_GUIDED")).toBeTruthy();
    expect(a.getByText("-3")).toBeTruthy();

    const b = within(scenarioB as HTMLElement);
    expect(b.getAllByText("POST_ADJUSTMENT_EVALUATION").length).toBeGreaterThan(0);
    expect(b.getAllByText("0.250000").length).toBeGreaterThan(0);
    expect(b.getAllByText("0.200000").length).toBeGreaterThan(0);
    expect(b.getAllByText("NO_MATERIAL_IMPROVEMENT").length).toBeGreaterThan(0);
    expect(b.getByText("未观察到显著改善")).toBeTruthy();
    expect(b.getByText("tw-aa-approved-003")).toBeTruthy();
    expect(b.getByText("CASE_GUIDED")).toBeTruthy();
    expect(b.getByText("-4")).toBeTruthy();

    expect(within(comparison).getAllByText("CONTEXT_MATCH")).toHaveLength(2);
    expect(within(comparison).getAllByText("合成调机过程")).toHaveLength(2);
    expect(within(comparison).getAllByText("合成案例条件")).toHaveLength(2);
    expect(within(comparison).getAllByText("当前适用案例")).toHaveLength(2);
    expect(within(comparison).getAllByText("已审核离线案例 · 合成调机过程条件")).toHaveLength(2);
    expect(within(comparison).getAllByText("用于案例排序，不是概率。")).toHaveLength(2);
  });

  test("keeps control candidates and the Safety Validator visibly unchanged without positive production claims", async () => {
    mockSuccessfulFetch();
    render(<ProcessAwareDemo />);

    await screen.findByRole("heading", { level: 3, name: "保守调整方案未改变" });
    expect(screen.getByRole("heading", { level: 3, name: "标准调整方案未改变" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 3, name: "安全校验规则未改变" })).toBeTruthy();
    const conservativeHashProof = screen.getByLabelText(
      "CONSERVATIVE A and B candidate hashes match",
    );
    const conservativeHashes = conservativeHashProof.querySelectorAll("code");
    expect(conservativeHashes).toHaveLength(2);
    expect(conservativeHashes[0].getAttribute("title")).toBe("3".repeat(64));
    expect(conservativeHashes[1].getAttribute("title")).toBe("3".repeat(64));
    expect(screen.getByLabelText("STANDARD A and B candidate hashes match")).toBeTruthy();
    expect(screen.getAllByText("tw-parameter-safety-v1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PASSED").length).toBeGreaterThan(0);
    expect(screen.getByText("CURRENT_VALUE_GRID")).toBeTruthy();
    expect(screen.getByText("MAXIMUM_SINGLE_PLAN_DELTA")).toBeTruthy();
    expect(screen.getByText("NOMINAL_NOT_CROSSED")).toBeTruthy();
    expect(screen.getByText("A / B 控制项一致")).toBeTruthy();

    for (const forbiddenClaim of [
      "Real AA Process",
      "Sunny Optical Workflow",
      "Production Tuning History",
      "Validated Production Recommendation",
    ]) {
      expect(screen.queryByText(forbiddenClaim, { exact: false })).toBeNull();
    }
  });

  test("flags a control hash mismatch instead of claiming the candidate is unchanged", async () => {
    const mismatchedResponse: ProcessAwareDemoResponse = {
      ...demoResponse,
      unchanged_controls: {
        ...demoResponse.unchanged_controls,
        safety_validator: {
          ...demoResponse.unchanged_controls.safety_validator,
          unchanged_across_scenarios: false,
        },
        scenario_candidate_hashes: {
          ...demoResponse.unchanged_controls.scenario_candidate_hashes,
          B: {
            ...demoResponse.unchanged_controls.scenario_candidate_hashes.B,
            CONSERVATIVE: "9".repeat(64),
          },
        },
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(mismatchedResponse),
    }));
    render(<ProcessAwareDemo />);

    expect(
      await screen.findByRole("heading", { level: 3, name: "保守调整方案不一致" }),
    ).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 3, name: "保守调整方案未改变" })).toBeNull();
    const proof = screen.getByLabelText("CONSERVATIVE A and B candidate hashes do not match");
    const hashes = proof.querySelectorAll("code");
    expect(hashes[0].getAttribute("title")).toBe("3".repeat(64));
    expect(hashes[1].getAttribute("title")).toBe("9".repeat(64));
    expect(proof.textContent).toContain("≠");
    expect(screen.getByRole("heading", { level: 3, name: "安全校验规则不一致" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 3, name: "安全校验规则未改变" })).toBeNull();
  });
});
