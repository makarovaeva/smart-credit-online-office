// Read-only navigation check; requires local frontend/backend and Chrome CDP on 9223.
import assert from "node:assert/strict";
const target = await (await fetch("http://127.0.0.1:9223/json/new?about:blank", { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
let id = 0;
const pending = new Map();
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data);
  const task = pending.get(message.id);
  if (!task) return;
  pending.delete(message.id); clearTimeout(task.timer);
  if (message.error) task.reject(new Error(JSON.stringify(message.error))); else task.resolve(message.result);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const key = ++id;
    const timer = setTimeout(() => reject(new Error(`Timeout: ${method}`)), 30000);
    pending.set(key, { resolve, reject, timer });
    socket.send(JSON.stringify({ id: key, method, params }));
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
const cases = [
  { role: "client", body: { kind: "client", phone: "+79990000001" }, path: "/applications", scenes: ["S1_Chat.dc.html", "S1_Docs.dc.html", "S4_Credits.dc.html", "S1_Profile.dc.html"] },
  { role: "credit_analyst", body: { email: "analyst1@alfa-demo.ru", password: "demo-password" }, path: "/staff/analyst", scenes: ["A_AnalystNew.dc.html", "A_AnalystFromUw.dc.html", "A_AnalystInWork.dc.html", "A_Analyst.dc.html"] },
  { role: "underwriter", body: { email: "underwriter1@alfa-demo.ru", password: "demo-password" }, path: "/staff/underwriter", scenes: ["U_Mine.dc.html", "U_Pending.dc.html", "U_Requests.dc.html", "U_Workspace.dc.html"] },
  { role: "admin", body: { email: "admin@alfa-demo.ru", password: "demo-password" }, path: "/staff/admin", scenes: ["AD_InWork.dc.html", "AD_Closed.dc.html", "AD_Done.dc.html", "AD_All.dc.html"] },
];
try {
  await command("Runtime.enable");
  await command("Page.navigate", { url: "http://localhost:3000/login" });
  await wait("!!document.querySelector('[data-api-ready=true]')");
  for (const test of cases) {
    const status = await evaluate(`fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:${JSON.stringify(JSON.stringify(test.body))}}).then(r=>r.status)`);
    assert.equal(status, 200, `${test.role}: login`);
    await command("Page.navigate", { url: `http://localhost:3000${test.path}` });
    await wait(`!!document.querySelector('[data-api-ready=true]') && !document.querySelector('[aria-label="Загрузка кабинета"]')`);
    await evaluate(`window.navigationMarker = 'same-document'; window.spinnerCount = 0;
      new MutationObserver(records => { for(const record of records)for(const n of record.addedNodes)if(n.nodeType===1 && (n.matches('[aria-label="Загрузка кабинета"]')||n.querySelector('[aria-label="Загрузка кабинета"]')))window.spinnerCount++; }).observe(document.body,{childList:true,subtree:true});
      window.originalFetch = window.fetch; window.fetch = async (...args) => {if(String(args[0]).includes('/api/'))await new Promise(r=>setTimeout(r,1200));return window.originalFetch(...args);};`);
    // Client templates change scenario prefixes; their public URLs stay the same.
    const links = test.role === "client"
      ? ["/chat", "/documents", "/credits", "/profile", "/applications"].map(path => ({ selector: `aside a[href="${path}"]`, path }))
      : test.scenes.map(scene => ({ selector: `a[data-screen="${scene}"]`, scene }));
    for (const link of links) {
      const result = await evaluate(`(async () => {const a=document.querySelector(${JSON.stringify(link.selector)});if(!a)return null;a.click();await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));return {name:document.querySelector('[data-screen-name]')?.dataset.screenName,spinner:!!document.querySelector('[aria-label="Загрузка кабинета"]')};})()`);
      assert.ok(result, `${test.role}: link ${link.selector}`);
      assert.equal(result.spinner, false, `${test.role}: no spinner while API is delayed`);
      if (link.scene) assert.equal(result.name, link.scene, "staff tab changes before API response");
      else {
        const category = { "/chat": "Chat", "/documents": "Docs", "/credits": "Credits", "/profile": "Profile", "/applications": "Home" }[link.path];
        assert.ok(result.name.includes(category), `${link.path}: content changes before API response`);
        await wait(`location.pathname === ${JSON.stringify(link.path)}`);
      }
      await new Promise(resolve => setTimeout(resolve, 1700));
      assert.equal(await evaluate("window.navigationMarker"), "same-document", `${test.role}: no page reload`);
      assert.equal(await evaluate("window.spinnerCount"), 0, `${test.role}: no loading overlay`);
      assert.equal(await evaluate("!!document.querySelector('[data-api-ready=true]')"), true);
    }
    if (test.role === "client") {
      const path = await evaluate("location.pathname");
      await evaluate("history.back()"); await wait(`location.pathname !== ${JSON.stringify(path)}`);
      await wait("document.querySelector('[data-screen-name]')?.dataset.screenName.includes('Profile')");
      await evaluate("history.forward()"); await wait(`location.pathname === ${JSON.stringify(path)}`);
      await wait("document.querySelector('[data-screen-name]')?.dataset.screenName.includes('Home')");
      assert.equal(await evaluate("window.spinnerCount"), 0, "back/forward: no loading overlay");
      const length = await evaluate("history.length");
      await evaluate("document.querySelector('aside a[href=\"/applications\"]').click()");
      assert.equal(await evaluate("history.length"), length, "active sidebar link does not duplicate history");
    }
    console.log(`${test.role}: ${links.length} transitions with delayed API, no loading overlay`);
    await evaluate("window.fetch = window.originalFetch");
  }
} finally {
  await command("Page.close").catch(() => {});
  socket.close();
}
