from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Enum, Float, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from datetime import datetime
from app.database import Base, GUID
import enum


class MessageType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LOCATION = "location"
    SYSTEM = "system"


class User(Base):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    online_status = Column(Boolean, default=False)
    last_seen = Column(DateTime(timezone=True))
    profile_image = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships с явным указанием foreign_keys
    sent_messages = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
        cascade="all, delete-orphan"
    )
    received_messages = relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan"
    )
    chats_as_user1 = relationship(
        "Chat",
        foreign_keys="Chat.user1_id",
        back_populates="user1"
    )
    chats_as_user2 = relationship(
        "Chat",
        foreign_keys="Chat.user2_id",
        back_populates="user2"
    )
    read_statuses = relationship(
        "MessageReadStatus",
        back_populates="user",
        cascade="all, delete-orphan"
    )


class Chat(Base):
    __tablename__ = "chats"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user1_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    user2_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    last_message_id = Column(GUID(), ForeignKey("messages.id"), nullable=True)
    unread_count_user1 = Column(Integer, default=0)
    unread_count_user2 = Column(Integer, default=0)

    # Relationships
    user1 = relationship(
        "User",
        foreign_keys=[user1_id],
        back_populates="chats_as_user1"
    )
    user2 = relationship(
        "User",
        foreign_keys=[user2_id],
        back_populates="chats_as_user2"
    )
    messages = relationship(
        "Message",
        back_populates="chat",
        foreign_keys="Message.chat_id",
        cascade="all, delete-orphan"
    )
    last_message = relationship(
        "Message",
        foreign_keys=[last_message_id]
    )

    __table_args__ = (
        UniqueConstraint('user1_id', 'user2_id', name='unique_chat_users'),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    chat_id = Column(GUID(), ForeignKey("chats.id"), nullable=False)
    sender_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    receiver_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    message_type = Column(Enum(MessageType), default=MessageType.TEXT)
    content = Column(Text)
    media_url = Column(String(500))
    file_name = Column(String(255))
    file_size = Column(Integer)
    file_type = Column(String(50))
    latitude = Column(Float)
    longitude = Column(Float)
    reply_to_id = Column(GUID(), ForeignKey("messages.id"), nullable=True)
    forwarded_from_id = Column(GUID(), ForeignKey("users.id"), nullable=True)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime(timezone=True))
    extra_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    chat = relationship(
        "Chat",
        foreign_keys=[chat_id],
        back_populates="messages"
    )
    sender = relationship(
        "User",
        foreign_keys=[sender_id],
        back_populates="sent_messages"
    )
    receiver = relationship(
        "User",
        foreign_keys=[receiver_id],
        back_populates="received_messages"
    )
    reply_to = relationship(
        "Message",
        foreign_keys=[reply_to_id],
        remote_side=[id],
        backref="replies"
    )
    forwarded_from = relationship(
        "User",
        foreign_keys=[forwarded_from_id]
    )
    read_statuses = relationship(
        "MessageReadStatus",
        back_populates="message",
        cascade="all, delete-orphan"
    )


class MessageReadStatus(Base):
    __tablename__ = "message_read_status"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    message_id = Column(GUID(), ForeignKey("messages.id"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    read_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship(
        "Message",
        foreign_keys=[message_id],
        back_populates="read_statuses"
    )
    user = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="read_statuses"
    )


class TypingStatus(Base):
    __tablename__ = "typing_status"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    chat_id = Column(GUID(), ForeignKey("chats.id"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    is_typing = Column(Boolean, default=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    chat = relationship("Chat", foreign_keys=[chat_id])
    user = relationship("User", foreign_keys=[user_id])