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
Object.assign(statuses, { data_collection: "Сбор данных", submitted: "Заявка отправлена", ai_verification: "Проверка документов", ai_financial_analysis: "Финансовый анализ", ai_risk_scoring: "Оценка риска", decision_routing: "Маршрутизация заявки", offer_accepted: "Оффер принят", offer_rejected: "Оффер отклонён", contract_generation: "Подготовка договора", approved: "Одобрено", conditional_approval: "Одобрено с изменениями", declined: "Отказано", more_information_required: "Запрошены данные", approve: "одобрить", counter_offer: "контр-предложение", decline: "отказать", request_more_info: "запросить данные", accepted: "Принят", rejected: "Отклонён", active: "Действует", green: "Зелёная зона", yellow: "Жёлтая зона", red: "Красная зона" });
const legalForms: Record<string, string> = { ooo: "ООО", ip: "ИП" };
const taxSystems: Record<string, string> = { usn_income: "УСН «Доходы»", usn_income_expense: "УСН «Доходы минус расходы»", osno: "ОСНО", psn: "Патент", eshn: "ЕСХН" };
const DOCUMENT_LABELS: Record<string, string> = { bank_statement: "Выписка по расчётному счёту за 12 месяцев", tax_return: "Налоговая декларация", kudir: "КУДИР", financial_statement: "Бухгалтерская отчётность", management_report: "Управленческая отчётность", contract: "Договор с контрагентом", egrn_extract: "Выписка из ЕГРН на залог", vehicle_passport: "ПТС транспортного средства", equipment_documents: "Документы на оборудование", appraisal_report: "Отчёт об оценке залога", credit_agreement: "Кредитный договор", other: "Другой документ" };
export const statusLabel = (value: unknown) => statuses[str(value)] ?? str(value);
const terminal = (a: ObjectData) => ["closed", "completed"].includes(str(a.status));

function tabRows(name: string, rows: ObjectData[], userId?: unknown) {
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
  // «Мои» - назначенные на меня и те, с которыми я уже работал (общая очередь этапа - во «Все»)
  if (name === "U_Mine.dc.html") return rows.filter(a => a.assignee_id === userId || a.status !== "underwriter_review");
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
      for (const row of tabRows(name, bank.applications, bank.user?.id)) {
        const tr = original ? original.cloneNode(true) as HTMLTableRowElement : doc.createElement("tr");
        tr.style.background = row.id === app.id ? "#f3f4f5" : "transparent";
        tr.replaceChildren(); tr.dataset.applicationId = str(row.id); tr.style.cursor = "pointer";
        const values = name.startsWith("AD_")
          ? [row.number, row.company_name, money(row.requested_amount), statusLabel(row.status), row.risk_zone, row.assignee_id === bank.user?.id ? "Вы" : str(row.assignee_name ?? "—")]
          : name.startsWith("A_")
            ? [row.number, row.company_name, money(row.requested_amount), row.risk_zone, statusLabel(row.status)]
            : [row.number, row.company_name, money(row.requested_amount), row.risk_zone, statusLabel(row.status), row.assignee_id === bank.user?.id ? "Вы" : str(row.assignee_name ?? "—")];
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
    if (p.textContent?.startsWith("Рекомендация:")) p.textContent = object(detail.credit_memo).analyst_conclusion ? `Рекомендация: ${statusLabel(object(detail.credit_memo).analyst_recommendation)}. ${str(object(detail.credit_memo).analyst_conclusion)}` : "Заключения аналитика нет: заявка пришла к андеррайтеру напрямую";
  });
  const fields: Record<string, unknown> = {
    "Сумма": money((displayedOffer ? offer.approved_amount : app.requested_amount) ?? bank.draft.amount), "Сумма кредита": money(loan.principal_amount),
    "Срок": `${str((displayedOffer ? offer.approved_term_months : app.requested_term_months) ?? bank.draft.term)} мес.`, "Ставка": [offer.interest_rate, loan.interest_rate, estimatedRate].find(v => v !== undefined && v !== null) !== undefined ? `${Number([offer.interest_rate, loan.interest_rate, estimatedRate].find(v => v !== undefined && v !== null)).toFixed(2).replace(".", ",")}% годовых` : "—",
    "Ежемесячный платёж": money(offer.estimated_monthly_payment ?? loan.monthly_payment),
    "Остаток долга": money(loan.outstanding_balance), "Ближайший платёж": object(loan.next_payment).total_amount ? `${money(object(loan.next_payment).total_amount)} · ${date(object(loan.next_payment).due_date)}` : "—",
    "Полное наименование": company.full_name ?? company.name, "Организационно-правовая форма": legalForms[str(company.legal_form)] ?? company.legal_form, "ИНН": company.inn, "КПП": company.kpp ?? "—", "ОГРН / ОГРНИП": company.ogrn,
    "Дата регистрации": date(company.registration_date), "Основной ОКВЭД": company.okved_name ? `${str(company.okved_main)} · ${str(company.okved_name)}` : company.okved_main, "Система налогообложения": taxSystems[str(company.tax_system)] ?? company.tax_system ?? "—", "Регион ведения бизнеса": company.region, "Число сотрудников": company.employees_count, "Юридический адрес": company.legal_address,
    "Руководитель": object(company.head).full_name ?? "—", "Должность": object(company.head).position ?? "—",
    "Бенефициарные владельцы": list(company.owners).filter(o => o.is_beneficiary).map(o => o.share_percent ? `${str(o.full_name)}, ${Number(o.share_percent)}%` : str(o.full_name)).join("; ") || "—",
    "Право подписи": (Array.isArray(company.signatories) ? company.signatories.map(String) : []).join(", ") || "—", "Телефон": company.phone ?? "—", "Электронная почта": company.email ?? "—",
    // Экран выдачи - счёт зачисления по договору, профиль компании - расчётный счёт компании
    "Расчётный счёт": loan.settlement_account_number && name.includes("_Home") ? loan.settlement_account_number : object(company.settlement_account).account_number ? `${str(object(company.settlement_account).account_number)} · ${str(object(company.settlement_account).bank_name)}` : "—",
    "Сумма зачисления": money(loan.principal_amount),
    "Тип платежа": loan.contract_number ? "Аннуитетный, ежемесячно" : "—",
    // Досрочного погашения в прототипе нет - не обещаем условий, которых нет
    "Досрочное погашение": loan.contract_number ? "Не поддерживается в прототипе" : "—",
    "Дата и время": loan.disbursed_at ? new Date(String(loan.disbursed_at)).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—",
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
    if (loan.contract_number) {
      const loanApp = bank.applications.find(a => a.id === loan.application_id);
      const productName = bank.products.find(p => p.id === (loanApp ?? app).product_id)?.name;
      value = value.replace("Кредит на развитие", str(productName ?? "Кредит")).replace("[номер договора]", str(loan.contract_number)).replace("[дата выдачи]", date(loan.disbursed_at));
    }
    value = value.replace(/\[[^\]]+\]/g, "—");
    text.textContent = value;
  }

  // Блок «Параметры заявки» в чате: заявка в работе - её условия («Подтверждено вами»),
  // иначе - черновик, который заполняет карточка ИИ-агента и подтверждает клиент
  if (!employee && name.includes("Chat") && !name.includes("ChatEdit")) {
    // Блок с параметрами - сообщение макета со строкой «Сумма» (до вставки истории чата)
    const block = Array.from(doc.querySelectorAll("main > section > div")).find(div => Array.from(div.querySelectorAll("span.t")).some(label => label.textContent?.trim() === "Сумма"));
    if (block) {
      const inWork = !!app.id && !["draft", "pre_approved", "completed", "closed"].includes(str(app.status));
      const purposes: Record<string, string> = { working_capital: "Пополнение оборотных средств", equipment: "Покупка оборудования", business_expansion: "Развитие бизнеса", refinancing: "Рефинансирование", other: "Другая цель" };
      const values: Record<string, string> = inWork
        ? { "Сумма": money(app.requested_amount), "Срок": `${str(app.requested_term_months)} мес.`, "Цель": purposes[str(app.purpose)] ?? str(app.purpose), "Залог": app.has_collateral ? "С залогом" : "Без залога" }
        : { "Сумма": money(bank.draft.amount), "Срок": `${bank.draft.term} мес.`, "Цель": bank.draft.purpose, "Залог": bank.draft.collateral };
      for (const label of Array.from(block.querySelectorAll(".t"))) {
        const key = label.textContent?.trim() ?? "";
        if (key in values && label.nextElementSibling) label.nextElementSibling.textContent = values[key];
        if (key === "Подтверждено вами" && !inWork) label.textContent = "Проверьте параметры и нажмите «Подтвердить и отправить заявку»";
      }
      // В вариантах экрана после подачи кнопки нет - для нового черновика она нужна
      if (!inWork && !Array.from(block.querySelectorAll("a, button")).some(el => el.textContent?.trim() === "Подтвердить и отправить заявку")) {
        const confirm = doc.createElement("button"); confirm.className = "bt"; confirm.style.cssText = "align-self:flex-start;margin-top:8px"; confirm.textContent = "Подтвердить и отправить заявку";
        (block.querySelector("div") ?? block).append(confirm);
      }
    }
  }

  // Выход для клиента: в макетах клиента кнопки нет, у сотрудников она в шапке
  const nav = doc.querySelector("aside.nav");
  if (!employee && nav && bank.user) {
    const footer = doc.createElement("div"); footer.style.cssText = "margin-top:24px;padding:16px;border-top:1px solid #eceef0;display:flex;flex-direction:column;gap:8px";
    const who = doc.createElement("p"); who.className = "t"; who.textContent = `${str(bank.user.full_name)} · ${str(companyName)}`;
    const logout = doc.createElement("a"); logout.href = "#"; logout.textContent = "Выйти"; logout.style.cssText = "color:#d92d20;font-weight:600;text-decoration:none;padding:0";
    footer.append(who, logout); nav.append(footer);
  }

  // Панель «Статус заявки» в чате: реальный этап выбранной заявки, без заявки - черновик
  if (!employee && name.includes("Chat")) {
    const panel = Array.from(doc.querySelectorAll("aside")).find(aside => aside.querySelector("h3")?.textContent?.includes("Статус заявки"));
    if (panel) {
      const status = str(app.status);
      const current: Record<string, number> = {
        submitted: 2, ai_verification: 2, need_additional_data: 2,
        ai_risk_scoring: 3, decision_routing: 3, ai_financial_analysis: 3, analyst_escalation: 3, analyst_completed: 3, underwriter_review: 3,
        offer_generated: 4, offer_accepted: 5, contract_generation: 5, e_sign: 5, disbursement: 6, completed: 7,
      };
      // Закрытая заявка: на каком этапе остановилась
      const stopped: Record<string, number> = { auto_declined: 3, underwriter_declined: 3, offer_rejected: 4 };
      const closed = status === "closed";
      const step = closed ? stopped[str(app.close_reason)] ?? 0 : current[status] ?? 0;
      const chips: Record<string, [string, string]> = {
        created: ["Заявка отправлена", "wr"], under_review: ["Заявка на рассмотрении", "wr"], documents_required: ["Нужны документы", "er"],
        approved: ["Одобрено", "ok"], counter_offer: ["Контр-предложение", "wr"], signed: ["Договор подписан", "ok"], disbursed: ["Кредит выдан", "ok"], closed: ["Заявка закрыта", "er"],
      };
      const [chipText, chipKind] = app.id ? chips[str(app.client_status)] ?? ["Заявка не отправлена", "in"] : ["Заявка не отправлена", "in"];
      const chip = panel.querySelector("span.chip");
      if (chip) { chip.textContent = chipText; chip.className = `chip ${chipKind}`; }
      const terms = panel.querySelector(":scope > p.t");
      if (terms) terms.textContent = app.id ? `${money(app.requested_amount)} · ${str(app.requested_term_months)} мес.` : `${money(bank.draft.amount)} · ${bank.draft.term} мес.`;
      Array.from(panel.querySelectorAll(":scope > div > p")).forEach((row, index) => {
        const no = index + 1; const dot = row.querySelector("span") as HTMLElement | null;
        const done = no < step || step === 7; const active = no === step && step !== 7;
        row.className = done || active ? "" : "t"; (row as HTMLElement).style.fontWeight = active ? "700" : "";
        if (dot) dot.style.background = active ? (closed ? "#d92d20" : "#f5b800") : done ? "#0a6b3a" : "#d5d9de";
      });
    }
  }

  // «Детали заявки»: окно на любом экране заявки клиента (в макете есть только после оффера)
  if (!employee && name.includes("_Home") && app.id) {
    const purposes: Record<string, string> = { working_capital: "Пополнение оборотных средств", equipment: "Покупка оборудования", business_expansion: "Развитие бизнеса", refinancing: "Рефинансирование", other: "Другая цель" };
    const decided = ["approved", "conditional_approval"].includes(str(offer.decision_type));
    const rateText = (value: unknown) => `${Number(value).toFixed(2).replace(".", ",")}% годовых`;
    const payment = offer.estimated_monthly_payment ?? bank.contract?.monthly_payment;
    const decision = decided ? statusLabel(offer.decision_type)
      : app.close_reason === "auto_declined" || app.close_reason === "underwriter_declined" ? "Отказано"
      : app.status === "closed" ? "Заявка закрыта" : "Ещё не принято";
    const offerState = offer.client_response === "accepted" ? "Принят вами" : offer.client_response === "rejected" ? "Отклонён вами"
      : app.status === "offer_generated" ? "Ожидает вашего ответа" : "—";
    const documents = bank.documents.map(d => str(d.file_name));
    const details: [string, string][] = [
      ["Статус", str(app.status_description ?? statusLabel(app.status))],
      ["Дата подачи", date(app.submitted_at)],
      ["Сумма", money(decided ? offer.approved_amount : app.requested_amount)],
      ["Срок", `${str(decided ? offer.approved_term_months : app.requested_term_months)} мес.`],
      ["Цель", purposes[str(app.purpose)] ?? str(app.purpose)],
      ["Обеспечение", app.has_collateral ? str(app.collateral_description ?? "Залог") : list(offer.conditions).map(c => str(c.description)).join(", ") || "Без залога"],
      ["Ставка по офферу", decided ? rateText(offer.interest_rate) : "Появится после решения банка"],
      ["Ориентировочный платёж", payment ? `${money(payment)} в месяц` : "—"],
      ["Решение банка", decision],
      ["Оффер", offerState],
      ["Поданные документы", documents.join(", ") || "Не загружались"],
      ["Способ подписания", bank.contract?.signed_at ? `Электронная подпись, ${date(bank.contract.signed_at)}` : "Электронная подпись (код подтверждения)"],
    ];
    const fill = (grid: Element) => {
      grid.replaceChildren();
      for (const [label, value] of details) {
        const cell = doc.createElement("div"); const caption = doc.createElement("p"); caption.className = "t"; caption.textContent = label;
        const text = doc.createElement("p"); text.style.cssText = "font-weight:600;margin-top:2px"; text.textContent = value; cell.append(caption, text); grid.append(cell);
      }
    };
    const existing = doc.querySelector('[role="dialog"][aria-label="Детали заявки"]');
    if (existing) { const grid = existing.querySelector("div[style*='grid']"); if (grid) fill(grid); }
    else if (bank.detailsOpen) {
      const overlay = doc.createElement("div"); overlay.style.cssText = "position:fixed;inset:0;background:rgba(11,31,53,.55);display:flex;align-items:center;justify-content:center;z-index:50";
      const dialog = doc.createElement("div"); dialog.setAttribute("role", "dialog"); dialog.setAttribute("aria-label", "Детали заявки"); dialog.style.cssText = "width:680px;max-width:calc(100vw - 32px);max-height:calc(100vh - 32px);overflow:auto;background:#fff;border-radius:20px;padding:32px;display:flex;flex-direction:column;gap:20px";
      const head = doc.createElement("div"); head.style.cssText = "display:flex;justify-content:space-between;align-items:center";
      const title = doc.createElement("h2"); title.style.fontSize = "22px"; title.textContent = `Детали заявки №${str(app.number)}`;
      const close = doc.createElement("button"); close.className = "bs"; close.textContent = "Закрыть"; close.dataset.closeDetails = "true";
      head.append(title, close);
      const grid = doc.createElement("div"); grid.style.cssText = "display:grid;grid-template-columns:repeat(2,1fr);gap:16px"; fill(grid);
      dialog.append(head, grid); overlay.append(dialog); doc.body.append(overlay);
    }
  }

  // Главная «Нужно загрузить документы»: что именно запросил банк и что уже загружено
  if (!employee && name.includes("MissingDocs") && !name.includes("Chat")) {
    const section = Array.from(doc.querySelectorAll("section")).find(s => s.querySelector("h2")?.textContent?.includes("Нужно загрузить документы"));
    const rows = section?.querySelector("div[style*='flex-direction:column']");
    if (rows) {
      rows.replaceChildren();
      for (const request of bank.requests.filter(r => r.status === "open")) {
        const types = list(request.requested_document_types).length ? (request.requested_document_types as string[]) : [];
        const items = types.length ? types : [""];
        for (const type of items) {
          const uploaded = type && bank.documents.some(d => d.type === type && (d.info_request_id === request.id || (!d.info_request_id && str(d.created_at) >= str(request.created_at))));
          const row = doc.createElement("div");
          row.style.cssText = `padding:12px 16px;border-radius:12px;font-weight:600;background:${uploaded ? "#e3f4ea" : "#fff6d6"}`;
          row.textContent = type ? `${DOCUMENT_LABELS[type] ?? type}${uploaded ? " - загружено" : ""}` : `Ответ на вопрос: ${str(request.message)}`;
          rows.append(row);
        }
      }
      if (!rows.children.length) { const row = doc.createElement("div"); row.className = "t"; row.textContent = "Запросов банка нет"; rows.append(row); }
    }
  }

  // Карточка заявки у администратора: заголовок, параметры, исполнитель, оценка и решения
  if (name.startsWith("AD_Detail") && app.id) {
    const staff = object(detail.staff);
    const scoring = object(detail.scoring);
    const decisions = list(detail.decisions);
    const offers = decisions.filter(d => ["approved", "conditional_approval"].includes(str(d.decision_type)));
    const purposes: Record<string, string> = { working_capital: "Пополнение оборотных средств", equipment: "Покупка оборудования", business_expansion: "Развитие бизнеса", refinancing: "Рефинансирование", other: "Другая цель" };
    // Текущий исполнитель; у завершённых - кто принял решение (андеррайтер) или писал заключение
    const decidedBy = decisions.at(-1)?.decided_by_id;
    const analystId = object(detail.credit_memo).analyst_id;
    const performer = detail.assignee_id ? str(staff[str(detail.assignee_id)] ?? "назначен")
      : decidedBy && staff[str(decidedBy)] ? `${str(staff[str(decidedBy)])} (андеррайтер)`
      : analystId && staff[str(analystId)] ? `${str(staff[str(analystId)])} (аналитик)` : "ИИ-агент";
    const title = doc.querySelector("h1");
    if (title) title.textContent = `Заявка ${str(app.number)} · ${str(company.name ?? companyName)}`;
    const values: Record<string, string> = {
      "Цель": purposes[str(app.purpose)] ?? str(app.purpose),
      "Обеспечение": app.has_collateral ? str(app.collateral_description ?? "Залог") : "Без залога",
      "Маршрут": app.close_reason === "auto_declined" ? "Автоотказ" : scoring.risk_zone ? statusLabel(scoring.risk_zone) : "Ещё не определён",
      "Исполнитель": performer,
      "Офферы": offers.length ? offers.map(d => `${money(d.approved_amount)} · ${str(d.approved_term_months)} мес. · ${Number(d.interest_rate).toFixed(2).replace(".", ",")}%`).join("; ") : "не формировались",
      "Договор": object(detail.contract).contract_number ? `${str(object(detail.contract).contract_number)} · ${statusLabel(object(detail.contract).status)}` : "нет",
      "DSCR": scoring.dscr !== undefined && scoring.dscr !== null ? Number(scoring.dscr).toFixed(2).replace(".", ",") : "—",
      "Debt Burden (аналитический)": scoring.debt_burden !== undefined && scoring.debt_burden !== null ? `${(Number(scoring.debt_burden) * 100).toFixed(2).replace(".", ",")} %` : "—",
      "LTV": scoring.ltv !== undefined && scoring.ltv !== null ? `${(Number(scoring.ltv) * 100).toFixed(2).replace(".", ",")} %` : "не применимо (без залога)",
      "Стоп-факторы": list(scoring.stop_factors).map(f => str(f.description)).join(", ") || (scoring.risk_zone ? "не сработали" : "—"),
      "ИИ-оффер": object(detail.credit_memo).recommended_amount ? `${money(object(detail.credit_memo).recommended_amount)} · ${str(object(detail.credit_memo).recommended_term_months)} мес. · ${Number(object(detail.credit_memo).recommended_rate).toFixed(2).replace(".", ",")}%` : "не формировался",
    };
    for (const label of Array.from(doc.querySelectorAll("p.t"))) {
      const key = label.textContent?.trim() ?? "";
      if (key in values && label.nextElementSibling) label.nextElementSibling.textContent = values[key];
    }
    // Причины автоотказа - все сработавшие стоп-факторы, а не два поля макета
    const reasons = Array.from(doc.querySelectorAll("p.t")).find(p => p.textContent?.trim() === "Стоп-фактор 1")?.closest("div[style*='grid']");
    if (reasons) {
      reasons.replaceChildren();
      const factors = list(scoring.stop_factors);
      const items: [string, string][] = factors.length ? factors.map((f, i) => [`Стоп-фактор ${i + 1}`, str(f.description)]) : [["Стоп-факторы", "не сработали"]];
      items.push(["Офферы", values["Офферы"]], ["Договор", values["Договор"]]);
      for (const [label, value] of items) {
        const cell = doc.createElement("div"); const caption = doc.createElement("p"); caption.className = "t"; caption.textContent = label;
        const text = doc.createElement("p"); text.style.cssText = "font-weight:600;margin-top:2px"; text.textContent = value; cell.append(caption, text); reasons.append(cell);
      }
    }
  }

  // Запрос экспертизы: выбор аналитика из списка (с загрузкой) вместо поля макета
  if (name === "U_Expertise.dc.html") {
    const field = doc.querySelector<HTMLInputElement>("#c2");
    if (field) {
      const select = doc.createElement("select"); select.id = "c2"; select.dataset.analyst = "true";
      select.style.cssText = "width:100%;padding:12px;border:1px solid #d5d9de;border-radius:12px;font:inherit;background:#fff";
      const auto = doc.createElement("option"); auto.value = ""; auto.textContent = "Автоматически: прежний аналитик заявки или наименее загруженный"; select.append(auto);
      for (const analyst of bank.employees.filter(e => e.role === "credit_analyst")) {
        const option = doc.createElement("option"); option.value = str(analyst.id);
        option.textContent = `${str(analyst.full_name)} · в работе: ${str(analyst.active_applications)}`; select.append(option);
      }
      field.replaceWith(select);
    }
  }

  // Заявка этапа, назначенная коллеге: видна всей очереди, решение - после «Взять в работу»
  if (employee && app.id && detail.assignee_id && detail.assignee_id !== bank.user?.id) {
    const stage = bank.user?.role === "underwriter" ? "underwriter_review" : bank.user?.role === "credit_analyst" ? "analyst_escalation" : null;
    const card = doc.querySelector("aside.b");
    if (stage && app.status === stage && card) {
      const note = doc.createElement("p"); note.className = "t";
      note.textContent = `Исполнитель: ${str(object(detail.staff)[str(detail.assignee_id)] ?? "коллега")}. Чтобы принять решение, возьмите заявку себе.`;
      const take = doc.createElement("button"); take.className = "bt"; take.style.alignSelf = "flex-start"; take.textContent = "Взять в работу";
      const heading = card.querySelector(":scope > div");
      (heading ?? card.firstElementChild)?.after(note, take);
    }
  }

  // Карточка заявки у аналитика: зачем заявка пришла (запрос андеррайтера или причины ИИ),
  // параметры, оценка ИИ, AI Credit Memo и дозапросы - вместо заглушек макета
  if (name.startsWith("A_") && app.id) {
    const card = doc.querySelector("aside.b");
    const header = card?.firstElementChild;
    if (card && header) {
      for (const child of Array.from(card.children)) if (child !== header && !child.querySelector("a, button")) child.remove();
      const staff = object(detail.staff);
      const memo = object(detail.credit_memo);
      const scoring = object(detail.scoring);
      const pct = (value: unknown) => `${(Number(value) * 100).toFixed(0)}%`;
      const box = (title: string, lines: string[], tone = "#f3f4f5") => {
        const block = doc.createElement("div"); block.style.cssText = `background:${tone};border-radius:12px;padding:12px;display:flex;flex-direction:column;gap:4px`;
        const caption = doc.createElement("p"); caption.className = "t"; caption.textContent = title; block.append(caption);
        for (const line of lines) { const p = doc.createElement("p"); p.style.whiteSpace = "pre-line"; p.textContent = line; block.append(p); }
        return block;
      };
      const blocks: HTMLElement[] = [];
      const expertise = list(detail.internal_requests).filter(r => ["open", "accepted"].includes(str(r.status))).at(-1);
      if (expertise) {
        const state = expertise.status === "accepted" ? `в работе с ${date(expertise.accepted_at)}` : "ждёт принятия";
        blocks.push(box(`Запрос экспертизы от андеррайтера · ${str(staff[str(expertise.from_user_id)] ?? "андеррайтер")} · ${date(expertise.created_at)} · ${state}`, [str(expertise.message)], "#fff6d6"));
      }
      const reasons = list(scoring.escalation_reasons).map(r => `• ${str(r.description)}`);
      if (reasons.length) blocks.push(box(expertise ? "Основания эскалации от ИИ" : "Причина эскалации (ИИ)", reasons, expertise ? "#f3f4f5" : "#fff6d6"));
      const purposes: Record<string, string> = { working_capital: "пополнение оборотных средств", equipment: "покупка оборудования", business_expansion: "развитие бизнеса", refinancing: "рефинансирование", other: "другая цель" };
      blocks.push(box(`Заявка ${str(app.number)}`, [
        `${money(app.requested_amount)} на ${str(app.requested_term_months)} мес., ${purposes[str(app.purpose)] ?? str(app.purpose)}`,
        app.has_collateral ? `Залог: ${str(app.collateral_description ?? app.collateral_type)}, ${money(app.collateral_market_value)}` : "Без залога",
        `ИНН ${str(company.inn)}${company.registration_date ? ` · зарегистрирована ${date(company.registration_date)}` : ""}`,
      ]));
      if (scoring.risk_zone) blocks.push(box("Оценка ИИ", [
        `${statusLabel(scoring.risk_zone)} · Risk Grade ${str(scoring.risk_grade)} · балл ${str(scoring.score)} · уверенность ${pct(scoring.confidence)}`,
        `DSCR ${scoring.dscr ? Number(scoring.dscr).toFixed(2).replace(".", ",") : "—"} · Debt Burden ${scoring.debt_burden ? pct(scoring.debt_burden) : "—"} · LTV ${scoring.ltv ? pct(scoring.ltv) : "не применимо"}`,
        memo.recommended_amount ? `Рекомендация ИИ: ${statusLabel(memo.ai_recommendation)}, ${money(memo.recommended_amount)} на ${str(memo.recommended_term_months)} мес. под ${Number(memo.recommended_rate).toFixed(2).replace(".", ",")}%` : `Рекомендация ИИ: ${statusLabel(memo.ai_recommendation)}`,
      ]));
      if (memo.summary) {
        const summary = box("AI Credit Memo", [str(memo.summary)]);
        summary.style.maxHeight = "220px"; summary.style.overflowY = "auto"; blocks.push(summary);
      }
      const openRequests = list(detail.info_requests).filter(r => r.status === "open");
      if (openRequests.length) blocks.push(box("Ждём от клиента", openRequests.map(r => `• ${str(r.message)}`), "#fff6d6"));
      if (memo.analyst_conclusion) blocks.push(box(`Прежнее заключение аналитика · ${statusLabel(memo.analyst_recommendation)}`, [str(memo.analyst_conclusion)]));
      header.after(...blocks);
      // Запрос экспертизы, назначенный на меня и ещё не принятый, - принять в работу
      const actions = Array.from(card.children).find(child => child.querySelector("a, button"));
      if (expertise?.status === "open" && detail.assignee_id === bank.user?.id && actions && !Array.from(actions.querySelectorAll("a, button")).some(el => el.textContent?.trim() === "Принять в работу")) {
        const accept = doc.createElement("button"); accept.className = "bs"; accept.textContent = "Принять в работу"; actions.prepend(accept);
      }
    }
  }

  // Контр-предложение: «было» - условия заявки и ставка предварительного расчёта,
  // подсвечены только изменённые условия
  if (!employee && name.includes("HomeCounter") && offer.approved_amount) {
    const rate = (value: unknown) => value === undefined || value === null ? "—" : `${Number(value).toFixed(2).replace(".", ",")}% годовых`;
    const wasCollateral = app.has_collateral ? str(app.collateral_description ?? "Залог") : "Без залога";
    const tiles: Record<string, [string, string]> = {
      "Сумма": [money(offer.approved_amount), money(app.requested_amount)],
      "Срок": [`${str(offer.approved_term_months)} мес.`, `${str(app.requested_term_months)} мес.`],
      "Ставка": [rate(offer.interest_rate), rate(bank.preApproval?.estimated_rate ?? bank.products.find(p => p.id === app.product_id)?.base_rate)],
      "Обеспечение": [list(offer.conditions).map(c => str(c.description)).join(", ") || wasCollateral, wasCollateral],
    };
    const counter = Array.from(doc.querySelectorAll("section")).find(section => section.querySelector("h2")?.textContent?.includes("Контр-предложение"));
    for (const label of Array.from(counter?.querySelectorAll("p.t") ?? [])) {
      const tile = label.parentElement; const values = tiles[label.textContent?.trim() ?? ""];
      if (!tile || !values) continue;
      const [now, was] = values; const [, current, before] = Array.from(tile.children);
      if (current) current.textContent = now;
      if (before) before.textContent = `Было: ${was}`;
      if (now === was) { (tile as HTMLElement).style.background = "transparent"; before?.remove(); }
    }
  }

  if (!employee) {
    doc.querySelectorAll("p").forEach(p => { if (/^Причин[аы]:/.test(p.textContent?.trim() ?? "")) p.textContent = list(app.decline_reasons).map(r => r.advice ? `${str(r.message)}. ${str(r.advice)}` : str(r.message)).join("; ") || list(offer.reasons).map(r => str(r.message)).join("; ") || str(app.status_description); });
    const chips = doc.querySelectorAll("main > section > div > .chip, main > section > .chip");
    // В «Кредитах» - статус кредита (действует), на главной - описание этапа заявки
    chips.forEach(chip => { chip.textContent = name.includes("Credits") && loan.status ? statusLabel(loan.status) : str(app.status_description ?? statusLabel(app.status)); });
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
            const rows: [string, unknown][] = [["Сумма", fields.amount ? money(fields.amount) : "—"], ["Срок", fields.term_months ? `${str(fields.term_months)} мес.` : "—"], ["Цель", fields.purpose_label ?? "—"], ["Залог", fields.collateral_label ?? "Не указан"], ["Продукт", fields.product_name ?? "—"]];
            for (const [label, value] of rows) {
              const row = doc.createElement("div"); row.style.cssText = "display:flex;justify-content:space-between;gap:16px";
              const caption = doc.createElement("span"); caption.style.color = "#5c6b7a"; caption.textContent = label;
              const strong = doc.createElement("b"); strong.textContent = str(value); row.append(caption, strong); card.append(row);
            }
            bubble.append(card);
          }
          anchor?.after(bubble); anchor = bubble;
        }
        // После отказа - быстрые вопросы агенту (кнопки макета были внутри убранного сообщения)
        if (app.close_reason === "auto_declined" || app.close_reason === "underwriter_declined") {
          const quick = doc.createElement("div"); quick.style.cssText = "display:flex;gap:8px;flex-wrap:wrap";
          for (const label of ["Уточнить причину", "Что можно исправить"]) { const button = doc.createElement("button"); button.className = "bs"; button.textContent = label; quick.append(button); }
          anchor?.after(quick); anchor = quick;
        }
        // Запрос документов банка: по строке на каждый требуемый документ, загрузка с типом
        // и привязкой к запросу, затем один ответ банку
        const openRequests = bank.requests.filter(r => r.status === "open");
        if (openRequests.length) {
          const panel = doc.createElement("div"); panel.dataset.docRequests = "true";
          panel.style.cssText = "max-width:560px;background:#fff6d6;border-radius:16px;padding:14px 16px;display:flex;flex-direction:column;gap:10px";
          const heading = doc.createElement("p"); heading.style.fontWeight = "600"; heading.textContent = "Запрос банка"; panel.append(heading);
          for (const request of openRequests) {
            const message = doc.createElement("p"); message.className = "t"; message.textContent = str(request.message); panel.append(message);
            for (const type of list(request.requested_document_types).length ? (request.requested_document_types as string[]) : []) {
              const row = doc.createElement("div"); row.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:12px;background:#fff;border-radius:12px;padding:10px 12px";
              const title = doc.createElement("span"); title.textContent = DOCUMENT_LABELS[type] ?? type;
              const uploaded = bank.documents.filter(d => d.type === type && (d.info_request_id === request.id || (!d.info_request_id && str(d.created_at) >= str(request.created_at))));
              if (uploaded.length) {
                const done = doc.createElement("span"); done.style.cssText = "color:#0a6b3a;font-weight:600"; done.textContent = `✓ ${uploaded.map(d => str(d.file_name)).join(", ")}`; row.append(title, done);
              } else {
                const pick = doc.createElement("label"); pick.className = "bs"; pick.style.cssText = "cursor:pointer;padding:8px 14px"; pick.textContent = "Выбрать файл";
                const input = doc.createElement("input"); input.type = "file"; input.hidden = true; input.accept = ".pdf,.xlsx,.xls,.docx,.csv,.png,.jpg,.jpeg";
                input.dataset.upload = "true"; input.dataset.docType = type; input.dataset.requestId = str(request.id);
                pick.append(input); row.append(title, pick);
              }
              panel.append(row);
            }
            // Запрос без документов (пояснение) - по желанию можно приложить файл
            if (!list(request.requested_document_types).length) {
              const attached = bank.documents.filter(d => d.info_request_id === request.id);
              const row = doc.createElement("div"); row.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:12px;background:#fff;border-radius:12px;padding:10px 12px";
              const title = doc.createElement("span"); title.className = "t"; title.textContent = attached.length ? `Приложено: ${attached.map(d => str(d.file_name)).join(", ")}` : "Файл к ответу (необязательно)";
              const pick = doc.createElement("label"); pick.className = "bs"; pick.style.cssText = "cursor:pointer;padding:8px 14px"; pick.textContent = "Приложить файл";
              const input = doc.createElement("input"); input.type = "file"; input.hidden = true; input.accept = ".pdf,.xlsx,.xls,.docx,.csv,.png,.jpg,.jpeg";
              input.dataset.upload = "true"; input.dataset.docType = "other"; input.dataset.requestId = str(request.id);
              pick.append(input); row.append(title, pick); panel.append(row);
            }
          }
          // Ответ пишется здесь: поле сообщения чата отправляет вопрос агенту, а не ответ банку
          const answer = doc.createElement("textarea"); answer.dataset.answer = "true";
          answer.placeholder = "Ваш ответ банку: пояснение или комментарий к документам";
          answer.style.cssText = "width:100%;min-height:72px;padding:10px 12px;border:1px solid #d5d9de;border-radius:12px;font:inherit;background:#fff;box-sizing:border-box";
          const needsFiles = openRequests.some(r => list(r.requested_document_types).length);
          const send = doc.createElement("button"); send.className = "bt"; send.style.alignSelf = "flex-start"; send.textContent = needsFiles ? "Отправить документы банку" : "Отправить ответ банку";
          panel.append(answer, send);
          const inputRow = section.querySelector('input[aria-label="Сообщение"]')?.closest("div");
          if (inputRow && inputRow.parentElement === section) section.insertBefore(panel, inputRow); else section.append(panel);
        } else if (app.id && Array.isArray(app.available_actions) && app.available_actions.includes("upload_documents")) {
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
      // Договор и график из выгрузок backend - первыми строками
      if (bank.contract?.application_id) {
        const contractApp = str(bank.contract.application_id);
        const rows: [string, unknown, string, string][] = [
          [`Кредитный договор №${str(bank.contract.contract_number)}`, bank.contract.signed_at ?? bank.contract.created_at, bank.contract.signed_at ? "Подписан" : "Проект", "document"],
          ["График платежей (XLSX)", bank.contract.signed_at ?? bank.contract.created_at, "Действует", "schedule-export?format=xlsx"],
        ];
        for (const [title, when, state, path] of rows) {
          const tr = doc.createElement("tr"); tr.style.borderTop = "1px solid #eceef0";
          for (const value of [title, date(when), state]) { const td = doc.createElement("td"); td.style.padding = "16px 8px"; td.textContent = str(value); tr.append(td); }
          const td = doc.createElement("td"); const link = doc.createElement("a"); link.className = "bs"; link.textContent = "Скачать"; link.href = `/api/backend/applications/${contractApp}/contract/${path}`; link.download = ""; td.append(link); tr.append(td); tbody.append(tr);
        }
      }
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
