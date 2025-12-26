import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./chat.db")

    # JWT
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    WEBSOCKET_TOKEN_EXPIRE_DAYS = 7

    # File uploads
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {
        'image': ['.jpg', '.jpeg', '.png', '.gif'],
        'video': ['.mp4', '.avi', '.mov'],
        'audio': ['.mp3', '.wav', '.ogg'],
        'document': ['.pdf', '.doc', '.docx', '.txt']
    }

    # WebSocket
    WEBSOCKET_PING_INTERVAL = 20
    WEBSOCKET_PING_TIMEOUT = 40

    # Redis (для горизонтального масштабирования)
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


settings = Settings()