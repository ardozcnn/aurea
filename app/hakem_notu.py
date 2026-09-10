"""Süper Lig orta hakem maç notu: puan motoru ve editöryal katalog."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.hakem_harvest import harvest_status, load_merged_catalog

START_SCORE = 100
IMPACT_PENALTY = {"LOW": 2, "MEDIUM": 5, "HIGH": 10, "CRITICAL": 15}
CONFIDENCE_FACTOR = {"HIGH_CONFIDENCE_WRONG": 1.0, "HIGH_CONFIDENCE": 1.0, "SPLIT": 0.4, "INSUFFICIENT": 0.0}

ROLE_TR = {
    "CENTER": "Orta hakem",
    "VAR": "VAR",
    "AVAR": "AVAR",
    "ASSISTANT": "Yardımcı hakem",
    "FOURTH": "Dördüncü hakem",
}
IMPACT_TR = {
    "LOW": "Düşük etki",
    "MEDIUM": "Orta etki",
    "HIGH": "Yüksek etki",
    "CRITICAL": "Kritik",
}
VERDICT_TR = {
    "CORRECT": "Doğru",
    "INCORRECT": "Hatalı",
    "DEBATABLE": "Tartışmalı",
    "OPEN_REVIEW": "İncelemeye açık",
}
CONFIDENCE_TR = {
    "HIGH_CONFIDENCE_WRONG": "Yüksek güvenle yanlış",
    "HIGH_CONFIDENCE": "Yüksek güvenle doğru",
    "SPLIT": "Uzmanlar bölünmüş",
    "INSUFFICIENT": "Yeterli kanıt yok",
}
EVENT_TR = {
    "PENALTY": "Penaltı",
    "RED_CARD": "Kırmızı kart",
    "YELLOW_CARD": "Sarı kart",
    "GOAL": "Gol",
    "OFFSIDE": "Ofsayt",
    "FOUL": "Faul",
    "VAR_CHECK": "VAR incelemesi",
    "TIME_WASTING": "Zaman kaybı",
    "ADVANTAGE": "Avantaj",
}
SOURCE_TR = {
    "OFFICIAL": "Resmî",
    "EXPERT_COMMENTARY": "Uzman yorumu",
    "NEWS": "Haber",
    "COMMUNITY": "Topluluk",
}

CATALOG_PATH = DATA_DIR / "hakem_notu.json"
CORRECTIONS_PATH = DATA_DIR / "hakem_notu_corrections.json"


def round_penalty(value: float) -> float:
    return round(value * 10) / 10


def clamp_score(value: float) -> int:
    return max(0, min(START_SCORE, int(round(value))))


def format_tr(value: float) -> str:
    return str(value).replace(".", ",")


def can_create_rating(role: str) -> bool:
    return role == "CENTER"


def penalty_for_incident(incident: dict[str, Any]) -> dict[str, Any]:
    verdict = incident.get("editorialVerdict") or incident.get("editorial_verdict")
    impact = incident.get("impactLevel") or incident.get("impact_level")
    confidence = incident.get("confidence")
    base = IMPACT_PENALTY[impact]
    factor = CONFIDENCE_FACTOR[confidence]

    if verdict == "CORRECT":
        return {
            "penalty": 0.0,
            "countsAsCorrect": True,
            "countsAsIncorrect": False,
            "countsAsDebatable": False,
            "countsAsOpenReview": False,
        }
    if verdict == "OPEN_REVIEW" or confidence == "INSUFFICIENT":
        return {
            "penalty": 0.0,
            "countsAsCorrect": False,
            "countsAsIncorrect": False,
            "countsAsDebatable": False,
            "countsAsOpenReview": True,
        }
    raw = round_penalty(base * factor)
    debatable = verdict == "DEBATABLE" or confidence == "SPLIT"
    return {
        "penalty": raw,
        "countsAsCorrect": False,
        "countsAsIncorrect": (not debatable) and raw > 0,
        "countsAsDebatable": debatable,
        "countsAsOpenReview": False,
    }


def rate_match(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [penalty_for_incident(item) for item in incidents]
    total_penalty = round_penalty(sum(row["penalty"] for row in rows))
    score = clamp_score(START_SCORE - total_penalty)
    correct = sum(1 for row in rows if row["countsAsCorrect"])
    incorrect = sum(1 for row in rows if row["countsAsIncorrect"])
    debatable = sum(1 for row in rows if row["countsAsDebatable"])
    open_review = sum(1 for row in rows if row["countsAsOpenReview"])

    confidence_level = "HIGH_CONFIDENCE_WRONG"
    if open_review > 0 and incorrect + debatable == 0:
        confidence_level = "INSUFFICIENT"
    elif debatable > 0 or any(item.get("confidence") == "SPLIT" for item in incidents):
        confidence_level = "SPLIT"

    bits = [
        f"Başlangıç 100, toplam kayıp {format_tr(total_penalty)} puan.",
        f"Maç notu {score}/100.",
    ]
    if correct:
        bits.append(f"{correct} karar doğru bulundu.")
    if incorrect:
        bits.append(f"{incorrect} karar hatalı bulundu.")
    if debatable:
        bits.append(f"{debatable} karar tartışmalı.")
    if open_review:
        bits.append(f"{open_review} pozisyon incelemeye açık; puan kesilmedi.")

    return {
        "score": score,
        "totalPenalty": total_penalty,
        "correctDecisionCount": correct,
        "incorrectDecisionCount": incorrect,
        "debatableDecisionCount": debatable,
        "openReviewCount": open_review,
        "confidenceLevel": confidence_level,
        "confidenceLabel": CONFIDENCE_TR[confidence_level],
        "summary": " ".join(bits),
    }


def source_queries(home: str, away: str, season: str, minute: int | None = None) -> list[str]:
    match_name = f"{home} {away}"
    minute_bit = f"{minute}. dakika " if minute else ""
    return [
        f"{home} {away} {season} {minute_bit}tartışmalı pozisyon".replace("  ", " ").strip(),
        f"{match_name} hakem kararı",
        f"{match_name} penaltı kırmızı kart VAR pozisyonu",
    ]


def _load_raw() -> dict[str, Any]:
    return load_merged_catalog()


def _ref_map(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["slug"]: row for row in raw.get("referees") or []}


def _minute_label(minute: int, extra: int | None) -> str:
    if extra:
        return f"{minute}+{extra}′"
    return f"{minute}′"


def _date_label(value: str) -> str:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        months = (
            "Ocak",
            "Şubat",
            "Mart",
            "Nisan",
            "Mayıs",
            "Haziran",
            "Temmuz",
            "Ağustos",
            "Eylül",
            "Ekim",
            "Kasım",
            "Aralık",
        )
        return f"{stamp.day} {months[stamp.month - 1]} {stamp.year}"
    except ValueError:
        return value


def _decorate_source(src: dict[str, Any]) -> dict[str, Any]:
    published = src.get("publishedAt")
    return {
        "title": src.get("title") or src.get("publisher") or "Kaynak bağlantısı",
        "publisher": src.get("publisher") or "",
        "url": src.get("url") or "",
        "sourceType": src.get("sourceType") or "",
        "sourceLabel": SOURCE_TR.get(src.get("sourceType") or "", src.get("sourceType") or ""),
        "excerpt": src.get("excerpt") or "",
        "publishedAt": published,
        "publishedLabel": _date_label(published) if published else "",
    }


def _decorate_incident(incident: dict[str, Any], home: str, away: str, season: str) -> dict[str, Any]:
    scored = penalty_for_incident(incident)
    extra = incident.get("extraMinute")
    skip = {"video", "videoStatus"}
    clean = {key: value for key, value in incident.items() if key not in skip}
    return {
        **clean,
        "penalty": scored["penalty"],
        "minuteLabel": _minute_label(int(incident.get("minute") or 0), extra),
        "eventLabel": EVENT_TR.get(incident.get("eventType") or "", incident.get("eventType") or ""),
        "verdictLabel": VERDICT_TR.get(incident.get("editorialVerdict") or "", ""),
        "impactLabel": IMPACT_TR.get(incident.get("impactLevel") or "", ""),
        "confidenceLabel": CONFIDENCE_TR.get(incident.get("confidence") or "", ""),
        "sources": [
            _decorate_source(src)
            for src in (incident.get("sources") or [])
            if src.get("approved", True) and src.get("sourceType") != "VIDEO"
        ],
    }


def _build_match(raw_match: dict[str, Any], refs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    officials = []
    for row in raw_match.get("officials") or []:
        ref = refs.get(row["refereeSlug"]) or {"firstName": "?", "lastName": "", "slug": row["refereeSlug"]}
        officials.append(
            {
                "role": row["role"],
                "roleLabel": ROLE_TR.get(row["role"], row["role"]),
                "scored": can_create_rating(row["role"]),
                "referee": {
                    "slug": ref.get("slug"),
                    "name": f"{ref.get('firstName', '')} {ref.get('lastName', '')}".strip(),
                    "firstName": ref.get("firstName"),
                    "lastName": ref.get("lastName"),
                    "bio": ref.get("bio") or "",
                    "isDemo": bool(ref.get("isDemo", False)),
                },
            }
        )
    center = next((row for row in officials if row["role"] == "CENTER"), None)
    home = raw_match["home"]["name"]
    away = raw_match["away"]["name"]
    season = raw_match["season"]
    incidents = [
        _decorate_incident(item, home, away, season) for item in (raw_match.get("incidents") or [])
    ]
    rating = None
    if center and can_create_rating("CENTER"):
        rating = rate_match(raw_match.get("incidents") or [])
        rating["referee"] = center["referee"]
    match_sources = [
        _decorate_source(src)
        for src in (raw_match.get("sources") or [])
        if src.get("approved", True) and src.get("sourceType") != "VIDEO"
    ]
    return {
        "slug": raw_match["slug"],
        "season": raw_match["season"],
        "week": raw_match["week"],
        "playedAt": raw_match["playedAt"],
        "playedLabel": _date_label(raw_match["playedAt"]),
        "stadium": raw_match["stadium"],
        "home": raw_match["home"],
        "away": raw_match["away"],
        "homeScore": raw_match["homeScore"],
        "awayScore": raw_match["awayScore"],
        "title": f"{home} – {away}",
        "scoreline": f"{raw_match['homeScore']}–{raw_match['awayScore']}",
        "isDemo": bool(raw_match.get("isDemo", False)),
        "officials": officials,
        "incidents": incidents,
        "sources": match_sources,
        "rating": rating,
        "href": f"/hakem-notu/maclar/{raw_match['slug']}",
    }


def catalog() -> dict[str, Any]:
    raw = _load_raw()
    refs = _ref_map(raw)
    matches = [_build_match(row, refs) for row in raw.get("matches") or []]
    matches.sort(key=lambda row: row["playedAt"], reverse=True)
    return {"referees": list(refs.values()), "matches": matches}


def _noted_match(match: dict[str, Any]) -> bool:
    """Uzman kararı yoksa 100’lük otomatik maç notlanmış sayılmaz."""
    return bool(match.get("rating") and match.get("incidents"))


def home_pack() -> dict[str, Any]:
    pack = catalog()
    matches = pack["matches"]
    rated = [row for row in matches if _noted_match(row)]
    ranked = sorted(
        rated,
        key=lambda row: row["rating"]["score"],
        reverse=True,
    )
    scores = [row["rating"]["score"] for row in rated]
    decision_counts = {
        "correct": sum(row["rating"]["correctDecisionCount"] for row in rated),
        "incorrect": sum(row["rating"]["incorrectDecisionCount"] for row in rated),
        "debatable": sum(row["rating"]["debatableDecisionCount"] for row in rated),
        "openReview": sum(row["rating"]["openReviewCount"] for row in rated),
    }
    incidents = []
    for match in matches:
        for incident in match["incidents"]:
            if incident.get("editorialVerdict") in {"INCORRECT", "DEBATABLE", "OPEN_REVIEW"}:
                incidents.append(
                    {
                        **incident,
                        "matchTitle": match["title"],
                        "href": match["href"],
                    }
                )
    return {
        "disclaimer": (
            "Bu içerik resmî bir MHK veya TFF hakem notu değildir. "
            "Bitmiş maçlar otomatik alınır. Hatalı ve tartışmalı kararlar "
            "eski hakem köşeleri (Aydınus, Çakar, Çulcu, Bitnel, Akçer, Toroğlu) ve beIN Trio metinlerinden okunur."
        ),
        "harvest": harvest_status(),
        "matches": matches,
        "summary": {
            "matchCount": len(matches),
            "ratedMatchCount": len(rated),
            "averageScore": int(round(sum(scores) / len(scores))) if scores else None,
            "decisionCount": sum(decision_counts.values()),
            "decisionCounts": decision_counts,
            "incidentCount": sum(len(row["incidents"]) for row in matches),
        },
        "highest": ranked[:3],
        "lowest": list(reversed(ranked[-3:])) if ranked else [],
        "incidents": incidents[:8],
        "impactTable": [
            {"id": "LOW", "label": IMPACT_TR["LOW"], "penalty": IMPACT_PENALTY["LOW"], "example": "Yanlış sarı"},
            {"id": "MEDIUM", "label": IMPACT_TR["MEDIUM"], "penalty": IMPACT_PENALTY["MEDIUM"], "example": "Kaçırılan taktik faul"},
            {"id": "HIGH", "label": IMPACT_TR["HIGH"], "penalty": IMPACT_PENALTY["HIGH"], "example": "Yanlış ofsayt / ikinci sarı"},
            {"id": "CRITICAL", "label": IMPACT_TR["CRITICAL"], "penalty": IMPACT_PENALTY["CRITICAL"], "example": "Penaltı, kırmızı, gol"},
        ],
    }


def match_pack(slug: str) -> dict[str, Any] | None:
    for row in catalog()["matches"]:
        if row["slug"] == slug:
            return row
    return None


def referee_list() -> list[dict[str, Any]]:
    pack = catalog()
    out = []
    for ref in pack["referees"]:
        ratings = [
            match
            for match in pack["matches"]
            if _noted_match(match) and match["rating"]["referee"]["slug"] == ref["slug"]
        ]
        if not ratings:
            continue
        scores = [row["rating"]["score"] for row in ratings]
        avg = int(round(sum(scores) / len(scores)))
        out.append(
            {
                **ref,
                "name": f"{ref['firstName']} {ref['lastName']}".strip(),
                "matchCount": len(ratings),
                "average": avg,
                "href": f"/hakem-notu/hakemler/{ref['slug']}",
            }
        )
    out.sort(key=lambda row: row["lastName"])
    return out


def referee_pack(slug: str) -> dict[str, Any] | None:
    pack = catalog()
    ref = next((row for row in pack["referees"] if row["slug"] == slug), None)
    if not ref:
        return None
    ratings = [
        {
            "slug": match["slug"],
            "title": match["title"],
            "playedLabel": match["playedLabel"],
            "season": match["season"],
            "week": match["week"],
            "href": match["href"],
            "score": match["rating"]["score"],
            "summary": match["rating"]["summary"],
            "incidents": match["incidents"],
        }
        for match in pack["matches"]
        if match.get("rating") and match["rating"]["referee"]["slug"] == slug
    ]
    ratings.sort(key=lambda row: row["week"])
    if not ratings:
        return {
            **ref,
            "name": f"{ref['firstName']} {ref['lastName']}".strip(),
            "ratings": [],
            "average": None,
        }
    scores = [row["score"] for row in ratings]
    avg = int(round(sum(scores) / len(scores)))
    best = max(ratings, key=lambda row: row["score"])
    worst = min(ratings, key=lambda row: row["score"])
    incidents = [item for row in ratings for item in row["incidents"]]
    by_verdict: dict[str, int] = {}
    by_event: dict[str, int] = {}
    for item in incidents:
        key = item.get("editorialVerdict") or ""
        by_verdict[key] = by_verdict.get(key, 0) + 1
        if key != "CORRECT":
            event = item.get("eventType") or ""
            by_event[event] = by_event.get(event, 0) + 1
    return {
        **ref,
        "name": f"{ref['firstName']} {ref['lastName']}".strip(),
        "ratings": ratings,
        "average": avg,
        "best": best,
        "worst": worst,
        "chart": [{"label": f"{row['week']}.hf", "score": row["score"]} for row in ratings],
        "byVerdict": [
            {"id": key, "label": VERDICT_TR.get(key, key), "count": value} for key, value in by_verdict.items()
        ],
        "byEvent": [
            {"id": key, "label": EVENT_TR.get(key, key), "count": value} for key, value in by_event.items()
        ],
        "seasons": sorted({row["season"] for row in ratings}),
    }


def method_pack() -> dict[str, Any]:
    return {
        "title": "Hakem Notu yöntemi",
        "lede": (
            "Her maç 100 ile başlar. Yalnızca orta hakemin sahadaki kararları düşülür. "
            "VAR, yardımcı hakem ve dördüncü hakem kadroda görünür; nota girmez."
        ),
        "disclaimer": (
            "Bu içerik resmî hakem değerlendirmesi değildir. Kararlar TFF maç kaydı, "
            "IFAB kural metni ve uzman yorumuyla incelenir. Görüntü veya fotoğraf kopyalanmaz."
        ),
        "table": [
            {"label": "Düşük etki", "penalty": 2, "example": "Yanlış sarı, küçük usul hatası"},
            {"label": "Orta etki", "penalty": 5, "example": "Kaçırılan taktik faul"},
            {"label": "Yüksek etki", "penalty": 10, "example": "Yanlış ofsayt / ikinci sarı"},
            {"label": "Kritik", "penalty": 15, "example": "Penaltı, kırmızı, gol, maç sonucunu etkileyebilecek hata"},
        ],
        "confidence": [
            "Yüksek güvenle yanlış: cezanın %100’ü",
            "Uzmanlar bölünmüş / tartışmalı: cezanın %40’ı",
            "Yeterli kanıt yok: 0 puan, “incelemeye açık”",
            "Not 0’ın altına inmez.",
        ],
        "sources": (
            "Bitmiş Süper Lig maçları, skor ve orta hakem kaydı her birkaç saatte bir otomatik alınır. "
            "Hatalı veya tartışmalı karar, yayımlanmış eski hakem yorumuna dayanır: beIN Trio yanı sıra "
            "Fırat Aydınus, Ahmet Çakar, Mustafa Çulcu, Deniz Ateş Bitnel, Serdar Akçer, Erman Toroğlu gibi köşe ve açıklamalar. "
            "Tek uzman veya dakika yoksa puan kesilmez; incelemeye açık kalır. "
            "Oyuncu/kulüp itirazı tek başına puan kesmez. Telifli video veya fotoğraf gösterilmez."
        ),
        "matches": [
            {"id": row["slug"], "label": f"{row['title']} ({row['week']}. hf)"}
            for row in catalog()["matches"]
        ],
    }


def save_correction(name: str, email: str, message: str, match_id: str | None = None) -> dict[str, str]:
    rows: list[dict[str, Any]] = []
    if CORRECTIONS_PATH.exists():
        try:
            rows = json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            rows = []
    rows.append(
        {
            "name": name,
            "email": email,
            "message": message,
            "matchId": match_id or None,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CORRECTIONS_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}
