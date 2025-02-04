import redis
from app.database.mysql_connect import get_connection


def sync_redis_to_mysql():
  connection = get_connection()
  cursor = None  # cursor 초기화

  try:
    redis_client = redis.StrictRedis(host="localhost", port=6379, db=0,
                                     decode_responses=True)
    keys = redis_client.keys("post_views:*")

    cursor = connection.cursor()  # cursor는 이 시점에서만 정의

    for key in keys:
      post_id = int(key.split(":")[1])  # Extract post_id from key
      redis_views = int(redis_client.get(key))

      if redis_views > 0:  # redis에 조회수가 추가되었다면
        # mysql에 저장
        cursor.execute(
            "UPDATE Posts SET views = views + %s WHERE post_id = %s",
            (redis_views, post_id)
        )
        connection.commit()

        # Reset Redis view count
        redis_client.delete(key)

    print("Sync completed successfully!")
  except Exception as e:
    print(f"⚠️ Sync failed: {e}")
  finally:
    # cursor가 정의되어 있을 경우에만 close() 호출
    if cursor:
      cursor.close()
    connection.close()
