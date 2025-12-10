import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fastapi
import hashlib
import document_db
from document_sql import *
from site_utils import archived_document_path, get_zip_namelist, get_zip_image, thumbnail_folder
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel
from email.utils import formatdate

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


@app.get('/documents.db', response_class=fastapi.responses.FileResponse)
async def get_document_db() -> fastapi.responses.FileResponse:
    return fastapi.responses.FileResponse(path='documents.db')


@app.get('/HayaseYuuka')
async def get_auth():
    resp = fastapi.responses.RedirectResponse(status_code=fastapi.status.HTTP_302_FOUND,
                                              url='/')
    resp.set_cookie(key='password', value=DEFAULT_AUTH_TOKEN)
    return resp


@app.get('/favicon.ico')
async def give_icon() -> fastapi.responses.FileResponse:
    return fastapi.responses.FileResponse(path='favicon.ico')


@app.get('/src/{filename}',
         response_class=fastapi.responses.FileResponse,
         dependencies=[fastapi.Depends(RequireCookies())])
async def give_src(filename: str) -> fastapi.responses.FileResponse:
    file_path = Path(f'src/{filename}')
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    return fastapi.responses.FileResponse(path=file_path)


class SearchDocumentRequest(BaseModel):
    target_tag: int | None = None
    author_name: str | None = None
    target_page: int | None = 1


class SearchDocumentResponse(BaseModel):
    total_count: int
    document_authors: dict[int, list[str]]
    documents_info: dict[int, Document]
    tags: dict[int, list[Tag]]


@app.post('/search_document', dependencies=[fastapi.Depends(RequireCookies())])
def search_document(request: SearchDocumentRequest,
                    db: document_db.DocumentDB = fastapi.Depends(get_db)) -> SearchDocumentResponse:
    if request.target_page is None:
        target_page = 1
    else:
        target_page = request.target_page
    if request.target_tag:
        total_count, documents_info = db.paginate_query(db.query_by_tags([request.target_tag]),
                                                        target_page, PAGE_COUNT)
    elif request.author_name:
        total_count, documents_info = db.paginate_query(db.query_by_author(request.author_name),
                                                        target_page, PAGE_COUNT)
    else:
        total_count, documents_info = db.paginate_query(db.query_all_documents(), target_page, PAGE_COUNT)
    return SearchDocumentResponse(
        total_count=total_count,
        documents_info={document.document_id: document for document in documents_info},
        document_authors={document.document_id: [author.name for author in document.authors] for document in documents_info},
        tags={document.document_id: document.tags for document in documents_info})


def generate_thumbnail(document_id: int, file_path: Path):
    pic_list = get_zip_namelist(file_path)
    assert isinstance(pic_list, list)
    if not pic_list:
        return

    thumbnail_content = get_zip_image(file_path, pic_list[0])
    if not thumbnail_folder.exists():
        thumbnail_folder.mkdir()

    with open(thumbnail_folder / Path(f'{document_id}.webp'), "wb") as fu:
        fu.write(thumbnail_content.read())


def create_content_response(request: fastapi.Request, document: Document, file_index: int) -> fastapi.responses.Response:
    current_etag = hashlib.md5(f"{document.file_path}-{file_index}".encode()).hexdigest()
    if request.headers.get("if-none-match") == current_etag:
        return fastapi.Response(status_code=fastapi.status.HTTP_304_NOT_MODIFIED, headers={"ETag": current_etag})
    # 构造通用 Header
    # formatdate(usegmt=True) 生成标准的 RFC 1123 格式时间 (e.g., Wed, 21 Oct 2015 07:28:00 GMT)
    # 这比手动 strftime 更严谨且兼容性更好
    headers = {
        "Cache-Control": "public, max-age=2678400",
        "ETag": current_etag,
        "Last-Modified": formatdate(usegmt=True)
    }
    # 6. 未命中缓存：返回完整数据
    document_path = archived_document_path / document.file_path
    if file_index == -1:
        thumbnail_path = thumbnail_folder / Path(f'{document.document_id}.webp')
        if not thumbnail_path.exists():
            generate_thumbnail(document.document_id, document_path)
        return fastapi.responses.FileResponse(path=thumbnail_path)
    file_namelist = get_zip_namelist(document_path)
    try:
        file_name = file_namelist[file_index]
    except IndexError:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='索引超出范围')
    content = get_zip_image(document_path, file_name)
    if content is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='无法获取文档内容')
    return fastapi.responses.Response(
        content=content.read(),
        media_type=f"image/webp",
        headers=headers
    )


@app.get('/document_content/{document_id}', dependencies=[fastapi.Depends(RequireCookies())])
def get_document_namelist(document_id: int,
                          db: document_db.DocumentDB = fastapi.Depends(get_db)) -> list[str]:
    if document_id < 0:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST)
    document = db.get_document_by_id(document_id)
    if document is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    file_path = archived_document_path / document.file_path
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='请先访问show页面提交下载任务')
    namelist = get_zip_namelist(file_path)
    if isinstance(namelist, str):
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=namelist)
    return namelist


@app.get('/show_document/{document_id}',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(RequireCookies())])
def show_comic(
        request: fastapi.Request,
        document_id: int,
        db: document_db.DocumentDB = fastapi.Depends(get_db)
):
    # 业务逻辑：获取漫画信息
    document_info = db.get_document_by_id(document_id)
    if not document_info:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail="Document not found")
    # 构建路径
    # 假设 document_info[2] 是文件名，建议后续用 Pydantic Model 替换 Tuple 索引访问
    document_path = archived_document_path / document_info.file_path
    if not document_path.exists():
        # 501 Not Implemented 语义上通常指服务器不支持该功能
        # 若指文件丢失，500 Internal Server Error 或 404 可能更合适，这里保留原逻辑
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_501_NOT_IMPLEMENTED, detail="Comic archive missing")
    # 处理文件操作
    pic_list = get_zip_namelist(document_path)
    if isinstance(pic_list, str):
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='无法获取内容列表')
    # 生成图片链接列表
    images = [f'/document_content/{document_id}/{i}' for i in range(len(pic_list))]

    # 渲染模板
    # FastAPI 的 Jinja2Templates 必须接收 request 对象
    return templates.TemplateResponse(
        name="gallery-v2.html",
        context={"request": request, "images": images}
    )


@app.get('/document_content/{document_id}/{content_index}',
         response_class=fastapi.responses.FileResponse,
         responses={
             fastapi.status.HTTP_304_NOT_MODIFIED: {
                "description": "资源未修改，使用本地缓存",
                "content": {}
             }
         },
         dependencies=[fastapi.Depends(RequireCookies())])
def get_document_content(request: fastapi.Request,
                         document_id: int,
                         content_index: int,
                         db: document_db.DocumentDB = fastapi.Depends(get_db)) -> fastapi.responses.Response:
    if document_id < 0:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST)
    if content_index < -1:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST)
    document = db.get_document_by_id(document_id)
    if document is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    file_path = archived_document_path / document.file_path
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='请先访问show页面提交下载任务')
    return create_content_response(request, document, content_index)


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
