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
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

app = fastapi.FastAPI()

DEFAULT_AUTH_TOKEN = 'HayaseYuuka'
REQUIRED_AUTH_COOKIE = {"password": DEFAULT_AUTH_TOKEN}
REDIRECT_TARGET = "login_page"
templates = Jinja2Templates(directory="templates")
PAGE_COUNT = 10


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


@app.get("/admin/{subpath:path}")
async def admin(subpath: str = ""):
    return fastapi.responses.FileResponse(
        path='boom.gz',
        media_type='text/html',
        headers={
            'Content-Encoding': 'gzip',
            'Vary': 'Accept-Encoding'
        }
    )


@app.get('/ducuments.sb')
async def get_document_db():
    return fastapi.responses.FileResponse(path='documents.db')


@app.get('/HayaseYuuka')
async def get_auth():
    resp = fastapi.responses.RedirectResponse(status_code=fastapi.status.HTTP_302_FOUND,
                                              url='/')
    resp.set_cookie(key='password', value=DEFAULT_AUTH_TOKEN)
    return resp


@app.get('/favicon.ico')
async def give_icon():
    return fastapi.responses.FileResponse(path='favicon.ico')


@app.get('/src/{filename}', dependencies=[fastapi.Depends(RequireCookies())])
async def give_src(filename: str):
    file_path = Path(f'src/{filename}')
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    return fastapi.responses.FileResponse(path=file_path)


class SearchDocumentRequest(BaseModel):
    target_tag: int | None = None,
    comic_author: str | None = None,
    target_page: int | None = 1


@app.post('/search_document', dependencies=[fastapi.Depends(RequireCookies())])
def search_document(request: SearchDocumentRequest,
                    db: document_db.DocumentDB = fastapi.Depends(get_db)):
    if request.target_page is None:
        target_page = 1
    else:
        target_page = request.target_page
    if request.target_tag:
        total_count, comics_info = db.paginate_query(db.query_by_tags([request.target_tag]),
                                                     target_page, PAGE_COUNT)
    elif request.comic_author:
        total_count, comics_info = db.paginate_query(db.query_by_author(request.comic_author),
                                                     target_page, PAGE_COUNT)
    else:
        total_count, comics_info = db.paginate_query(db.query_all_documents(), target_page, PAGE_COUNT)
    return {'total_count': total_count, 'comics_info': comics_info}


@app.get('/get_tags/{group_id}', dependencies=[fastapi.Depends(RequireCookies())])
def get_tags(db: document_db.DocumentDB = fastapi.Depends(get_db), group_id: int = -1):
    if group_id < 0:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST)
    db_result = db.get_tags_by_group(group_id)
    return {t.name: t.tag_id for t in db_result}


@app.get('/exploror', dependencies=[fastapi.Depends(RequireCookies())])
def exploror(request: fastapi.Request, db: document_db.DocumentDB = fastapi.Depends(get_db)):
    tag_groups = {tag_group.group_name: tag_group.tag_group_id for tag_group in db.get_tag_groups()}
    return templates.TemplateResponse(
        request=request,
        name="exploror.html",
        context={"tag_groups": tag_groups}
    )


@app.get('/', dependencies=[fastapi.Depends(RequireCookies())])
async def root():
    return fastapi.responses.RedirectResponse(url='/exploror', status_code=fastapi.status.HTTP_303_SEE_OTHER)
