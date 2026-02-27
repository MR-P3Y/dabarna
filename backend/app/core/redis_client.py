import os
import time
import uuid
import redis
import json
from typing import Any
from app.core.config import REDIS_URL

_client: redis.Redis | None = None

def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _client

class RedisLock:
    """
    Lock ساده با SET NX PX
    """
    def __init__(self, key: str, ttl_ms: int = 5000):
        self.key = key
        self.ttl_ms = ttl_ms
        self.token = uuid.uuid4().hex
        self.r = get_redis()

    def acquire(self) -> bool:
        return bool(self.r.set(self.key, self.token, nx=True, px=self.ttl_ms))

    def release(self) -> None:
        # آزادسازی امن (فقط اگر توکن خودش باشد)
        lua = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
          return redis.call("DEL", KEYS[1])
        else
          return 0
        end
        """
        try:
            self.r.eval(lua, 1, self.key, self.token)
        except Exception:
            # در dev اهمیتی نداره
            pass


def idem_get(key: str) -> dict | None:
    r = get_redis()
    v = r.get(key)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def idem_set(key: str, value: dict, ttl_sec: int = 3600) -> None:
    r = get_redis()
    r.setex(key, ttl_sec, json.dumps(value, ensure_ascii=False, separators=(",", ":")))