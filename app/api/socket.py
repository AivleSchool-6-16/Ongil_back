import socketio
from urllib.parse import parse_qs
from app.core.jwt_utils import verify_token  # Import JWT verification function
from datetime import datetime

# ✅ Create WebSocket Server
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    allow_upgrades=True,  # HTTP에서 WebSocket으로 업그레이드 허용
    transports=["websocket"]  # WebSocket만 허용
)
socket_app = socketio.ASGIApp(sio)

# 실시간 게시판 데이터 저장 (임시)
active_connections = []


# 1. WebSocket 연결 관리
@sio.event
async def connect(sid, environ):
  print("socket 실행")  # 이 로그가 출력되어야 합니다.
  query_params = parse_qs(environ.get("QUERY_STRING", ""))
  token = query_params.get("token", [None])[0]

  if not token:
    print("❌ WebSocket 인증 실패: 토큰 없음")
    return False  # 연결 거부

  try:
    payload = verify_token(token)
  except Exception as e:
    print(f"❌ WebSocket 인증 실패: {str(e)}")
    return False  # 연결 거부

  print(f"✅ WebSocket 인증 성공: {payload['sub']} 연결됨")
  # 연결 허용 (return 생략 시 기본적으로 True)


@sio.on("disconnect")
async def disconnect(sid):
  print(f"Client disconnected: {sid}")
  active_connections.remove(sid)


def serialize_datetime(obj):
  """
  만약 값이 datetime이면 ISO 포맷 문자열로 변환
  """
  if isinstance(obj, datetime):
    return obj.isoformat()
  return obj


def serialize_post(post: dict) -> dict:
  """
  post 딕셔너리 내의 모든 datetime 객체를 문자열로 변환
  """
  return {key: serialize_datetime(value) for key, value in post.items()}


async def notify_new_post(post):
  """ 새로운 게시글을 WebSocket을 통해 모든 클라이언트에게 전송 """
  # datetime 필드가 문자열로 변환된 새로운 딕셔너리 생성
  post_serialized = serialize_post(post)
  await sio.emit("newPost", post_serialized)


async def notify_updated_post(post):
  """ 게시글이 수정되었을 때 WebSocket으로 전송 """
  await sio.emit("updatedPost", post)


async def notify_new_comment(comment):
  """ 새로운 댓글이 달렸을 때 WebSocket으로 전송 """
  await sio.emit("newComment", comment)
