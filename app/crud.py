from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, update, delete, func, or_, desc

from app import models


class ChatCRUD:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_id(self, user_id: UUID) -> Optional[models.User]:
        """Получить пользователя по ID"""

        result = await self.db.execute(select(models.User).where(models.User.id == str(user_id)))
        return result.scalar_one_or_none()

    async def get_chat_by_participants(self, user1_id: UUID, user2_id: UUID) -> Optional[models.Chat]:
        """Получить чат по участникам"""

        user1_id_str, user2_id_str = str(user1_id), str(user2_id)
        user1_id_sorted, user2_id_sorted = sorted([user1_id_str, user2_id_str])
        result = await self.db.execute(
            select(models.Chat).where(models.Chat.user1_id == user1_id_sorted,
                                      models.Chat.user2_id == user2_id_sorted))
        return result.scalar_one_or_none()

    async def get_chat_by_id(self, chat_id: UUID, user_id: UUID = None) -> Optional[models.Chat]:
        """Получить чат по ID с проверкой доступа"""

        chat_id_str = str(chat_id)
        query = select(models.Chat).where(models.Chat.id == chat_id_str)

        if user_id:
            user_id_str = str(user_id)
            query = query.where(or_(models.Chat.user1_id == user_id_str, models.Chat.user2_id == user_id_str))

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_chat(self, user1_id: UUID, user2_id: UUID) -> models.Chat:
        """Создать новый чат"""

        user1_id_str, user2_id_str = str(user1_id), str(user2_id)
        user1_id_sorted, user2_id_sorted = sorted([user1_id_str, user2_id_str])

        chat = models.Chat(
            user1_id=user1_id_sorted,
            user2_id=user2_id_sorted,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.db.add(chat)
        await self.db.commit()
        await self.db.refresh(chat)
        return chat

    async def get_user_chats(self, user_id: UUID) -> List[models.Chat]:
        """Получить все чаты пользователя"""

        user_id_str = str(user_id)
        result = await self.db.execute(select(models.Chat)
                                       .where(
            or_(models.Chat.user1_id == user_id_str, models.Chat.user2_id == user_id_str),
            models.Chat.is_active == True).order_by(desc(models.Chat.updated_at)))
        return result.scalars().all()

    async def get_messages(self, chat_id: UUID, skip: int = 0, limit: int = 100) -> List[models.Message]:
        """Получить сообщения чата"""

        chat_id_str = str(chat_id)
        result = await self.db.execute(
            select(models.Message)
            .where(models.Message.chat_id == chat_id_str)
            .order_by(models.Message.created_at)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def create_message(self, message_data: Dict[str, Any]) -> models.Message:
        """Создать новое сообщение - избегаем циклических зависимостей"""

        try:
            message_data_copy = message_data.copy()
            for field in ['chat_id', 'sender_id', 'receiver_id', 'reply_to_id', 'forwarded_from_id']:
                if field in message_data_copy and message_data_copy[field] is not None:
                    if isinstance(message_data_copy[field], UUID):
                        message_data_copy[field] = str(message_data_copy[field])

            message = models.Message(**message_data_copy)
            self.db.add(message)
            await self.db.flush()
            await self.db.refresh(message)

            chat_id_str = str(message_data_copy['chat_id'])
            chat_result = await self.db.execute(select(models.Chat).where(models.Chat.id == chat_id_str))
            chat = chat_result.scalar_one_or_none()

            if chat:
                receiver_id_str = str(message_data_copy['receiver_id'])
                if chat.user1_id == receiver_id_str:
                    chat.unread_count_user1 += 1
                else:
                    chat.unread_count_user2 += 1

                await self.db.execute(
                    update(models.Chat)
                    .where(models.Chat.id == chat_id_str)
                    .values(
                        updated_at=datetime.utcnow(),
                        last_message_id=str(message.id)
                    )
                )

            await self.db.commit()
            await self.db.refresh(message)
            return message

        except IntegrityError as e:
            await self.db.rollback()
            raise e
        except Exception as e:
            await self.db.rollback()
            raise e

    async def get_message_by_id(self, message_id: UUID) -> Optional[models.Message]:
        """Получить сообщение по ID"""

        result = await self.db.execute(select(models.Message).where(models.Message.id == str(message_id)))
        return result.scalar_one_or_none()

    async def mark_message_as_read(self, message_id: UUID, user_id: UUID) -> Optional[models.Message]:
        """Пометить сообщение как прочитанное"""

        try:
            result = await self.db.execute(select(models.Message).where(models.Message.id == str(message_id)))
            message = result.scalar_one_or_none()

            if not message or str(message.receiver_id) != str(user_id):
                return None

            if not message.is_read:
                message.is_read = True
                message.read_at = datetime.utcnow()
                chat_result = await self.db.execute(select(models.Chat).where(models.Chat.id == str(message.chat_id)))
                chat = chat_result.scalar_one_or_none()

                if chat:
                    user_id_str = str(user_id)
                    if chat.user1_id == user_id_str:
                        chat.unread_count_user1 = 0
                    else:
                        chat.unread_count_user2 = 0

                read_status = models.MessageReadStatus(message_id=str(message_id), user_id=str(user_id))
                self.db.add(read_status)
                await self.db.flush()
                await self.db.refresh(message)
                await self.db.commit()
            return message

        except Exception as e:
            await self.db.rollback()
            raise e

    async def mark_messages_as_read_bulk(self, message_ids: List[UUID], user_id: UUID) -> bool:
        """Пометить несколько сообщений как прочитанные за один раз"""

        try:
            user_id_str = str(user_id)
            message_ids_str = [str(msg_id) for msg_id in message_ids]
            await self.db.execute(update(models.Message)
                                  .where(models.Message.id.in_(message_ids_str),
                                         models.Message.receiver_id == user_id_str)
                                  .values(is_read=True, read_at=datetime.utcnow()))

            for msg_id in message_ids_str:
                read_status = models.MessageReadStatus(message_id=msg_id, user_id=user_id_str)
                self.db.add(read_status)

            result = await self.db.execute(select(models.Message.chat_id)
                                           .where(models.Message.id.in_(message_ids_str)).distinct())
            chat_ids = [row[0] for row in result]

            for chat_id in chat_ids:
                chat_result = await self.db.execute(select(models.Chat).where(models.Chat.id == chat_id))
                chat = chat_result.scalar_one_or_none()

                if chat:
                    if chat.user1_id == user_id_str:
                        chat.unread_count_user1 = 0
                    else:
                        chat.unread_count_user2 = 0

            await self.db.commit()
            return True

        except Exception as e:
            await self.db.rollback()
            raise e

    async def update_user_online_status(self, user_id: UUID, online: bool) -> None:
        """Обновить онлайн статус пользователя"""

        values = {"online_status": online}
        if not online:
            values["last_seen"] = datetime.utcnow()

        await self.db.execute(update(models.User).where(models.User.id == str(user_id)).values(**values))
        await self.db.commit()

    async def update_typing_status(self, chat_id: UUID, user_id: UUID, is_typing: bool) -> None:
        """Обновить статус набора текста"""

        chat_id_str = str(chat_id)
        user_id_str = str(user_id)
        result = await self.db.execute(select(models.TypingStatus).where(
            models.TypingStatus.chat_id == chat_id_str,
            models.TypingStatus.user_id == user_id_str))
        typing_status = result.scalar_one_or_none()

        if typing_status:
            typing_status.is_typing = is_typing
            typing_status.updated_at = datetime.utcnow()
        else:
            typing_status = models.TypingStatus(chat_id=chat_id_str, user_id=user_id_str, is_typing=is_typing)
            self.db.add(typing_status)

        await self.db.commit()

    async def get_typing_statuses(self, chat_id: UUID) -> List[models.TypingStatus]:
        """Получить активные статусы набора"""

        cutoff_time = datetime.utcnow() - timedelta(seconds=10)
        chat_id_str = str(chat_id)
        result = await self.db.execute(select(models.TypingStatus).where(
            models.TypingStatus.chat_id == chat_id_str,
            models.TypingStatus.is_typing == True,
            models.TypingStatus.updated_at >= cutoff_time))

        await self.db.execute(delete(models.TypingStatus).where(models.TypingStatus.updated_at < cutoff_time))
        await self.db.commit()
        return result.scalars().all()

    async def archive_chat(self, chat_id: UUID) -> None:
        """Архивировать чат"""

        await self.db.execute(update(models.Chat).where(models.Chat.id == str(chat_id)).values(is_active=False))
        await self.db.commit()

    async def delete_chat(self, chat_id: UUID) -> None:
        """Удалить чат и все связанные данные"""

        chat_id_str = str(chat_id)
        try:
            if self.db.in_transaction():
                await self._delete_chat_in_transaction(chat_id_str)
            else:
                async with self.db.begin():
                    await self._delete_chat_in_transaction(chat_id_str)

            print(f"Chat {chat_id} deleted successfully")
        except Exception as e:
            print(f"Error deleting chat {chat_id}: {e}")
            raise

    async def _delete_chat_in_transaction(self, chat_id_str: str) -> None:
        """Внутренний метод для удаления чата в существующей транзакции"""

        result = await self.db.execute(select(models.Message.id).where(models.Message.chat_id == chat_id_str))
        message_ids = [row[0] for row in result]

        if message_ids:
            await self.db.execute(update(models.Chat).where(models.Chat.last_message_id.in_(message_ids))
                                  .values(last_message_id=None))

            await self.db.execute(delete(models.MessageReadStatus).where(
                models.MessageReadStatus.message_id.in_(message_ids)))

        await self.db.execute(delete(models.TypingStatus).where(models.TypingStatus.chat_id == chat_id_str))

        if message_ids:
            await self.db.execute(update(models.Message)
                                  .where(models.Message.reply_to_id.in_(message_ids)).values(reply_to_id=None))

        await self.db.execute(delete(models.Message).where(models.Message.chat_id == chat_id_str))
        await self.db.execute(delete(models.Chat).where(models.Chat.id == chat_id_str))

    async def get_chats_by_date_range(self, user_id: UUID, start_date: datetime, end_date: datetime) -> List[
        models.Chat]:
        """Получить чаты по диапазону дат последнего сообщения"""

        user_id_str = str(user_id)
        subquery = (select(models.Message.chat_id, func.max(models.Message.created_at).label('last_message_date'))
                    .group_by(models.Message.chat_id).subquery())

        result = await self.db.execute(select(models.Chat).join(subquery, models.Chat.id == subquery.c.chat_id).where(
            or_(models.Chat.user1_id == user_id_str, models.Chat.user2_id == user_id_str),
            models.Chat.is_active == True, subquery.c.last_message_date.between(start_date, end_date))
                                       .order_by(desc(subquery.c.last_message_date)))
        return result.scalars().all()

    async def get_other_user_in_chat(self, chat: models.Chat, current_user_id: UUID) -> Optional[models.User]:
        """Получить второго участника чата"""

        current_user_id_str = str(current_user_id)
        other_user_id = (chat.user2_id if chat.user1_id == current_user_id_str else chat.user1_id)
        result = await self.db.execute(select(models.User).where(models.User.id == other_user_id))
        return result.scalar_one_or_none()

    async def get_last_message(self, chat_id: UUID) -> Optional[models.Message]:
        """Получить последнее сообщение в чате"""

        chat_id_str = str(chat_id)
        result = await self.db.execute(select(models.Message).where(models.Message.chat_id == chat_id_str)
                                       .order_by(desc(models.Message.created_at)).limit(1))
        return result.scalar_one_or_none()
