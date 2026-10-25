import { list, object, str, type ObjectData } from "@/lib/api";
import type { BankState } from "./use-bank";

// Целые суммы - без копеек («3 000 000 ₽»), с копейками - всегда два знака («44 773,10 ₽»)
export const money = (value: unknown) => {
  if (value === undefined || value === null) return "—";
  const amount = Number(value);
  const digits = Number.isInteger(amount) ? 0 : 2;
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(amount);
};
const date = (value: unknown) => value ? new Date(String(value)).toLocaleDateString("ru-RU") : "—";
const statuses: Record<string, string> = { draft: "Черновик", pre_approved: "Предварительное одобрение", underwriter_review: "Рассмотрение", analyst_escalation: "Эскалация аналитику", analyst_completed: "Заключение готово", need_additional_data: "Нужны документы", offer_generated: "Оффер сформирован", e_sign: "Договор на подписание", disbursement: "Выдача средств", completed: "Кредит выдан", closed: "Заявка закрыта" };
Object.assign(statuses, { data_collection: "Сбор данных", submitted: "Заявка отправлена", ai_verification: "Проверка документов", ai_financial_analysis: "Финансовый анализ", ai_risk_scoring: "Оценка риска", decision_routing: "Маршрутизация заявки", offer_accepted: "Оффер принят", offer_rejected: "Оффер отклонён", contract_generation: "Подготовка договора", approved: "Одобрено", conditional_approval: "Одобрено с изменениями", declined: "Отказано", accepted: "Принят", rejected: "Отклонён", active: "Действует", green: "Зелёная зона", yellow: "Жёлтая зона", red: "Красная зона" });
const legalForms: Record<string, string> = { ooo: "ООО", ip: "ИП" };
const taxSystems: Record<string, string> = { usn_income: "УСН «Доходы»", usn_income_expense: "УСН «Доходы минус расходы»", osno: "ОСНО", psn: "Патент", eshn: "ЕСХН" };
export const statusLabel = (value: unknown) => statuses[str(value)] ?? str(value);
const terminal = (a: ObjectData) => ["closed", "completed"].includes(str(a.status));

function tabRows(name: string, rows: ObjectData[]) {
  if (name.startsWith("AD_")) {
    if (name.includes("InWork")) return rows.filter(a => !terminal(a));
    if (name.includes("Closed")) return rows.filter(a => a.status === "closed");
    if (name.includes("Done")) return rows.filter(a => a.status === "completed");
  }
  // Новые эскалации - от ИИ, запросы от андеррайтера - с активным запросом экспертизы
  if (name === "A_AnalystNew.dc.html") return rows.filter(a => a.status === "analyst_escalation" && !a.expertise_request);
  if (name === "A_AnalystFromUw.dc.html") return rows.filter(a => a.status === "analyst_escalation" && !!a.expertise_request);
  if (name === "A_AnalystInWork.dc.html") return rows.filter(a => a.status === "need_additional_data");
  if (name === "U_Pending.dc.html") return rows.filter(a => a.status === "underwriter_review");
  if (name === "U_Mine.dc.html") return rows;
  if (name === "U_Requests.dc.html") return rows.filter(a => ["analyst_escalation", "need_additional_data"].includes(str(a.status)));
  return rows;
}

export function bindBank(html: string, name: string, bank: BankState & { draft: { amount: string; term: number; purpose: string; collateral: string } }) {
  if (typeof DOMParser === "undefined") return html;
  const doc = new DOMParser().parseFromString(html, "text/html");
  const app = bank.application ?? {};
  const detail = bank.detail ?? {};
  const company = bank.company ?? object(detail.company);
  const employee = bank.user?.role !== "client";
  const companyName = company.name ?? list(bank.user?.companies).find(c => c.company_id === app.company_id)?.company_name ?? list(bank.user?.companies)[0]?.company_name ?? (employee ? "Заявка не выбрана" : bank.user?.full_name);

  if (name.includes("_Login.")) {
    const inputs = doc.querySelectorAll<HTMLInputElement>("input");
    inputs.forEach(input => { input.removeAttribute("value"); input.setAttribute("required", ""); });
    if (name.startsWith("S")) {
      inputs[0]?.setAttribute("placeholder", "+7 999 000-00-01");
      inputs[0]?.setAttribute("type", "tel"); inputs[0]?.setAttribute("autocomplete", "tel");
      const button = Array.from(doc.querySelectorAll("a")).find(a => a.textContent?.trim() === "Получить код");
      if (button) button.textContent = "Войти";
      const hint = Array.from(doc.querySelectorAll("p")).find(p => p.textContent?.includes("СМС"));
      if (hint) hint.textContent = "Вход по номеру телефона клиента банка. SMS не требуется.";
    } else { inputs[0]?.setAttribute("autocomplete", "username"); inputs[1]?.setAttribute("autocomplete", "current-password"); inputs[1]?.setAttribute("type", "password"); }
    return doc.body.innerHTML + Array.from(doc.head.querySelectorAll("style")).map(s => s.outerHTML).join("");
  }

  if (employee) {
    const tbody = doc.querySelector("table tbody");
    if (tbody) {
      const count = doc.querySelectorAll("table thead th").length;
      const original = tbody.querySelector("tr"); tbody.replaceChildren();
      for (const row of tabRows(name, bank.applications)) {
        const tr = original ? original.cloneNode(true) as HTMLTableRowElement : doc.createElement("tr");
        tr.style.background = row.id === app.id ? "#f3f4f5" : "transparent";
        tr.replaceChildren(); tr.dataset.applicationId = str(row.id); tr.style.cursor = "pointer";
        const values = name.startsWith("AD_")
          ? [row.number, row.company_name, money(row.requested_amount), statusLabel(row.status), row.risk_zone, row.assignee_id === bank.user?.id ? "Вы" : "—"]
          : name.startsWith("A_")
            ? [row.number, row.company_name, money(row.requested_amount), row.risk_zone, statusLabel(row.status)]
            : [row.number, row.company_name, money(row.requested_amount), row.risk_zone, statusLabel(row.status), row.assignee_id === bank.user?.id ? "Вы" : "—"];
        values.forEach((value, index) => {
          const td = doc.createElement("td"); td.style.padding = "12px 8px";
          if (["green", "yellow", "red"].includes(str(value))) {
            const chip = doc.createElement("span"); chip.className = `chip ${value === "green" ? "ok" : value === "red" ? "er" : "wr"}`;
            chip.textContent = ({ green: "Зелёная", yellow: "Жёлтая", red: "Красная" }[str(value)] ?? str(value)); td.append(chip);
          } else td.textContent = str(value);
          if (index === 0) td.style.fontWeight = "600"; tr.append(td);
        });
        tbody.append(tr);
      }
      if (!tbody.children.length) { const tr = doc.createElement("tr"); const td = doc.createElement("td"); td.colSpan = count; td.style.padding = "20px 8px"; td.textContent = "Заявок нет"; tr.append(td); tbody.append(tr); }
    }
    doc.querySelectorAll("a").forEach(a => { const text = a.textContent ?? ""; if (/\(\d+\)/.test(text)) {
      const target = a.dataset.screen ?? "";
      const count = tabRows(target || name, bank.applications).length;
      a.textContent = text.replace(/\(\d+\)/, `(${count})`);
    } });
  }

  const loan = bank.contract ?? bank.loans[0] ?? {};
  const offer = bank.offer ?? {};
  const scoring = object(detail.scoring);
  const estimatedRate = object(detail.credit_memo).recommended_rate ?? object(detail.pre_approval).estimated_rate ?? bank.products.find(p => p.id === app.product_id)?.base_rate;
  const displayedOffer = !employee && /HomeCounter|HomeOffer\./.test(name);
  if (employee) doc.querySelectorAll("aside.b h2, section.b > h2").forEach(h => { if (/^(ИП|ООО)/.test(h.textContent?.trim() ?? "")) h.textContent = str(companyName); });
  if (employee) {
    const badges = name.startsWith("AD_Detail") ? doc.querySelectorAll("span.chip") : doc.querySelectorAll("aside.b > div > span.chip");
    badges.forEach(badge => { badge.textContent = app.id ? statusLabel(app.status) : "Нет заявки"; badge.className = `chip ${app.status === "completed" ? "ok" : app.status === "closed" ? "er" : "wr"}`; });
  }
  if (employee) doc.querySelectorAll("p").forEach(p => {
    if (p.textContent?.startsWith("AI Credit Memo:")) p.textContent = str(object(detail.credit_memo).summary ?? "Кредитное заключение пока не сформировано");
    if (p.textContent?.startsWith("Рекомендация:")) p.textContent = `${str(object(detail.credit_memo).analyst_recommendation)}. ${str(object(detail.credit_memo).analyst_conclusion)}`;
  });
  const fields: Record<string, unknown> = {
    "Сумма": money((displayedOffer ? offer.approved_amount : app.requested_amount) ?? bank.draft.amount), "Сумма кредита": money(loan.principal_amount),
    "Срок": `${str((displayedOffer ? offer.approved_term_months : app.requested_term_months) ?? bank.draft.term)} мес.`, "Ставка": offer.interest_rate ? `${offer.interest_rate}% годовых` : loan.interest_rate ? `${loan.interest_rate}% годовых` : estimatedRate ? `${estimatedRate}% годовых` : "—",
    "Ежемесячный платёж": money(offer.estimated_monthly_payment ?? loan.monthly_payment),
    "Остаток долга": money(loan.outstanding_balance), "Ближайший платёж": object(loan.next_payment).total_amount ? `${money(object(loan.next_payment).total_amount)} · ${date(object(loan.next_payment).due_date)}` : "—",
    "Полное наименование": company.full_name ?? company.name, "Организационно-правовая форма": legalForms[str(company.legal_form)] ?? company.legal_form, "ИНН": company.inn, "КПП": company.kpp ?? "—", "ОГРН / ОГРНИП": company.ogrn,
    "Дата регистрации": date(company.registration_date), "Основной ОКВЭД": company.okved_name ? `${str(company.okved_main)} · ${str(company.okved_name)}` : company.okved_main, "Система налогообложения": taxSystems[str(company.tax_system)] ?? company.tax_system ?? "—", "Регион ведения бизнеса": company.region, "Число сотрудников": company.employees_count, "Юридический адрес": company.legal_address,
    "Руководитель": object(company.head).full_name ?? "—", "Должность": object(company.head).position ?? "—",
    "Бенефициарные владельцы": list(company.owners).filter(o => o.is_beneficiary).map(o => o.share_percent ? `${str(o.full_name)}, ${Number(o.share_percent)}%` : str(o.full_name)).join("; ") || "—",
    "Право подписи": list(company.signatories).map(str).join(", ") || "—", "Телефон": company.phone ?? "—", "Электронная почта": company.email ?? "—",
    "Расчётный счёт": object(company.settlement_account).account_number ? `${str(object(company.settlement_account).account_number)} · ${str(object(company.settlement_account).bank_name)}` : "—",
    "DSCR": scoring.dscr, "Debt Burden (аналитический)": scoring.debt_burden ? `${(Number(scoring.debt_burden) * 100).toFixed(2)}%` : "—", "LTV": scoring.ltv === undefined || scoring.ltv === null ? "—" : `${(Number(scoring.ltv) * 100).toFixed(2)}%`,
    "Риск-грейд": scoring.risk_grade, "Уверенность модели": scoring.confidence !== undefined ? `${Number(scoring.confidence) * 100}%` : "—",
    "Стоп-факторы": list(scoring.stop_factors).map(f => str(f.description)).join(", ") || "—",
    "Счёт зачисления": loan.settlement_account_number, "Дата окончания": date(loan.maturity_date),
    "Обеспечение": list(offer.conditions).map(c => str(c.description)).join(", ") || (app.has_collateral ? app.collateral_description : "Без залога"),
    "Договор": loan.contract_number ? `${loan.contract_number} · ${statusLabel(loan.status)}` : "—",
    "Маршрут": statusLabel(scoring.risk_zone),
    "Решение андеррайтера": offer.decision_type ? `${statusLabel(offer.decision_type)} · ${date(offer.created_at)}` : "—",
    "Финальный оффер": offer.client_response ? `${statusLabel(offer.client_response)} · ${date(offer.client_responded_at)}` : "—",
    "ИИ-оффер": object(detail.credit_memo).recommended_amount ? `${money(object(detail.credit_memo).recommended_amount)} · ${str(object(detail.credit_memo).recommended_term_months)} мес. · ${str(object(detail.credit_memo).recommended_rate)}%` : "—",
  };
  for (const label of Array.from(doc.querySelectorAll(".t"))) {
    const key = label.textContent?.trim() ?? "";
    if (Object.prototype.hasOwnProperty.call(fields, key) && label.nextElementSibling) label.nextElementSibling.textContent = str(fields[key]);
  }

  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT);
  const texts: Text[] = []; let node; while ((node = walker.nextNode())) if (node.parentElement?.tagName !== "STYLE") texts.push(node as Text);
  // На экранах кредита и графика - условия договора: после контр-предложения они отличаются от заявки
  const loanTerms = (name.includes("Credits") || name.includes("Schedule")) && loan.term_months !== undefined;
  for (const text of texts) {
    let value = text.textContent ?? "";
    value = value.replaceAll("ООО «Вектор»", str(companyName));
    value = value.replace(/\[ФИО сотрудника\]/g, str(bank.user?.full_name));
    value = value.replace(/ММБ-2026-000(?:123|130)/g, str(app.number));
    value = value.replace(/№\[номер\]/g, `№${str(app.number)}`);
    value = value.replace(/3 000 000 ₽/g, money(loanTerms ? loan.principal_amount : app.requested_amount ?? bank.draft.amount));
    value = value.replace(/24 месяца/g, `${str(loanTerms ? loan.term_months : app.requested_term_months ?? bank.draft.term)} мес.`);
    const expertise = list(detail.internal_requests).filter(r => ["open", "accepted"].includes(str(r.status))).at(-1);
    const info = list(detail.info_requests).filter(r => r.status === "open").at(-1);
    if (expertise) value = value.replace(/\[(Текст вопроса для экспертизы|текст вопроса)\]/g, str(expertise.message));
    if (info) value = value.replace("[перечень документов]", str(info.message));
    value = value.replace(/\[[^\]]+\]/g, "—");
    text.textContent = value;
  }

  if (!employee) {
    doc.querySelectorAll("p").forEach(p => { if (/^Причин[аы]:/.test(p.textContent?.trim() ?? "")) p.textContent = list(app.decline_reasons).map(r => r.advice ? `${str(r.message)}. ${str(r.advice)}` : str(r.message)).join("; ") || list(offer.reasons).map(r => str(r.message)).join("; ") || str(app.status_description); });
    const chips = doc.querySelectorAll("main > section > div > .chip, main > section > .chip");
    chips.forEach(chip => { chip.textContent = str(app.status_description ?? statusLabel(app.status)); });
    if (name.includes("Chat") && !name.includes("ChatEdit")) {
      const section = doc.querySelector("main > section");
      if (section) {
        for (const child of Array.from(section.children)) {
          const parameters = child.querySelector('a[data-screen*="ChatSubmitted"]') || child.textContent?.includes("Параметры заявки");
          if (child.tagName === "DIV" && !parameters && !child.querySelector('input[aria-label="Сообщение"]')) child.remove();
          if (parameters) for (const text of Array.from(child.childNodes)) if (text.nodeType === Node.TEXT_NODE && text.textContent?.trim()) text.textContent = "Параметры заявки:";
        }
        // История диалога с ИИ-агентом из API
        const bubbles = bank.chat.length ? bank.chat : [{ sender_type: "ai_agent", content: "Здравствуйте! Подберу кредит под ваш бизнес. Напишите, какая сумма и на какой срок нужна и на что пойдут средства." }];
        let anchor: Element | null = section.querySelector("h2");
        for (const item of bubbles) {
          const client = item.sender_type === "client";
          const bubble = doc.createElement("div");
          bubble.dataset.chatMessage = str(item.message_type ?? "text");
          bubble.style.cssText = client ? "align-self:flex-end;max-width:480px;background:#d92d20;color:#fff;border-radius:16px;padding:14px 16px;white-space:pre-line" : "max-width:560px;background:#f3f4f5;border-radius:16px;padding:14px 16px;white-space:pre-line";
          bubble.textContent = str(item.content);
          const fields = object(object(item.card_payload).fields);
          if (item.message_type === "confirmation_card") {
            const card = doc.createElement("div"); card.style.cssText = "margin-top:12px;background:#fff;color:#0b1f35;border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:8px";
            const rows: [string, unknown][] = [["Сумма", fields.amount ? money(fields.amount) : "—"], ["Срок", fields.term_months ? `${str(fields.term_months)} мес.` : "—"], ["Цель", fields.purpose_label ?? "—"], ["Залог", fields.collateral_label ?? "—"], ["Продукт", fields.product_name ?? "—"]];
            for (const [label, value] of rows) {
              const row = doc.createElement("div"); row.style.cssText = "display:flex;justify-content:space-between;gap:16px";
              const caption = doc.createElement("span"); caption.style.color = "#5c6b7a"; caption.textContent = label;
              const strong = doc.createElement("b"); strong.textContent = str(value); row.append(caption, strong); card.append(row);
            }
            bubble.append(card);
          }
          anchor?.after(bubble); anchor = bubble;
        }
        if (app.id && Array.isArray(app.available_actions) && app.available_actions.includes("upload_documents")) {
          const upload = doc.createElement("label"); upload.style.cssText = "border:1px dashed #5c6b7a;border-radius:12px;padding:16px;cursor:pointer";
          upload.textContent = "Выбрать документ для заявки";
          const input = doc.createElement("input"); input.type = "file"; input.hidden = true; input.dataset.upload = "true"; input.accept = ".pdf,.xlsx,.xls,.csv,.png,.jpg,.jpeg";
          upload.append(input); section.append(upload);
        }
      }
    }
    if (name.includes("ChatEdit")) {
      const values = [bank.draft.amount, String(bank.draft.term), bank.draft.purpose, bank.draft.collateral];
      doc.querySelectorAll("input").forEach((input, i) => { if (values[i] !== undefined) input.setAttribute("value", values[i]); });
    }
  }

  if (name.includes("Docs")) {
    const tbody = doc.querySelector("table tbody");
    if (tbody) {
      tbody.replaceChildren();
      for (const file of bank.documents) {
        const tr = doc.createElement("tr"); tr.style.borderTop = "1px solid #eceef0";
        for (const value of [file.file_name, date(file.created_at), "Загружен"]) { const td = doc.createElement("td"); td.style.padding = "16px 8px"; td.textContent = str(value); tr.append(td); }
        const td = doc.createElement("td"); const link = doc.createElement("a"); link.className = "bs"; link.textContent = "Скачать"; link.href = `/api/backend/applications/${app.id}/documents/${file.id}/content`; link.download = str(file.file_name); td.append(link); tr.append(td); tbody.append(tr);
      }
      if (!tbody.children.length) { const tr = doc.createElement("tr"); const td = doc.createElement("td"); td.colSpan = 4; td.style.padding = "16px 8px"; td.textContent = bank.warnings.length ? "Документы недоступны: backend ещё не реализовал этот метод" : "Документов нет"; tr.append(td); tbody.append(tr); }
    }
  }

  if (name.includes("Schedule")) {
    const tbody = doc.querySelector("table tbody");
    if (tbody) {
      tbody.replaceChildren();
      for (const payment of list(loan.schedule)) {
        const tr = doc.createElement("tr");
        for (const value of [payment.installment_no, date(payment.due_date), money(payment.total_amount), money(payment.principal_amount), money(payment.interest_amount), money(payment.balance_after)]) { const td = doc.createElement("td"); td.style.padding = "10px 8px"; td.textContent = str(value); tr.append(td); }
        tbody.append(tr);
      }
    }
    // В макете три строки, в реальном графике до 120: окно не выше экрана, прокручивается только таблица
    const dialog = doc.querySelector<HTMLElement>('[role="dialog"]');
    const table = dialog?.querySelector("table");
    if (dialog?.parentElement && table) {
      Object.assign(dialog.parentElement.style, { position: "fixed", zIndex: "10", padding: "24px" });
      Object.assign(dialog.style, { maxHeight: "calc(100vh - 48px)", maxWidth: "100%", boxSizing: "border-box" });
      const scroll = doc.createElement("div");
      Object.assign(scroll.style, { overflowY: "auto", minHeight: "0", flex: "1 1 auto" });
      table.replaceWith(scroll);
      scroll.append(table);
      table.querySelectorAll<HTMLElement>("thead th").forEach(th => Object.assign(th.style, { position: "sticky", top: "0", background: "#fff" }));
    }
  }

  if (name.startsWith("AD_Detail")) {
    const heading = Array.from(doc.querySelectorAll("h2, h3")).find(h => h.textContent?.trim() === "Журнал действий");
    const journal = heading?.parentElement;
    if (journal && heading) {
      journal.replaceChildren(heading);
      for (const entry of list(detail.history)) {
        const block = doc.createElement("div"); block.style.cssText = "background:#f3f4f5;border-radius:12px;padding:12px;margin-top:8px";
        const actor: Record<string, string> = { client: "Клиент", system: "Система", credit_analyst: "Кредитный аналитик", underwriter: "Андеррайтер" };
        const time = entry.created_at ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Moscow" }).format(new Date(str(entry.created_at))) : "—";
        const meta = doc.createElement("p"); meta.className = "t"; meta.textContent = `${time} · ${actor[str(entry.actor_type)] ?? str(entry.actor_type)}`;
        const text = doc.createElement("p"); text.textContent = str(entry.comment || statusLabel(entry.to_status)); block.append(meta, text); journal.append(block);
      }
    }
  }

  const employeeInputs = doc.querySelectorAll<HTMLInputElement>('input:not([type="radio"]):not([type="checkbox"])');
  if (employee && (name.includes("Approve") || name.includes("Counter"))) {
    const memo = object(detail.credit_memo);
    const values = [name.includes("Counter") ? memo.recommended_amount ?? app.requested_amount : app.requested_amount, name.includes("Counter") ? memo.recommended_term_months ?? app.requested_term_months : app.requested_term_months, estimatedRate, list(memo.recommended_conditions).map(c => str(c.description)).join(", ")];
    employeeInputs.forEach((input, i) => { if (i < values.length) input.setAttribute("value", values[i] === null || values[i] === undefined ? "" : str(values[i])); });
  }
  const allowed = Array.isArray(app.available_actions) ? app.available_actions : [];
  const clientActions: Record<string, string> = { "Принять оффер": "accept_offer", "Отклонить оффер": "reject_offer", "Подписать": "sign" };
  const employeeCommands = ["Одобрить", "Одобрить с изменениями", "Отказать", "Запросить документы у клиента", "Запросить экспертизу у аналитика", "Отправить заключение андеррайтеру", "Подтвердить одобрение", "Отправить контр-предложение", "Подтвердить отказ", "Отправить андеррайтеру"];
  doc.querySelectorAll("a, button").forEach(control => {
    const text = control.textContent?.trim() ?? "";
    const assignee = detail.assignee_id;
    const actor = !assignee || assignee === bank.user?.id;
    const employeeAllowed = actor && (bank.user?.role === "underwriter" ? app.status === "underwriter_review" : bank.user?.role === "credit_analyst" && app.status === "analyst_escalation");
    if ((!employee && clientActions[text] && !allowed.includes(clientActions[text])) || (employee && employeeCommands.includes(text) && !employeeAllowed)) {
      control.setAttribute("aria-disabled", "true");
      (control as HTMLElement).style.opacity = "0.5"; (control as HTMLElement).style.cursor = "not-allowed";
      control.setAttribute("title", "Действие недоступно на текущем этапе заявки");
    }
  });
  return doc.body.innerHTML + Array.from(doc.head.querySelectorAll("style")).map(s => s.outerHTML).join("");
}
