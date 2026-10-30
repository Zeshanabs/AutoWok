import redis

from app.core.config import get_settings

settings = get_settings()

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def ping_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False
