"""Схемы запросов API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MONTHS = 12


class RowIn(BaseModel):
    """Новая или изменённая строка бюджета."""
    budget_id: int | None = None
    cfo_id: int | None = None
    budget_name: str = "Основной бюджет"
    article: str = Field(min_length=1)
    counterparty: str = ""
    contract: str = ""
    detail: str = ""
    comment: str = ""
    approver_comment: str = ""
    plan_year: float = 0
    carryover: bool = True
    months: list[float] | None = None
    spread: Literal["even", "one", "none"] = "even"
    month: int | None = None

    @field_validator("article")
    @classmethod
    def article_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Укажите статью оборотов")
        return value.strip()

    @field_validator("plan_year")
    @classmethod
    def plan_not_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Годовая сумма не может быть отрицательной")
        return value

    def month_plan(self) -> list[float]:
        """Разбивка годовой суммы по месяцам согласно выбранному режиму."""
        if self.months is not None:
            out = [float(v or 0) for v in self.months][:MONTHS]
            return out + [0.0] * (MONTHS - len(out))
        out = [0.0] * MONTHS
        if self.spread == "even" and self.plan_year:
            for i in range(MONTHS):
                out[i] = self.plan_year / MONTHS
        elif self.spread == "one" and self.plan_year and self.month:
            out[max(1, min(MONTHS, self.month)) - 1] = self.plan_year
        return out


class FactIn(BaseModel):
    """Ручной расход, привязанный к строке бюджета."""
    row_id: int | None = None
    cfo_id: int | None = None
    pay_date: str
    amount: float = Field(gt=0)
    article: str = ""
    counterparty: str = ""
    contract: str = ""
    purpose: str = ""
    claim_number: str = ""
    out_of_budget: bool = False


class ClaimIn(BaseModel):
    """Заявка — обязательство, уменьшающее свободный лимит."""
    row_id: int | None = None
    cfo_id: int
    number_1c: str = ""
    pay_date: str
    amount: float = Field(gt=0)
    counterparty: str = ""
    contract: str = ""
    detail: str = ""
    out_of_budget: bool = False


class TransferIn(BaseModel):
    """Перенос лимита: между месяцами внутри строки или между строками ЦФО."""
    kind: Literal["month", "row"]
    from_row_id: int
    to_row_id: int | None = None
    from_month: int | None = None
    to_month: int | None = None
    amount: float = Field(gt=0)
    reason: str = Field(min_length=3)


class MatchIn(BaseModel):
    row_id: int


class SettingsIn(BaseModel):
    year: int | None = None
    closed_through: int | None = Field(default=None, ge=0, le=12)
    as_of: str | None = None
    pace_warning_pp: float | None = None

class MergeIn(BaseModel):
    """Сведение дублей справочника: данные source переезжают в target."""
    source_id: int
    target_id: int


class RenameIn(BaseModel):
    name: str = Field(min_length=2)


class AliasIn(BaseModel):
    alias: str = Field(min_length=2)
