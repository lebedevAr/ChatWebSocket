from typing import Dict, Set, List
import json
import asyncio
from uuid import UUID
from datetime import datetime


class ConnectionManager:
    def __init__(self):
        # user_id -> set of websocket connections
        self.active_connections: Dict[str, Set] = {}
        # user_id -> last seen timestamp
        self.user_status: Dict[str, datetime] = {}

    async def connect(self, user_id: UUID, websocket):
        """Добавить новое соединение для пользователя"""
        user_id_str = str(user_id)
        if user_id_str not in self.active_connections:
            self.active_connections[user_id_str] = set()

        self.active_connections[user_id_str].add(websocket)
        self.user_status[user_id_str] = datetime.now()

        print(f"User {user_id_str} connected. Total connections: {len(self.active_connections)}")
        return True

    async def disconnect(self, user_id: UUID, websocket):
        """Удалить соединение пользователя"""
        user_id_str = str(user_id)
        if user_id_str in self.active_connections:
            self.active_connections[user_id_str].discard(websocket)

            if not self.active_connections[user_id_str]:
                del self.active_connections[user_id_str]
                del self.user_status[user_id_str]
                print(f"User {user_id_str} fully disconnected")

        print(f"User {user_id_str} disconnected. Total connections: {len(self.active_connections)}")

    def get_connections(self, user_id: UUID):
        """Получить все соединения пользователя"""
        user_id_str = str(user_id)
        return self.active_connections.get(user_id_str, set())

    async def send_personal_message(self, message: dict, user_id: UUID):
        """Отправить личное сообщение пользователю"""
        user_id_str = str(user_id)
        connections = self.active_connections.get(user_id_str, set())

        if connections:
            message_json = json.dumps(message, default=str)
            for connection in connections:
                try:
                    await connection.send_text(message_json)
                except Exception as e:
                    print(f"Error sending message to {user_id_str}: {e}")
                    await self.disconnect(user_id, connection)
            return True
        return False

    def is_user_online(self, user_id: UUID) -> bool:
        """Проверить онлайн статус пользователя"""
        user_id_str = str(user_id)
        return user_id_str in self.active_connections and len(self.active_connections[user_id_str]) > 0

    async def get_online_users(self, user_ids: List[UUID]) -> Dict[str, bool]:
        """Получить статус онлайн для списка пользователей"""
        return {str(uid): self.is_user_online(uid) for uid in user_ids}


# Глобальный экземпляр менеджера
manager = ConnectionManager()