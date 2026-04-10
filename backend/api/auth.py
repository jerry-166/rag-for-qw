from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from datetime import timedelta

from config import init_logger
from services.database import db
from services.auth import get_password_hash, verify_password, create_access_token, get_current_user

logger = init_logger(__name__)
router = APIRouter()

# 用户注册模型
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

# 用户登录模型
class UserLogin(BaseModel):
    username: str
    password: str

# 令牌模型
class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int = None
    username: str = None
    role: str = None

# 令牌数据模型
class TokenData(BaseModel):
    username: str | None = None
    user_id: int | None = None
    role: str | None = None


@router.post("/register")
async def register(user: UserRegister):
    """用户注册"""
    logger.info(f"开始用户注册，用户名: {user.username}")
    try:
        # 检查用户名是否已存在
        existing_user = db.get_user_by_username(user.username)
        if existing_user:
            logger.warning(f"用户名已存在: {user.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 检查邮箱是否已存在
        existing_email = db.get_user_by_email(user.email)
        if existing_email:
            logger.warning(f"邮箱已存在: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已存在"
            )

        # 密码加密
        password_hash = get_password_hash(user.password)

        # 添加用户
        db.add_user(user.username, user.email, password_hash)

        logger.info(f"用户注册成功，用户名: {user.username}")
        return {
            "status": "success",
            "message": "注册成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """用户登录"""
    logger.info(f"开始用户登录，用户名: {form_data.username}")
    try:
        # 查找用户
        user = db.get_user_by_username(form_data.username)
        if not user:
            logger.warning(f"用户不存在: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 验证密码
        if not verify_password(form_data.password, user["password_hash"]):
            logger.warning(f"密码错误，用户名: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 创建访问令牌，包含用户ID和角色
        access_token_expires = timedelta(minutes=30)
        access_token = create_access_token(
            data={"sub": user["username"], "user_id": user["id"], "role": user["role"]},
            expires_delta=access_token_expires
        )

        logger.info(f"用户登录成功，用户名: {form_data.username}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user["id"],
            "username": user["username"],
            "role": user["role"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")
