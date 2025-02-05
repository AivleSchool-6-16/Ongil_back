import socketio
from urllib.parse import parse_qs
from app.core.jwt_utils import verify_token  # Import JWT verification function

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
    print(f"🔗 [Socket.IO] 연결 요청: {sid}")

    # ✅ Query Parameter 또는 Header에서 토큰 가져오기
    token = None

    # ✅ Query Parameter에서 가져오기
    query_params = environ.get("QUERY_STRING", "")
    token = dict(parse_qs(query_params)).get("token", [None])[0]

    # ✅ Headers에서 가져오기
    headers = {key: value for key, value in environ.items() if key.startswith("HTTP_")}
    if not token and "HTTP_AUTHORIZATION" in headers:
        token = headers["HTTP_AUTHORIZATION"].replace("Bearer ", "")

    if not token:
        print("❌ [Socket.IO] 인증 실패: 토큰이 없습니다.")
        return False  # 연결 거부

    try:
        payload = verify_token(token)
    except Exception as e:
        print(f"❌ [Socket.IO] 인증 실패: {str(e)}")
        return False  # 연결 거부

    print(f"✅ [Socket.IO] 인증 성공: {payload['sub']} 연결됨")

    # ✅ 연결된 사용자 리스트에 추가
    active_connections.append(sid)
    return True  # 연결 허용


@sio.event
async def disconnect(sid):
    """ 클라이언트 연결 해제 이벤트 """
    print(f"🔌 [Socket.IO] 클라이언트 연결 해제: {sid}")

    # ✅ sid가 리스트에 존재하는 경우만 제거
    if sid in active_connections:
        active_connections.remove(sid)

    print(f"📢 현재 활성 연결 수: {len(active_connections)}")


# ✅ 클라이언트로부터 메시지를 받을 때 실행
@sio.event
async def message(sid, data):
    """ 클라이언트가 메시지를 보낼 때 실행 """
    print(f"📩 [Socket.IO] 클라이언트({sid})로부터 메시지 수신: {data}")

    # 받은 메시지를 모든 클라이언트에게 전송 (브로드캐스트)
    await sio.emit("message", data)


# WebSocket을 통한 실시간 게시글 업데이트
async def notify_new_post(post):
    """ 새로운 게시글을 WebSocket을 통해 모든 클라이언트에게 전송 """
    print(f"📢 [Socket.IO] 새로운 게시글: {post}")
    await sio.emit("newPost", post)

async def notify_updated_post(post):
    """ 게시글이 수정되었을 때 WebSocket으로 전송 """
    print(f"📢 [Socket.IO] 게시글 수정: {post}")
    await sio.emit("updatedPost", post)


async def notify_new_comment(comment):
    """ 새로운 댓글이 달렸을 때 WebSocket으로 전송 """
    print(f"📢 [Socket.IO] 새로운 댓글: {comment}")
    await sio.emit("newComment", comment)
    
async def notify_updated_comment(comment):
    """ 댓글 수정 시 모든 클라이언트에 실시간 알림 """
    print(f"✏️ [Socket.IO] 댓글 수정됨: {comment}")
    await sio.emit("updatedComment", comment)

async def notify_deleted_comment(data):
    """ 댓글 삭제 시 모든 클라이언트에 실시간 알림 """
    print(f"🗑️ [Socket.IO] 댓글 삭제됨: {data}")
    await sio.emit("deletedComment", data)