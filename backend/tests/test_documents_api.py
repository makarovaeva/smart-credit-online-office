"""Документы заявки и дозапросы: загрузка, скачивание, комплект ИИ, ответы и возврат заявки."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Application, Document, InfoRequest, User
from app.models.enums import ApplicationStatus, UserRole
from tests.conftest import auth, make_user
from tests.test_applications_api import at_underwriter, set_status
from tests.test_pipeline import history, start, submit

S = ApplicationStatus
PDF = b"%PDF-1.7\n% test document\n"
OTHER_BANK_INN = "7701000019"


async def upload(
    api: AsyncClient,
    user: User,
    app_id: str,
    type: str = "bank_statement",
    name: str = "vypiska.pdf",
    content: bytes = PDF,
    **form: str,
):
    return await api.post(
        f"/api/v1/applications/{app_id}/documents",
        files={"file": (name, content, "application/octet-stream")},
        data={"type": type} | form,
        headers=auth(user),
    )


def stored_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


async def info_requests(api: AsyncClient, user: User, app_id: str) -> list[dict]:
    response = await api.get(f"/api/v1/applications/{app_id}/info-requests", headers=auth(user))
    assert response.status_code == 200, response.text
    return response.json()


async def answer(api: AsyncClient, user: User, app_id: str, request_id: str, message=None):
    return await api.post(
        f"/api/v1/applications/{app_id}/info-requests/{request_id}/answer",
        json={"message": message},
        headers=auth(user),
    )


# --- Файлы ---


async def test_upload_list_download_delete(
    api: AsyncClient, client_user: User, draft: dict, document_storage: Path
) -> None:
    url = f"/api/v1/applications/{draft['id']}/documents"
    uploaded = await upload(api, client_user, draft["id"], name="../../Выписка 2026.pdf")
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    # Каталоги из имени отбрасываются, тип определяется по содержимому
    assert document["file_name"] == "Выписка 2026.pdf"
    assert document["content_type"] == "application/pdf"
    assert document["size_bytes"] == len(PDF)
    assert document["verification_status"] == "uploaded"
    assert len(stored_files(document_storage)) == 1

    listed = await api.get(url, headers=auth(client_user))
    assert [d["id"] for d in listed.json()] == [document["id"]]

    content = await api.get(f"{url}/{document['id']}/content", headers=auth(client_user))
    assert content.status_code == 200
    assert content.content == PDF
    assert content.headers["content-type"] == "application/pdf"
    assert "attachment" in content.headers["content-disposition"]

    deleted = await api.delete(f"{url}/{document['id']}", headers=auth(client_user))
    assert deleted.status_code == 204
    assert (await api.get(url, headers=auth(client_user))).json() == []
    assert stored_files(document_storage) == []


@pytest.mark.parametrize(
    ("name", "content", "detail"),
    [
        ("script.exe", b"MZ", "Формат файла"),
        ("fake.pdf", b"<html>", "не соответствует"),
        ("empty.pdf", b"", "пустой"),
        ("table.csv", b"\xff\xfe\x00bad", "UTF-8"),
    ],
)
async def test_upload_rejects_bad_files(
    api: AsyncClient, client_user: User, draft: dict, name: str, content: bytes, detail: str
) -> None:
    response = await upload(api, client_user, draft["id"], name=name, content=content)
    assert response.status_code == 422
    assert detail in response.json()["detail"]


async def test_upload_size_limit(
    api: AsyncClient, client_user: User, draft: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "document_max_size_mb", 1)
    response = await upload(api, client_user, draft["id"], content=PDF + b"0" * 1024 * 1024)
    assert response.status_code == 422
    assert "1 МБ" in response.json()["detail"]


async def test_documents_of_other_company_are_hidden(
    api: AsyncClient, client_user: User, other_client: User, draft: dict
) -> None:
    document = (await upload(api, client_user, draft["id"])).json()
    url = f"/api/v1/applications/{draft['id']}/documents"
    assert (await upload(api, other_client, draft["id"])).status_code == 404
    assert (await api.get(url, headers=auth(other_client))).status_code == 404
    content = await api.get(f"{url}/{document['id']}/content", headers=auth(other_client))
    assert content.status_code == 404


async def test_upload_not_allowed_during_review(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    await set_status(session, draft["id"], S.UNDERWRITER_REVIEW)
    response = await upload(api, client_user, draft["id"])
    assert response.status_code == 409


# --- Комплект документов ИИ ---


async def test_ai_requests_bank_statement_and_resumes_pipeline(
    api: AsyncClient, session: AsyncSession, client_user: User, product
) -> None:
    app_id = await start(api, session, client_user, product, OTHER_BANK_INN)
    body = await submit(api, client_user, app_id)
    assert body["status"] == "need_additional_data"
    assert body["client_status"] == "documents_required"
    assert "answer_info_request" in body["available_actions"]

    [request] = await info_requests(api, client_user, app_id)
    assert request["requested_by"] == "system"
    assert request["requested_document_types"] == ["bank_statement"]
    assert "другом банке" in request["message"]

    # Без запрошенного документа ответ не принимается
    response = await answer(api, client_user, app_id, request["id"], "Готово")
    assert response.status_code == 422
    assert "выписка" in response.json()["detail"]

    uploaded = await upload(api, client_user, app_id, info_request_id=request["id"])
    assert uploaded.status_code == 201, uploaded.text
    response = await answer(api, client_user, app_id, request["id"])
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "answered"

    application = await session.get(Application, app_id)
    assert application.status == S.UNDERWRITER_REVIEW
    statuses = [h["to_status"] for h in await history(api, client_user, app_id)]
    assert statuses[statuses.index("need_additional_data") :] == [
        "need_additional_data",
        "ai_verification",
        "ai_risk_scoring",
        "decision_routing",
        "ai_financial_analysis",
        "underwriter_review",
    ]
    document = await session.get(Document, uploaded.json()["id"])
    assert document.verification_status == "verified"
    # Повторно ответить на закрытый дозапрос нельзя
    again = await answer(api, client_user, app_id, request["id"])
    assert again.status_code == 409


async def test_document_uploaded_before_submit_completes_set(
    api: AsyncClient, session: AsyncSession, client_user: User, product
) -> None:
    app_id = await start(api, session, client_user, product, OTHER_BANK_INN)
    document = (await upload(api, client_user, app_id)).json()
    body = await submit(api, client_user, app_id)
    assert body["status"] == "underwriter_review"
    assert await info_requests(api, client_user, app_id) == []

    deleted = await api.delete(
        f"/api/v1/applications/{app_id}/documents/{document['id']}", headers=auth(client_user)
    )
    assert deleted.status_code == 409


async def test_collateral_requires_title_document(
    api: AsyncClient, session: AsyncSession, client_user: User, product
) -> None:
    app_id = await start(api, session, client_user, product, "7701000001")
    url = f"/api/v1/applications/{app_id}"
    version = (await api.get(url, headers=auth(client_user))).json()["version"]
    patched = await api.patch(
        url,
        json={
            "has_collateral": True,
            "collateral_type": "vehicle",
            "collateral_market_value": "6000000.00",
            "version": version,
        },
        headers=auth(client_user),
    )
    assert patched.status_code == 200, patched.text
    body = await submit(api, client_user, app_id)
    assert body["status"] == "need_additional_data"
    [request] = await info_requests(api, client_user, app_id)
    assert request["requested_document_types"] == ["vehicle_passport"]


# --- Дозапросы сотрудников ---


async def test_underwriter_request_returns_to_underwriter(
    api: AsyncClient, session: AsyncSession, client_user: User, underwriter: User, draft: dict
) -> None:
    app_id = draft["id"]
    await at_underwriter(session, app_id)
    decision = await api.post(
        f"/api/v1/backoffice/applications/{app_id}/decision",
        json={
            "decision_type": "more_information_required",
            "more_info_target": "client",
            "info_request": {
                "message": "Пришлите КУДИР за 2026 год",
                "requested_document_types": ["kudir"],
            },
        },
        headers=auth(underwriter),
    )
    assert decision.status_code == 201, decision.text
    [request] = await info_requests(api, client_user, app_id)
    assert request["requested_by"] == "underwriter"

    # Документ без info_request_id тоже закрывает дозапрос, если загружен после него
    kudir = await upload(
        api, client_user, app_id, type="kudir", name="kudir.xlsx", content=b"PK\x03\x04xlsx"
    )
    assert kudir.status_code == 201, kudir.text
    response = await answer(api, client_user, app_id, request["id"], "КУДИР приложена")
    assert response.status_code == 200, response.text
    assert response.json()["response_message"] == "КУДИР приложена"

    application = await session.get(Application, app_id)
    assert application.status == S.UNDERWRITER_REVIEW
    assert application.assignee_id == underwriter.id
    document = await session.get(Document, kudir.json()["id"])
    assert str(document.info_request_id) == request["id"]

    # Сотрудник скачивает файл своей заявки, посторонний - нет
    url = f"/api/v1/backoffice/applications/{app_id}/documents/{document.id}/content"
    content = await api.get(url, headers=auth(underwriter))
    assert content.status_code == 200
    assert content.content == b"PK\x03\x04xlsx"
    # Аналитик, не работавший с заявкой андеррайтера, её не видит
    stranger = await make_user(session, "an-other@example.com", UserRole.CREDIT_ANALYST)
    assert (await api.get(url, headers=auth(stranger))).status_code == 404


async def test_analyst_request_returns_to_analyst(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    analyst: User,
    underwriter: User,
    draft: dict,
) -> None:
    app_id = draft["id"]
    application = await set_status(session, app_id, S.ANALYST_ESCALATION)
    application.assignee_id = analyst.id
    await session.flush()
    url = f"/api/v1/backoffice/applications/{app_id}/info-requests"
    body = {"message": "Поясните падение выручки в III квартале"}

    assert (await api.post(url, json=body, headers=auth(underwriter))).status_code == 403
    created = await api.post(url, json=body, headers=auth(analyst))
    assert created.status_code == 201, created.text
    assert created.json()["requested_by"] == "credit_analyst"
    await session.refresh(application)
    assert application.status == S.NEED_ADDITIONAL_DATA
    assert application.assignee_id is None

    request_id = created.json()["id"]
    # Без запрошенных документов нужен текст ответа
    assert (await answer(api, client_user, app_id, request_id, " ")).status_code == 422
    response = await answer(api, client_user, app_id, request_id, "Сезонность: ремонт склада")
    assert response.status_code == 200, response.text
    await session.refresh(application)
    assert application.status == S.ANALYST_ESCALATION
    assert application.assignee_id == analyst.id

    # Аналитик видит ответ в карточке
    detail = await api.get(f"/api/v1/backoffice/applications/{app_id}", headers=auth(analyst))
    [info] = detail.json()["info_requests"]
    assert info["response_message"] == "Сезонность: ремонт склада"


async def test_answer_waits_for_all_open_requests(
    api: AsyncClient, session: AsyncSession, client_user: User, draft: dict
) -> None:
    app_id = draft["id"]
    application = await set_status(session, app_id, S.NEED_ADDITIONAL_DATA)
    first, second = (
        InfoRequest(application_id=application.id, requested_by="underwriter", message=m)
        for m in ("Вопрос 1", "Вопрос 2")
    )
    session.add_all([first, second])
    await session.flush()

    assert (await answer(api, client_user, app_id, str(first.id), "Ответ 1")).status_code == 200
    await session.refresh(application)
    assert application.status == S.NEED_ADDITIONAL_DATA
    assert (await answer(api, client_user, app_id, str(second.id), "Ответ 2")).status_code == 200
    await session.refresh(application)
    assert application.status == S.UNDERWRITER_REVIEW
    statuses = await session.scalars(
        select(InfoRequest.status).where(InfoRequest.application_id == application.id)
    )
    assert set(statuses) == {"answered"}
