from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query, \
    Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from uuid import UUID
from datetime import datetime
import shutil
from pathlib import Path
import uuid as uuid_lib
from app.database import get_db
from app.crud import ChatCRUD
from app import schemas, models
from .auth import get_current_user, decode_token
from app.websocket_manager import manager as ws_manager

router = APIRouter(prefix="/chat", tags=["chat"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
templates = Jinja2Templates(directory="app/static/templates")


async def get_chat_repository(db: AsyncSession = Depends(get_db)) -> ChatCRUD:
    """Зависимость для получения репозитория чатов"""

    return ChatCRUD(db)


@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str, db: AsyncSession = Depends(get_db)):
    """WebSocket соединение для реального времени"""

    await websocket.accept()
    try:
        payload = decode_token(token)
        if not payload:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid token"
                }
            )
            await websocket.close(code=4001)
            return

        user_id_str = payload.get("sub")
        if not user_id_str:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "Invalid token payload"
                }
            )
            await websocket.close(code=4001)
            return

        user_id = UUID(user_id_str)
        repo = ChatCRUD(db)
        user = await repo.get_user_by_id(user_id)
        if not user:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "User not found"
                }
            )
            await websocket.close(code=4001)
            return

        await ws_manager.connect(user_id, websocket)
        await repo.update_user_online_status(user_id, True)
        await websocket.send_json(
            {
                "type": "connection",
                "status": "connected",
                "user_id": user_id_str,
                "timestamp": datetime.now().isoformat()
            }
        )
        print(f"User {user_id_str} successfully connected via WebSocket")
        try:
            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")
                if message_type == "ping":
                    await websocket.send_json(
                        {
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }
                    )

                elif message_type == "message":
                    await handle_message(data, user_id, repo)
                elif message_type == "typing":
                    await handle_typing(data, user_id, repo)
                elif message_type == "read":
                    await handle_read(data, user_id, repo)
                elif message_type == "chat_update":
                    await handle_chat_update(data, user_id, repo)

        except WebSocketDisconnect:
            print(f"User {user_id_str} disconnected normally")
    except Exception as e:
        print(f"WebSocket error: {e}")
        await websocket.send_json(
            {
                "type": "error",
                "message": str(e)
            }
        )
    finally:
        try:
            if 'user_id' in locals():
                await ws_manager.disconnect(user_id, websocket)
                try:
                    await repo.update_user_online_status(user_id, False)
                except:
                    pass
        except:
            pass
        print("WebSocket connection closed")


async def handle_message(data: Dict[str, Any], sender_id: UUID, repo: ChatCRUD):
    """Обработка нового сообщения"""

    try:
        receiver_id = UUID(data.get("receiver_id"))
        content = data.get("content", "")
        message_type = data.get("message_type", "text")
        chat = await repo.get_chat_by_participants(sender_id, receiver_id)
        if not chat:
            chat = await repo.create_chat(sender_id, receiver_id)

        message_data = {
            "chat_id": chat.id,
            "sender_id": sender_id,
            "receiver_id": receiver_id,
            "message_type": message_type,
            "content": content,
            "reply_to_id": data.get("reply_to_id"),
            "forwarded_from_id": data.get("forwarded_from_id"),
            "extra_data": data.get("extra_data", {})
        }
        message = await repo.create_message(message_data)

        ws_message = {
            "type": "message",
            "message_id": str(message.id),  # UUID -> str
            "chat_id": str(chat.id),  # UUID -> str
            "sender_id": str(sender_id),  # UUID -> str
            "receiver_id": str(receiver_id),  # UUID -> str
            "content": message.content,
            "message_type": message.message_type.value if hasattr(message.message_type,
                                                                  'value') else message.message_type,
            "created_at": message.created_at.isoformat(),  # datetime -> ISO string
            "is_read": message.is_read
        }
        await ws_manager.send_personal_message(ws_message, sender_id)
        await ws_manager.send_personal_message(ws_message, receiver_id)
        print(f"Message sent from {sender_id} to {receiver_id}")
    except Exception as e:
        print(f"Error handling message: {e}")


async def handle_typing(data: Dict[str, Any], user_id: UUID, repo: ChatCRUD):
    """Обработка индикатора набора"""

    try:
        chat_id = UUID(data.get("chat_id"))
        is_typing = data.get("is_typing", False)
        chat = await repo.get_chat_by_id(chat_id, user_id)
        if not chat:
            return

        receiver_id = chat.user2_id if str(chat.user1_id) == str(user_id) else chat.user1_id
        await repo.update_typing_status(chat_id, user_id, is_typing)

        typing_message = {
            "type": "typing",
            "chat_id": str(chat_id),
            "user_id": str(user_id),
            "is_typing": is_typing,
            "timestamp": datetime.now().isoformat()
        }
        await ws_manager.send_personal_message(typing_message, receiver_id)
        print(f"Typing indicator from {user_id} in chat {chat_id}")
    except Exception as e:
        print(f"Error handling typing: {e}")


async def handle_read(data: Dict[str, Any], user_id: UUID, repo: ChatCRUD):
    """Обработка отметки о прочтении"""

    try:
        message_id = UUID(data.get("message_id"))
        message = await repo.mark_message_as_read(message_id, user_id)
        if not message:
            return

        read_message = {
            "type": "message_read",
            "message_id": str(message_id),
            "chat_id": str(message.chat_id),
            "reader_id": str(user_id),
            "timestamp": datetime.now().isoformat()
        }
        await ws_manager.send_personal_message(read_message, message.sender_id)
        print(f"Message {message_id} marked as read by {user_id}")
    except Exception as e:
        print(f"Error handling read: {e}")


async def handle_chat_update(data: Dict[str, Any], user_id: UUID, repo: ChatCRUD):
    """Обработка обновления чата"""
    pass


@router.get("/messages/{user_id}", response_model=List[schemas.Message])
async def get_messages_by_id(user_id: UUID, skip: int = 0, limit: int = 100,
                             current_user: models.User = Depends(get_current_user),
                             repo: ChatCRUD = Depends(get_chat_repository)):
    """Получить все сообщения с пользователем"""

    chat = await repo.get_chat_by_participants(current_user.id, user_id)
    if not chat:
        return []

    messages = await repo.get_messages(chat.id, skip, limit)
    unread_message_ids = [
        message.id for message in messages
        if not message.is_read and str(message.receiver_id) == str(current_user.id)
    ]

    if unread_message_ids:
        try:
            await repo.mark_messages_as_read_bulk(unread_message_ids, current_user.id)
        except Exception as e:
            print(f"Error marking messages as read: {e}")

            for msg_id in unread_message_ids:
                try:
                    await repo.mark_message_as_read(msg_id, current_user.id)
                except:
                    continue
    return messages


@router.get("/chats", response_model=List[schemas.ChatInfo])
async def get_all_chats(current_user: models.User = Depends(get_current_user),
                        repo: ChatCRUD = Depends(get_chat_repository)):
    """Получить все чаты текущего пользователя с последним сообщением"""

    chats = await repo.get_user_chats(current_user.id)
    result = []
    for chat in chats:
        other_user = await repo.get_other_user_in_chat(chat, current_user.id)
        if not other_user:
            continue

        last_message = await repo.get_last_message(chat.id)
        if str(chat.user1_id) == str(current_user.id):
            unread_count = chat.unread_count_user1
        else:
            unread_count = chat.unread_count_user2

        is_online = ws_manager.is_user_online(other_user.id)
        other_user_with_status = schemas.User(
            id=other_user.id,
            username=other_user.username,
            email=other_user.email,
            is_active=other_user.is_active,
            online_status=other_user.online_status,
            last_seen=other_user.last_seen,
            profile_image=other_user.profile_image,
            created_at=other_user.created_at
        )

        other_user_with_status_dict = other_user_with_status.dict()
        other_user_with_status_dict["is_online"] = is_online
        result.append(schemas.ChatInfo(
            id=chat.id,
            user1_id=chat.user1_id,
            user2_id=chat.user2_id,
            other_user=other_user_with_status_dict,
            last_message=last_message,
            unread_count=unread_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at
        ))
    return result


@router.post("/chats/by-date", response_model=List[schemas.ChatInfo])
async def get_chats_by_date(date_filter: schemas.DateFilter, current_user: models.User = Depends(get_current_user),
                            repo: ChatCRUD = Depends(get_chat_repository)):
    """Получить чаты по диапазону дат последнего сообщения"""

    chats = await repo.get_chats_by_date_range(current_user.id, date_filter.start_date, date_filter.end_date)
    result = []
    for chat in chats:
        other_user = await repo.get_other_user_in_chat(chat, current_user.id)
        if not other_user:
            continue

        last_message = await repo.get_last_message(chat.id)
        if str(chat.user1_id) == str(current_user.id):
            unread_count = chat.unread_count_user1
        else:
            unread_count = chat.unread_count_user2

        is_online = ws_manager.is_user_online(other_user.id)
        other_user_with_status = schemas.User(
            id=other_user.id,
            username=other_user.username,
            email=other_user.email,
            is_active=other_user.is_active,
            online_status=other_user.online_status,
            last_seen=other_user.last_seen,
            profile_image=other_user.profile_image,
            created_at=other_user.created_at
        )

        other_user_with_status_dict = other_user_with_status.dict()
        other_user_with_status_dict["is_online"] = is_online
        result.append(schemas.ChatInfo(
            id=chat.id,
            user1_id=chat.user1_id,
            user2_id=chat.user2_id,
            other_user=other_user_with_status_dict,
            last_message=last_message,
            unread_count=unread_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at
        ))
    return result


@router.delete("/{chat_id}")
async def delete_chat_by_id(chat_id: UUID, current_user: models.User = Depends(get_current_user),
                            repo: ChatCRUD = Depends(get_chat_repository)):
    """Удалить чат по ID"""

    chat = await repo.get_chat_by_id(chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await repo.delete_chat(chat_id)
    return {"message": "Chat deleted successfully"}


@router.put("/archive/{chat_id}")
async def archive_chat_by_id(chat_id: UUID, current_user: models.User = Depends(get_current_user),
                             repo: ChatCRUD = Depends(get_chat_repository)):
    """Архивировать чат по ID"""

    chat = await repo.get_chat_by_id(chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    await repo.archive_chat(chat_id)
    return {"message": "Chat archived successfully"}


@router.post("/new", response_model=schemas.ChatInfo)
async def make_new_chat(chat_data: schemas.ChatCreate, current_user: models.User = Depends(get_current_user),
                        repo: ChatCRUD = Depends(get_chat_repository)):
    """Создать новый чат с пользователем или реактивировать архивный"""

    other_user = await repo.get_user_by_id(chat_data.user2_id)
    if not other_user or not other_user.is_active:
        raise HTTPException(status_code=404, detail="User not found or inactive")

    existing_chat = await repo.get_chat_by_participants(current_user.id, chat_data.user2_id)
    if existing_chat:
        if existing_chat.is_active:
            raise HTTPException(status_code=400, detail="Chat already exists")
        else:
            existing_chat.is_active = True
            existing_chat.updated_at = datetime.utcnow()
            await repo.db.commit()
            await repo.db.refresh(existing_chat)
            chat = existing_chat
    else:
        chat = await repo.create_chat(current_user.id, chat_data.user2_id)

    is_online = ws_manager.is_user_online(chat_data.user2_id)
    other_user_with_status = schemas.User(
        id=UUID(other_user.id),
        username=other_user.username,
        email=other_user.email,
        is_active=other_user.is_active,
        online_status=other_user.online_status,
        last_seen=other_user.last_seen,
        profile_image=other_user.profile_image,
        created_at=other_user.created_at
    )

    other_user_with_status_dict = other_user_with_status.dict()
    other_user_with_status_dict["is_online"] = is_online
    return schemas.ChatInfo(
        id=UUID(chat.id),
        user1_id=UUID(chat.user1_id),
        user2_id=UUID(chat.user2_id),
        other_user=other_user_with_status_dict,
        created_at=chat.created_at,
        updated_at=chat.updated_at
    )


@router.post("/message", response_model=schemas.Message)
async def send_message(message_data: schemas.MessageCreate, current_user: models.User = Depends(get_current_user),
                       repo: ChatCRUD = Depends(get_chat_repository)):
    """Отправить текстовое сообщение (HTTP)"""

    chat = await repo.get_chat_by_participants(current_user.id, message_data.receiver_id)
    if not chat:
        chat = await repo.create_chat(current_user.id, message_data.receiver_id)

    message_data_dict = {
        "chat_id": UUID(chat.id),
        "sender_id": current_user.id,
        "receiver_id": message_data.receiver_id,
        "message_type": message_data.message_type,
        "content": message_data.content,
        "reply_to_id": message_data.reply_to_id
    }
    message = await repo.create_message(message_data_dict)

    ws_message = {
        "type": "message",
        "message_id": str(message.id),
        "chat_id": str(chat.id),
        "sender_id": str(current_user.id),
        "receiver_id": str(message_data.receiver_id),
        "content": message.content,
        "message_type": message.message_type.value,
        "created_at": message.created_at.isoformat(),
        "is_read": message.is_read
    }
    await ws_manager.send_personal_message(ws_message, message_data.receiver_id)
    return message


@router.post("/media")
async def send_media(receiver_id: UUID = Form(...), file: UploadFile = File(...),
                     current_user: models.User = Depends(get_current_user),
                     repo: ChatCRUD = Depends(get_chat_repository)):
    """Отправить медиафайл"""

    content_type = file.content_type or ""
    if content_type.startswith('image/'):
        message_type = "image"
    elif content_type.startswith('video/'):
        message_type = "video"
    elif content_type.startswith('audio/'):
        message_type = "audio"
    else:
        message_type = "file"

    chat = await repo.get_chat_by_participants(current_user.id, receiver_id)
    if not chat:
        chat = await repo.create_chat(current_user.id, receiver_id)

    file_extension = Path(file.filename).suffix
    file_name = f"{uuid_lib.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / file_name
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = file_path.stat().st_size
    message_data = {
        "chat_id": chat.id,
        "sender_id": current_user.id,
        "receiver_id": receiver_id,
        "message_type": message_type,
        "media_url": f"/uploads/{file_name}",
        "file_name": file.filename,
        "file_size": file_size,
        "file_type": content_type
    }
    message = await repo.create_message(message_data)

    ws_message = {
        "type": "message",
        "message_id": str(message.id),
        "chat_id": str(chat.id),
        "sender_id": str(current_user.id),
        "receiver_id": str(receiver_id),
        "message_type": message_type,
        "media_url": f"/uploads/{file_name}",
        "file_name": file.filename,
        "created_at": message.created_at.isoformat(),
        "is_read": message.is_read
    }
    await ws_manager.send_personal_message(ws_message, receiver_id)
    return message


@router.post("/reply/{message_id}")
async def reply_message(message_id: UUID, content: str = Form(...),
                        current_user: models.User = Depends(get_current_user),
                        repo: ChatCRUD = Depends(get_chat_repository)):
    """Ответить на сообщение"""

    original_message = await repo.get_message_by_id(message_id)
    if not original_message:
        raise HTTPException(status_code=404, detail="Message not found")

    chat = await repo.get_chat_by_id(original_message.chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=403, detail="Not authorized")

    message_data = {
        "chat_id": chat.id,
        "sender_id": current_user.id,
        "receiver_id": original_message.sender_id,
        "message_type": "text",
        "content": content,
        "reply_to_id": message_id
    }
    message = await repo.create_message(message_data)

    ws_message = {
        "type": "message",
        "message_id": str(message.id),
        "chat_id": str(chat.id),
        "sender_id": str(current_user.id),
        "receiver_id": str(original_message.sender_id),
        "content": content,
        "message_type": "text",
        "reply_to_id": str(message_id),
        "created_at": message.created_at.isoformat(),
        "is_read": message.is_read
    }
    await ws_manager.send_personal_message(ws_message, original_message.sender_id)
    return message


@router.post("/forward/{message_id}")
async def forward_message(message_id: UUID, receiver_id: UUID = Form(...),
                          current_user: models.User = Depends(get_current_user),
                          repo: ChatCRUD = Depends(get_chat_repository)):
    """Переслать сообщение другому пользователю"""

    original_message = await repo.get_message_by_id(message_id)
    if not original_message:
        raise HTTPException(status_code=404, detail="Message not found")

    chat = await repo.get_chat_by_participants(current_user.id, receiver_id)
    if not chat:
        chat = await repo.create_chat(current_user.id, receiver_id)

    message_data = {
        "chat_id": chat.id,
        "sender_id": current_user.id,
        "receiver_id": receiver_id,
        "message_type": original_message.message_type,
        "content": original_message.content,
        "media_url": original_message.media_url,
        "file_name": original_message.file_name,
        "file_size": original_message.file_size,
        "file_type": original_message.file_type,
        "forwarded_from_id": original_message.sender_id
    }
    message = await repo.create_message(message_data)

    ws_message = {
        "type": "message",
        "message_id": str(message.id),
        "chat_id": str(chat.id),
        "sender_id": str(current_user.id),
        "receiver_id": str(receiver_id),
        "content": original_message.content,
        "message_type": original_message.message_type,
        "media_url": original_message.media_url,
        "file_name": original_message.file_name,
        "forwarded_from_id": str(original_message.sender_id),
        "created_at": message.created_at.isoformat(),
        "is_read": message.is_read
    }
    await ws_manager.send_personal_message(ws_message, receiver_id)
    return message


@router.post("/file")
async def send_file(receiver_id: UUID = Form(...), file: UploadFile = File(...),
                    current_user: models.User = Depends(get_current_user),
                    repo: ChatCRUD = Depends(get_chat_repository)):
    """Отправить файл"""
    return await send_media(receiver_id, file, current_user, repo)


@router.post("/read/{message_id}")
async def mark_message_as_read(message_id: UUID, current_user: models.User = Depends(get_current_user),
                               repo: ChatCRUD = Depends(get_chat_repository)):
    """Пометить сообщение как прочитанное"""

    message = await repo.mark_message_as_read(message_id, current_user.id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found or not authorized")

    read_message = {
        "type": "message_read",
        "message_id": str(message_id),
        "chat_id": str(message.chat_id),
        "reader_id": str(current_user.id),
        "timestamp": datetime.now().isoformat()
    }
    await ws_manager.send_personal_message(read_message, message.sender_id)
    return {"status": "success", "message": "Message marked as read"}


@router.get("/typing/{chat_id}")
async def get_typing_status(chat_id: UUID, current_user: models.User = Depends(get_current_user),
                            repo: ChatCRUD = Depends(get_chat_repository)):
    """Получить статус набора в чате"""

    chat = await repo.get_chat_by_id(chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    typing_statuses = await repo.get_typing_statuses(chat_id)
    return [
        {
            "user_id": str(status.user_id),
            "is_typing": status.is_typing,
            "updated_at": status.updated_at
        }
        for status in typing_statuses
    ]


@router.post("/typing/{chat_id}")
async def set_typing_status(chat_id: UUID, is_typing: bool = True,
                            current_user: models.User = Depends(get_current_user),
                            repo: ChatCRUD = Depends(get_chat_repository)):
    """Установить статус набора в чате"""

    chat = await repo.get_chat_by_id(chat_id, current_user.id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    receiver_id = chat.user2_id if str(chat.user1_id) == str(current_user.id) else chat.user1_id
    await repo.update_typing_status(chat_id, current_user.id, is_typing)

    typing_message = {
        "type": "typing",
        "chat_id": str(chat_id),
        "user_id": str(current_user.id),
        "is_typing": is_typing,
        "timestamp": datetime.now().isoformat()
    }
    await ws_manager.send_personal_message(typing_message, receiver_id)
    return {"status": "success", "is_typing": is_typing}


@router.get("/online/{user_id}")
async def check_user_online(user_id: UUID, repo: ChatCRUD = Depends(get_chat_repository)):
    """Проверить онлайн статус пользователя"""

    is_online = ws_manager.is_user_online(user_id)
    user = await repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": str(user_id),
        "is_online": is_online,
        "online_status": user.online_status,
        "last_seen": user.last_seen
    }


@router.get("/online-users")
async def get_online_users(user_ids: List[UUID] = Query(...)):
    """Получить статус онлайн для списка пользователей"""

    online_status = {}
    for uid in user_ids:
        online_status[str(uid)] = ws_manager.is_user_online(uid)

    return online_status


@router.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """Получить загруженный файл"""

    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.get("/test-ws", response_class=HTMLResponse)
async def test_websocket_page(request: Request):
    """Главная страница приложения"""

    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )
