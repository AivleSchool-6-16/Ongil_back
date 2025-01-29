import redis

# Connect to Redis
try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None 

def add_token_to_blacklist(token: str, expiration_seconds: int):
    """Redis blacklist에 토큰 추가."""
    redis_client.setex(token, expiration_seconds, "blacklisted")


def is_token_blacklisted(token: str) -> bool:
    """토큰이 블랙리스트에 있는지 체크"""
    return redis_client.get(token) == b"blacklisted"