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
const PURPOSE_LABELS: Record<string, string> = { working_capital: "Пополнение оборотных средств", equipment: "Покупка оборудования", business_expansion: "Развитие бизнеса", refinancing: "Рефинансирование", other: "Другая цель" };
const purposeCode = (label: string) => { const text = label.toLowerCase(); return text.includes("оборуд") ? "equipment" : text.includes("оборот") ? "working_capital" : text.includes("рефин") ? "refinancing" : text.includes("развит") ? "business_expansion" : "other"; };
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
  const syncedDraft = useRef<string | null>(null);
  const load: (selectedId?: string | null) => Promise<void> = useCallback(async (selectedId?: string | null) => {
    const requestId = ++sequence.current;
    const current = scene.current;
    if (isLogin(current)) return;
    try {
      const user = await api("/api/session");
      const employee = user.role !== "client";
      const expected = current.startsWith("AD_") ? "admin" : current.startsWith("U_") ? "underwriter" : current.startsWith("A_") ? "credit_analyst" : "client";
      if (user.role !== expected) {
        // Сессия одна на браузер: вход под другой ролью в соседней вкладке заменяет её
        const roles: Record<string, string> = { client: "клиент", credit_analyst: "кредитный аналитик", underwriter: "андеррайтер", admin: "администратор" };
        setState(previous => ({ ...previous, error: `В этом браузере выполнен вход под другой ролью: ${roles[str(user.role)] ?? str(user.role)}. Сессия общая для всех вкладок - войдите заново или используйте отдельное окно инкогнито для каждой роли.` }));
        transition(loginScene(current), true); return;
      }
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
      let offer: ObjectData | null = null; let contract: ObjectData | null = null; let documents: ObjectData[] = []; let requests: ObjectData[] = []; let chat: ObjectData[] = []; let preApproval: ObjectData | null = null; let employees: ObjectData[] = [];
      if (employee) {
        products = list(await optional("/products"));
        company = detail ? object(detail.company) : null;
        documents = list(detail?.documents); requests = list(detail?.info_requests); contract = detail?.contract ? object(detail.contract) : null;
        const decisions = list(detail?.decisions); offer = decisions.at(-1) ?? null;
        // Список аналитиков для выбора исполнителя экспертизы
        if (current === "U_Expertise.dc.html") employees = list(await optional("/backoffice/employees?role=credit_analyst"));
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
            // Ставка предварительного расчёта - «было» в контр-предложении
            if (application?.client_status === "counter_offer") { const pre = await optional(`/applications/${id}/pre-approval`); preApproval = pre ? object(pre) : null; }
          }
          if (["e_sign", "disbursement", "completed"].includes(str(application?.status))) {
            const value = await optional(`/applications/${id}/contract`); contract = value ? object(value) : null;
          }
          if (current.includes("Docs") || (current.includes("_Home") && (latest.current.detailsOpen || current.includes("HomeModal")))) documents = list(await optional(`/applications/${id}/documents`));
          // Запросы банка и загруженные файлы - на любом экране, пока заявка ждёт документов
          if (current.includes("MissingDocs") || application?.status === "need_additional_data") {
            requests = list(await optional(`/applications/${id}/info-requests`));
            if (!documents.length) documents = list(await optional(`/applications/${id}/documents`));
          }
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
      // Черновик формы чата берёт условия выбранной редактируемой заявки (один раз на заявку)
      if (!employee && application && ["draft", "pre_approved"].includes(str(application.status)) && syncedDraft.current !== application.id) {
        syncedDraft.current = str(application.id);
        setDraft(previous => ({ ...previous, amount: String(Math.round(Number(application.requested_amount))), term: Number(application.requested_term_months), purpose: PURPOSE_LABELS[str(application.purpose)] ?? previous.purpose, collateral: application.has_collateral ? "С залогом" : "Без залога" }));
      }
      setState(previous => ({ ...previous, user, applications, application, detail, products, loans, company, offer, contract, documents, requests, chat, preApproval, employees, warnings, loading: false }));
      if (!employee && current.includes("_Home") && !current.includes("Schedule") && !current.includes("Modal")) {
        const next = homeScene(application); if (next !== current) transition(next, true);
      }
      if (!employee && current.includes("Credits") && !current.includes("Schedule")) {
        const next = loans.length ? "S4_Credits.dc.html" : "S4_CreditsEmpty.dc.html";
        if (current !== next) transition(next, true);
      }
      if (employee && current.startsWith("AD_Detail") && application) {
        // Экран автоотказа - только для автоотказа; прочие закрытые и активные - общая карточка
        const next = application.close_reason === "auto_declined" ? "AD_DetailDeclined.dc.html" : "AD_DetailDone.dc.html";
        if (current !== next) transition(next, true);
      }
    } catch (error) {
      if (requestId !== sequence.current) return;
      if (error instanceof ApiError && error.status === 401) { setState(empty); transition(loginScene(current), true); }
      else setState(previous => ({ ...previous, loading: false, error: error instanceof Error ? error.message : "Не удалось загрузить данные" }));
    }
  }, [transition, setState, setDraft, drafting]);

  useEffect(() => {
    if (isLogin(name)) return;
    // Окно «Детали заявки» закрывается при переходе на другой экран
    setState(previous => ({ ...previous, loading: !previous.user, detailsOpen: false }));
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
        // Ответ входа - профиль: роль берётся из него, а не из страницы входа
        const user = await post("/api/session", current.startsWith("S") ? { kind: "client", phone: inputs[0]?.value } : { kind: "employee", email: inputs[0]?.value, password: inputs[1]?.value });
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
          const purpose = purposeCode(draft.purpose);
          if (!draft.collateral.toLowerCase().includes("без")) throw new Error("Для заявки с залогом нужны дополнительные поля. Эта форма пока поддерживает вариант без залога.");
          const product = products.find(p => Number(p.min_amount) <= Number(draft.amount) && Number(p.max_amount) >= Number(draft.amount) && Number(p.min_term_months) <= draft.term && Number(p.max_term_months) >= draft.term && !p.requires_collateral && Array.isArray(p.purposes) && p.purposes.includes(purpose));
          if (!company || !product) throw new Error("Нет подходящего продукта или компании для указанных условий");
          application = await post("/applications", { company_id: company.company_id, product_id: product.id, requested_amount: draft.amount, requested_term_months: draft.term, purpose, purpose_description: draft.purpose });
          drafting.current = false;
          storeId(str(application.id));
          setState(previous => ({ ...previous, application }));
        }
        else if (application && (Number(application.requested_amount) !== Number(draft.amount) || Number(application.requested_term_months) !== draft.term || application.purpose !== purposeCode(draft.purpose))) {
          // Клиент изменил параметры в чате - сначала сохраняем их в заявке
          application = await api(`/applications/${application.id}`, { method: "PATCH", body: JSON.stringify({ requested_amount: draft.amount, requested_term_months: draft.term, purpose: purposeCode(draft.purpose), version: application.version }) });
        }
        if (!application) throw new Error("Заявка не создана");
        if (application.status === "draft") application = await post(`/applications/${application.id}/consents`, { types: ["bki", "fns", "digital_profile"] });
        if (application.status === "pre_approved") application = await post(`/applications/${application.id}/submit`);
        await load(str(application.id)); transition(homeScene(application));
      } else if ((text === "Уточнить причину" || text === "Что можно исправить") && current.startsWith("S")) {
        // Быстрые вопросы агенту после отказа - обычные сообщения чата
        const companyId = app?.company_id ?? list(latest.current.user?.companies)[0]?.company_id;
        if (!companyId) throw new Error("Нет компании для диалога");
        await post("/chat/messages", { company_id: companyId, application_id: id, content: text === "Уточнить причину" ? "Почему отказ?" : "Что можно исправить?", client_message_id: crypto.randomUUID() });
        await load(id);
      } else if (text === "Посмотреть" && current.startsWith("S") && latest.current.contract) {
        // Договор на подписание - PDF в новой вкладке
        window.open(`/api/backend/applications/${str(latest.current.contract.application_id)}/contract/document`, "_blank", "noopener");
      } else if (text === "График платежей" && current === "S4_CreditsSchedule.dc.html") {
        // Окно графика уже открыто
      } else if (text === "Спросить ИИ-агента" && current.startsWith("S")) {
        // Чат по текущей заявке; в макетах это то ссылка, то кнопка без обработчика
        setState(previous => ({ ...previous, detailsOpen: false }));
        transition(app && !["draft", "pre_approved"].includes(str(app.status)) ? "S1_ChatSubmitted.dc.html" : "S1_Chat.dc.html");
      } else if (text === "Взять в работу" && id && latest.current.user) {
        await post(`/backoffice/applications/${id}/assign`, { assignee_id: latest.current.user.id });
        await load(id);
      } else if (text === "Детали заявки" && !current.startsWith("A") && !current.startsWith("U")) {
        if (!id) throw new Error("Сначала выберите заявку");
        latest.current = { ...latest.current, detailsOpen: true };
        setState(previous => ({ ...previous, detailsOpen: true }));
        await load(id);
      } else if (text === "Закрыть" && latest.current.detailsOpen && root.querySelector("[data-close-details]")) {
        setState(previous => ({ ...previous, detailsOpen: false }));
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
          const analystId = root.querySelector<HTMLSelectElement>("select[data-analyst]")?.value || null;
          body = { decision_type: "more_information_required", more_info_target: text === "Отправить запрос" ? "client" : "credit_analyst", comment: textarea, ...(text === "Отправить аналитику" && analystId ? { analyst_id: analystId } : {}), ...(text === "Отправить запрос" ? { info_request: { message: textarea, requested_document_types: requestedTypes } } : {}) };
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
      } else if (text === "Отправить документы банку" || text === "Отправить ответ банку") {
        if (!id) throw new Error("Сначала выберите заявку");
        const open = latest.current.requests.filter(r => r.status === "open");
        if (!open.length) throw new Error("Открытых запросов банка нет");
        const answer = root.querySelector<HTMLTextAreaElement>("textarea[data-answer]");
        const message = answer?.value.trim() || null;
        if (open.some(r => !list(r.requested_document_types).length) && !message) throw new Error("Напишите ответ банку в поле «Ваш ответ банку»");
        for (const request of open) await post(`/applications/${id}/info-requests/${request.id}/answer`, { message });
        if (answer) answer.value = "";
        const updated = await api(`/applications/${id}`);
        await load(id); transition(homeScene(updated));
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
        // Подписи пунктов без заглушек макета («за [период]» после привязки становится «за —»)
        const checked = Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:checked')).map(input => (input.closest("label")?.textContent ?? input.parentElement?.textContent ?? "").replace(/\s*(за|:)\s*—/g, "").trim());
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
      } else if (text === "Кредитный договор" || text === "Скачать договор" || text.includes("Скачать график")) {
        // Выгрузки backend: договор с графиком (PDF), график платежей (XLSX)
        const contractApp = str(latest.current.contract?.application_id ?? latest.current.loans.find(loan => loan.application_id === id)?.application_id ?? latest.current.loans[0]?.application_id ?? "");
        if (!contractApp) throw new Error("Договор ещё не подготовлен");
        const link = document.createElement("a");
        link.href = `/api/backend/applications/${contractApp}/contract/${text.includes("график") ? "schedule-export?format=xlsx" : "document"}`;
        link.download = ""; document.body.append(link); link.click(); link.remove();
      } else if (text === "Скачать") {
        throw new Error("Выберите документ в списке. Скачивание доступно только для файлов, возвращённых API.");
      } else handled = false;
    } catch (error) { setState(previous => ({ ...previous, error: error instanceof Error ? error.message : "Ошибка операции" })); }
    finally { setState(previous => ({ ...previous, busy: false })); }
    return handled;
  }

  async function upload(file: File, requestedType?: string, requestId?: string) {
    const id = latest.current.application?.id;
    if (!id) return;
    // Тип известен из запроса банка; без запроса (загрузка до подачи) - спрашиваем
    let type = requestedType;
    if (!type) {
      const answer = window.prompt("Тип документа: Выписка, Отчётность, КУДИР, Декларация, Другое", "Другое");
      if (answer === null) return;
      const types: Record<string, string> = { "выписка": "bank_statement", "отчётность": "financial_statement", "отчетность": "financial_statement", "кудир": "kudir", "декларация": "tax_return", "другое": "other" };
      type = types[answer.trim().toLowerCase()];
      if (!type) { setState(previous => ({ ...previous, error: "Выберите допустимый тип документа" })); return; }
    }
    const data = new FormData(); data.append("file", file); data.append("type", type);
    if (requestId) data.append("info_request_id", requestId);
    setState(previous => ({ ...previous, busy: true, error: "" }));
    try { await api(`/applications/${id}/documents`, { method: "POST", body: data }); await load(str(id)); }
    catch (error) { setState(previous => ({ ...previous, error: error instanceof Error ? error.message : "Не удалось загрузить файл" })); }
    finally { setState(previous => ({ ...previous, busy: false })); }
  }
  return { ...state, draft, action, upload, refresh: load, select: async (id: string) => { storeId(id); await load(id); } };
}
