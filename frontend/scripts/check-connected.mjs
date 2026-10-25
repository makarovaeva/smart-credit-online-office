// Real API/UI integration check against local synthetic demo data.
// Creates synthetic applications; never use against production.
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const out = fileURLToPath(new URL("../.qa/connected/", import.meta.url));
await mkdir(out, { recursive: true });
const target = await (await fetch("http://127.0.0.1:9223/json/new?about:blank", { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener("open", resolve, { once: true }));
let id = 0; const pending = new Map(); const requests = [];
socket.addEventListener("message", ({ data }) => {
  const message = JSON.parse(data);
  if (message.method === "Page.javascriptDialogOpening") void command("Page.handleJavaScriptDialog", { accept: true });
  if (message.method === "Network.responseReceived" && message.params.response.url.includes("/api/")) requests.push({ url: message.params.response.url, status: message.params.response.status });
  const task = pending.get(message.id); if (!task) return;
  clearTimeout(task.timer); pending.delete(message.id);
  if (message.error) task.reject(new Error(JSON.stringify(message.error))); else task.resolve(message.result);
});
function command(method, params = {}) {
  return new Promise((resolve, reject) => { const key = ++id; const timer = setTimeout(() => reject(new Error(`Timeout ${method}`)), 30000); pending.set(key, { resolve, reject, timer }); socket.send(JSON.stringify({ id: key, method, params })); });
}
async function evaluate(expression) { const data = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }); if (data.exceptionDetails) throw new Error(JSON.stringify(data.exceptionDetails)); return data.result.value; }
async function wait(expression) { for (let i = 0; i < 160; i++) { if (await evaluate(expression)) return; await new Promise(r => setTimeout(r, 100)); } throw new Error(`Condition failed: ${expression}\n${await evaluate("document.body.innerText.slice(0,1500)")}`); }
async function navigate(path) { await command("Page.navigate", { url: `http://localhost:3000${path}` }); await wait("!!document.querySelector('[data-api-ready=true]')"); }
async function click(text) {
  const point = await evaluate(`(() => { for(const a of document.querySelectorAll('a,button')) { if(a.textContent.trim()!==${JSON.stringify(text)})continue; a.scrollIntoView({block:'center'}); const r=a.getBoundingClientRect(); const x=r.left+r.width/2,y=r.top+r.height/2;if(a.contains(document.elementFromPoint(x,y)))return{x,y}; }return null;})()`);
  if (!point) throw new Error(`Missing button ${text}`);
  await command("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
  await command("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
}
async function fill(values) { await evaluate(`Array.from(document.querySelectorAll('input:not([type=radio]):not([type=checkbox])')).forEach((e,i)=>{if(${JSON.stringify(values)}[i]!==undefined){e.focus();e.value=${JSON.stringify(values)}[i];e.dispatchEvent(new Event('input',{bubbles:true}));}})`); }
async function api(path, body) { return evaluate(`fetch(${JSON.stringify(path)},${JSON.stringify(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })}).then(async r=>({status:r.status,data:await r.json()}))`); }
async function login(path, values, role) {
  await navigate(path); await fill(values); await click("Войти");
  await wait(`!location.pathname.includes('login') && !!document.querySelector('[data-screen-name]') && !document.querySelector('[aria-busy=true]')`);
  const user = await api("/api/session"); if (user.data.role !== role) throw new Error(`Wrong role ${JSON.stringify(user)}`);
  await wait("document.querySelectorAll('table tbody tr').length > 0 || location.pathname === '/applications'");
  console.log(`UI login: ${role}`);
}
// У компании одна заявка в работе: закрываем незавершённые заявки прошлых прогонов
async function closeActive() {
  const rows = (await api("/api/backend/applications?limit=100")).data.items;
  for (const app of rows.filter(a => !["completed", "closed"].includes(a.status))) {
    await api(`/api/backend/applications/${app.id}/${app.status === "offer_generated" ? "offer/reject" : "cancel"}`, {});
  }
}
async function fixture() {
  await closeActive();
  const user = (await api("/api/session")).data;
  const products = (await api("/api/backend/products")).data;
  const product = products.find(p => !p.requires_collateral && p.purposes.includes("working_capital") && Number(p.max_amount) >= 3000000 && Number(p.min_term_months) <= 24 && Number(p.max_term_months) >= 24);
  const created = await api("/api/backend/applications", { company_id: user.companies[0].company_id, product_id: product.id, requested_amount: "3000000", requested_term_months: 24, purpose: "working_capital" });
  if (created.status !== 201) throw new Error(`Fixture creation failed: ${JSON.stringify(created)}`);
  await api(`/api/backend/applications/${created.data.id}/consents`, { types: ["bki", "fns", "digital_profile"] });
  const submitted = await api(`/api/backend/applications/${created.data.id}/submit`, {});
  if (submitted.status !== 200) throw new Error(`Fixture submission failed: ${JSON.stringify(submitted)}`);
  await evaluate(`sessionStorage.setItem('credit-selected-application',${JSON.stringify(created.data.id)})`);
  return submitted.data;
}
await command("Page.enable"); await command("Runtime.enable"); await command("Network.enable");
await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
try {
  let application; let contract;
  if (process.argv.includes("--branches")) {
    const previous = JSON.parse(await readFile(`${out}/report.json`, "utf8"));
    application = { id: previous.applicationId }; contract = { data: { id: previous.contractId } };
  } else {
  await login("/login", ["+7 999 000-00-01"], "client");
  await closeActive();
  await navigate("/chat");
  await wait("document.body.innerText.includes('Подтвердить и отправить заявку')");
  await evaluate("(() => { const input = document.querySelector('input[aria-label=\"Сообщение\"]'); input.focus(); input.value = '3 млн на 2 года на пополнение оборотных средств'; input.dispatchEvent(new Event('input', { bubbles: true })); })()");
  await click("Отправить");
  await wait("!!document.querySelector('[data-chat-message=confirmation_card]') && document.querySelector('[data-chat-message=confirmation_card]').innerText.includes('Оборотный кредит') && !document.querySelector('[aria-busy=true]')");
  console.log("AI agent parsed loan parameters in chat and suggested a product");
  await click("Подтвердить и отправить заявку");
  await wait("location.pathname === '/applications' && !document.querySelector('[aria-busy=true]')");
  const applications = await api("/api/backend/applications?limit=1"); application = applications.data.items[0];
  if (!application?.id) throw new Error("No real application created");
  const created = await api(`/api/backend/applications/${application.id}`);
  if (created.data.status !== "underwriter_review") throw new Error(`Unexpected actual status: ${JSON.stringify(created.data)}`);
  console.log(`Created and submitted real application ${application.id}`);
  const dialog = await api(`/api/backend/chat/messages?company_id=${created.data.company_id}`);
  if (!dialog.data.some(m => m.message_type === "confirmation_card" && m.reply_to_id)) throw new Error("Chat exchange was not saved");

  let found = false;
  for (const number of [1, 2]) {
    await login("/staff/login?role=underwriter", [`underwriter${number}@alfa-demo.ru`, "demo-password"], "underwriter");
    const queue = await api("/api/backend/backoffice/applications?limit=100");
    if (queue.data.items.some(a => a.id === application.id)) { found = true; break; }
  }
  if (!found) throw new Error("Created application absent from underwriter queues");
  await wait(`!!document.querySelector('[data-application-id="${application.id}"]')`);
  await evaluate(`document.querySelector('[data-application-id="${application.id}"]').click()`);
  await new Promise(r => setTimeout(r, 800));
  await click("Одобрить"); await wait("document.body.innerText.includes('Подтвердить одобрение')");
  await fill(["3000000", "24", "18"]); await click("Подтвердить одобрение");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'U_Workspace.dc.html' && !document.querySelector('[aria-busy=true]')");
  const decision = await api(`/api/backend/backoffice/applications/${application.id}`);
  if (decision.data.application.status !== "offer_generated") throw new Error(`Decision not persisted: ${JSON.stringify(decision)}`);
  console.log("Underwriter decision persisted through UI");

  await login("/login", ["+7 999 000-00-01"], "client");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'S3_HomeOffer.dc.html'");
  await click("Принять оффер"); await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'S4_Home.dc.html'");
  await click("Подписать"); await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'S4_HomeIssued.dc.html'");
  const issued = await api(`/api/backend/applications/${application.id}`);
  if (issued.data.status !== "completed") throw new Error("Signing did not complete application");
  contract = await api(`/api/backend/applications/${application.id}/contract`);
  if (contract.data.schedule?.length !== 24) throw new Error("No actual 24-payment schedule");
  await click("Посмотреть кредит"); await click("График платежей");
  await wait("document.querySelectorAll('table tbody tr').length === 24");
  console.log("Offer acceptance, signing, disbursement and actual payment schedule verified");
  await navigate("/documents");
  await wait("document.body.innerText.includes('Кредитный договор №')");
  const exports = await evaluate(`Promise.all(Array.from(document.querySelectorAll('a[href*="/contract/"]')).map(a => fetch(a.href).then(async r => [r.status, r.headers.get('content-type'), (await r.arrayBuffer()).byteLength])))`);
  if (exports.length !== 2 || exports.some(([status, type, size]) => status !== 200 || size < 1000 || !/pdf|spreadsheet/.test(type))) throw new Error(`Contract exports failed: ${JSON.stringify(exports)}`);
  console.log("Documents show contract PDF and schedule XLSX downloads from API");
  await navigate("/profile");
  await wait("['7701000001', 'Генеральный директор', 'АО «Альфа-Банк»', 'finance@7701000001.example'].every(t => document.body.innerText.includes(t)) && !document.body.innerText.includes('[ФИО]')");
  console.log("Company profile shows registry, head, contacts and settlement account from API");
  }

  await login("/login", ["+7 999 000-00-03"], "client");
  const declined = await fixture();
  if (declined.close_reason !== "auto_declined") throw new Error("Automatic decline fixture did not decline");
  await navigate("/applications");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'S1_HomeAutoDecline.dc.html'");
  console.log("Actual automatic decline displayed from API");

  await login("/login", ["+7 999 000-00-04"], "client");
  const escalation = await fixture();
  if (escalation.status !== "analyst_escalation") throw new Error(`Expected analyst escalation: ${escalation.status}`);
  let analystFound = false;
  for (const number of [1, 2]) {
    await login("/staff/login?role=analyst", [`analyst${number}@alfa-demo.ru`, "demo-password"], "credit_analyst");
    const queue = await api("/api/backend/backoffice/applications?limit=100");
    if (queue.data.items.some(a => a.id === escalation.id)) { analystFound = true; break; }
  }
  if (!analystFound) throw new Error("Escalation absent from analyst queues");
  const analystLogin = (await api("/api/session")).data.email;
  const openEscalation = async () => {
    await wait(`!!document.querySelector('[data-application-id="${escalation.id}"]')`);
    await evaluate(`document.querySelector('[data-application-id="${escalation.id}"]').click()`);
    await new Promise(r => setTimeout(r, 800));
  };
  await openEscalation();
  await click("Запросить документы через ИИ-агента");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'A_RequestDocs.dc.html'");
  await evaluate("Array.from(document.querySelectorAll('label')).find(l => l.textContent.includes('Подтверждение оборота')).querySelector('input').click(); document.querySelector('textarea').value = 'Подтвердите обороты за последние 12 месяцев'");
  await click("Передать ИИ-агенту");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'A_Analyst.dc.html' && !document.querySelector('[aria-busy=true]')");
  const requested = await api(`/api/backend/backoffice/applications/${escalation.id}`);
  const docRequest = requested.data.info_requests.at(-1);
  if (requested.data.application.status !== "need_additional_data" || docRequest?.requested_by !== "credit_analyst" || docRequest.requested_document_types[0] !== "bank_statement") throw new Error(`Analyst document request not persisted: ${JSON.stringify(requested.data.info_requests)}`);
  console.log("Analyst document request sent to the client through UI");

  await login("/login", ["+7 999 000-00-04"], "client");
  const uploaded = await evaluate(`(() => { const data = new FormData(); data.append("file", new Blob(["%PDF-1.4\\n%%EOF\\n"], { type: "application/pdf" }), "vypiska.pdf"); data.append("type", "bank_statement"); data.append("info_request_id", ${JSON.stringify(docRequest.id)}); return fetch("/api/backend/applications/${escalation.id}/documents", { method: "POST", body: data }).then(r => r.status); })()`);
  if (uploaded !== 201) throw new Error(`Document upload failed: ${uploaded}`);
  const answered = await api(`/api/backend/applications/${escalation.id}/info-requests/${docRequest.id}/answer`, { message: "Выписка приложена" });
  if (answered.status !== 200) throw new Error(`Info request answer failed: ${JSON.stringify(answered)}`);
  if ((await api(`/api/backend/applications/${escalation.id}`)).data.status !== "analyst_escalation") throw new Error("Answered request did not return application to analyst");
  console.log("Client uploaded the document and answered; application returned to analyst");

  await login("/staff/login?role=analyst", [analystLogin, "demo-password"], "credit_analyst");
  const files = (await api(`/api/backend/backoffice/applications/${escalation.id}`)).data.documents;
  const download = await evaluate(`fetch("/api/backend/backoffice/applications/${escalation.id}/documents/${files[0]?.id}/content").then(r => r.status)`);
  if (files.length !== 1 || download !== 200) throw new Error(`Analyst cannot download uploaded file: ${download}`);
  await openEscalation();
  await click("Отправить заключение андеррайтеру");
  await wait("!!document.querySelector('textarea')");
  await evaluate("document.querySelector('textarea').value='Проверено на синтетических данных'; document.querySelector('input[type=radio]').click()");
  await click("Отправить андеррайтеру");
  await wait("document.querySelector('[data-screen-name]')?.dataset.screenName === 'A_Analyst.dc.html' && !document.querySelector('[aria-busy=true]')");
  const analysed = await api(`/api/backend/backoffice/applications/${escalation.id}`);
  if (analysed.data.application.status !== "underwriter_review" || analysed.data.credit_memo.analyst_conclusion !== "Проверено на синтетических данных") throw new Error("Analyst conclusion not persisted");
  console.log("Analyst conclusion persisted and routed to underwriter");

  await login("/staff/login?role=admin", ["admin@alfa-demo.ru", "demo-password"], "admin");
  application.number = (await api(`/api/backend/backoffice/applications/${application.id}`)).data.application.number;
  await wait(`!!document.querySelector('[data-application-id="${application.id}"]')`);
  await evaluate(`document.querySelector('[data-application-id="${application.id}"]').click()`);
  await wait(`location.pathname.endsWith('${application.id}')`);
  await command("Page.reload"); await wait("!!document.querySelector('[data-screen-name]')");
  await wait(`document.body.innerText.includes(${JSON.stringify(application.number)})`);
  const legacy = await evaluate("Array.from(document.querySelectorAll('a[href]')).some(a=>a.getAttribute('href').includes('.dc.html'))");
  if (legacy) throw new Error("Legacy HTML links remain");
  await click("← Все заявки"); await wait("location.pathname === '/staff/admin'");
  await evaluate("history.back()"); await wait(`location.pathname.endsWith('${application.id}') && !!document.querySelector('[data-api-ready=true]') && document.body.innerText.includes(${JSON.stringify(application.number)})`);
  await evaluate("document.fonts.ready.then(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))");
  const cookieVisible = await evaluate("document.cookie.includes('credit_session')");
  if (cookieVisible) throw new Error("Session token is exposed to browser JavaScript");
  await writeFile(`${out}/report.json`, JSON.stringify({ applicationId: application.id, contractId: contract.data.id, declinedId: declined.id, escalationId: escalation.id, requests }, null, 2));
  const shot = await command("Page.captureScreenshot", { format: "png" }); await writeFile(`${out}/admin-application.png`, Buffer.from(shot.data, "base64"));
  console.log("Admin sees the same application after reload. Clean URLs verified.");
} finally { await command("Page.close").catch(() => {}); socket.close(); }
