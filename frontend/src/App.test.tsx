import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
    rule_set_version: "tw-rules-v1",
    model_version: "tw-model-v1",
    preprocessing_version: "tw-preprocessing-v1",
    evaluation_rule_version: "tw-evaluation-v1",
    canonicalizer_version: "tw-canonicalizer-v1",
  },
  stages,
};

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
