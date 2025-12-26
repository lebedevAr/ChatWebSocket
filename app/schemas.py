from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Union, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LOCATION = "location"
    SYSTEM = "system"


class WebSocketMessageType(str, Enum):
    MESSAGE = "message"
    MESSAGE_READ = "message_read"
    TYPING = "typing"
    USER_STATUS = "user_status"
    ERROR = "error"
    CHAT_UPDATE = "chat_update"
    PING = "ping"
    PONG = "pong"
    CONNECTION = "connection"


# WebSocket схемы
class WebSocketMessage(BaseModel):
    type: WebSocketMessageType
    data: Dict[str, Any]


class MessageWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.MESSAGE
    message_id: UUID
    chat_id: UUID
    sender_id: UUID
    receiver_id: UUID
    content: Optional[str] = None
    message_type: MessageType
    media_url: Optional[str] = None
    file_name: Optional[str] = None
    created_at: datetime
    reply_to_id: Optional[UUID] = None
    forwarded_from_id: Optional[UUID] = None


class TypingWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.TYPING
    chat_id: UUID
    user_id: UUID
    is_typing: bool
    timestamp: datetime


class UserStatusWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.USER_STATUS
    user_id: UUID
    status: str  # online, offline, typing
    timestamp: datetime


class MessageReadWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.MESSAGE_READ
    message_id: UUID
    reader_id: UUID
    chat_id: UUID
    timestamp: datetime


# User schemas
class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class User(UserBase):
    id: UUID
    is_active: bool
    online_status: bool
    last_seen: Optional[datetime]
    profile_image: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class UserWithStatus(User):
    is_online: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[UUID] = None


# Message schemas
class MessageBase(BaseModel):
    content: Optional[str] = None
    message_type: MessageType = MessageType.TEXT


class MessageCreate(MessageBase):
    receiver_id: UUID
    reply_to_id: Optional[UUID] = None


class MediaCreate(BaseModel):
    receiver_id: UUID
    file_name: str


class LocationCreate(BaseModel):
    receiver_id: UUID
    latitude: float
    longitude: float


class Message(MessageBase):
    id: UUID
    chat_id: UUID
    sender_id: UUID
    receiver_id: UUID
    media_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    reply_to_id: Optional[UUID] = None
    forwarded_from_id: Optional[UUID] = None
    is_read: bool
    read_at: Optional[datetime] = None
    extra_data: Optional[Dict[str, Any]] = None  # Переименовано из metadata
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageWithReply(Message):
    reply_to: Optional["Message"] = None


# Chat schemas
class ChatBase(BaseModel):
    user2_id: UUID


class ChatCreate(ChatBase):
    pass


class ChatInfo(BaseModel):
    id: UUID
    user1_id: UUID
    user2_id: UUID
    other_user: UserWithStatus
    last_message: Optional[Message] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatWithMessages(ChatInfo):
    messages: List[Message] = []


# Filter schemas
class DateFilter(BaseModel):
    start_date: datetime
    end_date: datetime


# WebSocket connection
class WebSocketConnection(BaseModel):
    user_id: UUID
    token: str


# Ping/Pong для WebSocket
class PingMessage(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.PING


class PongMessage(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.PONG
    timestamp: datetime


# Connection status
class ConnectionStatus(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.CONNECTION
    status: str
    user_id: UUID
    timestamp: datetime