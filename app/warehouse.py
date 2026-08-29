"""Transfermarkt açık veri setini indirir ve oyuncu istatistiklerini derler."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import httpx
import pandas as pd

from app.config import (
    APPEARANCES_CSV,
    CLUBS_CSV,
    COMPETITIONS_CSV,
    DATASET_BASE,
    HF_DATASET,
    PLAYERS_CSV,
    PLAYERS_PARQUET,
    RAW_DIR,
    STATS_PARQUET,
    UNIVERSE_PARQUET,
    USER_AGENT,
)
from app.config import DATA_DIR as WAREHOUSE_DIR
from app import status as st

_FILES = (
    ("players.csv", PLAYERS_CSV, 100_000),
    ("clubs.csv", CLUBS_CSV, 20_000),
    ("competitions.csv", COMPETITIONS_CSV, 2_000),
    ("appearances.csv", APPEARANCES_CSV, 1_000_000),
)


def warehouse_ready() -> bool:
    return UNIVERSE_PARQUET.exists() and UNIVERSE_PARQUET.stat().st_size > 10_000


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def _download(name: str, dest: Path, start: float, end: float, min_size: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > min_size:
        st.set_state(message=f"{name} zaten var, atlanıyor.", progress=end)
        return
    urls = [
        f"{HF_DATASET}/{name}",
        f"{DATASET_BASE}/{name}.gz" if not name.endswith(".gz") else f"{DATASET_BASE}/{name}",
        f"{DATASET_BASE}/{name}",
    ]
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    last_error = None
    for url in urls:
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with httpx.Client(headers=headers, follow_redirects=True, timeout=None, verify=False) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = int(response.headers.get("content-length") or 0)
                    done = 0
                    last_emit = 0.0
                    with tmp.open("wb") as handle:
                        for chunk in response.iter_bytes(256 * 1024):
                            handle.write(chunk)
                            done += len(chunk)
                            now = time.time()
                            if now - last_emit > 0.4:
                                frac = (done / total) if total else 0.5
                                st.set_state(
                                    message=f"{name} indiriliyor ({done / 1_000_000:.1f} MB).",
                                    progress=start + (end - start) * min(frac, 0.99),
                                )
                                last_emit = now
            if tmp.exists() and tmp.stat().st_size > min_size:
                if dest.suffix == ".csv" and url.endswith(".gz"):
                    import gzip
                    import shutil

                    unpacked = dest.with_suffix(dest.suffix + ".unpack")
                    with gzip.open(tmp, "rb") as src, unpacked.open("wb") as out:
                        shutil.copyfileobj(src, out)
                    tmp.unlink(missing_ok=True)
                    unpacked.replace(dest)
                else:
                    tmp.replace(dest)
                st.set_state(message=f"{name} indirildi.", progress=end)
                return
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
            continue
    raise RuntimeError(f"{name} indirilemedi: {last_error}")


def _empty_stats(con: duckdb.DuckDBPyConnection) -> None:
    path = _posix(PLAYERS_CSV)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE player_stats AS
        SELECT
            player_id,
            0::BIGINT AS apps_all,
            0::BIGINT AS goals_all,
            0::BIGINT AS assists_all,
            0::BIGINT AS minutes_all,
            0::BIGINT AS yellow_all,
            0::BIGINT AS red_all,
            0::BIGINT AS apps_2y,
            0::BIGINT AS goals_2y,
            0::BIGINT AS assists_2y,
            0::BIGINT AS minutes_2y,
            0::BIGINT AS yellow_2y,
            0::BIGINT AS red_2y,
            0::BIGINT AS apps_365,
            0::BIGINT AS goals_365,
            0::BIGINT AS assists_365,
            0::BIGINT AS minutes_365,
            NULL::DATE AS last_match
        FROM read_csv_auto('{path}', SAMPLE_SIZE=-1)
        """
    )


def appearances_ready() -> bool:
    return APPEARANCES_CSV.exists() and APPEARANCES_CSV.stat().st_size > 120_000_000


def _build_stats(con: duckdb.DuckDBPyConnection) -> None:
    path = _posix(APPEARANCES_CSV)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE player_stats AS
        SELECT
            player_id,
            COUNT(*)::BIGINT AS apps_all,
            COALESCE(SUM(goals), 0)::BIGINT AS goals_all,
            COALESCE(SUM(assists), 0)::BIGINT AS assists_all,
            COALESCE(SUM(minutes_played), 0)::BIGINT AS minutes_all,
            COALESCE(SUM(yellow_cards), 0)::BIGINT AS yellow_all,
            COALESCE(SUM(red_cards), 0)::BIGINT AS red_all,
            COUNT(*) FILTER (WHERE date >= DATE '2023-07-01')::BIGINT AS apps_2y,
            COALESCE(SUM(goals) FILTER (WHERE date >= DATE '2023-07-01'), 0)::BIGINT AS goals_2y,
            COALESCE(SUM(assists) FILTER (WHERE date >= DATE '2023-07-01'), 0)::BIGINT AS assists_2y,
            COALESCE(SUM(minutes_played) FILTER (WHERE date >= DATE '2023-07-01'), 0)::BIGINT AS minutes_2y,
            COALESCE(SUM(yellow_cards) FILTER (WHERE date >= DATE '2023-07-01'), 0)::BIGINT AS yellow_2y,
            COALESCE(SUM(red_cards) FILTER (WHERE date >= DATE '2023-07-01'), 0)::BIGINT AS red_2y,
            COUNT(*) FILTER (WHERE date >= CURRENT_DATE - INTERVAL 365 DAY)::BIGINT AS apps_365,
            COALESCE(SUM(goals) FILTER (WHERE date >= CURRENT_DATE - INTERVAL 365 DAY), 0)::BIGINT AS goals_365,
            COALESCE(SUM(assists) FILTER (WHERE date >= CURRENT_DATE - INTERVAL 365 DAY), 0)::BIGINT AS assists_365,
            COALESCE(SUM(minutes_played) FILTER (WHERE date >= CURRENT_DATE - INTERVAL 365 DAY), 0)::BIGINT AS minutes_365,
            MAX(date) AS last_match
        FROM read_csv_auto('{path}', SAMPLE_SIZE=-1)
        GROUP BY player_id
        """
    )


def _export_tables(con: duckdb.DuckDBPyConnection) -> None:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT * FROM read_csv_auto('{_posix(PLAYERS_CSV)}', SAMPLE_SIZE=-1)) TO '{_posix(PLAYERS_PARQUET)}' (FORMAT PARQUET)")
    con.execute(f"COPY player_stats TO '{_posix(STATS_PARQUET)}' (FORMAT PARQUET)")


def build_universe() -> pd.DataFrame:
    players = pd.read_parquet(PLAYERS_PARQUET)
    stats = pd.read_parquet(STATS_PARQUET)
    players["player_id"] = pd.to_numeric(players["player_id"], errors="coerce")
    stats["player_id"] = pd.to_numeric(stats["player_id"], errors="coerce")
    frame = players.merge(stats, on="player_id", how="left")
    clubs_path = CLUBS_CSV
    if clubs_path.exists():
        clubs = pd.read_csv(clubs_path, low_memory=False)
        keep = [c for c in ("club_id", "name", "domestic_competition_id", "total_market_value", "squad_size", "average_age") if c in clubs.columns]
        clubs = clubs[keep].copy()
        clubs = clubs.rename(
            columns={
                "club_id": "current_club_id",
                "name": "club_name_official",
                "total_market_value": "club_total_market_value",
            }
        )
        clubs["current_club_id"] = pd.to_numeric(clubs["current_club_id"], errors="coerce")
        frame["current_club_id"] = pd.to_numeric(frame.get("current_club_id"), errors="coerce")
        frame = frame.merge(clubs, on="current_club_id", how="left")
    for col in (
        "apps_all",
        "goals_all",
        "assists_all",
        "minutes_all",
        "yellow_all",
        "red_all",
        "apps_2y",
        "goals_2y",
        "assists_2y",
        "minutes_2y",
        "yellow_2y",
        "red_2y",
        "apps_365",
        "goals_365",
        "assists_365",
        "minutes_365",
    ):
        if col not in frame.columns:
            frame[col] = 0
        frame[col] = pd.to_numeric(frame[col], errors="coerce").fillna(0)
    frame.to_parquet(UNIVERSE_PARQUET, index=False)
    return frame


def bootstrap() -> pd.DataFrame:
    if warehouse_ready():
        st.set_state(phase="ready", message="Veri ambarı hazır.", progress=1.0, error=None)
        return pd.read_parquet(UNIVERSE_PARQUET)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    st.set_state(phase="download", message="Transfermarkt veri seti indiriliyor.", progress=0.02, error=None)
    spans = [(0.02, 0.12), (0.12, 0.18), (0.18, 0.22)]
    for (name, dest, min_size), (a, b) in zip(_FILES[:3], spans):
        _download(name, dest, a, b, min_size)
    if not appearances_ready():
        st.set_state(
            message="Maç görünümleri henüz yok; model lig, yaş ve mevki ile kuruluyor. Gol ambarı arka planda tamamlanabilir.",
            progress=0.40,
        )
    st.set_state(phase="aggregate", message="Oyuncu tablosu kuruluyor.", progress=0.64)
    con = duckdb.connect(database=":memory:")
    if appearances_ready():
        st.set_state(message="Maç istatistikleri oyuncu bazında toplanıyor.", progress=0.70)
        _build_stats(con)
    else:
        _empty_stats(con)
    st.set_state(phase="export", message="Oyuncu tabloları yazılıyor.", progress=0.86)
    _export_tables(con)
    con.close()
    st.set_state(phase="export", message="Birleşik evren tablosu kuruluyor.", progress=0.92)
    frame = build_universe()
    st.set_state(phase="warehouse", message="Veri ambarı tamamlandı.", progress=0.94, error=None)
    return frame
