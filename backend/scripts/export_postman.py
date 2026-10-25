"""Postman-коллекция и окружение в docs/postman/.

Коллекция генерируется из этого файла - правьте его, а не JSON.
Запуск из backend/: uv run python -m scripts.export_postman

Сценарии идут по демо-данным (scripts/seed.py, app/integrations/synthetic.py) и выполняются
по порядку: id и токены передаются между запросами через переменные коллекции.
"""

import json
import uuid
from pathlib import Path
from typing import Any

POSTMAN_DIR = Path(__file__).resolve().parents[2] / "docs" / "postman"
COLLECTION_OUTPUT = POSTMAN_DIR / "smart-credit.postman_collection.json"
ENVIRONMENT_OUTPUT = POSTMAN_DIR / "smart-credit.local.postman_environment.json"

NAMESPACE = uuid.UUID("6f1c2b8e-4a1d-4c39-9d5e-0b7a2f3c9e11")

ENVIRONMENT = {
    "baseUrl": "http://localhost:8000/api/v1",
    "employeePassword": "demo-password",
    "underwriter1": "underwriter1@alfa-demo.ru",
    "underwriter2": "underwriter2@alfa-demo.ru",
    "analyst1": "analyst1@alfa-demo.ru",
    "analyst2": "analyst2@alfa-demo.ru",
}

CONSENTS = {"types": ["bki", "fns", "digital_profile"]}


def _id(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "/".join(parts)))


def request(
    name: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    form: list[dict[str, str]] | None = None,
    query: dict[str, str] | None = None,
    tests: list[str] | None = None,
    status: int = 200,
    description: str | None = None,
) -> dict[str, Any]:
    headers = [{"key": "Content-Type", "value": "application/json"}] if body is not None else []
    if token:
        headers.append({"key": "Authorization", "value": f"Bearer {{{{{token}}}}}"})
    raw = "{{baseUrl}}" + path
    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": path.strip("/").split("/")}
    if query:
        url["raw"] += "?" + "&".join(f"{k}={v}" for k, v in query.items())
        url["query"] = [{"key": k, "value": v} for k, v in query.items()]
    script = [
        f"pm.test('HTTP {status}', () => pm.response.to.have.status({status}));",
        *(tests or []),
    ]
    item: dict[str, Any] = {
        "name": name,
        "request": {"method": method, "header": headers, "url": url},
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": script}}],
    }
    if description:
        item["request"]["description"] = description
    if form is not None:
        # multipart/form-data: Content-Type с boundary проставляет Postman
        item["request"]["body"] = {"mode": "formdata", "formdata": form}
    if body is not None:
        item["request"]["body"] = {
            "mode": "raw",
            "raw": json.dumps(body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }
    return item


def folder(name: str, description: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "description": description, "item": items}


def js_set(var: str, expr: str) -> str:
    return f"pm.collectionVariables.set('{var}', {expr});"


def js_expect(expr: str, value: str) -> str:
    return f"pm.test('{expr} = {value}', () => pm.expect({expr}).to.eql({json.dumps(value)}));"


def client_start(prefix: str, phone: str, amount: str, term: int = 36) -> list[dict[str, Any]]:
    """Вход клиента, создание черновика, согласия и подача: общее начало сценариев."""
    token, app_id = f"{prefix}Token", f"{prefix}AppId"
    return [
        request(
            "Клиент: вход по телефону",
            "POST",
            "/auth/login/phone",
            body={"phone": phone},
            tests=[js_set(token, "pm.response.json().access_token")],
        ),
        request(
            "Клиент: профиль и компании",
            "GET",
            "/me",
            token=token,
            tests=[js_set(f"{prefix}CompanyId", "pm.response.json().companies[0].company_id")],
        ),
        request(
            "Клиент: создать черновик заявки",
            "POST",
            "/applications",
            token=token,
            status=201,
            body={
                "company_id": f"{{{{{prefix}CompanyId}}}}",
                "product_id": "{{productId}}",
                "requested_amount": amount,
                "requested_term_months": term,
                "purpose": "working_capital",
                "purpose_description": "Закупка товара под сезон",
            },
            tests=[
                js_set(app_id, "pm.response.json().id"),
                js_expect("pm.response.json().status", "draft"),
            ],
        ),
        request(
            "Клиент: согласия на получение данных",
            "POST",
            f"/applications/{{{{{app_id}}}}}/consents",
            token=token,
            body=CONSENTS,
            description="Запускает сбор данных и предварительный расчёт: draft -> pre_approved.",
            tests=[js_expect("pm.response.json().status", "pre_approved")],
        ),
        request(
            "Клиент: предварительный расчёт",
            "GET",
            f"/applications/{{{{{app_id}}}}}/pre-approval",
            token=token,
        ),
        request(
            "Клиент: подать заявку",
            "POST",
            f"/applications/{{{{{app_id}}}}}/submit",
            token=token,
            description="Запускает проверку, скоринг, политику и маршрутизацию.",
        ),
    ]


def employee_login(name: str, var: str, emails: tuple[str, str], app_id: str) -> dict[str, Any]:
    """Вход сотрудника, которому назначена заявка: назначение автоматическое (по загрузке),
    поэтому скрипт пробует первого и, если заявка не его, входит вторым."""
    first, second = emails
    script = f"""
const tokenOf = (res) => res.json().access_token;
const base = pm.environment.get('baseUrl') || pm.collectionVariables.get('baseUrl');
const appId = pm.collectionVariables.get('{app_id}');
pm.collectionVariables.set('{var}', tokenOf(pm.response));
pm.sendRequest({{
  url: `${{base}}/backoffice/applications/${{appId}}`,
  header: {{ Authorization: `Bearer ${{tokenOf(pm.response)}}` }},
}}, (err, res) => {{
  if (!err && res.code === 200) return;
  pm.sendRequest({{
    url: `${{base}}/auth/login`, method: 'POST',
    header: {{ 'Content-Type': 'application/json' }},
    body: {{ mode: 'raw', raw: JSON.stringify({{
      email: pm.environment.get('{second}'),
      password: pm.environment.get('employeePassword'),
    }}) }},
  }}, (err2, res2) => pm.collectionVariables.set('{var}', tokenOf(res2)));
}});
""".strip().splitlines()
    return request(
        name,
        "POST",
        "/auth/login",
        body={"email": f"{{{{{first}}}}}", "password": "{{employeePassword}}"},
        tests=script,
        description="Логин и пароль из окружения. Если заявка назначена на коллегу, "
        "скрипт входит под ним.",
    )


def build_collection() -> dict[str, Any]:
    happy = [
        request(
            "Клиент: вход по телефону",
            "POST",
            "/auth/login/phone",
            body={"phone": "+7 999 000-00-01"},
            description="Упрощённый вход клиента банка: только номер телефона, без SMS.",
            tests=[js_set("clientToken", "pm.response.json().access_token")],
        ),
        request(
            "Клиент: профиль и компании",
            "GET",
            "/me",
            token="clientToken",
            tests=[js_set("companyId", "pm.response.json().companies[0].company_id")],
        ),
        request(
            "Клиент: профиль компании",
            "GET",
            "/companies/{{companyId}}",
            token="clientToken",
            description="Реквизиты, руководитель и владельцы из ЕГРЮЛ, контакты и расчётный счёт.",
            tests=[
                js_expect("pm.response.json().inn", "7701000001"),
                "pm.test('есть руководитель и счёт', () => { const c = pm.response.json(); "
                "pm.expect(c.head.full_name).to.be.a('string'); "
                "pm.expect(c.settlement_account.account_number).to.match(/^40702810/); });",
            ],
        ),
        request(
            "Каталог продуктов",
            "GET",
            "/products",
            tests=[
                js_set(
                    "productId",
                    "pm.response.json().find(p => p.code === 'working-capital').id",
                )
            ],
        ),
        request(
            "Реквизиты компании по ИНН (мок ЕГРЮЛ)",
            "GET",
            "/companies/lookup",
            token="clientToken",
            query={"inn": "7701000001"},
        ),
        request(
            "Создать черновик заявки",
            "POST",
            "/applications",
            token="clientToken",
            status=201,
            body={
                "company_id": "{{companyId}}",
                "product_id": "{{productId}}",
                "requested_amount": "3000000.00",
                "requested_term_months": 36,
                "purpose": "working_capital",
            },
            tests=[
                js_set("applicationId", "pm.response.json().id"),
                js_set("applicationVersion", "pm.response.json().version"),
                js_expect("pm.response.json().status", "draft"),
            ],
        ),
        request(
            "Изменить черновик",
            "PATCH",
            "/applications/{{applicationId}}",
            token="clientToken",
            body={
                "purpose_description": "Пополнение оборотных средств",
                "version": "{{applicationVersion}}",
            },
            description="Нужна текущая version (оптимистичная блокировка), иначе 409.",
        ),
        request(
            "Согласия на получение данных",
            "POST",
            "/applications/{{applicationId}}/consents",
            token="clientToken",
            body=CONSENTS,
            description="Конвейер собирает данные (ЕГРЮЛ, ФНС, БКИ, комплаенс) и делает "
            "предварительный расчёт.",
            tests=[js_expect("pm.response.json().status", "pre_approved")],
        ),
        request(
            "Предварительный расчёт",
            "GET",
            "/applications/{{applicationId}}/pre-approval",
            token="clientToken",
        ),
        request(
            "Подать заявку",
            "POST",
            "/applications/{{applicationId}}/submit",
            token="clientToken",
            description="Проверка, скоринг, кредитная политика и маршрутизация. Здоровая "
            "компания в зелёной зоне уходит андеррайтеру.",
            tests=[js_expect("pm.response.json().status", "underwriter_review")],
        ),
        request(
            "История статусов",
            "GET",
            "/applications/{{applicationId}}/history",
            token="clientToken",
        ),
        employee_login(
            "Андеррайтер: вход",
            "underwriterToken",
            ("underwriter1", "underwriter2"),
            "applicationId",
        ),
        request(
            "Андеррайтер: мои заявки на рассмотрении",
            "GET",
            "/backoffice/applications",
            token="underwriterToken",
            query={"status": "underwriter_review"},
            tests=[
                "pm.test('заявка в очереди', () => pm.expect(pm.response.json().items"
                ".map(i => i.id)).to.include(pm.collectionVariables.get('applicationId')));"
            ],
        ),
        request(
            "Андеррайтер: карточка заявки и AI Credit Memo",
            "GET",
            "/backoffice/applications/{{applicationId}}",
            token="underwriterToken",
            tests=[js_expect("pm.response.json().credit_memo.ai_recommendation", "approve")],
        ),
        request(
            "Андеррайтер: одобрить",
            "POST",
            "/backoffice/applications/{{applicationId}}/decision",
            token="underwriterToken",
            status=201,
            body={
                "decision_type": "approved",
                "approved_amount": "3000000.00",
                "approved_term_months": 36,
                "interest_rate": "18.00",
                "comment": "Подтверждаю рекомендацию ИИ",
            },
        ),
        request(
            "Клиент: оффер", "GET", "/applications/{{applicationId}}/offer", token="clientToken"
        ),
        request(
            "Клиент: принять оффер",
            "POST",
            "/applications/{{applicationId}}/offer/accept",
            token="clientToken",
            description="Готовит договор и график платежей. Повторный вызов идемпотентен.",
            tests=[js_expect("pm.response.json().status", "e_sign")],
        ),
        request(
            "Клиент: договор и график платежей",
            "GET",
            "/applications/{{applicationId}}/contract",
            token="clientToken",
            tests=[
                js_set("contractId", "pm.response.json().id"),
                js_expect("pm.response.json().status", "awaiting_signature"),
            ],
        ),
        request(
            "Клиент: подписать договор (симуляция ЭП и выдачи)",
            "POST",
            "/applications/{{applicationId}}/sign",
            token="clientToken",
            body={"confirmation_code": "123456"},
            description="Подпись, открытие ссудного счёта, зачисление на расчётный счёт.",
            tests=[js_expect("pm.response.json().status", "completed")],
        ),
        request(
            "Клиент: мои кредиты",
            "GET",
            "/loans",
            token="clientToken",
            tests=[
                "pm.test('кредит в списке', () => pm.expect(pm.response.json().map(l => l.id))"
                ".to.include(pm.collectionVariables.get('contractId')));"
            ],
        ),
        request(
            "Клиент: кредит с графиком",
            "GET",
            "/loans/{{contractId}}",
            token="clientToken",
            tests=[js_expect("pm.response.json().status", "active")],
        ),
    ]

    counter = [
        *client_start("counter", "+7 999 000-00-02", "5000000.00", term=24),
        employee_login(
            "Андеррайтер: вход", "counterUwToken", ("underwriter1", "underwriter2"), "counterAppId"
        ),
        request(
            "Андеррайтер: карточка - контр-предложение ИИ и варианты",
            "GET",
            "/backoffice/applications/{{counterAppId}}",
            token="counterUwToken",
            tests=[
                js_expect("pm.response.json().credit_memo.ai_recommendation", "counter_offer"),
                "pm.test('есть альтернативные варианты', () => pm.expect(pm.response.json()"
                ".credit_memo.alternative_offers).to.not.be.empty);",
            ],
        ),
        request(
            "Андеррайтер: контр-предложение по варианту «дольше срок»",
            "POST",
            "/backoffice/applications/{{counterAppId}}/decision",
            token="counterUwToken",
            status=201,
            body={"decision_type": "conditional_approval", "alternative_offer": "longer_term"},
            description="Сумма, срок и ставка берутся из варианта в AI Credit Memo.",
        ),
        request(
            "Клиент: контр-предложение",
            "GET",
            "/applications/{{counterAppId}}/offer",
            token="counterToken",
            tests=[
                js_expect("pm.response.json().decision_type", "conditional_approval"),
                js_expect("pm.response.json().approved_amount", "5000000.00"),
            ],
        ),
    ]

    decline = client_start("decline", "+7 999 000-00-03", "3000000.00")
    decline[-1]["event"][0]["script"]["exec"] += [
        js_expect("pm.response.json().status", "closed"),
        js_expect("pm.response.json().close_reason", "auto_declined"),
    ]
    decline.append(
        request(
            "Клиент: причина отказа в истории",
            "GET",
            "/applications/{{declineAppId}}/history",
            token="declineToken",
            tests=[
                "pm.test('причина отказа', () => pm.expect(pm.response.json().at(-1).comment)"
                ".to.include('Автоматический отказ'));"
            ],
        )
    )

    escalation = client_start("escalation", "+7 999 000-00-04", "2000000.00")
    escalation[-1]["event"][0]["script"]["exec"].append(
        js_expect("pm.response.json().status", "analyst_escalation")
    )
    escalation += [
        employee_login(
            "Аналитик: вход", "analystToken", ("analyst1", "analyst2"), "escalationAppId"
        ),
        request(
            "Аналитик: новые эскалации",
            "GET",
            "/backoffice/applications",
            token="analystToken",
            query={"status": "analyst_escalation"},
        ),
        request(
            "Аналитик: заключение",
            "POST",
            "/backoffice/applications/{{escalationAppId}}/analyst-conclusion",
            token="analystToken",
            body={
                "conclusion": "Бизнес молодой, но обороты стабильные. Рекомендую одобрить.",
                "recommendation": "approve",
            },
            tests=[js_expect("pm.response.json().analyst_recommendation", "approve")],
        ),
        request(
            "Клиент: заявка снова на рассмотрении",
            "GET",
            "/applications/{{escalationAppId}}",
            token="escalationToken",
            tests=[js_expect("pm.response.json().status", "underwriter_review")],
        ),
    ]

    documents = client_start("docs", "+7 999 000-00-06", "3000000.00")
    documents[-1]["event"][0]["script"]["exec"] += [
        js_expect("pm.response.json().status", "need_additional_data"),
        js_expect("pm.response.json().client_status", "documents_required"),
    ]
    documents += [
        request(
            "Клиент: дозапрос ИИ",
            "GET",
            "/applications/{{docsAppId}}/info-requests",
            token="docsToken",
            description="Счёт в другом банке - ИИ запрашивает выписку за 12 месяцев.",
            tests=[
                js_set("docsRequestId", "pm.response.json()[0].id"),
                js_expect("pm.response.json()[0].requested_by", "system"),
                js_expect("pm.response.json()[0].requested_document_types[0]", "bank_statement"),
            ],
        ),
        request(
            "Клиент: загрузить выписку",
            "POST",
            "/applications/{{docsAppId}}/documents",
            token="docsToken",
            status=201,
            form=[
                {"key": "file", "type": "file", "src": "files/vypiska.pdf"},
                {"key": "type", "type": "text", "value": "bank_statement"},
                {"key": "info_request_id", "type": "text", "value": "{{docsRequestId}}"},
            ],
            description="Файл - docs/postman/files/vypiska.pdf (в Postman выберите его вручную).",
            tests=[
                js_set("docsDocumentId", "pm.response.json().id"),
                js_expect("pm.response.json().content_type", "application/pdf"),
            ],
        ),
        request(
            "Клиент: документы заявки",
            "GET",
            "/applications/{{docsAppId}}/documents",
            token="docsToken",
            tests=[
                "pm.test('один документ', () => pm.expect(pm.response.json()).to.have.length(1));"
            ],
        ),
        request(
            "Клиент: ответить на дозапрос",
            "POST",
            "/applications/{{docsAppId}}/info-requests/{{docsRequestId}}/answer",
            token="docsToken",
            body={"message": "Выписка за 12 месяцев приложена"},
            description="Все дозапросы закрыты - ИИ повторно проверяет комплект, конвейер "
            "продолжается.",
            tests=[js_expect("pm.response.json().status", "answered")],
        ),
        request(
            "Клиент: заявка у андеррайтера",
            "GET",
            "/applications/{{docsAppId}}",
            token="docsToken",
            tests=[js_expect("pm.response.json().status", "underwriter_review")],
        ),
        employee_login(
            "Андеррайтер: вход", "docsUwToken", ("underwriter1", "underwriter2"), "docsAppId"
        ),
        request(
            "Андеррайтер: скачать выписку",
            "GET",
            "/backoffice/applications/{{docsAppId}}/documents/{{docsDocumentId}}/content",
            token="docsUwToken",
            tests=[
                "pm.test('PDF', () => pm.expect(pm.response.headers.get('Content-Type'))"
                ".to.include('application/pdf'));"
            ],
        ),
    ]

    errors = [
        request("401: без токена", "GET", "/applications", status=401),
        request(
            "401: неверный пароль сотрудника",
            "POST",
            "/auth/login",
            status=401,
            body={"email": "{{underwriter1}}", "password": "wrong"},
        ),
        request(
            "401: неизвестный номер телефона",
            "POST",
            "/auth/login/phone",
            status=401,
            body={"phone": "+7 999 111-22-33"},
        ),
        request(
            "403: клиент в бэкофисе",
            "GET",
            "/backoffice/applications",
            token="clientToken",
            status=403,
        ),
        request(
            "409: компания уже привязана",
            "POST",
            "/companies",
            token="clientToken",
            status=409,
            body={"inn": "7701000001", "member_role": "owner"},
        ),
        request(
            "404: чужая компания",
            "GET",
            "/companies/{{companyId}}",
            token="counterToken",
            status=404,
        ),
        request(
            "404: чужая заявка",
            "GET",
            "/applications/{{applicationId}}",
            token="counterToken",
            status=404,
        ),
        request(
            "409: подпись до принятия оффера",
            "POST",
            "/applications/{{counterAppId}}/sign",
            token="counterToken",
            status=409,
            body={"confirmation_code": "123456"},
        ),
        request(
            "422: сумма больше лимита продукта",
            "POST",
            "/applications",
            token="clientToken",
            status=422,
            body={
                "company_id": "{{companyId}}",
                "product_id": "{{productId}}",
                "requested_amount": "50000000.00",
                "requested_term_months": 36,
                "purpose": "working_capital",
            },
        ),
    ]

    folders = [
        folder(
            "0. Готовность",
            "Сервис и БД доступны.",
            [
                request("Готовность (БД)", "GET", "/health/ready"),
            ],
        ),
        folder(
            "1. Happy path: от заявки до выдачи",
            "Клиент +7 999 000-00-01 (здоровая компания) проходит весь путь: заявка, "
            "конвейер, одобрение андеррайтером, договор, подписание и выдача.",
            happy,
        ),
        folder(
            "2. Контр-предложение с вариантами",
            "Клиент +7 999 000-00-02, 5 млн на 24 мес.: пограничный риск по DSCR, андеррайтер "
            "выбирает вариант.",
            counter,
        ),
        folder(
            "3. Автоотказ по стоп-фактору",
            "Клиент +7 999 000-00-03: действующее банкротство, красная зона.",
            decline,
        ),
        folder(
            "4. Эскалация аналитику",
            "Клиент +7 999 000-00-04: бизнесу 7 месяцев, жёлтая зона, заключение аналитика.",
            escalation,
        ),
        folder(
            "5. Документы и дозапрос",
            "Клиент +7 999 000-00-06: счёт в другом банке, ИИ запрашивает выписку, клиент "
            "загружает её и отвечает, конвейер продолжается, андеррайтер скачивает файл.",
            documents,
        ),
        folder("6. Ошибки", "Коды ответов при ошибочных сценариях.", errors),
    ]
    for f in folders:
        for item in f["item"]:
            item["id"] = _id(f["name"], item["name"])
    return {
        "info": {
            "_postman_id": _id("collection"),
            "name": "Smart Credit Office API",
            "description": "Кредитный кабинет предпринимателя: сценарии на демо-данных. "
            "Запускайте всю коллекцию по порядку с окружением "
            "smart-credit.local.postman_environment.json.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
    }


def build_environment() -> dict[str, Any]:
    return {
        "id": _id("environment"),
        "name": "Smart Credit - local",
        "values": [
            {
                "key": key,
                "value": value,
                "type": "secret" if "Password" in key else "default",
                "enabled": True,
            }
            for key, value in ENVIRONMENT.items()
        ],
        "_postman_variable_scope": "environment",
    }


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    POSTMAN_DIR.mkdir(parents=True, exist_ok=True)
    COLLECTION_OUTPUT.write_text(render(build_collection()))
    ENVIRONMENT_OUTPUT.write_text(render(build_environment()))
    print(f"written {COLLECTION_OUTPUT} and {ENVIRONMENT_OUTPUT}")


if __name__ == "__main__":
    main()
