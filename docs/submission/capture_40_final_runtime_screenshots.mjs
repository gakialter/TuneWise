import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  access,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "../..");
const outputDirectory = path.join(
  repositoryRoot,
  "docs",
  "submission",
  "assets",
  "40-final",
  "runtime-screenshots",
);
const ailySource = path.join(
  repositoryRoot,
  "docs",
  "submission",
  "assets",
  "40-final",
  "aily-screenshots",
  "03_hero_qa.png",
);
const frontendRequire = createRequire(
  path.join(repositoryRoot, "frontend", "package.json"),
);
const { chromium } = frontendRequire("playwright");

const webPort = Number(process.env.TUNEWISE_CAPTURE_PORT ?? "8123");
assert.ok(
  Number.isInteger(webPort) && webPort >= 1024 && webPort <= 65535,
  "TUNEWISE_CAPTURE_PORT must be an unprivileged TCP port.",
);
const targetUrl = `http://127.0.0.1:${webPort}`;
const processAwareUrl = `${targetUrl}/process-aware-demo/`;
const opcuaEndpoint = "opc.tcp://127.0.0.1:4841/tunewise/opcua-sandbox/";
const viewport = { width: 1440, height: 1100 };
const expectedScreenshotNames = [
  "fixed-01-root-cause-top1.png",
  "fixed-02-selected-conservative-candidate.png",
  "fixed-03-confirmed-plan.png",
  "fixed-04-replay-result.png",
  "fixed-05-device-receipt.png",
  "fixed-final-viewport-1440x1100.png",
  "process-01-shared-evidence.png",
  "process-02-scenario-a-path.png",
  "process-03-scenario-a-candidate.png",
  "process-04-scenario-b-path.png",
  "process-05-scenario-b-candidate.png",
  "process-06-invariant-band.png",
  "process-final-viewport-1440x1100.png",
];

await mkdir(outputDirectory, { recursive: true });
await access(ailySource);

const pythonExecutable = process.env.TUNEWISE_CAPTURE_PYTHON ?? path.join(
  repositoryRoot,
  ".venv",
  "Scripts",
  "python.exe",
);
await access(pythonExecutable);

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "tunewise-40-final-capture-"));
const databasePath = path.join(temporaryRoot, "tunewise-capture.db");
const sandboxStatePath = path.join(temporaryRoot, "opcua-sandbox-state.json");
const childLogs = [];
const children = [];
let browser;
let context;

function appendChildLog(name, stream, chunk) {
  const text = String(chunk).replaceAll(temporaryRoot, "<temporary-capture-root>");
  childLogs.push(`[${name}:${stream}] ${text}`);
}

function startChild(name, executable, args, environment) {
  const child = spawn(executable, args, {
    cwd: repositoryRoot,
    env: environment,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => appendChildLog(name, "stdout", chunk));
  child.stderr.on("data", (chunk) => appendChildLog(name, "stderr", chunk));
  children.push({ name, child });
  return child;
}

async function portIsOpen(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    socket.setTimeout(300);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("timeout", () => {
      socket.destroy();
      resolve(false);
    });
    socket.once("error", () => resolve(false));
  });
}

async function waitForPort(port, child, label) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${label} exited early with code ${child.exitCode}.`);
    }
    if (await portIsOpen(port)) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`${label} did not listen on 127.0.0.1:${port} within 30 seconds.`);
}

async function waitForHttp(url, child) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`TuneWise web server exited early with code ${child.exitCode}.`);
    }
    try {
      const response = await fetch(url, { redirect: "manual" });
      if (response.status >= 200 && response.status < 400) return;
    } catch {
      // The loop below owns the bounded retry interval.
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`TuneWise web server did not respond at ${url} within 30 seconds.`);
}

async function stopChild(name, child) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  const exited = await Promise.race([
    new Promise((resolve) => child.once("exit", () => resolve(true))),
    new Promise((resolve) => setTimeout(() => resolve(false), 5_000)),
  ]);
  if (!exited && child.exitCode === null) {
    child.kill("SIGKILL");
    await new Promise((resolve) => child.once("exit", resolve));
  }
  childLogs.push(`[capture] stopped ${name}\n`);
}

function observePage(page, label, observations) {
  page.on("console", (message) => {
    if (message.type() === "error") {
      observations.consoleErrors.push({ label, text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    observations.pageErrors.push({ label, message: error.message });
  });
  page.on("requestfailed", (request) => {
    observations.failedRequests.push({
      label,
      url: request.url(),
      failure: request.failure()?.errorText ?? "unknown",
    });
  });
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    observations.observedRequests.push({ label, url });
    if (new URL(url).origin !== new URL(targetUrl).origin) {
      observations.externalRequests.push({ label, url });
    }
  });
}

async function viewportFit(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const offenders = [...document.querySelectorAll("body *")]
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          rect.width > 0 &&
          rect.bottom > 0 &&
          rect.top < window.innerHeight &&
          (rect.left < -1 || rect.right > window.innerWidth + 1)
        );
      })
      .slice(0, 20)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: String(element.className),
          left: rect.left,
          right: rect.right,
          width: rect.width,
        };
      });
    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      canScrollX: root.scrollWidth > root.clientWidth,
      offenders,
    };
  });
}

async function clickAndWait(page, buttonName, resultLocator) {
  await page.getByRole("button", { name: buttonName }).click();
  await resultLocator.waitFor({ state: "visible", timeout: 60_000 });
}

async function elementViewportBox(locator) {
  return locator.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      x: rect.left,
      y: rect.top,
      width: rect.width,
      height: rect.height,
    };
  });
}

async function captureElement(locator, filename) {
  await locator.scrollIntoViewIfNeeded();
  await locator.screenshot({
    path: path.join(outputDirectory, filename),
    animations: "disabled",
    caret: "hide",
  });
}

async function captureUnion(page, locators, filename, padding = 0) {
  assert.ok(locators.length > 0, `No locators supplied for ${filename}.`);
  await locators[0].scrollIntoViewIfNeeded();
  const boxes = [];
  for (const locator of locators) {
    assert.equal(await locator.count(), 1, `${filename} locator must resolve once.`);
    boxes.push(await elementViewportBox(locator));
  }
  const left = Math.max(0, Math.floor(Math.min(...boxes.map((box) => box.x)) - padding));
  const top = Math.max(0, Math.floor(Math.min(...boxes.map((box) => box.y)) - padding));
  const right = Math.ceil(Math.max(...boxes.map((box) => box.x + box.width)) + padding);
  const bottom = Math.ceil(Math.max(...boxes.map((box) => box.y + box.height)) + padding);
  const currentViewport = page.viewportSize();
  assert.ok(currentViewport, `${filename} requires an explicit viewport.`);
  assert.ok(
    right <= currentViewport.width && bottom <= currentViewport.height,
    `${filename} union does not fit the current viewport: ${JSON.stringify({ left, top, right, bottom, currentViewport })}`,
  );
  await page.screenshot({
    path: path.join(outputDirectory, filename),
    clip: { x: left, y: top, width: right - left, height: bottom - top },
    animations: "disabled",
    caret: "hide",
  });
}

function pngDimensions(bytes) {
  assert.equal(bytes.subarray(1, 4).toString("ascii"), "PNG", "Expected PNG signature.");
  assert.equal(bytes.subarray(12, 16).toString("ascii"), "IHDR", "Expected PNG IHDR.");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

async function fileEvidence(filePath) {
  const bytes = await readFile(filePath);
  const dimensions = pngDimensions(bytes);
  return {
    file: path.relative(repositoryRoot, filePath).replaceAll("\\", "/"),
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    ...dimensions,
  };
}

async function captureFixedDemo(page) {
  await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 30_000 });
  await page.getByRole("heading", { name: "AA 工站 AI 调机决策支持" }).waitFor();
  assert.equal(
    await page.getByRole("heading", { name: "本地模拟设备执行" }).count(),
    0,
    "Device execution must not appear before Simulation Validation succeeds.",
  );

  await clickAndWait(
    page,
    "导入预置 AA 异常批次",
    page.getByText("CSV 与 Manifest 校验通过", { exact: true }),
  );
  await clickAndWait(
    page,
    "运行异常检测",
    page.getByRole("heading", { name: "检测到四角 MTF 不对称下降" }),
  );
  await clickAndWait(
    page,
    "运行根因诊断",
    page.getByRole("heading", { name: "根因优先级" }),
  );
  await clickAndWait(
    page,
    "检索已审核案例",
    page.getByRole("button", { name: "案例检索已完成" }),
  );
  await clickAndWait(
    page,
    "生成调参候选方案",
    page.getByRole("radio", { name: /保守调整方案/ }),
  );
  await page.getByRole("radio", { name: /保守调整方案/ }).click();
  await clickAndWait(
    page,
    "工程师确认采用",
    page.getByRole("heading", { name: "已确认调参方案" }),
  );
  await clickAndWait(
    page,
    "运行调参方案仿真",
    page.getByRole("heading", { name: "仿真验证结果" }),
  );
  await page.getByText(
    /仅表示该参数方案在当前固定模拟条件下满足预设评价规则/,
  ).waitFor();

  const deviceHeading = page.getByRole("heading", { name: "本地模拟设备执行" });
  await deviceHeading.waitFor({ state: "visible" });
  await clickAndWait(
    page,
    "检查执行条件",
    page.getByText("本地模拟执行条件已通过", { exact: true }),
  );
  const executeButton = page.getByRole("button", { name: "在本地模拟设备上执行" });
  assert.equal(await executeButton.isDisabled(), true, "Execution must require acknowledgement.");
  await page.getByRole("checkbox", { name: /我确认当前目标是本地 OPC-UA 模拟设备/ }).check();
  assert.equal(await executeButton.isEnabled(), true, "Acknowledgement must enable one execution.");
  await clickAndWait(
    page,
    "在本地模拟设备上执行",
    page.getByText("本地模拟设备执行成功", { exact: true }),
  );

  const rootCause = page.locator(".root-cause-card").first();
  const candidate = page.locator(".planning-candidate-card").first();
  const confirmedPlan = page.locator(".confirmed-plan");
  const replayResult = page.locator(".replay-result");
  const deviceReceipt = page.locator(".device-receipt");
  const rootText = await rootCause.textContent();
  const candidateText = await candidate.textContent();
  const confirmedText = await confirmedPlan.textContent();
  const replayText = await replayResult.textContent();
  const receiptText = await deviceReceipt.textContent();
  for (const expected of ["PLANE_TILT", "0.997781", "相对排序分数"]) {
    assert.ok(rootText?.includes(expected), `Fixed root-cause evidence is missing ${expected}.`);
  }
  for (const expected of ["保守调整方案", "CONSERVATIVE", "0.250000", "0.200000", "-1 ticks", "PASSED"]) {
    assert.ok(candidateText?.includes(expected), `Fixed candidate evidence is missing ${expected}.`);
  }
  for (const expected of ["已确认调参方案", "AA_PROCESS_ENGINEER"]) {
    assert.ok(confirmedText?.includes(expected), `ConfirmedPlan evidence is missing ${expected}.`);
  }
  for (const expected of ["仿真验证结果", "SUCCESS", "基线复现通过"]) {
    assert.ok(replayText?.includes(expected), `Simulation Validation evidence is missing ${expected}.`);
  }
  for (const expected of ["本地模拟设备执行成功", "SUCCEEDED", "0.200000"]) {
    assert.ok(receiptText?.includes(expected), `Device receipt evidence is missing ${expected}.`);
  }

  const actualAfter = (
    await page
      .locator(".device-receipt-grid > div")
      .filter({ hasText: "执行后读回值" })
      .locator("dd")
      .innerText()
  ).trim();
  const receiptHash = (await page.locator(".device-receipt-hash dd").innerText()).trim();
  assert.equal(actualAfter, "0.200000");
  assert.match(receiptHash, /^[a-f0-9]{64}$/);

  await captureElement(rootCause, "fixed-01-root-cause-top1.png");
  await captureElement(candidate, "fixed-02-selected-conservative-candidate.png");
  await captureElement(confirmedPlan, "fixed-03-confirmed-plan.png");
  await captureUnion(
    page,
    [page.locator(".replay-result-heading"), page.locator(".baseline-reproduction")],
    "fixed-04-replay-result.png",
  );
  await captureElement(deviceReceipt, "fixed-05-device-receipt.png");
  await deviceHeading.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: path.join(outputDirectory, "fixed-final-viewport-1440x1100.png"),
    fullPage: false,
    animations: "disabled",
    caret: "hide",
  });

  const fit = await viewportFit(page);
  assert.equal(fit.canScrollX, false, JSON.stringify(fit));
  assert.deepEqual(fit.offenders, [], JSON.stringify(fit));
  return {
    task_id: "tw-demo-task-001",
    top_root_cause: "PLANE_TILT",
    relative_ranking_score: "0.997781",
    selected_candidate: {
      parameter_name: "pitch",
      current_value: "0.250000",
      target_value: "0.200000",
      generation_type: "CONSERVATIVE",
      delta_ticks: -1,
      validation_status: "PASSED",
    },
    confirmed_plan_status: "VALID",
    simulation_validation_status: "SUCCESS",
    execution_surface: "LOCAL_OPCUA_SANDBOX",
    execution_status: "SUCCEEDED",
    actual_after_readback: actualAfter,
    receipt_hash: receiptHash,
    viewport_fit: fit,
  };
}

async function captureProcessAwareDemo(page) {
  await page.goto(processAwareUrl, { waitUntil: "networkidle", timeout: 30_000 });
  await page.getByTestId("scenario-comparison").waitFor({ state: "visible", timeout: 30_000 });
  await page.getByRole("heading", { level: 1, name: "结合调机步骤的决策演示" }).waitFor();
  const sharedEvidence = page.locator(".shared-evidence");
  const sharedTechnicalDetails = sharedEvidence.locator(".fingerprint-panel");
  await sharedTechnicalDetails.locator("summary").click();
  const sharedText = await sharedEvidence.textContent();
  for (const expected of ["测量数据", "相同", "根因判断", "PLANE_TILT", "Top-1"]) {
    assert.ok(sharedText?.includes(expected), `Shared process evidence is missing ${expected}.`);
  }

  const cards = page.getByTestId("scenario-comparison").locator(".scenario-card");
  assert.equal(await cards.count(), 2, "Process-aware A/B cards must share one comparison surface.");
  const scenarioA = cards.nth(0);
  const scenarioB = cards.nth(1);
  const scenarioAText = await scenarioA.textContent();
  const scenarioBText = await scenarioB.textContent();
  for (const expected of ["初始评估", "上一步调整", "无", "tw-aa-approved-011", "-3", "案例参考方案", "PASSED"]) {
    assert.ok(scenarioAText?.includes(expected), `Scenario A is missing ${expected}.`);
  }
  for (const expected of ["调整后评估", "0.250000", "0.200000", "未观察到显著改善", "tw-aa-approved-003", "-4", "案例参考方案", "PASSED"]) {
    assert.ok(scenarioBText?.includes(expected), `Scenario B is missing ${expected}.`);
  }
  const invariantBand = page.locator(".invariant-band");
  const invariantText = await invariantBand.textContent();
  for (const expected of ["保守调整方案未改变", "-1 ticks", "标准调整方案未改变", "-2 ticks", "PASSED"]) {
    assert.ok(invariantText?.includes(expected), `Process invariant evidence is missing ${expected}.`);
  }
  const pageText = await page.locator("body").textContent();
  for (const boundary of [
    "这是合成调机过程演示。",
    "它不代表舜宇真实调机 SOP，也不证明真实生产环境中的推荐准确率。",
  ]) {
    assert.ok(pageText?.includes(boundary), `Process-aware facts boundary is missing: ${boundary}`);
  }

  await captureElement(sharedEvidence.locator(".shared-evidence-grid"), "process-01-shared-evidence.png");
  await captureUnion(
    page,
    [scenarioA.locator(".scenario-header"), scenarioA.locator(".context-state"), scenarioA.locator(".eligible-case")],
    "process-02-scenario-a-path.png",
  );
  await captureElement(scenarioA.locator(".candidate-readout"), "process-03-scenario-a-candidate.png");
  await captureUnion(
    page,
    [scenarioB.locator(".scenario-header"), scenarioB.locator(".context-state"), scenarioB.locator(".eligible-case")],
    "process-04-scenario-b-path.png",
  );
  await captureElement(scenarioB.locator(".candidate-readout"), "process-05-scenario-b-candidate.png");
  await captureElement(invariantBand.locator(".invariant-grid"), "process-06-invariant-band.png");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(outputDirectory, "process-final-viewport-1440x1100.png"),
    fullPage: false,
    animations: "disabled",
    caret: "hide",
  });

  const fit = await viewportFit(page);
  assert.equal(fit.canScrollX, false, JSON.stringify(fit));
  assert.deepEqual(fit.offenders, [], JSON.stringify(fit));
  return {
    demo_version: "tw-process-aware-demo-v1",
    source_kind: "SYNTHETIC_TEST_FIXTURE",
    shared_evidence: {
      measurement_evidence: "SAME",
      top_root_cause: "PLANE_TILT",
      root_cause_evidence: "SAME",
    },
    scenario_a: {
      process_stage: "INITIAL_ASSESSMENT",
      previous_action: null,
      eligible_case: "tw-aa-approved-011",
      case_guided_pitch_ticks: -3,
    },
    scenario_b: {
      process_stage: "POST_ADJUSTMENT_EVALUATION",
      previous_action: "pitch 0.250000 -> 0.200000",
      previous_action_outcome: "NO_MATERIAL_IMPROVEMENT",
      eligible_case: "tw-aa-approved-003",
      case_guided_pitch_ticks: -4,
    },
    unchanged_controls: {
      conservative_pitch_ticks: -1,
      standard_pitch_ticks: -2,
      parameter_safety_validator: "PASSED",
    },
    viewport_fit: fit,
  };
}

const observations = {
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  externalRequests: [],
  observedRequests: [],
};

try {
  assert.equal(await portIsOpen(4841), false, "127.0.0.1:4841 must be free for the fixed sandbox.");
  assert.equal(await portIsOpen(webPort), false, `127.0.0.1:${webPort} must be free for capture.`);
  const pythonPath = path.join(repositoryRoot, "src");
  const baseEnvironment = {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH
      ? `${pythonPath}${path.delimiter}${process.env.PYTHONPATH}`
      : pythonPath,
  };
  const sandbox = startChild(
    "opcua-sandbox",
    pythonExecutable,
    [
      "-m",
      "tunewise.opcua_sandbox",
      "--endpoint",
      opcuaEndpoint,
      "--fault",
      "NORMAL",
      "--state-file",
      sandboxStatePath,
    ],
    baseEnvironment,
  );
  await waitForPort(4841, sandbox, "OPC-UA sandbox");

  const webEnvironment = {
    ...baseEnvironment,
    TUNEWISE_DATABASE_PATH: databasePath,
    TUNEWISE_DEVICE_EXECUTION_ENABLED: "true",
    TUNEWISE_OPCUA_MODE: "OPCUA_SANDBOX",
    TUNEWISE_RUNTIME_PROFILE: "OPCUA_SANDBOX_DEMO",
    TUNEWISE_OPCUA_SANDBOX_ENDPOINT: opcuaEndpoint,
  };
  const webServer = startChild(
    "tunewise-web",
    pythonExecutable,
    [
      "-m",
      "uvicorn",
      "tunewise.main:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(webPort),
      "--log-level",
      "info",
    ],
    webEnvironment,
  );
  await waitForHttp(targetUrl, webServer);

  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const fixedPage = await context.newPage();
  observePage(fixedPage, "fixed-demo", observations);
  const fixedDemo = await captureFixedDemo(fixedPage);
  const processPage = await context.newPage();
  observePage(processPage, "process-aware-demo", observations);
  const processAwareDemo = await captureProcessAwareDemo(processPage);

  assert.deepEqual(observations.consoleErrors, [], JSON.stringify(observations.consoleErrors));
  assert.deepEqual(observations.pageErrors, [], JSON.stringify(observations.pageErrors));
  assert.deepEqual(observations.failedRequests, [], JSON.stringify(observations.failedRequests));
  assert.deepEqual(observations.externalRequests, [], JSON.stringify(observations.externalRequests));
  assert.ok(
    observations.observedRequests.some(({ url }) => new URL(url).pathname === "/api/demos/process-aware"),
    "Process-aware endpoint request was not observed.",
  );

  const screenshots = [];
  for (const name of expectedScreenshotNames) {
    const filePath = path.join(outputDirectory, name);
    const info = await stat(filePath);
    assert.ok(info.size > 0, `${name} is empty.`);
    screenshots.push(await fileEvidence(filePath));
  }
  const ailyEvidence = await fileEvidence(ailySource);
  const evidence = {
    evidence_version: "tw-40-final-runtime-screenshot-evidence-v1",
    generated_at: new Date().toISOString(),
    capture_script: "docs/submission/capture_40_final_runtime_screenshots.mjs",
    viewport,
    runtime: {
      web_origin: targetUrl,
      loopback_only: true,
      independent_temporary_database: true,
      temporary_database_removed_after_capture: true,
      opcua_surface: "LOCAL_OPCUA_SANDBOX",
    },
    fixed_demo: fixedDemo,
    process_aware_demo: processAwareDemo,
    aily_live_screenshot: {
      ...ailyEvidence,
      evidence_kind: "manual UI / conversational acceptance evidence",
      question_scope: "fixed Demo PLANE_TILT Top-1 explanation",
      process_aware_q5: false,
      device_control_evidence: false,
    },
    screenshots,
    observations: {
      observed_http_request_count: observations.observedRequests.length,
      console_error_count: observations.consoleErrors.length,
      page_error_count: observations.pageErrors.length,
      failed_request_count: observations.failedRequests.length,
      external_request_count: observations.externalRequests.length,
    },
    facts_boundary: {
      fixed_demo: "Real running software UI; synthetic fixed dataset; LOCAL OPC-UA SANDBOX; not production validation.",
      process_aware_demo: "Real running software UI; synthetic process-context fixtures; not Sunny Optical SOP or production tuning accuracy.",
      aily: "Real published Aily screenshot for a fixed-Demo question; not Process-aware Q5 and not device-control evidence.",
    },
  };
  const evidencePath = path.join(outputDirectory, "runtime-screenshot-evidence.json");
  await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  const manifestEntries = [
    ...screenshots,
    ailyEvidence,
    {
      file: path.relative(repositoryRoot, evidencePath).replaceAll("\\", "/"),
      sha256: createHash("sha256").update(await readFile(evidencePath)).digest("hex"),
    },
  ];
  await writeFile(
    path.join(outputDirectory, "runtime-screenshot-manifest.sha256"),
    `${manifestEntries.map((entry) => `${entry.sha256}  ${entry.file}`).join("\n")}\n`,
    "utf8",
  );
  await writeFile(
    path.join(outputDirectory, "capture-services.log"),
    childLogs.join(""),
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
} finally {
  await context?.close().catch(() => {});
  await browser?.close().catch(() => {});
  for (const { name, child } of children.reverse()) {
    await stopChild(name, child).catch((error) => {
      process.stderr.write(`Failed to stop ${name}: ${String(error)}\n`);
    });
  }
  const resolvedTemporaryRoot = path.resolve(temporaryRoot);
  const resolvedOsTemp = path.resolve(os.tmpdir());
  assert.ok(
    resolvedTemporaryRoot.startsWith(`${resolvedOsTemp}${path.sep}tunewise-40-final-capture-`),
    "Refusing to remove an unexpected temporary capture directory.",
  );
  await rm(resolvedTemporaryRoot, { recursive: true, force: false });
}
