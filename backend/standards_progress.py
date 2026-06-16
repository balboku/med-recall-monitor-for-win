"""法規標準掃描進度（單例，跨執行緒共用）。

local 任務佇列模式下，爬蟲在 ThreadPoolExecutor 執行緒、API 在主執行緒，
兩者同一程序，可透過此記憶體單例共用即時進度。以 threading.Lock 確保讀寫安全。
（celery 多程序模式不適用，但本專案預設 local 模式。）
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_state = {
    "running": False,
    "mode": "",            # routine | browser
    "total": 0,            # 預計處理筆數
    "current": 0,          # 已處理筆數
    "updated": 0,          # 判定有更新筆數
    "skipped": 0,          # 略過筆數（非 ISO 等）
    "current_title": "",   # 目前處理中的標準名稱
    "status": "idle",      # idle | running | success | error
    "message": "",
    "started_at": None,
    "finished_at": None,
}


def start(total: int, mode: str):
    with _lock:
        _state.update({
            "running": True, "mode": mode, "total": int(total), "current": 0,
            "updated": 0, "skipped": 0, "current_title": "",
            "status": "running", "message": "",
            "started_at": datetime.now().isoformat(), "finished_at": None,
        })


def set_current_title(title: str):
    with _lock:
        _state["current_title"] = title or ""


def advance(updated: bool = False, skipped: bool = False):
    """完成一筆，累加進度計數。"""
    with _lock:
        _state["current"] += 1
        if updated:
            _state["updated"] += 1
        if skipped:
            _state["skipped"] += 1


def finish(status: str = "success", message: str = ""):
    with _lock:
        _state["running"] = False
        _state["status"] = status
        _state["message"] = message
        _state["finished_at"] = datetime.now().isoformat()


def get() -> dict:
    with _lock:
        return dict(_state)
