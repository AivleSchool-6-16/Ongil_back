import redis

# Connect to Redis
try:
    redis_client = redis.StrictRedis(host="ongil_redis", port=6379, db=0)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None


def add_token_to_blacklist(token: str, expiration_seconds: int):
    """Redis blacklist에 토큰 추가."""
    redis_client.setex(token, expiration_seconds, "blacklisted")


def is_token_blacklisted(token):
    if not token:  # None 체크 추가
        return False

    try:
        return redis_client.get(token) == "blacklisted"
    except Exception as e:
        print(f"🔴 Redis 오류 발생: {e}")
        return False  # Redis 오류 발생 시 블랙리스트 체크를 우회
