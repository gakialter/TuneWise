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
  "这是合成调机过程演示。",
  "当前演示用于证明 TuneWise 能根据不同调机过程信息选择不同的历史参考案例。",
  "它不代表舜宇真实调机 SOP，也不证明真实生产环境中的推荐准确率。",
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
      clippedChinese: [...document.querySelectorAll("body *")]
        .filter((element) => {
          const style = window.getComputedStyle(element);
          const text = element.childElementCount === 0 ? element.textContent?.trim() ?? "" : "";
          return (
            /[\u3400-\u9fff]/u.test(text) &&
            ["hidden", "clip"].includes(style.overflow) &&
            (element.scrollWidth > element.clientWidth + 1 ||
              element.scrollHeight > element.clientHeight + 1)
          );
        })
        .slice(0, 20)
        .map((element) => ({ tag: element.tagName, text: element.textContent?.trim() })),
    };
  });
}

async function assertVisibleText(page, text, message = text) {
  const locator = page.getByText(text, { exact: true });
  assert.ok(await locator.count(), `Missing ${message}.`);
  assert.equal(await locator.first().isVisible(), true, `${message} is not visible.`);
}

async function scrollToTopInstantly(page) {
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = "auto";
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.waitForFunction(() => window.scrollY === 0);
}

async function assertSharedContent(page) {
  await page.getByTestId("scenario-comparison").waitFor({ state: "visible", timeout: 30_000 });
  assert.equal(
    await page.getByRole("heading", { level: 1, name: "结合调机步骤的决策演示" }).count(),
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
  await assertVisibleText(page, "测量数据");
  await assertVisibleText(page, "根因判断");
  await assertVisibleText(page, "异常数据相同");
  await assertVisibleText(page, "调机过程不同");
  await assertVisibleText(page, "当前适用案例不同");
  await assertVisibleText(page, "案例参考方案不同");

  const sharedEvidence = page.locator(".shared-evidence");
  assert.ok((await sharedEvidence.textContent())?.includes("pitch/roll 平面倾斜"), "Chinese Top-1 must be visible.");
  assert.ok((await sharedEvidence.textContent())?.includes("Top-1"), "Shared evidence must label Top-1.");

  const englishBoundary = page.locator(".boundary-english");
  await englishBoundary.locator("summary").click();
  await assertVisibleText(
    page,
    "Synthetic process-context demonstration. Does not represent Sunny Optical SOP or validated production tuning accuracy.",
  );
  await englishBoundary.locator("summary").click();

  const sharedTechnicalDetails = page.locator(".fingerprint-panel");
  await sharedTechnicalDetails.locator("summary").click();
  await assertVisibleText(page, "PLANE_TILT");
  await assertVisibleText(page, "50 维");
  await sharedTechnicalDetails.locator("summary").click();

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
    "上一步调整",
    "无",
    "tw-aa-approved-011",
    "CONTEXT_MATCH",
    "-3",
    "合成调机过程",
    "合成案例条件",
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
    "未观察到显著改善",
    "tw-aa-approved-003",
    "CONTEXT_MATCH",
    "-4",
    "合成调机过程",
    "合成案例条件",
  ]) {
    assert.ok(scenarioBText?.includes(expected), `Scenario B is missing ${expected}.`);
  }

  const scenarioTechnicalDetails = scenarioA.locator(".scenario-technical-details");
  await scenarioTechnicalDetails.locator("summary").click();
  assert.equal(
    await scenarioTechnicalDetails.getByText("CONTEXT_MATCH", { exact: true }).isVisible(),
    true,
    "Scenario reason code must be available on demand.",
  );
  await scenarioTechnicalDetails.locator("summary").click();

  assert.equal(
    await comparison.getByText("用于案例排序，不是概率。", { exact: true }).count(),
    2,
    "Both distances must be distinguished from probabilities.",
  );
  await assertVisibleText(page, "保守调整方案未改变");
  await assertVisibleText(page, "标准调整方案未改变");
  await assertVisibleText(page, "安全校验规则未改变");
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
  assert.deepEqual(desktopFit.clippedChinese, [], "Desktop page has clipped Chinese text.");
  await scrollToTopInstantly(desktopPage);
  await desktopPage.screenshot({
    path: path.join(outputDirectory, "process-aware-desktop-1440.png"),
    fullPage: false,
  });
  await desktopPage.getByTestId("scenario-comparison").scrollIntoViewIfNeeded();
  await desktopPage.screenshot({
    path: path.join(outputDirectory, "process-aware-desktop-comparison-1440.png"),
    fullPage: false,
  });
  report.viewports.desktop = {
    width: 1440,
    height: 1100,
    fit: desktopFit,
    screenshots: ["process-aware-desktop-1440.png", "process-aware-desktop-comparison-1440.png"],
  };

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
  assert.deepEqual(mobileFit.clippedChinese, [], "Mobile page has clipped Chinese text.");
  await scrollToTopInstantly(mobilePage);
  await mobilePage.screenshot({
    path: path.join(outputDirectory, "process-aware-mobile-390.png"),
    fullPage: false,
  });
  await mobilePage.getByTestId("scenario-comparison").scrollIntoViewIfNeeded();
  await mobilePage.screenshot({
    path: path.join(outputDirectory, "process-aware-mobile-comparison-390.png"),
    fullPage: false,
  });
  report.viewports.mobile = {
    width: 390,
    height: 844,
    fit: mobileFit,
    screenshots: ["process-aware-mobile-390.png", "process-aware-mobile-comparison-390.png"],
  };

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
