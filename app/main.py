from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

from app.database import engine, Base
from app.models import User, Chat, Message, MessageReadStatus, TypingStatus
from app.routes import chat, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаем таблицы базы данных
    print("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully!")

        # Проверяем созданные таблицы
        from sqlalchemy import inspect
        from sqlalchemy import text

        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = [row[0] for row in result]
            print(f"Tables in database: {tables}")

    except Exception as e:
        print(f"Error creating tables: {e}")
        import traceback
        traceback.print_exc()

    # Создаем директории
    upload_dir = Path("uploads")
    upload_dir.mkdir(exist_ok=True)
    print("Upload directory created")

    print("Server started successfully!")
    yield

    print("Server shutting down...")


app = FastAPI(
    title="Chat API",
    description="Chat system with WebSocket support",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Монтируем статические файлы
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Подключаем роутеры
app.include_router(chat.router)
app.include_router(auth.router)


@app.get("/")
async def root():
    return {
        "message": "Chat API",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "register": "/auth/register",
            "login": "/auth/token",
            "websocket": "/chat/ws/{token}",
            "test_page": "/chat/test-ws",
            "docs": "/docs",
            "redoc": "/redoc"
        }
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": "SQLite"
    }


@app.get("/debug/tables")
async def debug_tables():
    """Эндпоинт для отладки - показывает таблицы в базе"""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]

        table_details = {}
        for table in tables:
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            columns = [{"name": row[1], "type": row[2]} for row in result]
            table_details[table] = columns

    return {
        "tables": tables,
        "details": table_details
    }