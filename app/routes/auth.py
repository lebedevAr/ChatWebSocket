from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from datetime import datetime, timedelta
from jose import JWTError, jwt
import hashlib
from typing import Optional

from app.database import get_db
from app import schemas, models

SECRET_KEY = "your-secret-key-here-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def hash_password(password: str) -> str:
    """Простое хеширование пароля с использованием SHA256"""

    salt = "chat_system_salt_2024"
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""

    return hash_password(plain_password) == hashed_password


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Создание JWT токена авторизации"""

    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Декодирование токена JWT"""

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> models.User:
    """Получение информации о текущем пользователе по токену JWT"""

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


@router.post("/register", response_model=schemas.User)
async def register(user_data: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    """Регистрация пользователя"""

    result = await db.execute(select(models.User).where(models.User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    result = await db.execute(select(models.User).where(models.User.username == user_data.username))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")

    hashed_password = hash_password(user_data.password)
    db_user = models.User(username=user_data.username, email=user_data.email, hashed_password=hashed_password)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@router.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """Авторизация по email/username"""

    result = await db.execute(select(models.User).where(
        or_(models.User.email == form_data.username, models.User.username == form_data.username)))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": str(user.id)}, expires_delta=access_token_expires)
    user.last_seen = datetime.utcnow()
    await db.commit()
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    """Получить информацию о текущем пользователе"""

    return current_user


@router.put("/me", response_model=schemas.User)
async def update_user_profile(user_update, current_user: models.User = Depends(get_current_user),
                              db: AsyncSession = Depends(get_db)):
    """Обновить профиль пользователя"""

    update_data = user_update.dict(exclude_unset=True)
    if "password" in update_data:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))

    for field, value in update_data.items():
        if hasattr(current_user, field):
            setattr(current_user, field, value)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/logout")
async def logout(current_user: models.User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Выход из системы"""

    current_user.last_seen = datetime.utcnow()
    current_user.online_status = False
    await db.commit()
    return {"message": "Successfully logged out"}


@router.post("/verify")
async def verify_token(token: str = Depends(oauth2_scheme)):
    """Проверка валидности токена"""

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    return {"valid": True, "user_id": payload.get("sub")}


@router.get("/user/{user_id}", response_model=schemas.User)
async def get_user_by_id(user_id: str, current_user: models.User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    """Получить информацию о пользователе по ID"""

    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="User is not active")

    result = await db.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
