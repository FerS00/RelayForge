from __future__ import annotations

import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOCK = threading.Lock()
_LAST_MS = -1
_LAST_RANDOM = 0


def new_ulid() -> str:
    global _LAST_MS, _LAST_RANDOM
    with _LOCK:
        now = time.time_ns() // 1_000_000
        if now > _LAST_MS:
            _LAST_MS, _LAST_RANDOM = now, int.from_bytes(__import__("secrets").token_bytes(10), "big")
        else:
            now = _LAST_MS
            _LAST_RANDOM = (_LAST_RANDOM + 1) & ((1 << 80) - 1)
            if _LAST_RANDOM == 0:
                while (now := time.time_ns() // 1_000_000) <= _LAST_MS:
                    time.sleep(0.0001)
                _LAST_MS = now
        value = (now << 80) | _LAST_RANDOM
    chars = ["0"] * 26
    for index in range(25, -1, -1):
        chars[index] = _ALPHABET[value & 31]
        value >>= 5
    return "".join(chars)
