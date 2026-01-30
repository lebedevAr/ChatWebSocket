from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional, List, Dict, Any
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


class WebSocketMessage(BaseModel):
    type: WebSocketMessageType
    data: Dict[str, Any]


class MessageWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.MESSAGE
    message_id: str
    chat_id: str
    sender_id: str
    receiver_id: str
    content: Optional[str] = None
    message_type: MessageType
    media_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    created_at: str
    is_read: bool = False
    reply_to_id: Optional[str] = None
    forwarded_from_id: Optional[str] = None


class TypingWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.TYPING
    chat_id: str
    user_id: str
    is_typing: bool
    timestamp: str


class UserStatusWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.USER_STATUS
    user_id: str
    status: str
    timestamp: str


class MessageReadWebSocket(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.MESSAGE_READ
    message_id: str
    reader_id: str
    chat_id: str
    timestamp: str


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
    model_config = ConfigDict(from_attributes=True)


class UserWithStatus(User):
    is_online: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[UUID] = None


class MessageBase(BaseModel):
    content: Optional[str] = None
    message_type: MessageType = MessageType.TEXT


class MessageCreate(MessageBase):
    receiver_id: UUID
    reply_to_id: Optional[UUID] = None


class MessageUpdate(BaseModel):
    is_read: Optional[bool] = None


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
    extra_data: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class MessageWithReply(Message):
    reply_to: Optional["Message"] = None


class ChatBase(BaseModel):
    user2_id: UUID


class ChatCreate(ChatBase):
    pass


class Chat(BaseModel):
    id: UUID
    user1_id: UUID
    user2_id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    last_message_id: Optional[UUID] = None
    unread_count_user1: int = 0
    unread_count_user2: int = 0
    model_config = ConfigDict(from_attributes=True)


class ChatInfo(BaseModel):
    id: UUID
    user1_id: UUID
    user2_id: UUID
    other_user: Dict[str, Any]
    last_message: Optional[Message] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ChatWithMessages(ChatInfo):
    messages: List[Message] = []


class DateFilter(BaseModel):
    start_date: datetime
    end_date: datetime


class WebSocketConnection(BaseModel):
    user_id: UUID
    token: str


class PingMessage(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.PING


class PongMessage(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.PONG
    timestamp: datetime


class ConnectionStatus(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.CONNECTION
    status: str
    user_id: str
    timestamp: str


class OnlineStatusResponse(BaseModel):
    user_id: UUID
    is_online: bool
    online_status: bool
    last_seen: Optional[datetime]


class FileUpload(BaseModel):
    receiver_id: UUID
    file_name: str
    file_size: int
    file_type: str


class TypingUpdate(BaseModel):
    is_typing: bool = True


class ErrorResponse(BaseModel):
    type: WebSocketMessageType = WebSocketMessageType.ERROR
    message: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class MessageCreateRepo(BaseModel):
    chat_id: UUID
    sender_id: UUID
    receiver_id: UUID
    message_type: MessageType = MessageType.TEXT
    content: Optional[str] = None
    media_url: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None
    reply_to_id: Optional[UUID] = None
    forwarded_from_id: Optional[UUID] = None
    extra_data: Optional[Dict[str, Any]] = None


MessageWithReply.model_rebuild()