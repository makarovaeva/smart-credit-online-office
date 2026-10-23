import uuid

from fastapi import APIRouter

from app.api.deps import AUTH_RESPONSES, NOT_FOUND, CurrentClient, SessionDep
from app.schemas.loan import LoanContractRead, LoanShort
from app.services import loans

router = APIRouter(prefix="/loans", tags=["loans"], responses=AUTH_RESPONSES)


@router.get("")
async def list_loans(user: CurrentClient, session: SessionDep) -> list[LoanShort]:
    """Раздел «Кредиты»: договоры компаний клиента с остатком долга и ближайшим платежом."""
    return await loans.list_loans(session, user)


@router.get("/{contract_id}", responses=NOT_FOUND)
async def get_loan(
    contract_id: uuid.UUID, user: CurrentClient, session: SessionDep
) -> LoanContractRead:
    """Кредит с графиком платежей."""
    return await loans.get_loan(session, user, contract_id)
