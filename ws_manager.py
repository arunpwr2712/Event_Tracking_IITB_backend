from typing import List
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected: {getattr(websocket, 'client', None)}")

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            # already removed
            pass
        logger.info(f"WebSocket disconnected: {getattr(websocket, 'client', None)}")

    async def broadcast(self, message: dict):
        # Send to connections and remove those that error
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.exception(f"Removing broken WebSocket connection {getattr(connection, 'client', None)}: {exc}")
                try:
                    self.active_connections.remove(connection)
                except ValueError:
                    pass
