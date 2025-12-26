from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import TypeDecorator, CHAR
import uuid


# Кастомный тип GUID для SQLite
class GUID(TypeDecorator):
    """Platform-independent GUID type."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value

        if isinstance(value, uuid.UUID):
            return value.hex
        elif isinstance(value, str):
            # Если это строка UUID, конвертируем в hex
            try:
                return uuid.UUID(value).hex
            except ValueError:
                # Если уже hex строка (32 символа)
                if len(value) == 32 and all(c in '0123456789abcdefABCDEF' for c in value):
                    return value.lower()
                return value
        else:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value

        try:
            # Пытаемся создать UUID из hex строки
            return uuid.UUID(hex=value)
        except (ValueError, TypeError):
            return value


# Используем SQLite для простоты
SQLALCHEMY_DATABASE_URL = "sqlite:///./chat.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=True  # Оставляем True для отладки
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()