from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form, Query, \
    Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import os
import shutil
import json
from pathlib import Path

from app.database import get_db
from app import schemas, models
from .auth import get_current_user, decode_token
from app.websocket_manager import manager as ws_manager

router = APIRouter(prefix="/chat", tags=["chat"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# WebSocket endpoint
@router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """WebSocket соединение для реального времени"""
    await websocket.accept()

    try:
        # Декодируем токен
        payload = decode_token(token)
        if not payload:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid token"
            })
            await websocket.close(code=4001)
            return

        user_id_str = payload.get("sub")
        if not user_id_str:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid token payload"
            })
            await websocket.close(code=4001)
            return

        user_id = UUID(user_id_str)
        db_gen = get_db()
        db = next(db_gen)

        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            await websocket.send_json({
                "type": "error",
                "message": "User not found"
            })
            await websocket.close(code=4001)
            return

        await ws_manager.connect(user_id, websocket)
        user.online_status = True
        user.last_seen = None
        db.commit()
        await websocket.send_json({
            "type": "connection",
            "status": "connected",
            "user_id": user_id_str,
            "timestamp": datetime.now().isoformat()
        })

        print(f"User {user_id_str} successfully connected via WebSocket")

        try:
            while True:
                data = await websocket.receive_json()
                message_type = data.get("type")

                if message_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })

                elif message_type == "message":
                    await handle_message(data, user_id, db)

                elif message_type == "typing":
                    await handle_typing(data, user_id, db)

                elif message_type == "read":
                    await handle_read(data, user_id, db)

                elif message_type == "chat_update":
                    await handle_chat_update(data, user_id, db)

        except WebSocketDisconnect:
            print(f"User {user_id_str} disconnected normally")

    except Exception as e:
        print(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass
    finally:
        try:
            if 'user_id' in locals():
                await ws_manager.disconnect(user_id, websocket)

                try:
                    db_gen = get_db()
                    db = next(db_gen)
                    user = db.query(models.User).filter(models.User.id == user_id).first()
                    if user:
                        user.online_status = False
                        user.last_seen = datetime.utcnow()
                        db.commit()
                except:
                    pass
        except:
            pass
        print("WebSocket connection closed")


async def handle_message(data: Dict[str, Any], sender_id: UUID, db: Session):
    """Обработка нового сообщения"""
    try:
        receiver_id = UUID(data.get("receiver_id"))
        content = data.get("content", "")
        message_type = data.get("message_type", "text")

        # Находим или создаем чат
        chat = db.query(models.Chat).filter(
            (models.Chat.user1_id == sender_id) & (models.Chat.user2_id == receiver_id) |
            (models.Chat.user1_id == receiver_id) & (models.Chat.user2_id == sender_id)
        ).first()

        if not chat:
            user1_id, user2_id = sorted([sender_id, receiver_id])
            chat = models.Chat(user1_id=user1_id, user2_id=user2_id)
            db.add(chat)
            db.commit()
            db.refresh(chat)

        message = models.Message(
            chat_id=chat.id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=message_type,
            content=content,
            reply_to_id=data.get("reply_to_id"),
            forwarded_from_id=data.get("forwarded_from_id"),
            extra_data=data.get("extra_data", {})
        )

        db.add(message)

        chat.updated_at = datetime.utcnow()
        chat.last_message_id = message.id

        if str(chat.user1_id) == str(receiver_id):
            chat.unread_count_user1 += 1
        else:
            chat.unread_count_user2 += 1

        db.commit()
        db.refresh(message)

        ws_message = {
            "type": "message",
            "message_id": str(message.id),
            "chat_id": str(chat.id),
            "sender_id": str(sender_id),
            "receiver_id": str(receiver_id),
            "content": message.content,
            "message_type": message.message_type,
            "created_at": message.created_at.isoformat(),
            "is_read": message.is_read
        }

        await ws_manager.send_personal_message(ws_message, sender_id)
        await ws_manager.send_personal_message(ws_message, receiver_id)

        print(f"Message sent from {sender_id} to {receiver_id}")

    except Exception as e:
        print(f"Error handling message: {e}")


async def handle_typing(data: Dict[str, Any], user_id: UUID, db: Session):
    """Обработка индикатора набора"""
    try:
        chat_id = UUID(data.get("chat_id"))
        is_typing = data.get("is_typing", False)

        chat = db.query(models.Chat).filter(
            models.Chat.id == chat_id,(models.Chat.user1_id == user_id) | (models.Chat.user2_id == user_id)).first()

        if not chat:
            return

        receiver_id = chat.user2_id if str(chat.user1_id) == str(user_id) else chat.user1_id
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


async def handle_read(data: Dict[str, Any], user_id: UUID, db: Session):
    """Обработка отметки о прочтении"""
    try:
        message_id = UUID(data.get("message_id"))
        message = db.query(models.Message).filter(models.Message.id == message_id).first()
        if not message:
            return

        if str(message.receiver_id) != str(user_id):
            return

        if not message.is_read:
            message.is_read = True
            message.read_at = datetime.utcnow()
            chat = db.query(models.Chat).filter(models.Chat.id == message.chat_id).first()
            if chat:
                if str(chat.user1_id) == str(user_id):
                    chat.unread_count_user1 = 0
                else:
                    chat.unread_count_user2 = 0

            read_status = models.MessageReadStatus(
                message_id=message_id,
                user_id=user_id
            )
            db.add(read_status)
            db.commit()

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


async def handle_chat_update(data: Dict[str, Any], user_id: UUID, db: Session):
    """Обработка обновления чата"""
    pass


# HTTP endpoints
@router.get("/messages/{user_id}", response_model=List[schemas.Message])
async def get_messages_by_id(
        user_id: UUID,
        skip: int = 0,
        limit: int = 100,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получить все сообщения с указанным пользователем"""
    chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == user_id) |
        (models.Chat.user1_id == user_id) & (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        return []

    messages = db.query(models.Message).filter(
        models.Message.chat_id == chat.id
    ).order_by(models.Message.created_at).offset(skip).limit(limit).all()

    for message in messages:
        if not message.is_read and str(message.receiver_id) == str(current_user.id):
            message.is_read = True
            message.read_at = datetime.utcnow()
            read_status = models.MessageReadStatus(
                message_id=message.id,
                user_id=current_user.id
            )
            db.add(read_status)

    db.commit()

    return messages


@router.get("/chats", response_model=List[schemas.ChatInfo])
async def get_all_chats(
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получить все чаты пользователя с последним сообщением"""
    chats = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) | (models.Chat.user2_id == current_user.id),
        models.Chat.is_active == True
    ).order_by(models.Chat.updated_at.desc()).all()

    result = []

    for chat in chats:
        other_user_id = chat.user2_id if str(chat.user1_id) == str(current_user.id) else chat.user1_id
        other_user = db.query(models.User).filter(models.User.id == other_user_id).first()

        if not other_user:
            continue

        last_message = db.query(models.Message).filter(
            models.Message.chat_id == chat.id
        ).order_by(models.Message.created_at.desc()).first()

        if str(chat.user1_id) == str(current_user.id):
            unread_count = chat.unread_count_user1
        else:
            unread_count = chat.unread_count_user2

        is_online = ws_manager.is_user_online(other_user_id)
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
async def get_chats_by_date(
        date_filter: schemas.DateFilter,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получить чаты по диапазону дат последнего сообщения"""
    from sqlalchemy import func

    subquery = db.query(
        models.Message.chat_id,
        func.max(models.Message.created_at).label('last_message_date')
    ).group_by(models.Message.chat_id).subquery()

    chats = db.query(models.Chat).join(
        subquery, models.Chat.id == subquery.c.chat_id).filter(
        (models.Chat.user1_id == current_user.id) | (models.Chat.user2_id == current_user.id),
        models.Chat.is_active == True,
        subquery.c.last_message_date.between(date_filter.start_date, date_filter.end_date)
    ).order_by(subquery.c.last_message_date.desc()).all()

    result = []

    for chat in chats:
        other_user_id = chat.user2_id if str(chat.user1_id) == str(current_user.id) else chat.user1_id
        other_user = db.query(models.User).filter(models.User.id == other_user_id).first()

        if not other_user:
            continue

        last_message = db.query(models.Message).filter(models.Message.chat_id == chat.id
        ).order_by(models.Message.created_at.desc()).first()

        if str(chat.user1_id) == str(current_user.id):
            unread_count = chat.unread_count_user1
        else:
            unread_count = chat.unread_count_user2

        is_online = ws_manager.is_user_online(other_user_id)
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
async def delete_chat_by_id(
        chat_id: UUID,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Удалить чат по ID"""
    chat = db.query(models.Chat).filter(models.Chat.id == chat_id,models.Chat.is_active == True).first()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    if str(current_user.id) not in [str(chat.user1_id), str(chat.user2_id)]:
        raise HTTPException(status_code=403, detail="Not authorized to delete this chat")
    chat.is_active = False
    db.commit()

    return {"message": "Chat deleted successfully"}


@router.post("/new", response_model=schemas.ChatInfo)
async def make_new_chat(
        chat_data: schemas.ChatCreate,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Создать новый чат с пользователем"""
    other_user = db.query(models.User).filter(models.User.id == chat_data.user2_id,models.User.is_active == True).first()

    if not other_user:
        raise HTTPException(status_code=404, detail="User not found")

    existing_chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == chat_data.user2_id) |
        (models.Chat.user1_id == chat_data.user2_id) & (models.Chat.user2_id == current_user.id),
        models.Chat.is_active == True
    ).first()

    if existing_chat:
        raise HTTPException(status_code=400, detail="Chat already exists")

    user1_id, user2_id = sorted([current_user.id, chat_data.user2_id])
    chat = models.Chat(
        user1_id=user1_id,
        user2_id=user2_id
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)

    is_online = ws_manager.is_user_online(chat_data.user2_id)
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

    return schemas.ChatInfo(
        id=chat.id,
        user1_id=chat.user1_id,
        user2_id=chat.user2_id,
        other_user=other_user_with_status_dict,
        created_at=chat.created_at,
        updated_at=chat.updated_at
    )


@router.post("/message", response_model=schemas.Message)
async def send_message(
        message_data: schemas.MessageCreate,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Отправить текстовое сообщение (HTTP)"""

    chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == message_data.receiver_id) |
        (models.Chat.user1_id == message_data.receiver_id) & (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        user1_id, user2_id = sorted([current_user.id, message_data.receiver_id])
        chat = models.Chat(user1_id=user1_id, user2_id=user2_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)

    message = models.Message(
        chat_id=chat.id,
        sender_id=current_user.id,
        receiver_id=message_data.receiver_id,
        message_type=message_data.message_type,
        content=message_data.content,
        reply_to_id=message_data.reply_to_id
    )

    db.add(message)

    chat.updated_at = datetime.utcnow()
    chat.last_message_id = message.id
    if str(chat.user1_id) == str(message_data.receiver_id):
        chat.unread_count_user1 += 1
    else:
        chat.unread_count_user2 += 1

    db.commit()
    db.refresh(message)

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
async def send_media(
        receiver_id: UUID = Form(...),
        file: UploadFile = File(...),
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
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

    chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == receiver_id) |
        (models.Chat.user1_id == receiver_id) & (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        user1_id, user2_id = sorted([current_user.id, receiver_id])
        chat = models.Chat(user1_id=user1_id, user2_id=user2_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)

    import uuid as uuid_lib
    file_extension = Path(file.filename).suffix
    file_name = f"{uuid_lib.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / file_name

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    file_size = file_path.stat().st_size

    message = models.Message(
        chat_id=chat.id,
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message_type=message_type,
        media_url=f"/uploads/{file_name}",
        file_name=file.filename,
        file_size=file_size,
        file_type=content_type
    )

    db.add(message)
    chat.updated_at = datetime.utcnow()
    chat.last_message_id = message.id

    if str(chat.user1_id) == str(receiver_id):
        chat.unread_count_user1 += 1
    else:
        chat.unread_count_user2 += 1

    db.commit()
    db.refresh(message)

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
async def reply_message(
        message_id: UUID,
        content: str = Form(...),
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Ответить на сообщение"""
    original_message = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not original_message:
        raise HTTPException(status_code=404, detail="Message not found")

    chat = db.query(models.Chat).filter(models.Chat.id == original_message.chat_id).first()
    if not chat or (str(current_user.id) not in [str(chat.user1_id), str(chat.user2_id)]):
        raise HTTPException(status_code=403, detail="Not authorized")

    message = models.Message(
        chat_id=chat.id,
        sender_id=current_user.id,
        receiver_id=original_message.sender_id,
        message_type="text",
        content=content,
        reply_to_id=message_id
    )

    db.add(message)

    chat.updated_at = datetime.utcnow()
    chat.last_message_id = message.id

    if str(chat.user1_id) == str(original_message.sender_id):
        chat.unread_count_user1 += 1
    else:
        chat.unread_count_user2 += 1

    db.commit()
    db.refresh(message)

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
async def reply_message_to_id(
        message_id: UUID,
        receiver_id: UUID = Form(...),
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Переслать сообщение другому пользователю"""
    original_message = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not original_message:
        raise HTTPException(status_code=404, detail="Message not found")

    chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == receiver_id) |
        (models.Chat.user1_id == receiver_id) & (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        user1_id, user2_id = sorted([current_user.id, receiver_id])
        chat = models.Chat(user1_id=user1_id, user2_id=user2_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)

    message = models.Message(
        chat_id=chat.id,
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message_type=original_message.message_type,
        content=original_message.content,
        media_url=original_message.media_url,
        file_name=original_message.file_name,
        file_size=original_message.file_size,
        file_type=original_message.file_type,
        forwarded_from_id=original_message.sender_id
    )

    db.add(message)

    chat.updated_at = datetime.utcnow()
    chat.last_message_id = message.id
    if str(chat.user1_id) == str(receiver_id):
        chat.unread_count_user1 += 1
    else:
        chat.unread_count_user2 += 1

    db.commit()
    db.refresh(message)

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
async def send_file(
        receiver_id: UUID = Form(...),
        file: UploadFile = File(...),
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Отправить файл"""
    return await send_media(receiver_id, file, current_user, db)


@router.post("/location")
async def send_geolocation(
        location_data: schemas.LocationCreate,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Отправить геолокацию"""
    chat = db.query(models.Chat).filter(
        (models.Chat.user1_id == current_user.id) & (models.Chat.user2_id == location_data.receiver_id) |
        (models.Chat.user1_id == location_data.receiver_id) & (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        user1_id, user2_id = sorted([current_user.id, location_data.receiver_id])
        chat = models.Chat(user1_id=user1_id, user2_id=user2_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)

    message = models.Message(
        chat_id=chat.id,
        sender_id=current_user.id,
        receiver_id=location_data.receiver_id,
        message_type="location",
        latitude=location_data.latitude,
        longitude=location_data.longitude
    )

    db.add(message)

    chat.updated_at = datetime.utcnow()
    chat.last_message_id = message.id
    if str(chat.user1_id) == str(location_data.receiver_id):
        chat.unread_count_user1 += 1
    else:
        chat.unread_count_user2 += 1

    db.commit()
    db.refresh(message)

    ws_message = {
        "type": "message",
        "message_id": str(message.id),
        "chat_id": str(chat.id),
        "sender_id": str(current_user.id),
        "receiver_id": str(location_data.receiver_id),
        "message_type": "location",
        "latitude": location_data.latitude,
        "longitude": location_data.longitude,
        "created_at": message.created_at.isoformat(),
        "is_read": message.is_read
    }

    await ws_manager.send_personal_message(ws_message, location_data.receiver_id)

    return message


@router.post("/read/{message_id}")
async def mark_message_as_read(
        message_id: UUID,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Пометить сообщение как прочитанное"""
    message = db.query(models.Message).filter(models.Message.id == message_id).first()

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if str(message.receiver_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to mark this message as read")

    if not message.is_read:
        message.is_read = True
        message.read_at = datetime.utcnow()
        chat = db.query(models.Chat).filter(models.Chat.id == message.chat_id).first()
        if chat:
            if str(chat.user1_id) == str(current_user.id):
                chat.unread_count_user1 = 0
            else:
                chat.unread_count_user2 = 0

        read_status = models.MessageReadStatus(
            message_id=message_id,
            user_id=current_user.id
        )
        db.add(read_status)
        db.commit()
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
async def get_typing_status(
        chat_id: UUID,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Получить статус набора в чате"""
    chat = db.query(models.Chat).filter(
        models.Chat.id == chat_id,
        (models.Chat.user1_id == current_user.id) | (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    from datetime import timedelta
    cutoff_time = datetime.utcnow() - timedelta(seconds=10)

    typing_statuses = db.query(models.TypingStatus).filter(
        models.TypingStatus.chat_id == chat_id,
        models.TypingStatus.is_typing == True,
        models.TypingStatus.updated_at >= cutoff_time
    ).all()

    db.query(models.TypingStatus).filter(
        models.TypingStatus.updated_at < cutoff_time
    ).delete()
    db.commit()
    return [
        {
            "user_id": status.user_id,
            "is_typing": status.is_typing,
            "updated_at": status.updated_at
        }
        for status in typing_statuses
    ]


@router.post("/typing/{chat_id}")
async def set_typing_status(
        chat_id: UUID,
        is_typing: bool = True,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Установить статус набора в чате"""
    chat = db.query(models.Chat).filter(
        models.Chat.id == chat_id,
        (models.Chat.user1_id == current_user.id) | (models.Chat.user2_id == current_user.id)
    ).first()

    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    receiver_id = chat.user2_id if str(chat.user1_id) == str(current_user.id) else chat.user1_id
    typing_status = db.query(models.TypingStatus).filter(
        models.TypingStatus.chat_id == chat_id,
        models.TypingStatus.user_id == current_user.id
    ).first()

    if typing_status:
        typing_status.is_typing = is_typing
        typing_status.updated_at = datetime.utcnow()
    else:
        typing_status = models.TypingStatus(
            chat_id=chat_id,
            user_id=current_user.id,
            is_typing=is_typing
        )
        db.add(typing_status)

    db.commit()
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
async def check_user_online(
        user_id: UUID,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db)
):
    """Проверить онлайн статус пользователя"""
    is_online = ws_manager.is_user_online(user_id)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": str(user_id),
        "is_online": is_online,
        "online_status": user.online_status,
        "last_seen": user.last_seen
    }


@router.get("/online-users")
async def get_online_users(
        user_ids: List[UUID] = Query(...),
        current_user: models.User = Depends(get_current_user)
):
    """Получить статус онлайн для списка пользователей"""
    online_status = {}
    for uid in user_ids:
        online_status[str(uid)] = ws_manager.is_user_online(uid)

    return online_status


@router.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """
    Получить загруженный файл
    """
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@router.get("/test-ws", response_class=HTMLResponse)
async def test_websocket_page():
    """Тестовая страница для WebSocket"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WebSocket Chat Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .section { margin-bottom: 20px; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            .messages { height: 300px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; }
            .message { margin: 5px 0; padding: 8px; border-radius: 4px; }
            .sent { background: #e3f2fd; text-align: right; }
            .received { background: #f5f5f5; }
            .status { color: #666; font-size: 12px; }
            .typing { color: #2196f3; font-style: italic; }
            .online { color: #4caf50; }
            .offline { color: #f44336; }
            input, button, textarea { padding: 8px; margin: 5px; }
            textarea { width: 70%; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>WebSocket Chat Test</h1>

            <div class="section">
                <h3>Authentication</h3>
                <input type="text" id="token" placeholder="JWT Token" style="width: 300px;">
                <button onclick="connectWebSocket()">Connect</button>
                <button onclick="disconnectWebSocket()">Disconnect</button>
                <div id="connectionStatus" class="status">Not connected</div>
            </div>

            <div class="section">
                <h3>Send Test Message</h3>
                <input type="text" id="receiverId" placeholder="Receiver ID (UUID)" style="width: 300px;">
                <br>
                <textarea id="messageContent" placeholder="Message" rows="3"></textarea>
                <br>
                <button onclick="sendTestMessage()">Send Message</button>
                <button onclick="sendTyping(true)">Start Typing</button>
                <button onclick="sendTyping(false)">Stop Typing</button>
            </div>

            <div class="section">
                <h3>Messages</h3>
                <div id="messages" class="messages"></div>
                <div id="typingIndicator" class="typing" style="display: none;">
                    User is typing...
                </div>
            </div>

            <div class="section">
                <h3>Log</h3>
                <div id="log" style="height: 200px; overflow-y: auto; font-family: monospace; font-size: 12px;"></div>
            </div>
        </div>

        <script>
            let ws = null;
            let userId = null;

            function log(message) {
                const logDiv = document.getElementById('log');
                logDiv.innerHTML += `[${new Date().toLocaleTimeString()}] ${message}\\n`;
                logDiv.scrollTop = logDiv.scrollHeight;
            }

            function updateConnectionStatus(status, isOnline = false) {
                const statusDiv = document.getElementById('connectionStatus');
                statusDiv.textContent = status;
                statusDiv.className = isOnline ? 'status online' : 'status offline';
            }

            async function connectWebSocket() {
                const token = document.getElementById('token').value;
                if (!token) {
                    alert('Please enter a token');
                    return;
                }

                try {
                    // Decode token to get user ID
                    const payload = JSON.parse(atob(token.split('.')[1]));
                    userId = payload.sub;
                    log(`User ID from token: ${userId}`);
                } catch (e) {
                    log('Invalid token format');
                    return;
                }

                // Connect WebSocket
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const host = window.location.host;
                ws = new WebSocket(`${protocol}//${host}/chat/ws/${token}`);

                ws.onopen = () => {
                    updateConnectionStatus('Connected', true);
                    log('WebSocket connected');
                };

                ws.onclose = (event) => {
                    updateConnectionStatus('Disconnected', false);
                    log(`WebSocket disconnected: ${event.code} ${event.reason}`);
                    ws = null;
                    userId = null;
                };

                ws.onerror = (error) => {
                    log(`WebSocket error: ${error}`);
                };

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        handleWebSocketMessage(data);
                    } catch (e) {
                        log(`Error parsing message: ${e}, raw: ${event.data}`);
                    }
                };
            }

            function disconnectWebSocket() {
                if (ws) {
                    ws.close();
                    ws = null;
                    updateConnectionStatus('Disconnected', false);
                }
            }

            function handleWebSocketMessage(data) {
                log(`Received: ${data.type}`);

                const messagesDiv = document.getElementById('messages');

                switch(data.type) {
                    case 'connection':
                        log(`Connected as user: ${data.user_id}`);
                        break;

                    case 'message':
                        const messageDiv = document.createElement('div');
                        messageDiv.className = `message ${data.sender_id === userId ? 'sent' : 'received'}`;
                        messageDiv.innerHTML = `
                            <strong>${data.sender_id === userId ? 'You' : 'User ' + data.sender_id}</strong><br>
                            ${data.content || '(media message)'}<br>
                            <small>${new Date(data.created_at).toLocaleTimeString()}</small>
                        `;
                        messagesDiv.appendChild(messageDiv);
                        messagesDiv.scrollTop = messagesDiv.scrollHeight;
                        break;

                    case 'typing':
                        const typingDiv = document.getElementById('typingIndicator');
                        if (data.is_typing) {
                            typingDiv.textContent = `User ${data.user_id} is typing...`;
                            typingDiv.style.display = 'block';

                            // Hide after 3 seconds
                            setTimeout(() => {
                                typingDiv.style.display = 'none';
                            }, 3000);
                        } else {
                            typingDiv.style.display = 'none';
                        }
                        break;

                    case 'message_read':
                        log(`Message ${data.message_id} read by ${data.reader_id}`);
                        break;

                    case 'user_status':
                        log(`User ${data.user_id} is now ${data.status}`);
                        break;

                    case 'pong':
                        log('Pong received');
                        break;

                    case 'error':
                        log(`Error: ${data.message}`);
                        break;
                }
            }

            function sendTestMessage() {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    alert('Not connected to WebSocket');
                    return;
                }

                const receiverId = document.getElementById('receiverId').value;
                const messageContent = document.getElementById('messageContent').value;

                if (!receiverId || !messageContent) {
                    alert('Please enter receiver ID and message');
                    return;
                }

                const message = {
                    type: 'message',
                    receiver_id: receiverId,
                    content: messageContent,
                    message_type: 'text'
                };

                ws.send(JSON.stringify(message));
                log(`Sent message to ${receiverId}: ${messageContent}`);

                // Clear input
                document.getElementById('messageContent').value = '';
            }

            function sendTyping(isTyping) {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    return;
                }

                const receiverId = document.getElementById('receiverId').value;
                if (!receiverId) {
                    alert('Please enter receiver ID first');
                    return;
                }

                // For this demo, we'll assume chat_id is the same as receiver_id
                const typingMessage = {
                    type: 'typing',
                    chat_id: receiverId,
                    is_typing: isTyping
                };

                ws.send(JSON.stringify(typingMessage));
                log(`${isTyping ? 'Started' : 'Stopped'} typing`);
            }

            // Auto-connect if token exists in localStorage
            window.addEventListener('load', () => {
                const savedToken = localStorage.getItem('chat_token');
                if (savedToken) {
                    document.getElementById('token').value = savedToken;
                    setTimeout(() => connectWebSocket(), 1000);
                }
            });

            // Save token to localStorage
            document.getElementById('token').addEventListener('change', function() {
                localStorage.setItem('chat_token', this.value);
            });

            // Handle Enter key in message input
            document.getElementById('messageContent').addEventListener('keypress', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendTestMessage();
                }
            });
        </script>
    </body>
    </html>
    """