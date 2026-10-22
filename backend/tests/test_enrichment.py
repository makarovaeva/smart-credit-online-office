from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Company, CreditProduct, User
from app.models.enums import CheckSource, CheckStatus, LoanPurpose
from app.services.enrichment import application_features, collect_external_data
from tests.conftest import auth, make_company


async def make_application(
    session: AsyncSession, company: Company, product: CreditProduct, user: User
) -> Application:
    application = Application(
        number=f"CR-TEST-{company.inn}",
        company_id=company.id,
        applicant_id=user.id,
        product_id=product.id,
        requested_amount=Decimal("3000000"),
        requested_term_months=36,
        purpose=LoanPurpose.WORKING_CAPITAL,
    )
    session.add(application)
    await session.flush()
    return application


async def test_collects_all_sources(
    session: AsyncSession, company: Company, product: CreditProduct, client_user: User
) -> None:
    application = await make_application(session, company, product, client_user)
    checks = await collect_external_data(session, application)

    assert {c.source for c in checks} == {CheckSource.EGRUL, CheckSource.FNS, CheckSource.BKI}
    assert all(c.status == CheckStatus.SUCCESS and c.completed_at for c in checks)

    features = await application_features(session, application)
    assert features.missing_sources == []
    assert features.values["fin_revenue"] > 0


async def test_failed_source_is_saved(
    session: AsyncSession, product: CreditProduct, client_user: User
) -> None:
    company = await make_company(session, "7701000011", client_user)
    application = await make_application(session, company, product, client_user)
    checks = {c.source: c for c in await collect_external_data(session, application)}

    assert checks[CheckSource.BKI].status == CheckStatus.FAILED
    assert checks[CheckSource.BKI].error == "bki не отвечает"
    assert checks[CheckSource.FNS].status == CheckStatus.SUCCESS
    features = await application_features(session, application)
    assert features.missing_sources == [CheckSource.BKI]


async def test_lookup_requisites(api: AsyncClient, client_user: User) -> None:
    response = await api.get(
        "/api/v1/companies/lookup", params={"inn": "7701000004"}, headers=auth(client_user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["inn"] == "7701000004"
    assert body["legal_form"] == "ooo"
    assert body["ogrn"].startswith("1")
    assert body["region"]

    missing = await api.get(
        "/api/v1/companies/lookup", params={"inn": "7701000099"}, headers=auth(client_user)
    )
    assert missing.status_code == 404
