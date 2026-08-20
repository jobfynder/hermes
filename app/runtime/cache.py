import hashlib
import json
import threading
import time
from typing import Any

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _hash_parts(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_cache_key(namespace: str, *parts: Any) -> str:
    """Mirrors the jf:hermes:{namespace}:{hash} key pattern from the Hermes
    integration blueprint - same shape, in-process store instead of Redis
    until a dedicated Redis instance exists for Hermes (the current Redis
    is policy-locked to LiteLLM caching only).
    """
    return f"jf:hermes:{namespace}:{_hash_parts(*parts)}"


def cache_get(key: str) -> Any | None:
    with _lock:
        entry = _store.get(key)

        if entry is None:
            return None

        expires_at, value = entry

        if time.time() > expires_at:
            _store.pop(key, None)
            return None

        return value


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return

    with _lock:
        _store[key] = (time.time() + ttl_seconds, value)


def cache_invalidate(key: str) -> None:
    with _lock:
        _store.pop(key, None)


def cache_invalidate_namespace(namespace: str) -> int:
    prefix = f"jf:hermes:{namespace}:"

    with _lock:
        keys = [key for key in _store if key.startswith(prefix)]
        for key in keys:
            _store.pop(key, None)

    return len(keys)


def cache_stats() -> dict[str, Any]:
    with _lock:
        now = time.time()
        live = sum(1 for expires_at, _ in _store.values() if expires_at > now)
        return {
            "backend": "in_process",
            "total_entries": len(_store),
            "live_entries": live,
            "expired_entries": len(_store) - live,
        }
