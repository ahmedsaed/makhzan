"""Jinja filters for the dashboard's templates: ages, numbers, percentages."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal


def _when(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value if isinstance(value, datetime) else None


def age(value, empty: str = "never") -> str:
    """'8h ago', '3d ago', as `make status` words it."""
    moment = _when(value)
    if moment is None:
        return empty
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 0:
        return "in the future"
    hours = seconds / 3600
    if hours < 1:
        return f"{seconds / 60:.0f}m ago"
    if hours < 48:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


def age_days(value) -> int | None:
    moment = _when(value)
    if moment is None:
        return None
    return int((datetime.now(timezone.utc) - moment).total_seconds() // 86400)


def dt(value, fmt: str = "%d %b %Y %H:%M") -> str:
    moment = _when(value)
    return moment.strftime(fmt) if moment else ""


def num(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    if isinstance(value, (int, float, Decimal)):
        return f"{int(value):,}" if float(value).is_integer() else f"{value:,}"
    return str(value)


def pct(part, whole) -> int:
    return round(100 * part / whole) if whole else 0


def money(value, currency: str | None = None) -> str:
    # A report snapshot's offer may carry no price at all (Jinja's Undefined).
    if not isinstance(value, (int, float, Decimal, str)) or value == "":
        return "no price"
    try:
        amount = f"{Decimal(str(value)):,.2f}".rstrip("0").rstrip(".")
    except ArithmeticError:
        return str(value)
    return f"{amount} {currency or 'EGP'}"


def short(value, n: int = 8) -> str:
    return str(value)[:n] if value else ""


filters = {
    "age": age,
    "age_days": age_days,
    "dt": dt,
    "num": num,
    "pct": pct,
    "money": money,
    "short": short,
}
