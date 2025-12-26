from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from app import models


class CRUDUser:
    def __init__(self, db: Session):
        self.db = db

    async def get_user_by_id(self, user_id: UUID) -> Optional[models.User]:
        return self.db.query(models.User).filter(models.User.id == user_id,
                                                 models.User.is_active == True).first()

    async def get_user_by_email(self, email: str) -> Optional[models.User]:
        return self.db.query(models.User).filter(models.User.email == email,
                                                 models.User.is_active == True).first()


class CRUDChat:
    def __init__(self, db: Session):
        self.db = db

    async def get_chat_by_users(self, user1_id: UUID, user2_id: UUID) -> Optional[models.Chat]:
        chat = self.db.query(models.Chat).filter(or_(
            and_(models.Chat.user1_id == user1_id, models.Chat.user2_id == user2_id),
            and_(models.Chat.user1_id == user2_id, models.Chat.user2_id == user1_id)),
            models.Chat.is_active == True).first()
        return chat

    async def get_chat_by_id(self, chat_id: UUID) -> Optional[models.Chat]:
        return self.db.query(models.Chat).filter(models.Chat.id == chat_id,
                                                 models.Chat.is_active == True).first()

    async def create_chat(self, user1_id: UUID, user2_id: UUID) -> models.Chat:
        if user1_id > user2_id:
            user1_id, user2_id = user2_id, user1_id

        existing_chat = await self.get_chat_by_users(user1_id, user2_id)
        if existing_chat:
            return existing_chat

        db_chat = models.Chat(
            user1_id=user1_id,
            user2_id=user2_id
        )
        self.db.add(db_chat)
        self.db.commit()
        self.db.refresh(db_chat)
        return db_chat

    async def get_user_chats(self, user_id: UUID) -> List[models.Chat]:
        return self.db.query(models.Chat).filter(or_(
            models.Chat.user1_id == user_id, models.Chat.user2_id == user_id), models.Chat.is_active == True).order_by(
            desc(models.Chat.updated_at)).all()

    async def get_last_message(self, chat_id: UUID) -> Optional[models.Message]:
        return self.db.query(models.Message).filter(models.Message.chat_id == chat_id).order_by(
            desc(models.Message.created_at)).first()

    async def get_messages_by_chat(self, chat_id: UUID, skip: int = 0, limit: int = 100) -> List[models.Message]:
        return self.db.query(models.Message).filter(models.Message.chat_id == chat_id).order_by(
            models.Message.created_at).offset(skip).limit(limit).all()

    async def get_message_by_id(self, message_id: UUID) -> Optional[models.Message]:
        return self.db.query(models.Message).filter(models.Message.id == message_id).first()

    async def create_message(self, message_data: dict) -> models.Message:
        db_message = models.Message(**message_data)
        self.db.add(db_message)

        chat = await self.get_chat_by_id(message_data["chat_id"])
        if chat:
            chat.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(db_message)
        return db_message

    async def create_message_with_ws(self, message_data: dict) -> models.Message:
        db_message = models.Message(**message_data)
        self.db.add(db_message)

        chat = await self.get_chat_by_id(message_data["chat_id"])
        if chat:
            chat.updated_at = datetime.utcnow()
            chat.last_message_id = db_message.id
            receiver_id = message_data["receiver_id"]
            if str(chat.user1_id) == str(receiver_id):
                chat.unread_count_user1 += 1
            else:
                chat.unread_count_user2 += 1

        self.db.commit()
        self.db.refresh(db_message)
        return db_message

    async def mark_message_as_read(self, message_id: UUID, user_id: UUID):
        message = await self.get_message_by_id(message_id)
        if message and str(message.receiver_id) == str(user_id) and not message.is_read:
            message.is_read = True
            message.read_at = datetime.utcnow()

            chat = await self.get_chat_by_id(message.chat_id)
            if chat:
                if str(chat.user1_id) == str(user_id):
                    chat.unread_count_user1 = 0
                else:
                    chat.unread_count_user2 = 0

            read_status = models.MessageReadStatus(
                message_id=message_id,
                user_id=user_id
            )
            self.db.add(read_status)
            self.db.commit()
            return True
        return False

    async def get_unread_count(self, chat_id: UUID, user_id: UUID) -> int:
        chat = await self.get_chat_by_id(chat_id)
        if chat:
            if str(chat.user1_id) == str(user_id):
                return chat.unread_count_user1
            else:
                return chat.unread_count_user2
        return 0