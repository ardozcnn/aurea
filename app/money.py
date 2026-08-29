"""Euro tutarlarını resmi Türkçe gösterime çevirir."""


def format_eur(value) -> str:
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if amount != amount:
        return "—"
    if amount >= 1_000_000:
        n = amount / 1_000_000
        text = f"{n:.1f}".replace(".", ",")
        if text.endswith(",0"):
            text = text[:-2]
        return f"{text} milyon €"
    if amount >= 1_000:
        n = amount / 1_000
        text = f"{n:.0f}".replace(".", ",")
        return f"{text} bin €"
    return f"{int(round(amount))} €"


def format_pct(value, signed: bool = True) -> str:
    if value is None:
        return "—"
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n != n:
        return "—"
    body = f"{abs(n):.0f}".replace(".", ",")
    if signed:
        if n > 0.5:
            return f"+%{body}"
        if n < -0.5:
            return f"−%{body}"
        return "%0"
    return f"%{body}"


def gap_direction(gap_pct) -> str:
    if gap_pct is None:
        return "belirsiz"
    if gap_pct <= -12:
        return "dusuk"
    if gap_pct >= 12:
        return "yuksek"
    return "denge"
