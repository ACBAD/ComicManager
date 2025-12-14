import document_db
import fastapi
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

# --- 1. 常量与配置 ---
PASSWORD_FILE = Path('password')
if not PASSWORD_FILE.exists():
    raise ValueError('Password file not found')
with open(PASSWORD_FILE) as pwd_f:
    DEFAULT_AUTH_TOKEN = pwd_f.read()
REQUIRED_AUTH_COOKIE = {"password": DEFAULT_AUTH_TOKEN}
REDIRECT_TARGET = "login_page"
PAGE_COUNT = 10


class AddComicRequest(BaseModel):
    source_id: int
    source_document_id: str
    inexistent_tags: Optional[dict[str, tuple[Optional[int], str]]] = None


class AddComicResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    redirect_url: Optional[str] = None


class TaskStatus(BaseModel):
    percent: int | float = 0
    message: Optional[str] = None


# 这里的 task_status 是全局共享的状态
task_status: dict[str, TaskStatus] = {}


# --- 3. 依赖注入函数 ---
class RequireCookies:
    def __init__(
            self,
            required_cookies: Optional[dict[str, str]] = None,
            redirect_endpoint: Optional[str] = None,
            **redirect_args
    ):
        self.required_cookies = required_cookies or REQUIRED_AUTH_COOKIE
        self.redirect_endpoint = redirect_endpoint or REDIRECT_TARGET
        self.redirect_args = redirect_args

    async def __call__(self, request: fastapi.Request):
        for cookie_name, expected_value in self.required_cookies.items():
            actual_value = request.cookies.get(cookie_name)
            if actual_value is None or actual_value != expected_value:
                raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=None)
        return True


def get_db():
    with document_db.DocumentDB() as db:
        yield db
