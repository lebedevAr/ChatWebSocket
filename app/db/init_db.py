from app.database import engine, Base
from sqlalchemy import text
import sys
import os


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def init_database():
    """Инициализация базы данных"""

    print("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully!")
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = [row[0] for row in result]
            print(f"\nCreated tables: {tables}")
            for table in tables:
                print(f"\nStructure of table '{table}':")
                result = conn.execute(text(f"PRAGMA table_info({table})"))
                for row in result:
                    print(f"  Column: {row[1]} ({row[2]})")
    except Exception as e:
        print(f"Error creating tables: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    init_database()