import redis
from app.database.mysql_connect import get_connection

# 조회수 동기화 
def sync_redis_to_mysql():
    connection = get_connection()
    cursor = connection.cursor()

    try:
        redis_client = redis.StrictRedis(host="localhost", port=6379, db=0, decode_responses=True)
        keys = redis_client.keys("post_views:*")

        for key in keys:
            post_id = int(key.split(":")[1])  # key에서 post_id 추출하기 
            redis_views = int(redis_client.get(key))

            if redis_views > 0:  # redis에 조회수가 추가되었다면 
                # mysql에 저장 
                cursor.execute(
                    "UPDATE Posts SET views = views + %s WHERE post_id = %s",
                    (redis_views, post_id)
                )
                connection.commit()

                # 리셋 redis 
                redis_client.delete(key)

        print("Sync completed successfully!")
    except Exception as e:
        print(f"⚠️ Sync failed: {e}")
    finally:
        cursor.close()
        connection.close()