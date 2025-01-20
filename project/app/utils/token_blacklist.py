import redis

# Connect to Redis
#redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0)
    
    # Test the connection
    redis_client.ping()
    print("Connected to Redis")
except Exception as e:
    print(f"Redis connection failed: {e}")
    redis_client = None 

def add_token_to_blacklist(token: str, expiration_seconds: int):
    """Redis blacklist에 토큰 추가."""
    redis_client.setex(token, expiration_seconds, "blacklisted")


def is_token_blacklisted(token: str) -> bool:
    """토큰이 블랙리스트에 있는지 체크"""
    return redis_client.get(token) == b"blacklisted"