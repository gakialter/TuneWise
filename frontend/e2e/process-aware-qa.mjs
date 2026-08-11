import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const requestedOutput = process.env.TUNEWISE_PROCESS_QA_OUTPUT;
assert.ok(
  requestedOutput,
  "TUNEWISE_PROCESS_QA_OUTPUT must name a dedicated QA output directory.",
);

const outputDirectory = path.resolve(requestedOutput);
const protectedValidationDirectory = path.resolve(scriptDirectory, "../../docs/validation");
assert.ok(
  outputDirectory !== protectedValidationDirectory &&
    !outputDirectory.startsWith(`${protectedValidationDirectory}${path.sep}`),
  "Process-aware QA refuses to write into docs/validation.",
);

const targetUrl = process.env.TUNEWISE_PROCESS_QA_URL ??
  "http://127.0.0.1:8000/process-aware-demo/";
const targetOrigin = new URL(targetUrl).origin;
const factsBoundary = [
  "Synthetic process-context demonstration.",
  "Demonstrates deterministic context-sensitive evidence selection.",
  "Does not represent Sunny Optical SOP or validated production tuning accuracy.",
];
const forbiddenClaims = [
  "Real AA Process",
  "Sunny Optical Workflow",
  "Production Tuning History",
  "Validated Production Recommendation",
];

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({
  headless: process.env.TUNEWISE_PROCESS_QA_HEADLESS !== "false",
});
const observations = {
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
  externalRequests: [],
  observedRequests: [],
};

function observe(page, surface) {
  page.on("console", (message) => {
    if (message.type() === "error") {
      observations.consoleErrors.push({ surface, text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    observations.pageErrors.push({ surface, message: error.message });
  });
  page.on("requestfailed", (request) => {
    observations.failedRequests.push({
      surface,
      url: request.url(),
      failure: request.failure()?.errorText ?? "unknown",
    });
  });
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    observations.observedRequests.push({ surface, url });
    if (new URL(url).origin !== targetOrigin) {
      observations.externalRequests.push({ surface, url });
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
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      canScrollX: root.scrollWidth > root.clientWidth,
      offenders,
    };
  });
}

async function assertVisibleText(page, text, message = text) {
  const locator = page.getByText(text, { exact: true });
  assert.ok(await locator.count(), `Missing ${message}.`);
  assert.equal(await locator.first().isVisible(), true, `${message} is not visible.`);
}

async function assertSharedContent(page) {
  await page.getByTestId("scenario-comparison").waitFor({ state: "visible", timeout: 30_000 });
  assert.equal(
    await page.getByRole("heading", { level: 1, name: "Process-aware Decision Demo" }).count(),
    1,
    "The exact h1 must appear once.",
  );

  for (const sentence of factsBoundary) {
    await assertVisibleText(page, sentence, `facts-boundary sentence: ${sentence}`);
  }
  await assertVisibleText(
    page,
    "TuneWise process-context abstractions; not industry-standard states.",
  );
  await assertVisibleText(page, "Same measurement evidence");
  await assertVisibleText(page, "Same root-cause ranking");
  await assertVisibleText(page, "50-D");

  const sharedEvidence = page.locator(".shared-evidence");
  assert.ok((await sharedEvidence.textContent())?.includes("PLANE_TILT"), "PLANE_TILT must be shared Top-1.");
  assert.ok((await sharedEvidence.textContent())?.includes("Top-1"), "Shared evidence must label Top-1.");

  const comparison = page.getByTestId("scenario-comparison");
  const scenarioCards = comparison.locator(".scenario-card");
  assert.equal(await scenarioCards.count(), 2, "A and B must be present in one comparison region.");

  const scenarioA = scenarioCards.nth(0);
  const scenarioB = scenarioCards.nth(1);
  const scenarioAText = await scenarioA.textContent();
  const scenarioBText = await scenarioB.textContent();
  for (const expected of [
    "Initial Assessment",
    "初始评估",
    "INITIAL_ASSESSMENT",
    "No previous action / outcome",
    "Case 011",
    "tw-aa-approved-011",
    "CONTEXT_MATCH",
    "-3",
    "Synthetic context",
    "Synthetic profile",
  ]) {
    assert.ok(scenarioAText?.includes(expected), `Scenario A is missing ${expected}.`);
  }
  for (const expected of [
    "Post-adjustment Evaluation",
    "调整后评估",
    "POST_ADJUSTMENT_EVALUATION",
    "0.250000",
    "0.200000",
    "NO_MATERIAL_IMPROVEMENT",
    "No Material Improvement / 未观察到显著改善",
    "Case 003",
    "tw-aa-approved-003",
    "CONTEXT_MATCH",
    "-4",
    "Synthetic context",
    "Synthetic profile",
  ]) {
    assert.ok(scenarioBText?.includes(expected), `Scenario B is missing ${expected}.`);
  }

  assert.equal(
    await comparison.getByText("Retrieval distance, not a probability.", { exact: true }).count(),
    2,
    "Both distances must be distinguished from probabilities.",
  );
  await assertVisibleText(page, "CONSERVATIVE unchanged");
  await assertVisibleText(page, "STANDARD unchanged");
  await assertVisibleText(page, "Safety Validator unchanged");
  const hashProofs = page.locator(".control-hash-proof");
  assert.equal(await hashProofs.count(), 2, "Both controls must expose A/B hash evidence.");
  for (let index = 0; index < 2; index += 1) {
    const proof = hashProofs.nth(index);
    const renderedHashes = await proof.locator("code").evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("title")),
    );
    assert.equal(renderedHashes.length, 2, "Each control must render A and B hashes.");
    assert.equal(renderedHashes[0], renderedHashes[1], "Rendered A/B control hashes must match.");
    assert.ok((await proof.textContent())?.includes("="), "Hash proof must display equality.");
  }
  await assertVisibleText(page, "PASSED");

  const bodyText = await page.locator("body").textContent();
  for (const forbiddenClaim of forbiddenClaims) {
    assert.equal(
      bodyText?.includes(forbiddenClaim),
      false,
      `Forbidden positive claim rendered: ${forbiddenClaim}`,
    );
  }
}

const report = {
  targetUrl,
  generatedAt: new Date().toISOString(),
  viewports: {},
  observations,
};

let desktopContext;
let mobileContext;
try {
  desktopContext = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const desktopPage = await desktopContext.newPage();
  observe(desktopPage, "desktop-1440");
  await desktopPage.goto(targetUrl, { waitUntil: "networkidle", timeout: 30_000 });
  await assertSharedContent(desktopPage);

  const desktopCards = desktopPage.getByTestId("scenario-comparison").locator(".scenario-card");
  const desktopA = await desktopCards.nth(0).boundingBox();
  const desktopB = await desktopCards.nth(1).boundingBox();
  assert.ok(desktopA && desktopB, "Desktop A/B cards must have layout boxes.");
  assert.ok(desktopA.x < desktopB.x, "Desktop A must appear left of B.");
  assert.ok(Math.abs(desktopA.y - desktopB.y) <= 2, "Desktop A/B must share one row.");

  const desktopFit = await viewportFit(desktopPage);
  assert.equal(desktopFit.canScrollX, false, "Desktop page must not scroll horizontally.");
  assert.deepEqual(desktopFit.offenders, [], "Desktop page has horizontal overflow offenders.");
  await desktopPage.screenshot({
    path: path.join(outputDirectory, "process-aware-desktop-1440.png"),
    fullPage: true,
  });
  report.viewports.desktop = { width: 1440, height: 1100, fit: desktopFit };

  mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const mobilePage = await mobileContext.newPage();
  observe(mobilePage, "mobile-390");
  await mobilePage.goto(targetUrl, { waitUntil: "networkidle", timeout: 30_000 });
  await assertSharedContent(mobilePage);

  const mobileCards = mobilePage.getByTestId("scenario-comparison").locator(".scenario-card");
  const mobileA = await mobileCards.nth(0).boundingBox();
  const mobileB = await mobileCards.nth(1).boundingBox();
  assert.ok(mobileA && mobileB, "Mobile A/B cards must have layout boxes.");
  assert.ok(mobileA.y < mobileB.y, "Mobile B must stack below A.");
  assert.ok(mobileA.width <= 390 && mobileB.width <= 390, "Mobile cards must fit 390px.");

  const mobileFit = await viewportFit(mobilePage);
  assert.equal(mobileFit.canScrollX, false, "Mobile page must not scroll horizontally.");
  assert.deepEqual(mobileFit.offenders, [], "Mobile page has horizontal overflow offenders.");
  await mobilePage.screenshot({
    path: path.join(outputDirectory, "process-aware-mobile-390.png"),
    fullPage: true,
  });
  report.viewports.mobile = { width: 390, height: 844, fit: mobileFit };

  assert.ok(
    observations.observedRequests.some(({ url }) =>
      new URL(url).pathname === "/api/demos/process-aware"),
    "QA must observe the process-aware API request.",
  );
  assert.deepEqual(observations.externalRequests, [], "No external requests are allowed.");
  assert.deepEqual(observations.failedRequests, [], "No requests may fail.");
  assert.deepEqual(observations.consoleErrors, [], "Console errors are not allowed.");
  assert.deepEqual(observations.pageErrors, [], "Page errors are not allowed.");

  await writeFile(
    path.join(outputDirectory, "process-aware-qa-evidence.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
  console.log(JSON.stringify({ status: "passed", outputDirectory, ...report }, null, 2));
} finally {
  await mobileContext?.close();
  await desktopContext?.close();
  await browser.close();
}
