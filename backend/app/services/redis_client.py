import redis

from app.core.config import get_settings

settings = get_settings()

# Timeouts matter: without them a silently dropped connection blocks the caller
# forever (the worker's blocking pop, or an API request that only wanted to
# wake the worker). Blocking pops pass their own, longer timeout per call.
redis_client = redis.Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=settings.redis_socket_timeout_seconds,
    socket_timeout=settings.redis_socket_timeout_seconds,
    health_check_interval=30,
    retry_on_timeout=False,
)


def ping_redis() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False
