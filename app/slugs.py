"""Paylaşılabilir yol ve Transfermarkt adresi çözümlemesi."""

from __future__ import annotations

import re

_FOLD = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "I": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)
_TM_ID = re.compile(r"(?:spieler|player)/(\d+)", re.IGNORECASE)
_LEADING_ID = re.compile(r"^(\d+)")


def fold_tr(text: str) -> str:
    return str(text or "").translate(_FOLD).casefold()


def slugify(text: str, limit: int = 56) -> str:
    raw = fold_tr(text)
    out: list[str] = []
    dash = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            dash = False
        elif out and not dash:
            out.append("-")
            dash = True
    return "".join(out).strip("-")[:limit].strip("-")


def player_slug(player_id, name: str) -> str:
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return slugify(name) or "oyuncu"
    body = slugify(name)
    return f"{pid}-{body}" if body else str(pid)


def player_path(player_id, name: str) -> str:
    return "/oyuncu/" + player_slug(player_id, name)


def parse_id_token(token: str) -> int | None:
    found = _LEADING_ID.match(str(token or "").strip())
    if not found:
        return None
    return int(found.group(1))


def parse_tm_id(text: str) -> int | None:
    raw = str(text or "").strip()
    found = _TM_ID.search(raw)
    if found:
        return int(found.group(1))
    if raw.isdigit() and 2 <= len(raw) <= 9:
        return int(raw)
    return None


def club_token(club_id, name: str, league_id: str = "") -> str:
    try:
        if club_id is not None and club_id == club_id:
            number = int(float(club_id))
            if number > 0:
                return f"c{number}"
    except (TypeError, ValueError):
        pass
    body = slugify(name) or "kulup"
    lig = slugify(str(league_id or ""), 8)
    return f"n-{lig}-{body}" if lig else f"n-{body}"


def club_path(club_id, name: str, league_id: str = "") -> str:
    return "/kulup/" + club_token(club_id, name, league_id)


def is_free_agent(name: str) -> bool:
    n = fold_tr(name).replace(" ", "").replace("-", "")
    if not n:
        return True
    return any(
        key in n
        for key in (
            "withoutclub",
            "vereinslos",
            "ohneverein",
            "freeagent",
            "unattached",
            "kulupsuz",
            "noclub",
        )
    )


def club_display(name: str) -> str:
    raw = str(name or "").strip()
    if is_free_agent(raw):
        return "Kulüpsüz"
    if not raw:
        return ""
    if raw.isupper() and len(raw) > 3:
        raw = raw.title()
    elif raw == raw.lower():
        bits: list[str] = []
        for part in re.split(r"(\s+|-|/)", raw):
            if not part or part in {" ", "-", "/"} or part.isspace():
                bits.append(part)
            else:
                bits.append(part[:1].upper() + part[1:])
        raw = "".join(bits)
    return raw
