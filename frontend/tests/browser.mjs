import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = fileURLToPath(new URL("../../", import.meta.url));
const output = path.join(root, "test-results");
await fs.mkdir(path.join(output, "screenshots"), { recursive: true });
const temporary = await fs.mkdtemp(
  path.join(os.tmpdir(), "agent-arena-browser-"),
);
const portServer = net.createServer();
await new Promise((resolve) => portServer.listen(0, "127.0.0.1", resolve));
const port = portServer.address().port;
await new Promise((resolve) => portServer.close(resolve));
const base = `http://127.0.0.1:${port}`;
const python =
  process.env.ARENA_PYTHON ||
  path.join(
    root,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
const server = spawn(python, ["-m", "arena.main"], {
  cwd: root,
  env: {
    ...process.env,
    ARENA_DATA_DIR: temporary,
    ARENA_PORT: String(port),
    REDIS_URL: "",
    PYTHONIOENCODING: "utf-8",
    MODEL_API_KEY: "",
    MODEL_NAME: "",
  },
  windowsHide: true,
});
let serverLog = "";
server.stdout.on("data", (chunk) => {
  serverLog += chunk.toString();
});
server.stderr.on("data", (chunk) => {
  serverLog += chunk.toString();
});
const deadline = Date.now() + 30000;
let ready = false;
while (Date.now() < deadline && server.exitCode === null) {
  try {
    const response = await fetch(base + "/api/health");
    if (response.ok) {
      ready = true;
      break;
    }
  } catch {}
  await new Promise((resolve) => setTimeout(resolve, 150));
}
if (!ready) {
  server.kill();
  throw new Error("API did not start: " + serverLog);
}
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BROWSER_PATH
    ? { executablePath: process.env.BROWSER_PATH }
    : process.platform === "win32"
      ? {
          executablePath:
            "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        }
      : {}),
});
const page = await browser.newPage({
  viewport: { width: 1440, height: 1100 },
  deviceScaleFactor: 1,
  reducedMotion: "reduce",
});
const errors = [],
  results = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 500)
    errors.push(`${response.status()} ${response.url()}`);
});
page.setDefaultTimeout(12000);
async function check(name, work) {
  try {
    await work();
    results.push({ name, passed: true });
    console.log("PASS", name);
  } catch (error) {
    results.push({ name, passed: false, error: error.message });
    await page.screenshot({
      path: path.join(output, "screenshots", "failure.png"),
      fullPage: true,
    });
    throw error;
  }
}
async function shot(name) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: path.join(output, "screenshots", name + ".png"),
    fullPage: true,
  });
}
async function noOverflow() {
  // Chromium may expose the previous layout's scroll extent for a frame after resize.
  await page.waitForFunction(
    () =>
      document.documentElement.scrollWidth <=
      document.documentElement.clientWidth + 1,
    null,
    { timeout: 2000 },
  );
  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  assert(dimensions.scroll <= dimensions.width + 1, JSON.stringify(dimensions));
}
async function get(pathname) {
  return (await fetch(base + "/api" + pathname)).json();
}
let arenaId;
let reviewedArenaId;
let panoramaArenaId;
try {
  await check("Dashboard renders actual persisted competitions", async () => {
    await page.goto(base);
    await page.getByRole("heading", { name: "竞技场", exact: true }).waitFor();
    assert.equal(await page.locator(".arena-card").count(), 2);
    await noOverflow();
    await shot("dashboard-desktop");
    await page.getByRole("link", { name: /周末市集/ }).click();
    await page.locator(".theatre-shop").first().waitFor();
    assert.equal(
      await page.locator(".round-display>strong").textContent(),
      "12",
    );
    await shot("arena-desktop");
  });
  await check("Create form fits desktop and mobile and limits tool options to LLM", async () => {
    await page.goto(base);
    await page.getByRole("button", { name: "创建对局", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "创建对局", exact: true });
    assert.equal(await dialog.getByLabel("商店 1 工具预算").count(), 0);
    await dialog.getByLabel("商店 1 决策引擎").selectOption("llm");
    await dialog.getByLabel("商店 1 工具预算").fill("2");
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 1100 });
      const card = dialog.locator(".merchant-form").first();
      await card.scrollIntoViewIfNeeded();
      const layout = await card.evaluate((element) => {
        const controls = [...element.querySelectorAll("input, select, button")];
        const boxes = controls.map((control) => control.getBoundingClientRect());
        return {
          overflow: element.scrollWidth > element.clientWidth + 1,
          overlapping: boxes.some((a, i) => boxes.slice(i + 1).some((b) =>
            Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1)),
          clipped: controls.filter((control) => control.tagName !== "BUTTON").some((control) => {
            const canvas = document.createElement("canvas");
            const context = canvas.getContext("2d");
            const style = getComputedStyle(control);
            context.font = `${style.fontSize} ${style.fontFamily}`;
            const value = control.tagName === "SELECT" ? control.selectedOptions[0]?.textContent || "" : control.value;
            return context.measureText(value).width + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + (control.tagName === "SELECT" ? 22 : 0) > control.clientWidth;
          }),
        };
      });
      assert.deepEqual(layout, { overflow: false, overlapping: false, clipped: false }, `Form width ${width}`);
      await shot(`create-form-${width}`);
    }
    await dialog.getByLabel("商店 1 决策引擎").selectOption("rule");
    assert.equal(await dialog.getByLabel("商店 1 工具预算").count(), 0);
    assert.equal(await dialog.getByLabel("商店 1 模型", { exact: true }).count(), 0);
    assert.equal(await dialog.getByLabel("商店 1 名称").inputValue(), "北辰商店");
    assert((await dialog.getByLabel("商店 1 决策流程").textContent()).includes("按风险触发规则试算"));
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 1100 });
  });
  await check("Create, step, run, pause and resume a competition", async () => {
    await page.goto(base);
    await page.getByRole("button", { name: "创建对局", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "创建对局", exact: true });
    await dialog.getByLabel("对局名称").fill("浏览器完整验收");
    await dialog.getByLabel("回合数", { exact: true }).fill("6");
    await dialog.getByLabel("市场种子").fill("314");
    await dialog.getByRole("button", { name: "创建对局", exact: true }).click();
    await page.waitForURL(/\/arenas\/\d+$/);
    arenaId = Number(new URL(page.url()).pathname.split("/").pop());
    await page.getByRole("button", { name: "单步", exact: true }).click();
    await page.waitForFunction(
      () =>
        document.querySelector(".round-display>strong")?.textContent === "01",
    );
    await page.getByRole("button", { name: "继续比赛", exact: true }).click();
    await page.getByRole("button", { name: "暂停比赛", exact: true }).click();
    await page.waitForFunction(
      () =>
        document.querySelector(".arena-subtitle .status-badge")?.textContent ===
        "已暂停",
    );
    const paused = await get(`/arenas/${arenaId}`);
    assert(paused.current_round < 6);
    await page.getByLabel("比赛速度").selectOption("4");
    await page.getByRole("button", { name: "继续比赛", exact: true }).click();
    await page.waitForFunction(
      () =>
        document.querySelector(".arena-subtitle .status-badge")?.textContent ===
        "已完赛",
    );
    const completed = await get(`/arenas/${arenaId}`);
    assert.equal(completed.current_round, 6);
    await page.reload();
    await page.waitForFunction(
      () =>
        document.querySelector(".round-display>strong")?.textContent === "06",
    );
  });
  await check("Replay, tool traces, ledger and complete export", async () => {
    const slider = page.getByRole("slider", { name: "回放回合" });
    await slider.focus();
    await slider.press("Home");
    await slider.press("ArrowRight");
    await page.waitForFunction(
      () =>
        document.querySelector(".round-display>strong")?.textContent === "01",
    );
    await page.getByRole("tab", { name: /决策轨迹/ }).click();
    await page.locator(".decision-summary").waitFor();
    assert.equal(await page.locator(".workflow-line>div").count(), 5);
    assert.equal(await page.locator(".tool-list").count(), 0);
    await page.locator(".context-data").last().locator("summary").click();
    assert(
      (await page.locator(".context-data pre").last().textContent()).includes(
        "cash",
      ),
    );
    await shot("decision-trace");
    await page.getByRole("tab", { name: "交易账本" }).click();
    await page.locator("tbody tr").first().waitFor();
    const roundLabels = await page
      .locator("tbody .round-tag")
      .allTextContents();
    assert(roundLabels.every((value) => value === "R01"));
    await page.getByText("导出", { exact: true }).click();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: "完整比赛 · JSON" }).click();
    const download = await downloadPromise;
    const exported = JSON.parse(
      await fs.readFile(await download.path(), "utf8"),
    );
    assert.equal(exported.snapshots.length, 7);
    assert.equal(exported.decisions.length, 18);
    await page.getByRole("button", { name: "当前", exact: true }).click();
    await page.getByRole("button", { name: "再赛一场" }).click();
    await page.waitForURL(
      (url) => Number(url.pathname.split("/").pop()) !== arenaId,
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".round-display>strong")?.textContent === "00",
    );
  });
  await check("Strategies can be copied, edited and persisted", async () => {
    await page.goto(base + "/strategies");
    await page
      .getByRole("button", { name: "复制稳健经营", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "创建策略", exact: true });
    await dialog.getByLabel("策略名称", { exact: true }).fill("我的周转策略");
    await dialog.getByLabel("策略摘要").fill("低库存，高周转");
    await dialog.getByLabel("目标备货回合").fill("0.9");
    await dialog.getByRole("button", { name: "保存策略" }).click();
    await page
      .getByRole("heading", { name: "我的周转策略", exact: true })
      .waitFor();
    await page.reload();
    await page
      .getByRole("heading", { name: "我的周转策略", exact: true })
      .waitFor();
    const saved = (await get("/strategies")).find(
      (strategy) => strategy.name === "我的周转策略",
    );
    assert.equal(saved.stock_days, 0.9);
    await shot("strategies-desktop");
  });
  await check(
    "Experiment runs multiple seeds and reports measured strategy results",
    async () => {
      await page.goto(base + "/experiments");
      await page.getByRole("button", { name: "新建实验", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "新建策略实验" });
      await dialog.getByLabel("实验名称").fill("浏览器策略对照");
      await dialog.getByLabel("每场回合").fill("3");
      await dialog.getByLabel("市场种子").fill("11, 23, 37");
      await dialog.getByRole("button", { name: "创建并运行" }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".experiment-scores .panel-heading>span")
            ?.textContent === "3 场已结算",
        { timeout: 20000 },
      );
      assert.equal(await page.locator(".experiment-matches>a").count(), 3);
      const experiment = (await get("/experiments"))[0];
      assert.equal(experiment.status, "completed");
      assert(experiment.scores.every((score) => score.samples === 3));
      await shot("experiments-desktop");
    },
  );
  await check(
    "Settings persist without disclosing model credentials",
    async () => {
      await page.goto(base + "/settings");
      await page.getByLabel("API 地址").fill("http://127.0.0.1:9998/v1");
      await page
        .getByLabel("模型名称", { exact: true })
        .fill("browser-test-model");
      await page
        .getByLabel("API Key", { exact: false })
        .fill("browser-test-key");
      await page.getByRole("button", { name: "测试连接", exact: true }).click();
      await page.locator(".connection-result.negative").waitFor();
      assert(
        !/请填写模型名称/.test(
          await page.locator(".connection-result").textContent(),
        ),
      );
      await page.getByRole("button", { name: "保存模型" }).click();
      await page.locator(".connection-badge.configured").waitFor();
      await page.reload();
      assert.equal(
        await page.getByLabel("API Key", { exact: false }).inputValue(),
        "",
      );
      assert.equal((await get("/settings")).has_key, true);
      assert(
        !JSON.stringify(await get("/settings")).includes("browser-test-key"),
      );
      await page.getByRole("button", { name: "复制连接" }).click();
      await page
        .getByRole("heading", { name: "默认连接 · 副本", exact: true })
        .waitFor();
      await page.getByLabel("连接名称").fill("DeepSeek Pro");
      await page
        .getByLabel("模型名称", { exact: true })
        .fill("deepseek-v4-pro");
      await page.getByRole("button", { name: "保存模型" }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".model-profile-card.selected strong")
            ?.textContent === "DeepSeek Pro",
      );
      const profiles = await get("/model-profiles");
      assert(
        profiles.some(
          (profile) => profile.model === "deepseek-v4-pro" && profile.has_key,
        ),
      );
      assert(!JSON.stringify(profiles).includes("browser-test-key"));
      await page.getByRole("button", { name: /默认连接/ }).click();
      await page.getByRole("button", { name: "清除已保存密钥" }).click();
      await page.getByRole("button", { name: "保存模型" }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".connection-badge")?.textContent === "未配置",
      );
      await shot("settings-desktop");
    },
  );
  await check("Each store can select a separate model connection", async () => {
    await page.goto(base + "/settings");
    await page.getByRole("button", { name: "添加模型", exact: true }).click();
    await page.getByLabel("连接名称").fill("DeepSeek Flash");
    await page.getByLabel("模型名称", { exact: true }).fill("deepseek-flash");
    await page
      .getByLabel("API Key", { exact: false })
      .fill("flash-browser-secret");
    await page.getByRole("button", { name: "保存模型" }).click();
    await page.waitForFunction(
      () =>
        document.querySelector(".model-profile-card.selected strong")
          ?.textContent === "DeepSeek Flash",
    );
    const profiles = await get("/model-profiles");
    const flash = profiles.find((profile) => profile.name === "DeepSeek Flash");
    const pro = profiles.find((profile) => profile.name === "DeepSeek Pro");
    await page.goto(base);
    await page.getByRole("button", { name: "创建对局", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "创建对局", exact: true });
    await dialog.getByLabel("商店 1 决策引擎").selectOption("llm");
    await dialog
      .getByLabel("商店 1 模型", { exact: true })
      .selectOption(flash.id);
    await dialog.getByLabel("商店 2 决策引擎").selectOption("llm");
    await dialog
      .getByLabel("商店 2 模型", { exact: true })
      .selectOption(pro.id);
    await dialog.getByRole("button", { name: "创建对局", exact: true }).click();
    await page.waitForURL(/\/arenas\/\d+$/);
    await page.locator(".theatre-shop").first().waitFor();
    const created = await get(new URL(page.url()).pathname);
    assert.deepEqual(
      created.snapshot.merchants
        .slice(0, 2)
        .map((store) => store.model_config.model),
      ["deepseek-flash", "deepseek-v4-pro"],
    );
    assert(!JSON.stringify(created).includes("flash-browser-secret"));
  });
  await check(
    "Candidate simulation and independent review are visible in replay",
    async () => {
      await page.goto(base);
      await page.getByRole("button", { name: "创建对局", exact: true }).click();
      const dialog = page.getByRole("dialog", {
        name: "创建对局",
        exact: true,
      });
      await dialog.getByLabel("商店 1 决策流程").selectOption("reviewed");
      await dialog.getByLabel("回合数", { exact: true }).fill("3");
      await dialog
        .getByRole("button", { name: "创建对局", exact: true })
        .click();
      await page.waitForURL(/\/arenas\/\d+$/);
      reviewedArenaId = Number(new URL(page.url()).pathname.split("/").pop());
      await page.getByRole("button", { name: "单步", exact: true }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".round-display>strong")?.textContent === "01",
      );
      await page.getByRole("tab", { name: /决策轨迹/ }).click();
      assert.equal(await page.locator(".projection-card").count(), 2);
      await page
        .getByRole("heading", { name: "独立审核", exact: true })
        .waitFor();
      await shot("reviewed-workflow-desktop");
    },
  );
  await check(
    "Execution jobs show persistent completion and attempt counts",
    async () => {
      await page.goto(base + `/arenas/${arenaId}`);
      await page.getByRole("tab", { name: "执行记录", exact: true }).click();
      await page.locator(".execution-job").first().waitFor();
      assert(
        (await get(`/arenas/${arenaId}/tasks`)).some(
          (job) => job.state === "completed" && job.attempts >= 1,
        ),
      );
      await shot("execution-desktop");
    },
  );
  await check(
    "Workflow ablation compares the same strategy with paired metrics",
    async () => {
      await page.goto(base + "/experiments");
      await page.getByRole("button", { name: "新建实验", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "新建策略实验" });
      await dialog
        .getByRole("button", { name: "模型与流程对照", exact: true })
        .click();
      await dialog.getByLabel("实验名称").fill("流程消融验收");
      await dialog.getByLabel("每场回合").fill("3");
      await dialog.getByLabel("市场种子").fill("101, 203");
      await dialog.getByRole("button", { name: "创建并运行" }).click();
      await page
        .getByRole("heading", { name: "流程消融验收", exact: true })
        .waitFor();
      await page.waitForFunction(
        () =>
          document.querySelector(".experiment-scores .panel-heading>span")
            ?.textContent === "2 场已结算",
      );
      await page
        .getByRole("heading", { name: "相对基线收益", exact: true })
        .waitFor();
      const experiment = (await get("/experiments"))[0];
      assert.equal(experiment.comparisons[0].samples, 2);
      assert(
        experiment.scores.every(
          (score) => score.confidence_interval.length === 2,
        ),
      );
      assert.equal(await page.locator(".experiment-visual-cards article").count(), 2);
      await page.locator(".experiment-visual").getByRole("button", { name: "耗时", exact: true }).click();
      await page.getByRole("img", { name: "平均收益与每轮耗时对比", exact: true }).waitFor();
      await page.locator(".experiment-visual").getByRole("button", { name: "Token", exact: true }).click();
      await shot("ablation-desktop");
    },
  );
  await check(
    "All product views fit desktop, tablet and narrow mobile screens",
    async () => {
      for (const width of [1280, 820, 390, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        for (const route of [
          "/",
          `/arenas/${arenaId}`,
          "/strategies",
          "/experiments",
          "/settings",
        ]) {
          await page.goto(base + route);
          await page.locator("h1").waitFor();
          await page.waitForTimeout(100);
          await noOverflow();
        }
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(base + `/arenas/${reviewedArenaId}`);
      await page.getByRole("tab", { name: /决策轨迹/ }).click();
      await page.locator(".projection-card").first().waitFor();
      await noOverflow();
      await shot("reviewed-workflow-mobile");
      await page.goto(base + `/arenas/${arenaId}`);
      await page.locator(".theatre-shop").first().waitFor();
      await shot("arena-mobile");
      await page.goto(base);
      await page
        .getByRole("heading", { name: "竞技场", exact: true })
        .waitFor();
      await shot("dashboard-mobile");
      await page.getByRole("button", { name: "创建对局", exact: true }).click();
      const create = page.getByRole("dialog", {
        name: "创建对局",
        exact: true,
      });
      await create.getByLabel("商店 1 决策引擎").selectOption("llm");
      assert(
        await create.evaluate(
          (element) => element.scrollWidth <= element.clientWidth + 1,
        ),
      );
      await shot("create-mobile");
      await create.getByRole("button", { name: "取消", exact: true }).click();
      await page.getByRole("button", { name: "打开导航" }).click();
      await page.locator(".mobile-nav").waitFor();
      await page
        .locator(".mobile-nav")
        .getByRole("link", { name: /策略库/ })
        .click();
      await page.waitForURL("**/strategies");
      assert.equal(await page.locator(".mobile-nav").isVisible(), false);
    },
  );
  await check(
    "Live graph, real event replay, reduced motion and supplier contracts",
    async () => {
      await page.setViewportSize({ width: 1440, height: 1100 });
      await page.goto(base + `/arenas/${arenaId}`);
      await page.getByRole("tab", { name: "决策现场", exact: true }).click();
      await page.locator(".event-row").first().waitFor();
      assert.equal(await page.locator(".flow-node").count(), 8);
      await page
        .getByRole("button", { name: "播放事件回放", exact: true })
        .click();
      await page
        .getByRole("button", { name: "暂停事件回放", exact: true })
        .waitFor();
      await page
        .getByRole("button", { name: "暂停事件回放", exact: true })
        .click();
      await page.getByLabel("事件回放速度").selectOption("2");
      await page.getByRole("button", { name: "返回最新", exact: true }).click();
      await page.locator(".contract-list").waitFor();
      await noOverflow();
      await shot("decision-live-desktop");
      const timeline = await get(`/arenas/${arenaId}/timeline?limit=1000`);
      const cursor = timeline[5].id;
      const abort = new AbortController();
      const response = await fetch(base + `/api/arenas/${arenaId}/events`, {
        headers: { "Last-Event-ID": String(cursor) },
        signal: abort.signal,
      });
      const reader = response.body.getReader();
      let chunk = "";
      while (!chunk.includes("event: decision"))
        chunk += new TextDecoder().decode((await reader.read()).value);
      assert(Number(chunk.match(/id: (\d+)/)[1]) > cursor);
      abort.abort();
      const animations = await page
        .locator(".flow-node rect")
        .first()
        .evaluate((el) => getComputedStyle(el).animationName);
      assert.equal(animations, "none");
      await page.emulateMedia({ reducedMotion: "no-preference" });
      await page
        .getByRole("slider", { name: "执行事件位置", exact: true })
        .fill("0");
      await page.locator(".flow-node.active rect").waitFor();
      assert.equal(
        await page
          .locator(".flow-node.active rect")
          .evaluate((el) => getComputedStyle(el).animationName),
        "node-breathe",
      );
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.getByRole("button", { name: "返回最新", exact: true }).click();
      for (const width of [820, 390, 320]) {
        await page.setViewportSize({ width, height: 950 });
        await noOverflow();
        await shot(`decision-live-${width}`);
      }
    },
  );
  await check(
    "Human approval edits, rejection, resume and historical fork",
    async () => {
      const created = await fetch(base + "/api/arenas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "人工审批验收",
          total_rounds: 3,
          approval_policy: "all",
          merchants: [
            {
              name: "审批甲店",
              strategy_id: "balanced",
              mode: "rule",
              color: "violet",
              workflow: "adaptive",
              agent_options: { memory: "episodic", negotiation: true },
            },
            {
              name: "审批乙店",
              strategy_id: "discount",
              mode: "rule",
              color: "orange",
              workflow: "adaptive",
              agent_options: { memory: "episodic", negotiation: true },
            },
          ],
        }),
      }).then((r) => r.json());
      await page.setViewportSize({ width: 1440, height: 1100 });
      await page.goto(base + `/arenas/${created.id}`);
      await page.getByRole("button", { name: "单步", exact: true }).click();
      await page.locator(".approval-card").waitFor();
      await page.getByLabel("审批意见").fill("降低采购规模");
      await page
        .getByRole("button", { name: "退回重新规划", exact: true })
        .click();
      await page.waitForTimeout(800);
      assert.equal((await get(`/arenas/${created.id}`)).current_round, 0);
      await page.locator(".approval-card summary").click();
      await page.getByLabel("coffee审批补货").fill("5");
      await shot("human-approval-desktop");
      await page.setViewportSize({ width: 390, height: 950 });
      await noOverflow();
      await shot("human-approval-mobile");
      await page
        .getByRole("button", { name: "采用修改并继续", exact: true })
        .click();
      await page.waitForTimeout(800);
      await page
        .getByRole("button", { name: "批准并继续", exact: true })
        .click();
      await page.waitForFunction(
        () =>
          document.querySelector(".round-display>strong")?.textContent === "01",
      );
      assert.equal(await page.locator(".approval-card").count(), 0);
      await page.getByRole("tab", { name: "分叉对照", exact: true }).click();
      await page.getByLabel("分叉回合").fill("1");
      await page.getByLabel("后续流程").selectOption("reviewed");
      await noOverflow();
      await page
        .getByRole("button", { name: "创建独立分叉", exact: true })
        .click();
      await page.waitForURL(
        (url) => Number(url.pathname.split("/").pop()) !== created.id,
      );
      const forkId = Number(new URL(page.url()).pathname.split("/").pop());
      assert.equal((await get(`/arenas/${forkId}`)).current_round, 1);
      await page.getByRole("button", { name: "单步", exact: true }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".round-display>strong")?.textContent === "02",
      );
      await page.getByRole("tab", { name: "分叉对照", exact: true }).click();
      await page.locator(".branch-result").waitFor();
      await page.setViewportSize({ width: 1440, height: 1100 });
      await shot("counterfactual-desktop");
      assert.equal((await get(`/arenas/${created.id}`)).current_round, 1);
    },
  );
  await check(
    "Four stores replay one event cursor without leaking future balances",
    async () => {
      const created = await fetch(base + "/api/arenas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "四店全景验收",
          total_rounds: 3,
          seed: 83,
          merchants: [
            { name: "星河咖啡", color: "violet", strategy_id: "balanced" },
            { name: "橙子便利", color: "orange", strategy_id: "discount" },
            { name: "森林补给", color: "teal", strategy_id: "premium" },
            { name: "蓝鲸市集", color: "blue", strategy_id: "adaptive" },
          ].map((store) => ({
            ...store,
            mode: "rule",
            workflow: "adaptive",
            agent_options: {
              memory: "episodic",
              negotiation: true,
              tool_budget: 4,
            },
          })),
        }),
      }).then((response) => response.json());
      panoramaArenaId = created.id;
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(base + `/arenas/${created.id}`);
      await page.locator(".theatre-shop").first().waitFor();
      assert.equal(await page.locator(".theatre-shop").count(), 4);
      await page.getByRole("button", { name: "单步", exact: true }).click();
      await page.waitForFunction(
        () =>
          document.querySelector(".round-display>strong")?.textContent === "01",
      );
      await page.waitForFunction(
        () => document.querySelectorAll(".shop-settled").length === 4,
      );
      const after = await get(`/arenas/${created.id}`);
      const timeline = await get(
        `/arenas/${created.id}/timeline?round=1&limit=1000`,
      );
      const firstSettlement = timeline.findIndex(
        (event) => event.node === "settle",
      );
      const slider = page.getByRole("slider", { name: "全景事件位置" });
      await slider.fill("-1");
      await page.waitForFunction(
        () => document.querySelectorAll(".shop-settled").length === 0,
      );
      const cash = (value) =>
        `¥${(value / 100).toLocaleString("zh-CN", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
      assert.deepEqual(
        await page.locator(".shop-wallet strong").allTextContents(),
        created.snapshot.merchants.map((store) => cash(store.cash)),
      );
      await slider.fill(String(firstSettlement - 1));
      assert.equal(await page.locator(".shop-settled").count(), 0);
      assert.equal(await page.locator(".product-delivery").count(), 0);
      assert.equal(await page.locator(".planned-action").count(), 12);
      assert((await page.locator(".planned-action").allTextContents()).every((text) => /^计划进货 \d+ 件$/.test(text)));
      assert((await page.locator(".product-caption b").allTextContents()).every((text) => text.startsWith("拟售价 ¥")));
      assert((await page.locator(".stock-caption strong").allTextContents()).every((text) => text.startsWith("库存 ")));
      for (const width of [390, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        await noOverflow();
      }
      await shot("panorama-planned-mobile");
      await page.setViewportSize({ width: 1440, height: 1000 });
      assert.deepEqual(
        await page.locator(".shop-wallet strong").allTextContents(),
        created.snapshot.merchants.map((store) => cash(store.cash)),
      );
      await slider.fill(String(firstSettlement));
      await page.waitForFunction(
        () => document.querySelectorAll(".shop-settled").length === 1,
      );
      await page.getByRole("button", { name: "跟随最新", exact: true }).click();
      await page.waitForFunction(
        () => document.querySelectorAll(".shop-settled").length === 4,
      );
      const expectedCash = after.snapshot.merchants.map((store) =>
        cash(store.cash),
      );
      await page.waitForFunction(
        (expected) =>
          JSON.stringify(
            [...document.querySelectorAll(".shop-wallet strong")].map(
              (el) => el.textContent,
            ),
          ) === JSON.stringify(expected),
        expectedCash,
      );
      assert.deepEqual(
        await page.locator(".shop-wallet strong").allTextContents(),
        expectedCash,
      );
      assert.equal(await page.locator(".product-shelf").count(), 12);
      assert.equal(await page.locator(".product-delivery").count(), 12);
      assert.equal(await page.locator(".shop-profit-breakdown").count(), 4);
      assert.equal(await page.locator(".quote-visual").count(), 0);
      for (const [index, store] of after.snapshot.merchants.entries()) {
        const rows = await page.locator(".theatre-shop").nth(index).locator(".product-delivery").allTextContents();
        for (const [productIndex, delivery] of store.procurement.entries()) {
          if (delivery.quantity) {
            assert(rows[productIndex].includes(`到货 ${delivery.quantity}/${delivery.requested_quantity} 件`));
            assert(rows[productIndex].includes(`进价 ${cash(delivery.unit_price)}`));
          } else {
            assert(!rows[productIndex].includes("进价"));
          }
        }
      }
      assert.equal(await page.locator(".planned-action").count(), 0);
      assert((await page.locator(".product-caption b").allTextContents()).every((text) => text.startsWith("售价 ¥")));
      await shot("panorama-four-stores");
      for (const width of [1280, 820, 390, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        await noOverflow();
        assert.equal(await page.locator(".theatre-shop").count(), 4);
      }
      await shot("panorama-four-mobile");
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.getByRole("button", { name: "查看星河咖啡决策详情" }).click();
      await page.getByRole("dialog", { name: "星河咖啡 · 决策详情" }).waitFor();
      await page.keyboard.press("Escape");
      assert.equal(await page.locator(".theatre-shop").count(), 4);
      await page.emulateMedia({ reducedMotion: "no-preference" });
      await slider.fill(String(firstSettlement - 1));
      await page.getByRole("button", { name: "跟随最新", exact: true }).click();
      assert.equal(
        await page
          .locator(".arriving-truck")
          .first()
          .evaluate((element) => getComputedStyle(element).animationName),
        "shop-delivery",
      );
      await page.emulateMedia({ reducedMotion: "reduce" });
      assert.equal(
        await page.locator(".shop-trade-motion").first().isVisible(),
        false,
      );
    },
  );
  await check("Zero-price rejection is shown without a free price or a price-axis point", async () => {
    const fullTimeline = await get(`/arenas/${panoramaArenaId}/timeline?round=1&limit=1000`);
    const timeline = fullTimeline.filter((event) => event.node !== "settle");
    const quoted = timeline.find((event) => event.payload.message?.action === "offer");
    const rejected = {
      ...quoted,
      id: fullTimeline.at(-1).id + 1,
      payload: {
        ...quoted.payload,
        message: { sender: "buyer", action: "reject", unit_price: 0, quantity: 0, reason: "本轮退出交易" },
      },
    };
    const endpoint = `**/api/arenas/${panoramaArenaId}/timeline?*`;
    await page.route(endpoint, (route) => route.fulfill({ json: [...timeline, rejected] }));
    await page.goto(base + `/arenas/${panoramaArenaId}`);
    const quote = page.locator(".quote-strip").filter({ hasText: "拒绝交易" });
    await quote.waitFor();
    assert.equal(await quote.locator("strong").count(), 0);
    const points = timeline.filter((event) =>
      event.merchant_id === quoted.merchant_id &&
      event.payload.product_id === quoted.payload.product_id &&
      ["offer", "accept"].includes(event.payload.message?.action) &&
      event.payload.message.unit_price > 0,
    );
    assert.equal(await quote.locator("..").locator(".quote-axis i").count(), points.length);
    await shot("panorama-rejected-trade");
    await page.unroute(endpoint);
  });
  await check(
    "Agent capability ablation and budgeted independent validation",
    async () => {
      const experiment = await fetch(base + "/api/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: "能力开发集验收",
          scenario: "festival",
          rounds: 3,
          seeds: [1711],
          split: "development",
          variants: [
            {
              name: "关闭记忆",
              strategy_id: "balanced",
              workflow: "adaptive",
              agent_options: {
                memory: "none",
                negotiation: false,
                tool_budget: 2,
              },
            },
            {
              name: "经验与谈判",
              strategy_id: "balanced",
              workflow: "adaptive",
              agent_options: {
                memory: "episodic",
                negotiation: true,
                tool_budget: 4,
              },
            },
          ],
        }),
      }).then((r) => r.json());
      await fetch(base + `/api/experiments/${experiment.id}/run`, {
        method: "POST",
      });
      await page.goto(base + "/experiments");
      await page
        .getByRole("button", { name: "筛选并运行独立验证", exact: true })
        .waitFor();
      await page.getByText("完整指标与统计明细", { exact: true }).click();
      assert(
        await page
          .getByRole("columnheader", { name: "提供经验", exact: true })
          .count(),
      );
      await page.getByLabel("独立验证种子").fill("1811");
      await page.getByLabel("验证预算", { exact: true }).fill("6");
      await page
        .getByRole("button", { name: "筛选并运行独立验证", exact: true })
        .click();
      await page
        .getByRole("heading", {
          name: "能力开发集验收 · 独立验证",
          exact: true,
        })
        .waitFor();
      await noOverflow();
      await shot("capability-validation-desktop");
      const experiments = await get("/experiments");
      assert.equal(
        experiments[0].config.selection.development_id,
        experiment.id,
      );
      assert.equal(experiments[0].config.seeds[0], 1811);
    },
  );
  await check("No unhandled browser or server errors", async () =>
    assert.deepEqual(errors, []),
  );
} finally {
  await fs.writeFile(
    path.join(output, "browser-report.json"),
    JSON.stringify({ results, errors, serverLog }, null, 2),
  );
  await browser.close();
  server.kill();
  await new Promise((resolve) => server.once("exit", resolve));
}
console.log(
  `BROWSER ${results.filter((item) => item.passed).length}/${results.length}`,
);
