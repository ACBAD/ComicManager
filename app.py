import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fastapi
import hashlib
import io
from datetime import datetime, timezone
from typing import Optional
import document_db
from document_sql import *
from site_utils import archived_document_path, getZipNamelist, getZipImage, thumbnail_folder
from functools import wraps

app = fastapi.FastAPI()

DEFAULT_AUTH_TOKEN = 'HayaseYuuka'
REQUIRED_AUTH_COOKIE = {"password": DEFAULT_AUTH_TOKEN}
REDIRECT_TARGET = "login_page"


class RequireCookies:
    """
    鉴权依赖类：检查 Cookies 是否匹配。
    如果失败，根据配置抛出 403 异常或执行重定向。
    """
    def __init__(
        self,
        required_cookies: Optional[dict[str, str]] = None,
        redirect_endpoint: Optional[str] = None,
        **redirect_args
    ):
        # 初始化配置，类似于原装饰器的外层函数
        self.required_cookies = required_cookies or REQUIRED_AUTH_COOKIE
        self.redirect_endpoint = redirect_endpoint or REDIRECT_TARGET
        self.redirect_args = redirect_args

    async def __call__(self, request: fastapi.Request):
        """
        依赖调用的核心逻辑，类似于原装饰器的内层函数
        FastAPI 会自动注入 Request 对象
        """
        for cookie_name, expected_value in self.required_cookies.items():
            actual_value = request.cookies.get(cookie_name)
            # 核心验证逻辑
            if actual_value is None or actual_value != expected_value:
                # 场景 A: 如果你需要构建 API，通常直接返回 403 禁止访问
                # 注意：raise 异常会中断请求处理，类似 flask.abort
                raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail=None)
                # 场景 B: 如果你是做服务端渲染 (SSR) 且必须重定向 (原代码注释逻辑)
                # url = request.url_for(self.redirect_endpoint, **self.redirect_args)
                # return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
        # 验证通过，返回 None 或需要的用户对象
        return True


def get_db():
    with document_db.DocumentDB() as db:
        yield db


@app.get('/HayaseYuuka')
async def get_auth():
    resp = fastapi.responses.RedirectResponse(status_code=fastapi.status.HTTP_302_FOUND,
                                              url='/')
    resp.set_cookie(key='password', value=DEFAULT_AUTH_TOKEN)
    return resp


@app.get('/exploror', dependencies=[fastapi.Depends(RequireCookies())])
async def exploror():
    return 'Hello!'


@app.get('/', dependencies=[fastapi.Depends(RequireCookies())])
async def root():
    return fastapi.responses.RedirectResponse(url='/exploror', status_code=fastapi.status.HTTP_303_SEE_OTHER)
