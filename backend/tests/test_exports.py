"""Выгрузки по кредиту: договор PDF, график XLSX и PDF."""

import io
import zipfile
from urllib.parse import unquote
from xml.etree import ElementTree

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import UserRole
from tests.conftest import auth, make_user
from tests.test_loans_api import SIGN, approved  # noqa: F401 - фикстура

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _filename(response) -> str:
    return unquote(response.headers["content-disposition"].split("filename*=UTF-8''")[1])


async def test_contract_and_schedule_exports(
    api: AsyncClient,
    client_user: User,
    approved: str,  # noqa: F811
) -> None:
    url = f"/api/v1/applications/{approved}"
    headers = auth(client_user)
    # До принятия оффера договора нет
    assert (await api.get(f"{url}/contract/document", headers=headers)).status_code == 404

    await api.post(f"{url}/offer/accept", headers=headers)
    contract = (await api.get(f"{url}/contract", headers=headers)).json()

    pdf = await api.get(f"{url}/contract/document", headers=headers)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert len(pdf.content) > 5000
    assert _filename(pdf) == f"Кредитный договор {contract['contract_number']}.pdf"

    xlsx = await api.get(f"{url}/contract/schedule-export", headers=headers)
    assert xlsx.status_code == 200
    assert xlsx.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert _filename(xlsx).endswith(".xlsx")
    with zipfile.ZipFile(io.BytesIO(xlsx.content)) as archive:
        assert archive.testzip() is None
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows = sheet.findall(".//x:row", NS)
    # 6 строк шапки + заголовок таблицы + 36 платежей + итог
    assert len(rows) == 6 + 1 + 36 + 1
    first_payment = rows[7].findall("x:c", NS)
    assert first_payment[0].find("x:v", NS).text == "1"
    assert first_payment[4].find("x:v", NS).text == contract["schedule"][0]["total_amount"]
    totals = rows[-1].findall("x:c", NS)
    assert totals[1].find("x:f", NS).text == "SUM(C9:C44)"

    schedule_pdf = await api.get(
        f"{url}/contract/schedule-export", params={"format": "pdf"}, headers=headers
    )
    assert schedule_pdf.content.startswith(b"%PDF-")
    assert _filename(schedule_pdf).startswith("График платежей")
    bad = await api.get(
        f"{url}/contract/schedule-export", params={"format": "doc"}, headers=headers
    )
    assert bad.status_code == 422


async def test_signed_contract_and_access(
    api: AsyncClient,
    session: AsyncSession,
    client_user: User,
    other_client: User,
    underwriter: User,
    approved: str,  # noqa: F811
) -> None:
    url = f"/api/v1/applications/{approved}"
    await api.post(f"{url}/offer/accept", headers=auth(client_user))
    await api.post(f"{url}/sign", json=SIGN, headers=auth(client_user))
    assert (await api.get(f"{url}/contract/document", headers=auth(client_user))).status_code == 200
    assert (
        await api.get(f"{url}/contract/document", headers=auth(other_client))
    ).status_code == 404

    backoffice = f"/api/v1/backoffice/applications/{approved}/contract"
    assert (await api.get(f"{backoffice}/document", headers=auth(underwriter))).status_code == 200
    xlsx = await api.get(f"{backoffice}/schedule-export", headers=auth(underwriter))
    assert xlsx.status_code == 200
    stranger = await make_user(session, "uw-export@example.com", UserRole.UNDERWRITER)
    assert (await api.get(f"{backoffice}/document", headers=auth(stranger))).status_code == 404
