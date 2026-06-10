import hashlib
import os
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        if os.environ.get("USE_FAKEREDIS", "").lower() in ("1", "true", "yes") or get_settings().use_fakeredis:
            import fakeredis.aioredis as fakeredis_async
            _redis = fakeredis_async.FakeRedis(decode_responses=True)
        else:
            _redis = aioredis.from_url(
                get_settings().redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def _key(prefix: str, value: str) -> str:
    h = hashlib.sha256(value.encode()).hexdigest()[:20]
    return f"{prefix}:{h}"


async def get_cached(prefix: str, value: str) -> Optional[str]:
    r = await get_redis()
    return await r.get(_key(prefix, value))


async def set_cached(prefix: str, value: str, data: str, ttl: int) -> None:
    r = await get_redis()
    await r.setex(_key(prefix, value), ttl, data)


async def incr_stat(key: str, ttl: int = 86400) -> int:
    r = await get_redis()
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, ttl)
    result = await pipe.execute()
    return result[0]


async def get_stat(key: str) -> int:
    r = await get_redis()
    val = await r.get(key)
    return int(val) if val else 0


async def lpush_capped(key: str, value: str, cap: int = 20, ttl: int = 86400) -> None:
    r = await get_redis()
    pipe = r.pipeline()
    pipe.lpush(key, value)
    pipe.ltrim(key, 0, cap - 1)
    pipe.expire(key, ttl)
    await pipe.execute()


async def lrange(key: str, start: int = 0, end: int = -1) -> list:
    r = await get_redis()
    return await r.lrange(key, start, end)


async def get_admin_settings() -> dict:
    r = await get_redis()
    data = await r.hgetall("admin:settings")
    return data or {}


async def set_admin_setting(field: str, value: str) -> None:
    r = await get_redis()
    await r.hset("admin:settings", field, value)


async def get_blocked_ips() -> set:
    r = await get_redis()
    members = await r.smembers("admin:blocked_ips")
    return members or set()


async def add_blocked_ip(ip: str) -> None:
    r = await get_redis()
    await r.sadd("admin:blocked_ips", ip)


async def remove_blocked_ip(ip: str) -> None:
    r = await get_redis()
    await r.srem("admin:blocked_ips", ip)
