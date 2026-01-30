from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import traceback

from .models import Base

DB_USER = 'postgres'
DB_PASSWORD = 'postgres'
DB_HOST = 'localhost'
DB_PORT = 5432
DB_NAME = 'postgres'
DB_ECHO = False
DB_POOL_SIZE = 20
DB_MAX_OVERFLOW = 10
SQLALCHEMY_DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=DB_ECHO,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base_model = Base


async def get_db() -> AsyncSession:
    """Асинхронная зависимость для получения сессии БД"""

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Асинхронная инициализация базы данных (создание таблиц)"""

    try:
        print("Creating database tables")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            print("Database tables created")

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"Database version: {version}")
            result = await conn.execute(text(
                """
                SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
                """))
            tables = [row[0] for row in result]
            if tables:
                print(f"Tables in database: {', '.join(tables)}")
            else:
                print("No tables found in database")

            for table in ['users', 'chats', 'messages']:
                if table in tables:
                    try:
                        count_result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = count_result.scalar()
                        print(f"  - {table}: {count} records")
                    except:
                        print(f"  - {table}: exists but empty")

    except Exception as e:
        print(f"Error creating tables: {e}")
        traceback.print_exc()
        raise
