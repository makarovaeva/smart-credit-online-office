"use client";

import { useCallback, useEffect, useRef } from "react";
import { api, ApiError, list, object, post, str, type ObjectData } from "@/lib/api";
import type { ScreenName } from "./routes";
import { empty, useBankContext } from "./bank-provider";
export type { BankState } from "./bank-provider";
export const loginScene = (name: string): ScreenName => name.startsWith("AD_") ? "AD_Login.dc.html" : name.startsWith("U_") ? "U_Login.dc.html" : name.startsWith("A_") ? "A_Login.dc.html" : "S1_Login.dc.html";
export const isLogin = (name: string) => name.includes("_Login.");
export const homeScene = (application: ObjectData | null): ScreenName => {
  if (!application) return "S1_HomeEmpty.dc.html";
  if (Array.isArray(application.available_actions) && application.available_actions.includes("sign")) return "S4_Home.dc.html";
  switch (application.client_status) {
    case "approved": return "S3_HomeOffer.dc.html";
    case "counter_offer": return "S4_HomeCounter.dc.html";
    case "signed": return "S4_Home.dc.html";
    case "disbursed": return "S4_HomeIssued.dc.html";
    case "documents_required": return "S2_HomeMissingDocs.dc.html";
    case "under_review": return "S3_HomeReview.dc.html";
    case "closed": return application.close_reason === "offer_rejected" ? "S3_HomeOfferRejected.dc.html" : application.close_reason === "auto_declined" ? "S1_HomeAutoDecline.dc.html" : "S2_HomeDeclined.dc.html";
    default: return Array.isArray(application.available_actions) && application.available_actions.includes("sign") ? "S4_Home.dc.html" : "S1_HomeSubmitted.dc.html";
  }
};
const selectionKey = "credit-selected-application";
function storedId() { try { return sessionStorage.getItem(selectionKey); } catch { return null; } }
function storeId(id: string | null) { try { if (id) sessionStorage.setItem(selectionKey, id); else sessionStorage.removeItem(selectionKey); } catch {} }

async function collection(path: string): Promise<ObjectData[]> {
  const result = await api<unknown>(`${path}${path.includes("?") ? "&" : "?"}limit=100`);
  if (Array.isArray(result)) return list(result);
  const data = object(result); const rows = list(data.items);
  for (let offset = rows.length; offset < Number(data.total); offset += 100) {
    const page = await api(`${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`);
    const next = list(page.items); if (!next.length) break; rows.push(...next);
  }
  return rows;
}

export function useBank(name: ScreenName, transition: (next: ScreenName, replace?: boolean) => void) {
  const { state, setState, draft, setDraft, drafting } = useBankContext();
  const latest = useRef(state); latest.current = state;
  const scene = useRef(name); scene.current = name;
  const sequence = useRef(0);
  const load: (selectedId?: string | null) => Promise<void> = useCallback(async (selectedId?: string | null) => {
    const requestId = ++sequence.current;
    const current = scene.current;
    if (isLogin(current)) return;
    try {
      const user = await api("/api/session");
      const employee = user.role !== "client";
      const expected = current.startsWith("AD_") ? "admin" : current.startsWith("U_") ? "underwriter" : current.startsWith("A_") ? "credit_analyst" : "client";
      if (user.role !== expected) { transition(loginScene(current), true); return; }
      const applications = await collection(employee ? "/backoffice/applications" : "/applications");
      const urlId = current.startsWith("AD_") ? window.location.pathname.split("/").at(-1) : null;
      const requested = selectedId === undefined ? (urlId && /^[0-9a-f-]{36}$/.test(urlId) ? urlId : storedId()) : selectedId;
      const selected = !employee && drafting.current ? undefined : applications.find(a => a.id === requested) ?? applications[0];
      const id = selected ? str(selected.id) : null;
      storeId(id);
      const detail = id ? await api(employee ? `/backoffice/applications/${id}` : `/applications/${id}`) : null;
      const application = detail ? employee ? object(detail.application) : detail : null;
      const warnings: string[] = [];
      async function optional(path: string) {
        try { return await api<unknown>(path); } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) warnings.push(`${path.includes("companies") ? "Профиль компании" : path.includes("documents") ? "Документы" : path.includes("info-requests") ? "Дозапросы" : "Часть данных"}: временно недоступны`);
          return null;
        }
      }
      let products: ObjectData[] = []; let loans: ObjectData[] = []; let company: ObjectData | null = null;
      let offer: ObjectData | null = null; let contract: ObjectData | null = null; let documents: ObjectData[] = []; let requests: ObjectData[] = []; let chat: ObjectData[] = [];
      if (employee) {
        products = list(await optional("/products"));
        company = detail ? object(detail.company) : null;
        documents = list(detail?.documents); requests = list(detail?.info_requests); contract = detail?.contract ? object(detail.contract) : null;
        const decisions = list(detail?.decisions); offer = decisions.at(-1) ?? null;
      } else {
        const values = await Promise.all([optional("/products"), optional("/loans")]);
        products = list(values[0]); loans = list(values[1]);
        const selectedLoan = loans.find(loan => loan.application_id === application?.id) ?? loans[0];
        if (current.includes("Credits") && selectedLoan && application?.id !== selectedLoan.application_id) {
          await load(str(selectedLoan.application_id)); return;
        }
        if (id) {
          if (application?.client_status === "approved" || application?.client_status === "counter_offer" || application?.status === "e_sign" || application?.client_status === "disbursed" || application?.client_status === "closed") {
            const value = await optional(`/applications/${id}/offer`); offer = value ? object(value) : null;
          }
          if (["e_sign", "disbursement", "completed"].includes(str(application?.status))) {
            const value = await optional(`/applications/${id}/contract`); contract = value ? object(value) : null;
          }
          if (current.includes("Docs")) documents = list(await optional(`/applications/${id}/documents`));
          if (current.includes("MissingDocs")) requests = list(await optional(`/applications/${id}/info-requests`));
        }
        if (current.includes("Chat")) {
          // Диалог по выбранной заявке; при оформлении новой - сообщения до создания заявки
          const companyId = (!drafting.current && application?.company_id) || list(user.companies)[0]?.company_id;
          if (companyId) {
            const rows = list(await optional(`/chat/messages?company_id=${companyId}${!drafting.current && id ? `&application_id=${id}` : ""}`));
            chat = drafting.current || !id ? rows.filter(m => !m.application_id) : rows;
          }
        }
        if (current.includes("Profile")) {
          const companyId = application?.company_id ?? list(user.companies)[0]?.company_id;
          if (companyId) { const value = await optional(`/companies/${companyId}`); company = value ? object(value) : null; }
        }
      }
      if (requestId !== sequence.current) return;
      setState(previous => ({ ...previous, user, applications, application, detail, products, loans, company, offer, contract, documents, requests, chat, warnings, loading: false }));
      if (!employee && current.includes("_Home") && !current.includes("Schedule") && !current.includes("Modal")) {
        const next = homeScene(application); if (next !== current) transition(next, true);
      }
      if (!employee && current.includes("Credits") && !current.includes("Schedule")) {
        const next = loans.length ? "S4_Credits.dc.html" : "S4_CreditsEmpty.dc.html";
        if (current !== next) transition(next, true);
      }
      if (employee && current.startsWith("AD_Detail") && application) {
        const next = application.status === "closed" ? "AD_DetailDeclined.dc.html" : "AD_DetailDone.dc.html";
        if (current !== next) transition(next, true);
      }
    } catch (error) {
      if (requestId !== sequence.current) return;
      if (error instanceof ApiError && error.status === 401) { setState(empty); transition(loginScene(current), true); }
      else setState(previous => ({ ...previous, loading: false, error: error instanceof Error ? error.message : "Не удалось загрузить данные" }));
    }
  }, [transition, setState, drafting]);

  useEffect(() => {
    if (isLogin(name)) return;
    setState(previous => ({ ...previous, loading: !previous.user }));
    void load();
    const timer = setInterval(() => { if (!document.hidden && !latest.current.busy && !document.activeElement?.matches("input, textarea, select")) void load(); }, 5_000);
    return () => { clearInterval(timer); ++sequence.current; };
  }, [name, load, setState]);

  async function action(text: string, root: HTMLElement, target?: ScreenName): Promise<boolean> {
    const current = scene.current;
    const inputs = Array.from(root.querySelectorAll<HTMLInputElement>("input:not([type=radio]):not([type=checkbox])"));
    const textarea = root.querySelector<HTMLTextAreaElement>("textarea")?.value.trim() ?? "";
    const cleanAmount = (value: string) => value.replace(/\s/g, "").replace(/[^\d.,]/g, "").replace(",", ".");
    const readDraft = () => ({ amount: cleanAmount(inputs[0]?.value ?? draft.amount), term: Number(inputs[1]?.value ?? draft.term), purpose: inputs[2]?.value ?? draft.purpose, collateral: inputs[3]?.value ?? draft.collateral });
    const app = latest.current.application;
    const id = app ? str(app.id) : null;
    let handled = true;
    setState(previous => ({ ...previous, busy: true, error: "" }));
    try {
      if (isLogin(current) && ["Войти", "Получить код"].includes(text)) {
        await post("/api/session", current.startsWith("S") ? { kind: "client", phone: inputs[0]?.value } : { kind: "employee", email: inputs[0]?.value, password: inputs[1]?.value });
        const user = await api("/api/session");
        storeId(null); drafting.current = false; setState({ ...empty, user });
        transition(user.role === "admin" ? "AD_All.dc.html" : user.role === "underwriter" ? "U_Workspace.dc.html" : user.role === "credit_analyst" ? "A_Analyst.dc.html" : "S1_HomeEmpty.dc.html");
      } else if (text === "Выйти") {
        await api("/api/session", { method: "DELETE" }); storeId(null); setState(empty); transition(loginScene(current));
      } else if (text === "Подать новую заявку" || text === "Подать заявку в чате") {
        storeId(null); drafting.current = true; setState(previous => ({ ...previous, application: null })); setDraft({ amount: "3000000", term: 24, purpose: "Пополнение оборотных средств", collateral: "Без залога" });
        transition("S1_Chat.dc.html");
      } else if (text === "Сохранить изменения") {
        const next = readDraft();
        if (!next.amount || !Number.isInteger(next.term) || next.term < 1) throw new Error("Укажите корректные сумму и срок");
        setDraft(next);
        if (id && ["draft", "pre_approved"].includes(str(app?.status))) await api(`/applications/${id}`, { method: "PATCH", body: JSON.stringify({ requested_amount: next.amount, requested_term_months: next.term, version: app?.version }) });
        transition("S1_Chat.dc.html");
      } else if (text === "Подтвердить и отправить заявку") {
        if (!window.confirm("Подтверждаете заявку и согласия на получение данных БКИ, ФНС и цифрового профиля?")) return true;
        let application = app;
        if (!application || !["draft", "pre_approved"].includes(str(application.status))) {
          const user = latest.current.user;
          const company = list(user?.companies)[0];
          const products = latest.current.products.length ? latest.current.products : await api<ObjectData[]>("/products");
          const purposeText = draft.purpose.toLowerCase();
          const purpose = purposeText.includes("оборуд") ? "equipment" : purposeText.includes("оборот") ? "working_capital" : purposeText.includes("рефин") ? "refinancing" : purposeText.includes("развит") ? "business_expansion" : "other";
          if (!draft.collateral.toLowerCase().includes("без")) throw new Error("Для заявки с залогом нужны дополнительные поля. Эта форма пока поддерживает вариант без залога.");
          const product = products.find(p => Number(p.min_amount) <= Number(draft.amount) && Number(p.max_amount) >= Number(draft.amount) && Number(p.min_term_months) <= draft.term && Number(p.max_term_months) >= draft.term && !p.requires_collateral && Array.isArray(p.purposes) && p.purposes.includes(purpose));
          if (!company || !product) throw new Error("Нет подходящего продукта или компании для указанных условий");
          application = await post("/applications", { company_id: company.company_id, product_id: product.id, requested_amount: draft.amount, requested_term_months: draft.term, purpose, purpose_description: draft.purpose });
          drafting.current = false;
          storeId(str(application.id));
          setState(previous => ({ ...previous, application }));
        }
        if (application.status === "draft") application = await post(`/applications/${application.id}/consents`, { types: ["bki", "fns", "digital_profile"] });
        if (application.status === "pre_approved") application = await post(`/applications/${application.id}/submit`);
        await load(str(application.id)); transition(homeScene(application));
      } else if (text === "Принять оффер" || text === "Отклонить оффер" || text === "Подписать") {
        if (!id) throw new Error("Сначала выберите заявку");
        const result = await post(`/applications/${id}/${text === "Принять оффер" ? "offer/accept" : text === "Отклонить оффер" ? "offer/reject" : "sign"}`, text === "Подписать" ? { confirmation_code: "123456" } : {});
        await load(id); transition(homeScene(result));
      } else if (text === "Отправить андеррайтеру") {
        if (!id || !textarea) throw new Error("Выберите заявку и заполните заключение");
        const checked = root.querySelector<HTMLInputElement>('input[type="radio"]:checked');
        if (!checked) throw new Error("Выберите рекомендацию");
        const label = checked.closest("label")?.textContent ?? checked.parentElement?.textContent ?? "";
        await post(`/backoffice/applications/${id}/analyst-conclusion`, { conclusion: textarea, recommendation: label.includes("отказать") ? "decline" : label.includes("измен") ? "counter_offer" : "approve" });
        await load(id); transition("A_Analyst.dc.html");
      } else if (["Подтвердить одобрение", "Отправить контр-предложение", "Подтвердить отказ", "Отправить запрос", "Отправить аналитику"].includes(text)) {
        if (!id) throw new Error("Выберите заявку");
        let body: ObjectData;
        if (text === "Подтвердить отказ") {
          if (!textarea) throw new Error("Укажите причину отказа");
          body = { decision_type: "declined", reasons: [{ code: "underwriter_declined", message: textarea }], comment: textarea };
        } else if (text === "Отправить запрос" || text === "Отправить аналитику") {
          if (!textarea) throw new Error("Заполните текст запроса");
          const requestedTypes = Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:checked')).map(input => {
            const text = (input.closest("label")?.textContent ?? input.parentElement?.textContent ?? "").toLowerCase();
            return text.includes("выпис") ? "bank_statement" : text.includes("кудир") ? "kudir" : text.includes("деклар") ? "tax_return" : text.includes("отч") ? "financial_statement" : "other";
          });
          body = { decision_type: "more_information_required", more_info_target: text === "Отправить запрос" ? "client" : "credit_analyst", comment: textarea, ...(text === "Отправить запрос" ? { info_request: { message: textarea, requested_document_types: requestedTypes } } : {}) };
        } else {
          const memo = object(latest.current.detail?.credit_memo);
          const preliminary = object(latest.current.detail?.pre_approval);
          const product = latest.current.products.find(p => p.id === app?.product_id);
          const approve = text === "Подтвердить одобрение";
          const rate = cleanAmount(approve ? str(memo.recommended_rate ?? preliminary.estimated_rate ?? product?.base_rate) : inputs[2]?.value ?? "");
          if (!rate || Number(rate) <= 0) throw new Error("Укажите корректную ставку");
          body = { decision_type: approve ? "approved" : "conditional_approval", approved_amount: approve ? app?.requested_amount : cleanAmount(inputs[0]?.value ?? ""), approved_term_months: approve ? app?.requested_term_months : Number(inputs[1]?.value), interest_rate: rate, comment: textarea, conditions: approve ? list(memo.recommended_conditions) : inputs[3]?.value ? [{ code: "security", description: inputs[3].value }] : [] };
        }
        await post(`/backoffice/applications/${id}/decision`, body); await load(id); transition("U_Workspace.dc.html");
      } else if (text === "Отправить" && current.includes("Chat") && root.querySelector<HTMLInputElement>('input[aria-label="Сообщение"]')?.value.trim()) {
        const input = root.querySelector<HTMLInputElement>('input[aria-label="Сообщение"]');
        const content = input?.value.trim() ?? "";
        const companyId = (!drafting.current && app?.company_id) || list(latest.current.user?.companies)[0]?.company_id;
        if (!companyId) throw new Error("Нет компании для диалога");
        const exchange = await post("/chat/messages", { company_id: companyId, application_id: !drafting.current && id ? id : null, content, client_message_id: crypto.randomUUID() });
        if (input) input.value = "";
        // Карточка агента заполняет параметры заявки; подтверждает их клиент
        const fields = object(object(object(exchange.reply).card_payload).fields);
        if (fields.amount || fields.term_months) setDraft(previous => ({ ...previous, amount: fields.amount ? String(Math.round(Number(fields.amount))) : previous.amount, term: fields.term_months ? Number(fields.term_months) : previous.term, purpose: fields.purpose_label ? str(fields.purpose_label) : previous.purpose, collateral: fields.collateral_label ? str(fields.collateral_label) : previous.collateral }));
        await load(id);
      } else if (text === "Отправить" && id && latest.current.requests.some(r => r.status === "open")) {
        const open = latest.current.requests.filter(r => r.status === "open");
        if (open.length !== 1) throw new Error("Выберите конкретный дозапрос перед отправкой ответа");
        const message = root.querySelector<HTMLInputElement>('input[aria-label="Сообщение"]')?.value;
        await post(`/applications/${id}/info-requests/${open[0].id}/answer`, { message: message || null }); await load(id);
      } else if (text === "Передать ИИ-агенту" && current === "A_RequestDocs.dc.html") {
        if (!id) throw new Error("Выберите заявку");
        const checked = Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:checked')).map(input => (input.closest("label")?.textContent ?? input.parentElement?.textContent ?? "").trim());
        if (!checked.length && !textarea) throw new Error("Отметьте документы или напишите, что уточнить у клиента");
        const requestedTypes = [...new Set(checked.flatMap(label => {
          const lower = label.toLowerCase();
          return lower.includes("договор") ? ["contract"] : lower.includes("оборот") ? ["bank_statement"] : lower.includes("пояснен") ? [] : ["other"];
        }))];
        const message = [textarea, checked.length ? `Нужно: ${checked.join("; ")}` : ""].filter(Boolean).join("\n");
        await post(`/backoffice/applications/${id}/info-requests`, { message, requested_document_types: requestedTypes });
        await load(id); transition("A_Analyst.dc.html");
      } else if (["Принять в работу", "Вернуть с комментарием", "Напомнить клиенту через ИИ-агента", "Напомнить аналитику", "Отозвать запрос"].includes(text)) {
        if (!id) throw new Error("Выберите заявку");
        const detail = latest.current.detail ?? {};
        const expertise = list(detail.internal_requests).filter(r => ["open", "accepted"].includes(str(r.status))).at(-1);
        const role = latest.current.user?.role === "credit_analyst" ? "credit_analyst" : "underwriter";
        const info = list(detail.info_requests).filter(r => r.status === "open" && r.requested_by === role).at(-1);
        const base = `/backoffice/applications/${id}`;
        if (text === "Принять в работу") {
          if (!expertise) throw new Error("По заявке нет запроса экспертизы");
          await post(`${base}/internal-requests/${expertise.id}/accept`, {});
        } else if (text === "Вернуть с комментарием") {
          if (!expertise) throw new Error("По заявке нет запроса экспертизы");
          const comment = window.prompt("Комментарий андеррайтеру: почему запрос возвращается без заключения");
          if (!comment?.trim()) return true;
          await post(`${base}/internal-requests/${expertise.id}/return`, { comment: comment.trim() });
        } else if (text === "Напомнить клиенту через ИИ-агента") {
          if (!info) throw new Error("Нет открытого запроса документов от вас");
          await post(`${base}/info-requests/${info.id}/remind`, {});
        } else if (text === "Напомнить аналитику") {
          if (!expertise) throw new Error("Нет открытого запроса аналитику");
          await post(`${base}/internal-requests/${expertise.id}/remind`, {});
        } else if (expertise) {
          await post(`${base}/internal-requests/${expertise.id}/cancel`, {});
        } else {
          if (!info) throw new Error("Нет открытого запроса, который можно отозвать");
          await post(`${base}/info-requests/${info.id}/cancel`, {});
        }
        await load(id);
        if (text === "Принять в работу" || text === "Вернуть с комментарием") transition("A_Analyst.dc.html");
      } else if (text === "Отправить") {
        throw new Error("Для этого действия ещё нет рабочего backend API. Запрос не отправлен.");
      } else if (text === "Скачать" || text.includes("Скачать график") || text === "Кредитный договор") {
        throw new Error("Выберите документ в списке. Скачивание доступно только для файлов, возвращённых API.");
      } else handled = false;
    } catch (error) { setState(previous => ({ ...previous, error: error instanceof Error ? error.message : "Ошибка операции" })); }
    finally { setState(previous => ({ ...previous, busy: false })); }
    return handled;
  }

  async function upload(file: File) {
    const id = latest.current.application?.id;
    if (!id) return;
    const answer = window.prompt("Тип документа: Выписка, Отчётность, КУДИР, Декларация, Другое", "Другое");
    if (answer === null) return;
    const types: Record<string, string> = { "выписка": "bank_statement", "отчётность": "financial_statement", "отчетность": "financial_statement", "кудир": "kudir", "декларация": "tax_return", "другое": "other" };
    const type = types[answer.trim().toLowerCase()];
    if (!type) { setState(previous => ({ ...previous, error: "Выберите допустимый тип документа" })); return; }
    const data = new FormData(); data.append("file", file); data.append("type", type);
    const open = latest.current.requests.filter(r => r.status === "open");
    if (open.length === 1) data.append("info_request_id", str(open[0].id));
    setState(previous => ({ ...previous, busy: true, error: "" }));
    try { await api(`/applications/${id}/documents`, { method: "POST", body: data }); await load(str(id)); }
    catch (error) { setState(previous => ({ ...previous, error: error instanceof Error ? error.message : "Не удалось загрузить файл" })); }
    finally { setState(previous => ({ ...previous, busy: false })); }
  }
  return { ...state, draft, action, upload, refresh: load, select: async (id: string) => { storeId(id); await load(id); } };
}
