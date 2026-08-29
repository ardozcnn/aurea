"""Kurulum ve eğitim ilerlemesini süreçler arasında paylaşır."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR

_LOCK = threading.Lock()
_STATE = {
    "phase": "idle",
    "message": "Hazır.",
    "progress": 0.0,
    "error": None,
    "updated_at": None,
}

STATE_PATH = DATA_DIR / "bootstrap_state.json"


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot() -> dict:
    with _LOCK:
        return dict(_STATE)


def set_state(*, phase: str | None = None, message: str | None = None, progress: float | None = None, error: str | None = False):
    with _LOCK:
        if phase is not None:
            _STATE["phase"] = phase
        if message is not None:
            _STATE["message"] = message
        if progress is not None:
            _STATE["progress"] = float(max(0.0, min(1.0, progress)))
        if error is not False:
            _STATE["error"] = error
        _STATE["updated_at"] = _stamp()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")


def load_persisted() -> None:
    if not STATE_PATH.exists():
        return
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    with _LOCK:
        _STATE.update({k: data.get(k, _STATE.get(k)) for k in _STATE})
