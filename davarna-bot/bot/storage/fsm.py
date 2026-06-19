from redis.asyncio import Redis
from aiogram.fsm.storage.redis import RedisStorage
from bot.config import settings


def build_storage() -> RedisStorage:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return RedisStorage(redis=redis)
