from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.websockets.manager import ConnectionManager
from src.websockets.protocol import WebSocketMessageHandler

router = APIRouter()
manager = ConnectionManager()
message_handler = WebSocketMessageHandler()


@router.websocket("/ws/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    await manager.connect(websocket, room)
    try:
        while True:
            data = await websocket.receive_json()
            await message_handler.handle(websocket, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room)
