import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    
    async with websockets.connect(uri) as websocket:
        print("✅ WebSocket 서버에 연결됨!")

        message = {
            "event": "createPost",
            "data": {
                "post_id": 1,
                "title": "테스트 게시글",
                "content": "이건 WebSocket 테스트입니다."
            }
        }
        await websocket.send(json.dumps(message))
        print("📤 메시지 전송:", message)

        response = await websocket.recv()
        print("📩 서버 응답:", response)

# 실행
asyncio.run(test_websocket())