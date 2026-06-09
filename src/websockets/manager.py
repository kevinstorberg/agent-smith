from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room: str) -> None:
        await websocket.accept()
        if room not in self.active_connections:
            self.active_connections[room] = []
        self.active_connections[room].append(websocket)

    def disconnect(self, websocket: WebSocket, room: str) -> None:
        if room in self.active_connections:
            self.active_connections[room] = [ws for ws in self.active_connections[room] if ws != websocket]
            if not self.active_connections[room]:
                del self.active_connections[room]

    def get_room_connections(self, room: str) -> list[WebSocket]:
        return self.active_connections.get(room, [])

    async def broadcast(self, room: str, message: dict) -> None:
        for connection in self.get_room_connections(room):
            await connection.send_json(message)
