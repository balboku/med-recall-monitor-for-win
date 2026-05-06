"""Singleton translation state shared across threads."""
import logging
import threading

logger = logging.getLogger(__name__)

_stop_translation = True
_translation_running = False
_lock = threading.Lock()


def start_translation():
    """Returns True if successfully started, False if already running."""
    global _stop_translation, _translation_running
    with _lock:
        if _translation_running:
            return False
        _stop_translation = False
        _translation_running = True
        return True


def stop_translation():
    global _stop_translation
    _stop_translation = True


def mark_done():
    global _translation_running, _stop_translation
    with _lock:
        _translation_running = False
        _stop_translation = True


def is_running():
    return _translation_running


def is_stopped():
    return _stop_translation
