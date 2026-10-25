// Compare the app against original bundled screens in a separate headless Chrome.
// Requires Chrome started with --remote-debugging-port=9223 and a separate profile.
// Usage: node scripts/check-scenario.mjs 1
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const scenario = Number(process.argv[2] ?? 1);
const origin = process.env.PREVIEW_URL ?? "http://localhost:3000";
const directory = resolve(root, `.qa/scenario${scenario}-reference`);
const output = resolve(root, `.qa/scenario${scenario}-qa`);
await mkdir(output, { recursive: true });
const screens = JSON.parse(await readFile(resolve(root, "src/prototype/screens.json"), "utf8"));
const prefix = scenario === 5 ? "A_" : scenario === 6 ? "U_" : scenario === 7 ? "AD_" : `S${scenario}_`;
const entries = Object.entries(screens).filter(([name]) => name.startsWith(prefix));
const screenName = step => step === "Main" ? (scenario === 6 ? "U_Login.dc.html" : scenario === 7 ? "AD_Login.dc.html" : "Main.dc.html") : `${prefix}${step}.dc.html`;
const target = await (await fetch("http://127.0.0.1:9223/json/new?about:blank", { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
const pending = new Map();
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data);
  const request = pending.get(message.id);
  if (!request) return;
  clearTimeout(request.timer);
  pending.delete(message.id);
  if (message.error) request.reject(new Error(JSON.stringify(message.error)));
  else request.resolve(message.result);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 20_000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function waitFor(expression) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Condition not met: ${expression}`);
}
async function navigate(url) {
  const result = await command("Page.navigate", { url });
  if (result.errorText) throw new Error(`${url}: ${result.errorText}`);
  const expected = new URL(url).origin === origin ? decodeURIComponent(new URL(url).pathname.slice(1)) : null;
  const condition = expected && screens[expected]
    ? `document.querySelector('[data-screen-name]')?.dataset.screenName === ${JSON.stringify(expected)} && !location.pathname.endsWith('.dc.html')`
    : `location.href === ${JSON.stringify(url)} && !!document.querySelector('x-dc')`;
  await waitFor(condition);
  await waitFor(`!document.querySelector('sc-raw-table') || getComputedStyle(document.querySelector('sc-raw-table')).display === 'table'`);
  await evaluate("document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))");
}
await command("Page.enable");
await command("Runtime.enable");
const report = [];
try {
  for (const [name, screen] of entries) {
    await command("Emulation.setDeviceMetricsOverride", { width: screen.width, height: screen.height, deviceScaleFactor: 1, mobile: false });
    const appUrl = `${origin}/${name}`;
    for (const kind of ["reference", "app"]) {
      const url = kind === "reference" ? pathToFileURL(resolve(directory, name)).href : appUrl;
      await navigate(url);
      if (kind === "reference") {
        await evaluate("Array.from(document.querySelectorAll('a')).filter(a => a.textContent.trim() === 'Обновить статус').forEach(a => a.remove())");
      }
      const { data } = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      await writeFile(resolve(output, `${name}.${kind}.png`), Buffer.from(data, "base64"));
    }
    const links = await evaluate("Array.from(document.querySelectorAll('a[href]')).map(a => ({text: a.textContent.trim(), href: a.getAttribute('href')}))");
    const customTables = await evaluate("document.querySelectorAll('sc-raw-table').length");
    const legacyLinks = await evaluate("Array.from(document.querySelectorAll('a[href]')).some(a => a.getAttribute('href').includes('.dc.html'))");
    if (legacyLinks) throw new Error(`Legacy HTML links are visible in ${name}`);
    const tableRows = await evaluate("document.querySelectorAll('table tbody tr').length");
    if (customTables) throw new Error(`Unrestored export tables in ${name}`);
    report.push({ name, width: screen.width, height: screen.height, links, tableRows });
    console.log(`Captured ${name}`);
  }

  // Follow the actual scenario links, including edit/cancel, refusal and reapply.
  const paths = {
    1: ["Login", "HomeEmpty", "Chat", "ChatEdit", "Chat", "ChatSubmitted", "HomeSubmitted", "HomeAutoDecline", "ChatAutoDecline", "Chat", "HomeEmpty"],
    2: ["Login", "HomeEmpty", "Chat", "ChatEdit", "Chat", "ChatSubmitted", "HomeSubmitted", "HomeMissingDocs", "ChatMissingDocs", "HomeReview", "HomeDeclined", "Docs", "Credits", "Profile", "HomeDeclined", "Chat", "HomeEmpty"],
    3: ["Login", "HomeEmpty", "Chat", "ChatEdit", "Chat", "ChatSubmitted", "HomeSubmitted", "HomeReview", "ChatReview", "HomeReview", "HomeOffer", "HomeOfferRejected", "Docs", "Credits", "Profile", "HomeOfferRejected", "Chat", "HomeEmpty"],
    4: ["Login", "HomeEmpty", "Chat", "ChatEdit", "Chat", "ChatSubmitted", "HomeSubmitted", "HomeReview", "ChatReview", "HomeReview", "HomeCounter", "Home", "HomeSchedule", "Home", "HomeModal", "Home", "DocsPre", "CreditsEmpty", "ProfilePre", "Home", "HomeIssued", "Credits", "CreditsSchedule", "Credits", "Docs", "Profile", "HomeIssued"],
    5: ["Login", "Analyst", "AnalystNew", "RequestDocs", "Analyst", "Conclusion", "Analyst", "AnalystFromUw", "Accept", "Conclusion", "Analyst", "AnalystInWork", "Analyst", "Main"],
    7: ["Login", "All", "InWork", "Closed", "DetailDeclined", "All", "Done", "DetailDone", "All", "DetailDone", "All", "DetailDeclined", "All", "Main", "All"],
    6: ["Login", "Workspace", "Mine", "Pending", "Requests", "Workspace",
      "RequestDocs", { screen: "Workspace", text: "Отправить запрос" },
      "RequestDocs", { screen: "Workspace", text: "Отмена" },
      "Expertise", { screen: "Workspace", text: "Отправить аналитику" },
      "Approve", { screen: "Workspace", text: "Подтвердить одобрение" },
      "Counter", { screen: "Workspace", text: "Отправить контр-предложение" },
      "Refuse", { screen: "Workspace", text: "Подтвердить отказ" },
      "Refuse", { screen: "Workspace", text: "Закрыть" }, "Main", "Workspace"],
  };
  const path = paths[scenario];
  if (!path) throw new Error(`No verified click path configured for scenario ${scenario}`);
  await navigate(`${origin}/${screenName(path[0])}`);
  for (const step of path.slice(1)) {
    const name = screenName(typeof step === "string" ? step : step.screen);
    const text = typeof step === "string" ? null : step.text;
    const from = await evaluate("document.querySelector('[data-screen-name]')?.dataset.screenName");
    const target = name === "Main.dc.html" ? "A_Login.dc.html" : name;
    const point = await evaluate(`(() => {
      const links = Array.from(document.querySelectorAll('a[href]')).filter(a => a.dataset.screen === ${JSON.stringify(target)} && (${JSON.stringify(text)} === null || a.textContent.trim() === ${JSON.stringify(text)}));
      for (const a of links) {
        a.scrollIntoView({block: 'center'});
        const r = a.getBoundingClientRect(); const x = r.left + r.width / 2; const y = r.top + r.height / 2;
        if (r.width && r.height && a.contains(document.elementFromPoint(x, y))) return {x, y};
      }
      return null;
    })()`);
    if (point) {
      await command("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
      await command("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
    } else {
      if (screens[from]?.auto_next !== name) throw new Error(`No link or automatic transition to ${name} from ${from}`);
    }
    await waitFor(`document.querySelector('[data-screen-name]')?.dataset.screenName === ${JSON.stringify(target)} && !location.pathname.endsWith('.dc.html')`);
  }
  const automatic = [];
  for (const [name, screen] of entries.filter(([, screen]) => screen.auto_next)) {
    await navigate(`${origin}/${name}`);
    const hasRefresh = await evaluate("Array.from(document.querySelectorAll('a, button')).some(a => a.textContent.trim() === 'Обновить статус')");
    if (hasRefresh) throw new Error(`Prototype linking control is visible in ${name}`);
    await waitFor(`document.querySelector('[data-screen-name]')?.dataset.screenName === ${JSON.stringify(screen.auto_next)} && !location.pathname.endsWith('.dc.html')`);
    automatic.push({ from: name, to: screen.auto_next });
    console.log(`Automatic: ${name} -> ${screen.auto_next}`);
  }
  await writeFile(resolve(output, "report.json"), JSON.stringify({ screens: report, clickPath: path, automatic }, null, 2));
  console.log(`Verified ${entries.length} screens, ${path.length - 1} path transitions and ${automatic.length} automatic transitions.`);
} finally {
  await command("Page.close").catch(() => {});
  socket.close();
}
