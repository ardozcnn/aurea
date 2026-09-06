"""Adil Değer web API ve arayüz sunucusu."""

from __future__ import annotations

import threading

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import status as st
from app.config import MODELS_DIR, WEB_DIR
from app.fantasy_bridge import account_public as fantasy_account
from app.fantasy_bridge import last_payload as fantasy_last
from app.fantasy_bridge import load_cached as fantasy_load_cached
from app.fantasy_bridge import login_account as fantasy_login
from app.fantasy_bridge import logout_account as fantasy_logout
from app.fantasy_bridge import start as fantasy_start
from app.fantasy_bridge import status as fantasy_status
from app.hakem_harvest import harvest_status as hakem_harvest_status
from app.hakem_harvest import start_harvest_async as hakem_start_harvest
from app.hakem_harvest import start_scheduler as hakem_start_scheduler
from app.hakem_notu import home_pack as hakem_home
from app.hakem_notu import match_pack as hakem_match
from app.hakem_notu import method_pack as hakem_method
from app.hakem_notu import referee_list as hakem_referees
from app.hakem_notu import referee_pack as hakem_referee
from app.hakem_notu import save_correction as hakem_save_correction
from app.method import method_pack
from app.model import load_engine, train_engine
from app.store import (
    calibration_pack,
    club_list,
    club_roster,
    compare_pack,
    leagues,
    market,
    player_detail,
    pulse,
    ready,
    scout,
    search,
    set_store,
    try_load_existing,
)
from app.transfers import desk as superlig_desk
from app.warehouse import bootstrap

app = FastAPI(title="Aurea", version="0.6.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

_BOOT_LOCK = threading.Lock()
_BOOT_THREAD: threading.Thread | None = None


def _run_bootstrap() -> None:
    try:
        st.set_state(phase="start", message="Kurulum başladı.", progress=0.01, error=None)
        frame = bootstrap()
        engine = load_engine()
        if engine is None:
            st.set_state(phase="train", message="sklearn motoru eğitiliyor. Bu işlem bir kez yapılır.", progress=0.945)
            engine = train_engine(frame)
        set_store(frame, engine)
        st.set_state(phase="ready", message="Motor hazır.", progress=1.0, error=None)
    except Exception as extra:
        st.set_state(phase="error", message="Kurulum başarısız.", error=str(extra))


def start_bootstrap() -> None:
    global _BOOT_THREAD
    with _BOOT_LOCK:
        if ready():
            st.set_state(phase="ready", message="Motor hazır.", progress=1.0, error=None)
            return
        if _BOOT_THREAD and _BOOT_THREAD.is_alive():
            return
        _BOOT_THREAD = threading.Thread(target=_run_bootstrap, daemon=True)
        _BOOT_THREAD.start()


@app.on_event("startup")
def _startup() -> None:
    st.load_persisted()
    fantasy_load_cached()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    hakem_start_scheduler()
    if try_load_existing():
        st.set_state(phase="ready", message="Kayıtlı motor yüklendi.", progress=1.0, error=None)
        return
    start_bootstrap()


@app.api_route("/", methods=["GET", "HEAD"])
def home(request: Request):
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/html")
    return FileResponse(WEB_DIR / "index.html")


@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return Response(status_code=200, content="ok", media_type="text/plain")


@app.get("/api/status")
def api_status():
    snap = st.snapshot()
    snap["ready"] = ready()
    return snap


@app.post("/api/bootstrap")
def api_bootstrap():
    start_bootstrap()
    return {"ok": True, "status": st.snapshot()}


@app.get("/api/search")
def api_search(
    q: str = Query("", min_length=0),
    league: str | None = None,
    position: str | None = None,
    age_min: int | None = None,
    age_max: int | None = None,
    live: bool = False,
):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return {
        "results": search(
            q,
            league=league,
            position=position,
            age_min=age_min,
            age_max=age_max,
            live=live,
        )
    }


@app.get("/api/pulse")
def api_pulse():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return pulse()


@app.get("/api/leagues")
def api_leagues():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return {"leagues": leagues()}


@app.get("/api/market")
def api_market(
    league: str | None = None,
    position: str | None = None,
    direction: str | None = None,
    q: str | None = None,
    sort: str = "true_value",
    order: str = "desc",
    page: int = 1,
    min_minutes: int = 0,
    age_min: int | None = None,
    age_max: int | None = None,
):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return market(
        league=league,
        position=position,
        direction=direction,
        q=q,
        sort=sort,
        order=order,
        page=page,
        min_minutes=min_minutes,
        age_min=age_min,
        age_max=age_max,
    )


@app.get("/api/superlig")
def api_superlig(refresh: bool = False):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    try:
        return superlig_desk(refresh=refresh)
    except Exception as extra:
        raise HTTPException(502, f"Süper Lig transferleri alınamadı: {extra}") from extra


@app.get("/api/scout")
def api_scout():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    try:
        return scout()
    except Exception as extra:
        raise HTTPException(502, f"Scout listesi alınamadı: {extra}") from extra


@app.get("/api/players/{player_id}")
def api_player(player_id: int, live: bool = True):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    try:
        return player_detail(player_id, live=live)
    except KeyError:
        raise HTTPException(404, "Oyuncu bulunamadı.")
    except Exception as extra:
        raise HTTPException(502, f"Oyuncu dosyası alınamadı: {extra}") from extra


@app.get("/api/players/{player_id}/pdf")
def api_player_pdf(player_id: int):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    try:
        pack = player_detail(player_id, live=True)
    except KeyError:
        raise HTTPException(404, "Oyuncu bulunamadı.")
    except Exception as extra:
        raise HTTPException(502, f"Oyuncu dosyası alınamadı: {extra}") from extra
    try:
        from app.pdf_report import build_player_pdf

        data = build_player_pdf(pack)
    except Exception as extra:
        raise HTTPException(500, f"PDF üretilemedi: {extra}") from extra
    name = (pack.get("player") or {}).get("name") or f"oyuncu-{player_id}"
    slug = "".join(ch if ch.isalnum() else "-" for ch in str(name))[:48].strip("-")
    filename = f"aurea-{slug or player_id}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/clubs")
def api_clubs():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return club_list()


@app.get("/api/clubs/{token}")
def api_club(token: str):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    try:
        return club_roster(token)
    except KeyError:
        raise HTTPException(404, "Kulüp bulunamadı.")


@app.get("/api/compare")
def api_compare(left: int = Query(...), right: int = Query(...)):
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    if left == right:
        raise HTTPException(400, "İki farklı oyuncu seçin.")
    try:
        return compare_pack(left, right)
    except KeyError:
        raise HTTPException(404, "Oyuncu bulunamadı.")
    except Exception as extra:
        raise HTTPException(502, f"Karşılaştırma alınamadı: {extra}") from extra


@app.get("/api/yontem")
def api_yontem():
    return method_pack()


@app.get("/api/olcum")
def api_olcum():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    return calibration_pack()


@app.get("/api/model")
def api_model():
    if not ready():
        raise HTTPException(409, "Motor henüz hazır değil.")
    from app.store import engine

    eng = engine()
    return eng.meta if eng else {}


class FantasyLoginIn(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class HakemCorrectionIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    message: str = Field(min_length=10, max_length=4000)
    matchId: str | None = None


@app.get("/api/hakem-notu")
def api_hakem_home():
    return hakem_home()


@app.get("/api/hakem-notu/yontem")
def api_hakem_method():
    return hakem_method()


@app.get("/api/hakem-notu/hakemler")
def api_hakem_referees():
    return {"referees": hakem_referees()}


@app.get("/api/hakem-notu/hakemler/{slug}")
def api_hakem_referee(slug: str):
    pack = hakem_referee(slug)
    if not pack:
        raise HTTPException(404, "Hakem bulunamadı.")
    return pack


@app.get("/api/hakem-notu/maclar/{slug}")
def api_hakem_match(slug: str):
    pack = hakem_match(slug)
    if not pack:
        raise HTTPException(404, "Maç bulunamadı.")
    return pack


@app.get("/api/hakem-notu/hasat")
def api_hakem_harvest_status():
    return hakem_harvest_status()


@app.post("/api/hakem-notu/hasat")
def api_hakem_harvest_start():
    return hakem_start_harvest()


@app.post("/api/hakem-notu/duzeltme")
def api_hakem_correction(body: HakemCorrectionIn):
    return hakem_save_correction(body.name, body.email, body.message, body.matchId)


@app.get("/api/fantasy/status")
def api_fantasy_status():
    snap = fantasy_status()
    snap["account"] = fantasy_account()
    return snap


@app.get("/api/fantasy")
def api_fantasy():
    snap = fantasy_status()
    payload = fantasy_last()
    return {"ok": bool(payload), "status": snap, "payload": payload, "account": fantasy_account()}


@app.post("/api/fantasy/login")
def api_fantasy_login(body: FantasyLoginIn):
    try:
        return fantasy_login(body.email, body.password)
    except Exception as extra:
        from src.tff_client import network_message

        raise HTTPException(401, network_message(extra) or "Giriş başarısız.") from extra


@app.post("/api/fantasy/logout")
def api_fantasy_logout():
    fantasy_logout()
    return {"ok": True}


@app.get("/api/fantasy/account")
def api_fantasy_account():
    data = fantasy_account()
    if not data:
        return {"ok": False}
    return data


@app.post("/api/fantasy/run")
def api_fantasy_run(refresh_cache: bool = False, fetch_prices: bool = True):
    if not fantasy_account():
        raise HTTPException(401, "Önce TFF Fantezi Lig hesabına girin.")
    return fantasy_start(fetch_prices=fetch_prices, refresh_cache=refresh_cache)


@app.get("/favicon.svg")
def favicon():
    path = WEB_DIR / "favicon.svg"
    if path.exists():
        return FileResponse(path)
    return JSONResponse({"detail": "yok"}, status_code=404)


@app.get("/{path:path}")
def spa(path: str):
    candidate = WEB_DIR / path
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(WEB_DIR / "index.html")
