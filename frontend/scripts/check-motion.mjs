// Capture geometry and visual stability with real read-only demo API requests.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
const out = new URL("../.qa/motion/", import.meta.url);
await mkdir(out, { recursive: true });
const target = await (await fetch("http://127.0.0.1:9223/json/new?about:blank", { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
let id = 0;
const pending = new Map();
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data); const task = pending.get(message.id);
  if (!task) return;
  pending.delete(message.id); clearTimeout(task.timer);
  if (message.error) task.reject(new Error(JSON.stringify(message.error))); else task.resolve(message.result);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const key = ++id; const timer = setTimeout(() => reject(new Error(`Timeout: ${method}`)), 30000);
    pending.set(key, { resolve, reject, timer }); socket.send(JSON.stringify({ id: key, method, params }));
  });
}
async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function wait(expression) {
  for (let i = 0; i < 200; i++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Condition failed: ${expression}`);
}
async function screenshot(name) {
  const { data } = await command("Page.captureScreenshot", { format: "png" });
  await writeFile(new URL(name, out), Buffer.from(data, "base64"));
}
const baseline = process.argv.includes("--baseline");
const report = [];
try {
  await command("Runtime.enable");
  await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: "http://localhost:3000/login" });
  await wait("!!document.querySelector('[data-api-ready=true]')");
  assert.equal(await evaluate(`fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'client',phone:'+79990000001'})}).then(r=>r.status)`), 200);
  await command("Page.navigate", { url: "http://localhost:3000/applications" });
  await wait("!!document.querySelector('main')");
  await new Promise(resolve => setTimeout(resolve, 1800));
  await screenshot(`${baseline ? "before" : "after"}-01-home.png`);
  // Record every animation frame, not only the final stable position.
  await evaluate(`window.motionFrames=[]; window.motionObserver=new MutationObserver(()=>{window.motionReplacements++});window.motionReplacements=0;window.motionObserver.observe(document.querySelector('[data-screen-name]'),{childList:true});
    window.motionStart=performance.now();window.motionRunning=true;window.mainMounts=0;window.lastMain=null;
    function sample(){const main=document.querySelector('main'),side=document.querySelector('aside.nav');if(main&&side){if(main!==window.lastMain){window.mainMounts++;window.lastMain=main}const r=main.getBoundingClientRect(),s=side.getBoundingClientRect();window.motionFrames.push({t:performance.now()-window.motionStart,name:document.querySelector('[data-screen-name]')?.dataset.screenName,x:r.x,y:r.y,width:r.width,sideWidth:s.width,sideY:s.y,opacity:getComputedStyle(main).opacity,scrollY:scrollY});}if(window.motionRunning)requestAnimationFrame(sample)}requestAnimationFrame(sample);`);
  const paths = ["/documents", "/credits", "/profile", "/chat", "/applications"];
  for (const [index, path] of paths.entries()) {
    await evaluate(`window.motionFrames=[];window.mainMounts=0;window.motionReplacements=0;document.querySelector('aside a[href="${path}"]').click()`);
    await wait(`location.pathname === ${JSON.stringify(path)}`);
    await new Promise(resolve => setTimeout(resolve, 2200));
    const frames = await evaluate("window.motionFrames");
    const summary = await evaluate("({mounts:window.mainMounts,replacements:window.motionReplacements,scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth})");
    report.push({ path, ...summary, geometry: [...new Set(frames.map(f => JSON.stringify([Math.round(f.x), Math.round(f.y), Math.round(f.width), Math.round(f.sideWidth), Math.round(f.sideY)])))], frames });
    await screenshot(`${baseline ? "before" : "after"}-${index + 2}-${path.slice(1)}.png`);
    console.log(path, JSON.stringify({ ...summary, geometry: report.at(-1).geometry }));
  }
  await evaluate("window.motionRunning=false;window.motionObserver.disconnect()");
  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await new Promise(resolve => setTimeout(resolve, 200));
  await screenshot(`${baseline ? "before" : "after"}-07-mobile.png`);
  const mobile = await evaluate("({viewport:innerWidth,width:document.documentElement.scrollWidth,sidebar:document.querySelector('aside.nav')?.getBoundingClientRect().width})");
  console.log("mobile", JSON.stringify(mobile));
  await writeFile(new URL(`${baseline ? "before" : "after"}.json`, out), JSON.stringify({ report, mobile }, null, 2));
  if (!baseline) for (const step of report) {
    assert.equal(step.geometry.length, 1, `${step.path}: page geometry must stay stable through navigation and API updates`);
    assert.ok(step.replacements <= 1, `${step.path}: background API must not replace the entire screen`);
  }
} finally {
  await command("Page.close").catch(() => {}); socket.close();
}
