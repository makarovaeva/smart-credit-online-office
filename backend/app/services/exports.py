"""Выгрузки по кредиту: договор с графиком (PDF) и график платежей (PDF, XLSX).

PDF собирается fpdf2 со шрифтом DejaVu Sans (кириллица, app/assets/fonts). XLSX - минимальный
OOXML через zipfile, без зависимостей. Документы - демонстрационные: подписание и выдача в
прототипе смоделированы, юридической силы у файлов нет.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Company, CreditDecision, LoanContract, PaymentScheduleItem
from app.models.enums import DecisionType, LoanContractStatus
from app.services.chat_events import rub
from app.services.errors import NotFoundError

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
DEMO_NOTE = "Демонстрационный документ прототипа: подписание и выдача смоделированы."
STATUS_LABELS = {
    LoanContractStatus.AWAITING_SIGNATURE: "проект, ожидает подписания",
    LoanContractStatus.SIGNED: "подписан электронной подписью",
    LoanContractStatus.ACTIVE: "действует",
}


@dataclass
class ContractData:
    contract: LoanContract
    company: Company
    application: Application
    schedule: list[PaymentScheduleItem]
    conditions: list[str]


async def contract_data(session: AsyncSession, application: Application) -> ContractData:
    contract = await session.scalar(
        select(LoanContract).where(LoanContract.application_id == application.id)
    )
    if contract is None:
        raise NotFoundError("Договор по заявке ещё не подготовлен")
    company = await session.get(Company, application.company_id)
    assert company is not None
    schedule = list(
        await session.scalars(
            select(PaymentScheduleItem)
            .where(PaymentScheduleItem.contract_id == contract.id)
            .order_by(PaymentScheduleItem.installment_no)
        )
    )
    decision = await session.scalar(
        select(CreditDecision)
        .where(
            CreditDecision.application_id == application.id,
            CreditDecision.decision_type.in_(
                [DecisionType.APPROVED, DecisionType.CONDITIONAL_APPROVAL]
            ),
        )
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )
    conditions = [c["description"] for c in (decision.conditions if decision else [])]
    return ContractData(contract, company, application, schedule, conditions)


def _d(value: date | datetime | None) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _rate(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",") + "% годовых"


def _money(value: Decimal) -> str:
    """В таблицах - всегда с копейками, разряды через неразрывный пробел."""
    return f"{value:,.2f}".replace(",", "\u00a0").replace(".", ",")


def _rub(value: Decimal) -> str:
    """Сумма в тексте: знак рубля не отрывается от числа при переносе."""
    return rub(value).replace(" ", "\u00a0")


# --- PDF ---


class _Pdf(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(format="A4")
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_title(title)
        self.set_author("Умный кредитный кабинет предпринимателя (прототип)")
        self.set_auto_page_break(auto=True, margin=15)
        self.add_page()

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(120)
        self.cell(0, 5, f"{DEMO_NOTE}  Стр. {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0)

    def heading(self, text: str, size: int = 14) -> None:
        self.set_font("DejaVu", "B", size)
        self.multi_cell(0, 7, text)
        self.ln(1)

    def paragraph(self, text: str, size: int = 9) -> None:
        self.set_font("DejaVu", "", size)
        self.multi_cell(0, 5, text, align="L")
        self.ln(1)

    def pairs(self, rows: list[tuple[str, str]]) -> None:
        self.set_font("DejaVu", "", 9)
        with self.table(col_widths=(60, 120), first_row_as_headings=False, line_height=6) as table:
            for label, value in rows:
                row = table.row()
                row.cell(label)
                row.cell(value)
        self.ln(3)

    def schedule(self, items: list[PaymentScheduleItem]) -> None:
        self.set_font("DejaVu", "", 8)
        headings = ("№", "Дата", "Основной долг", "Проценты", "Платёж", "Остаток долга")
        with self.table(
            col_widths=(10, 24, 34, 30, 34, 38),
            text_align=("CENTER", "CENTER", "RIGHT", "RIGHT", "RIGHT", "RIGHT"),
            line_height=5,
        ) as table:
            table.row(headings)
            for item in items:
                table.row(
                    (
                        str(item.installment_no),
                        _d(item.due_date),
                        _money(item.principal_amount),
                        _money(item.interest_amount),
                        _money(item.total_amount),
                        _money(item.balance_after),
                    )
                )
            table.row(
                (
                    "",
                    "Итого",
                    _money(sum((i.principal_amount for i in items), Decimal(0))),
                    _money(sum((i.interest_amount for i in items), Decimal(0))),
                    _money(sum((i.total_amount for i in items), Decimal(0))),
                    "",
                )
            )


def _terms(data: ContractData) -> list[tuple[str, str]]:
    c = data.contract
    return [
        ("Сумма кредита", _rub(c.principal_amount)),
        ("Срок", f"{c.term_months} мес."),
        ("Процентная ставка", _rate(c.interest_rate)),
        ("Погашение", "аннуитетными ежемесячными платежами"),
        ("Ежемесячный платёж", _rub(c.monthly_payment)),
        ("Первый платёж", _d(c.first_payment_date)),
        ("Дата окончания", _d(c.maturity_date)),
        ("Ссудный счёт", c.loan_account_number or "открывается при подписании"),
        ("Счёт зачисления", c.settlement_account_number or "—"),
    ]


def _borrower(company: Company) -> list[tuple[str, str]]:
    rows = [
        ("Наименование", company.full_name or company.name),
        ("ИНН / КПП", f"{company.inn} / {company.kpp}" if company.kpp else company.inn),
        ("ОГРН / ОГРНИП", company.ogrn),
        ("Юридический адрес", company.legal_address),
    ]
    if company.head_full_name:
        rows.append(("Руководитель", f"{company.head_full_name}, {company.head_position or ''}"))
    return rows


def contract_pdf(data: ContractData) -> bytes:
    c = data.contract
    pdf = _Pdf(f"Кредитный договор {c.contract_number}")
    pdf.heading(f"Кредитный договор № {c.contract_number}")
    pdf.paragraph(
        f"Дата: {_d(c.signed_at or c.created_at)}. Заявка {data.application.number}. "
        f"Статус: {STATUS_LABELS.get(c.status, str(c.status))}."
    )
    pdf.heading("1. Заёмщик", 11)
    pdf.pairs(_borrower(data.company))
    pdf.heading("2. Условия кредита", 11)
    pdf.pairs(_terms(data))
    if data.conditions:
        pdf.heading("3. Дополнительные условия", 11)
        pdf.paragraph("\n".join(f"• {text}" for text in data.conditions))
    pdf.heading(f"{4 if data.conditions else 3}. Подписание", 11)
    if c.signed_at:
        pdf.paragraph(
            f"Договор подписан простой электронной подписью {_d(c.signed_at)}, "
            f"идентификатор подписи {c.signature_id}. Средства зачислены на счёт "
            f"{c.settlement_account_number or '—'}"
            + (
                f", операция {c.disbursement_transaction_id}."
                if c.disbursement_transaction_id
                else "."
            )
        )
    else:
        pdf.paragraph("Проект договора. Подписание - в кабинете, кодом подтверждения.")
    pdf.add_page()
    pdf.heading("Приложение. График платежей", 12)
    pdf.schedule(data.schedule)
    return bytes(pdf.output())


def schedule_pdf(data: ContractData) -> bytes:
    c = data.contract
    pdf = _Pdf(f"График платежей {c.contract_number}")
    pdf.heading(f"График платежей по договору № {c.contract_number}")
    pdf.paragraph(
        f"{data.company.name}, ИНН {data.company.inn}. {_rub(c.principal_amount)} на "
        f"{c.term_months} мес. под {_rate(c.interest_rate)}, ежемесячный платёж "
        f"{_rub(c.monthly_payment)}."
    )
    pdf.schedule(data.schedule)
    return bytes(pdf.output())


# --- XLSX ---

_XLSX_EPOCH = date(1899, 12, 30)


def _cell(ref: str, value: object, style: int = 0) -> str:
    if isinstance(value, date):
        return f'<c r="{ref}" s="1"><v>{(value - _XLSX_EPOCH).days}</v></c>'
    if isinstance(value, Decimal):
        return f'<c r="{ref}" s="{style or 2}"><v>{value}</v></c>'
    if isinstance(value, int):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t>{text}</t></is></c>'


def _row(number: int, values: list[object], style: int = 0) -> str:
    cells = "".join(
        _cell(f"{chr(ord('A') + i)}{number}", v, style if not isinstance(v, date) else 0)
        for i, v in enumerate(values)
        if v is not None
    )
    return f'<row r="{number}">{cells}</row>'


def schedule_xlsx(data: ContractData) -> bytes:
    """График платежей: шапка с условиями и таблица с числами и датами (формулы итогов)."""
    c = data.contract
    rows = [
        _row(1, [f"График платежей по договору № {c.contract_number}"], 3),
        _row(2, ["Заёмщик", f"{data.company.name}, ИНН {data.company.inn}"]),
        _row(3, ["Сумма кредита", c.principal_amount]),
        _row(4, ["Срок, мес.", c.term_months]),
        _row(5, ["Ставка, % годовых", c.interest_rate]),
        _row(6, ["Ежемесячный платёж", c.monthly_payment]),
        _row(8, ["№", "Дата", "Основной долг", "Проценты", "Платёж", "Остаток долга"], 3),
    ]
    first = 9
    for offset, item in enumerate(data.schedule):
        rows.append(
            _row(
                first + offset,
                [
                    item.installment_no,
                    item.due_date,
                    item.principal_amount,
                    item.interest_amount,
                    item.total_amount,
                    item.balance_after,
                ],
            )
        )
    last = first + len(data.schedule) - 1
    total = last + 1
    totals = "".join(
        f'<c r="{col}{total}" s="2"><f>SUM({col}{first}:{col}{last})</f></c>' for col in "CDE"
    )
    rows.append(
        f'<row r="{total}"><c r="B{total}" t="inlineStr" s="3"><is><t>Итого</t></is></c>'
        f"{totals}</row>"
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols><col min="1" max="1" width="22" customWidth="1"/>'
        '<col min="2" max="6" width="18" customWidth="1"/></cols>'
        f"<sheetData>{''.join(rows)}</sheetData></worksheet>"
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="График" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/styles" Target="styles.xml"/></Relationships>'
        ),
        # Стили: 0 - обычный, 1 - дата, 2 - сумма, 3 - жирный заголовок
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            "</cellStyleXfs>"
            '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
            '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="4" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" applyFont="1"/></cellXfs>'
            "</styleSheet>"
        ),
        "xl/worksheets/sheet1.xml": sheet,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def filename(data: ContractData, kind: str, extension: str) -> str:
    number = data.contract.contract_number.replace("/", "-")
    return f"{kind} {number}.{extension}"


async def export(
    session: AsyncSession, application: Application, document: str, file_format: str
) -> tuple[bytes, str, str]:
    """document: contract (PDF договора с графиком) | schedule (PDF или XLSX графика)."""
    data = await contract_data(session, application)
    if document == "contract":
        return contract_pdf(data), "application/pdf", filename(data, "Кредитный договор", "pdf")
    if file_format == "xlsx":
        return (
            schedule_xlsx(data),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename(data, "График платежей", "xlsx"),
        )
    return schedule_pdf(data), "application/pdf", filename(data, "График платежей", "pdf")
