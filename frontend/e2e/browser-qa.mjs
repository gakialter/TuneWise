import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

import { chromium } from "playwright";

const targetUrl = process.env.TUNEWISE_QA_URL ?? "http://127.0.0.1:8123";
const outputDirectory = path.resolve(
  process.env.TUNEWISE_QA_OUTPUT ?? "../docs/validation",
);
const targetOrigin = new URL(targetUrl).origin;

await mkdir(outputDirectory, { recursive: true });

const browser = await chromium.launch({
  headless: process.env.TUNEWISE_QA_HEADLESS === "true",
});
const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];
const externalRequests = [];
const observedRequests = [];

function observe(page) {
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    failedRequests.push({
      url: request.url(),
      failure: request.failure()?.errorText ?? "unknown",
    });
  });
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith("http://") && !url.startsWith("https://")) return;
    observedRequests.push(url);
    if (new URL(url).origin !== targetOrigin) externalRequests.push(url);
  });
}

async function viewportFit(page) {
  return page.evaluate(() => {
    const root = document.documentElement;
    const isInsideHorizontalScroller = (element) => {
      let parent = element.parentElement;
      while (parent && parent !== document.body) {
        const style = window.getComputedStyle(parent);
        if (
          ["auto", "scroll"].includes(style.overflowX) &&
          parent.scrollWidth > parent.clientWidth
        ) return true;
        parent = parent.parentElement;
      }
      return false;
    };
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
          !isInsideHorizontalScroller(element) &&
          (rect.left < -1 || rect.right > window.innerWidth + 1)
        );
      })
      .slice(0, 20)
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: element.className,
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

async function clickAndWait(page, buttonName, result) {
  await page.getByRole("button", { name: buttonName }).click();
  await result.waitFor({ state: "visible", timeout: 60_000 });
}

let mobileContext;
let desktopContext;
try {
  mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const mobilePage = await mobileContext.newPage();
  observe(mobilePage);
  await mobilePage.goto(targetUrl, { waitUntil: "networkidle" });

  assert.equal(
    await mobilePage.getByRole("heading", { name: "本地 OPC-UA 模拟设备受控下发" }).count(),
    0,
    "设备执行区不得早于成功回放出现",
  );

  await clickAndWait(
    mobilePage,
    "导入预置 AA 异常批次",
    mobilePage.getByText("CSV 与 Manifest 校验通过", { exact: true }),
  );
  await clickAndWait(
    mobilePage,
    "运行异常检测",
    mobilePage.getByRole("heading", { name: "检测到四角 MTF 不对称下降" }),
  );
  await clickAndWait(
    mobilePage,
    "运行根因诊断",
    mobilePage.getByRole("heading", { name: "Top-3 根因排查顺序" }),
  );
  await clickAndWait(
    mobilePage,
    "检索已审核案例",
    mobilePage.getByRole("button", { name: "案例检索已完成" }),
  );
  await clickAndWait(
    mobilePage,
    "生成安全参数候选",
    mobilePage.getByRole("radio", { name: /CONSERVATIVE/ }),
  );
  await mobilePage.getByRole("radio", { name: /CONSERVATIVE/ }).click();
  await clickAndWait(
    mobilePage,
    "人工确认候选方案",
    mobilePage.getByRole("heading", { name: "方案已人工确认并冻结" }),
  );
  await clickAndWait(
    mobilePage,
    "运行离线模拟回放",
    mobilePage.getByRole("heading", { name: "回放结果" }),
  );

  const devicePanel = mobilePage.getByRole("heading", {
    name: "本地 OPC-UA 模拟设备受控下发",
  });
  await devicePanel.waitFor({ state: "visible" });
  assert.equal(
    await mobilePage.getByText("模拟设备连接状态待确认", { exact: true }).count(),
    1,
    "资格响应前不得宣称 sandbox 已开启",
  );
  await mobilePage.getByText(
    /当前功能仅面向本地 OPC-UA 模拟设备，连接状态以上方服务端检查为准/,
  ).waitFor();

  await clickAndWait(
    mobilePage,
    "检查设备执行资格",
    mobilePage.getByText("设备执行资格已通过", { exact: true }),
  );
  const executeButton = mobilePage.getByRole("button", {
    name: "向模拟设备执行受控下发",
  });
  assert.equal(await executeButton.isDisabled(), true, "未独立确认时执行按钮必须禁用");
  await mobilePage.getByRole("checkbox", { name: /我确认当前目标是本地 OPC-UA 模拟设备/ }).check();
  assert.equal(await executeButton.isEnabled(), true, "独立确认后才允许提交受控执行");
  await clickAndWait(
    mobilePage,
    "向模拟设备执行受控下发",
    mobilePage.getByText("写入并回读验证成功", { exact: true }),
  );

  const receiptHash = (
    await mobilePage.locator(".device-receipt-hash dd").innerText()
  ).trim();
  const actualAfter = (
    await mobilePage
      .locator(".device-receipt-grid > div")
      .filter({ hasText: "写后回读值" })
      .locator("dd")
      .innerText()
  ).trim();
  assert.match(receiptHash, /^[a-f0-9]{64}$/);
  assert.equal(actualAfter, "0.200000");

  await devicePanel.scrollIntoViewIfNeeded();
  const mobileTopFit = await viewportFit(mobilePage);
  assert.equal(mobileTopFit.canScrollX, false, JSON.stringify(mobileTopFit));
  assert.deepEqual(mobileTopFit.offenders, [], JSON.stringify(mobileTopFit));
  const mobileTopScreenshot = path.join(
    outputDirectory,
    "opcua-sandbox-mobile-390.png",
  );
  await mobilePage.screenshot({ path: mobileTopScreenshot, fullPage: false });
  await mobilePage.locator(".device-receipt").scrollIntoViewIfNeeded();
  const mobileReceiptFit = await viewportFit(mobilePage);
  assert.equal(
    mobileReceiptFit.canScrollX,
    false,
    JSON.stringify(mobileReceiptFit),
  );
  assert.deepEqual(
    mobileReceiptFit.offenders,
    [],
    JSON.stringify(mobileReceiptFit),
  );
  const mobileReceiptScreenshot = path.join(
    outputDirectory,
    "opcua-sandbox-mobile-390-receipt.png",
  );
  await mobilePage.screenshot({
    path: mobileReceiptScreenshot,
    fullPage: false,
  });

  desktopContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const desktopPage = await desktopContext.newPage();
  observe(desktopPage);
  await desktopPage.goto(targetUrl, { waitUntil: "networkidle" });
  const desktopPanel = desktopPage.getByRole("heading", {
    name: "本地 OPC-UA 模拟设备受控下发",
  });
  await desktopPanel.waitFor({ state: "visible" });
  await desktopPanel.scrollIntoViewIfNeeded();
  const desktopFit = await viewportFit(desktopPage);
  assert.equal(desktopFit.canScrollX, false, JSON.stringify(desktopFit));
  const desktopScreenshot = path.join(
    outputDirectory,
    "opcua-sandbox-desktop-1440.png",
  );
  await desktopPage.screenshot({ path: desktopScreenshot, fullPage: false });

  assert.deepEqual(consoleErrors, [], `console errors: ${consoleErrors.join(" | ")}`);
  assert.deepEqual(pageErrors, [], `page errors: ${pageErrors.join(" | ")}`);
  assert.deepEqual(failedRequests, [], JSON.stringify(failedRequests));
  assert.deepEqual(externalRequests, [], JSON.stringify(externalRequests));

  const evidence = {
    evidence_version: "tw-browser-qa-evidence-v1",
    target_origin: targetOrigin,
    execution_surface: "LOCAL_OPCUA_SANDBOX",
    replay_status: "SUCCESS",
    execution_status: "SUCCEEDED",
    actual_after_value: actualAfter,
    receipt_hash: receiptHash,
    mobile_viewport: { width: 390, height: 844 },
    mobile_fit: {
      device_panel_top: mobileTopFit,
      receipt: mobileReceiptFit,
    },
    desktop_viewport: { width: 1440, height: 900 },
    desktop_fit: desktopFit,
    observed_http_request_count: observedRequests.length,
    external_http_request_count: externalRequests.length,
    console_error_count: consoleErrors.length,
    page_error_count: pageErrors.length,
    failed_request_count: failedRequests.length,
    screenshots: [
      path.basename(mobileTopScreenshot),
      path.basename(mobileReceiptScreenshot),
      path.basename(desktopScreenshot),
    ],
  };
  await writeFile(
    path.join(outputDirectory, "browser-qa-evidence.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
} finally {
  await desktopContext?.close();
  await mobileContext?.close();
  await browser.close();
}
