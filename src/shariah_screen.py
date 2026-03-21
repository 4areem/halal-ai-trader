"""Shariah compliance screening per AAOIFI Standard No. 21."""

from dataclasses import dataclass

from src.config import MAX_DEBT_RATIO, MAX_SECURITIES_RATIO, MAX_IMPURE_REVENUE

PROHIBITED_INDUSTRIES = {
    "alcohol",
    "pork",
    "conventional_banking",
    "insurance",
    "gambling",
    "adult_entertainment",
    "tobacco",
    "weapons_defense",
}


@dataclass
class ShariahResult:
    ticker: str
    compliant: bool
    core_business: str
    core_business_pass: bool
    debt_ratio: float | None
    debt_ratio_pass: bool
    securities_ratio: float | None
    securities_ratio_pass: bool
    impure_revenue: float | None
    impure_revenue_pass: bool
    purification_rate: float
    notes: str = ""

    @property
    def status(self) -> str:
        if self.compliant:
            return "COMPLIANT"
        return "NON-COMPLIANT"


def check_industry(sector: str) -> bool:
    """Return True if the industry is permissible."""
    return sector.lower().replace(" ", "_") not in PROHIBITED_INDUSTRIES


def check_financial_ratios(
    debt_ratio: float,
    securities_ratio: float,
    impure_revenue: float,
) -> tuple[bool, bool, bool]:
    """Check the three AAOIFI financial ratios. Returns (debt_ok, securities_ok, revenue_ok)."""
    return (
        debt_ratio < MAX_DEBT_RATIO,
        securities_ratio < MAX_SECURITIES_RATIO,
        impure_revenue < MAX_IMPURE_REVENUE,
    )


def screen_stock(
    ticker: str,
    core_business: str,
    sector: str,
    debt_ratio: float | None = None,
    securities_ratio: float | None = None,
    impure_revenue: float | None = None,
) -> ShariahResult:
    """Run full Shariah compliance screen on a stock."""
    industry_ok = check_industry(sector)

    if not industry_ok:
        return ShariahResult(
            ticker=ticker,
            compliant=False,
            core_business=core_business,
            core_business_pass=False,
            debt_ratio=debt_ratio,
            debt_ratio_pass=False,
            securities_ratio=securities_ratio,
            securities_ratio_pass=False,
            impure_revenue=impure_revenue,
            impure_revenue_pass=False,
            purification_rate=0.0,
            notes=f"Prohibited industry: {sector}",
        )

    if debt_ratio is None or securities_ratio is None or impure_revenue is None:
        return ShariahResult(
            ticker=ticker,
            compliant=False,
            core_business=core_business,
            core_business_pass=True,
            debt_ratio=debt_ratio,
            debt_ratio_pass=False,
            securities_ratio=securities_ratio,
            securities_ratio_pass=False,
            impure_revenue=impure_revenue,
            impure_revenue_pass=False,
            purification_rate=0.0,
            notes="Missing financial data for screening",
        )

    debt_ok, sec_ok, rev_ok = check_financial_ratios(
        debt_ratio, securities_ratio, impure_revenue
    )

    compliant = debt_ok and sec_ok and rev_ok
    purification_rate = impure_revenue if compliant else 0.0

    return ShariahResult(
        ticker=ticker,
        compliant=compliant,
        core_business=core_business,
        core_business_pass=True,
        debt_ratio=debt_ratio,
        debt_ratio_pass=debt_ok,
        securities_ratio=securities_ratio,
        securities_ratio_pass=sec_ok,
        impure_revenue=impure_revenue,
        impure_revenue_pass=rev_ok,
        purification_rate=purification_rate,
        notes="" if compliant else "Failed financial ratio screening",
    )
