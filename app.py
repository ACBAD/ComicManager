import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fastapi
import hashlib
import document_db
from document_sql import *
from site_utils import archived_document_path, get_zip_namelist, get_zip_image, thumbnail_folder
from contextlib import asynccontextmanager
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from pathlib import Path
from pydantic import BaseModel
from email.utils import formatdate
from shared import RequireCookies, DEFAULT_AUTH_TOKEN, get_db, PAGE_COUNT, task_status, TaskStatus
import asyncio

hitomi_router = None

try:
    import hitomi_plugin

    hitomi_router = hitomi_plugin.router
    print("Hitomi 插件加载成功")
except ImportError as e:
    print(f"Hitomi 插件未加载: {e}")
    hitomi_plugin = None

app_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}


# noinspection PyUnusedLocal
@asynccontextmanager
async def lifespan(app_instance: fastapi.FastAPI):
    # 如果插件存在，启动插件的后台任务
    hitomi_bg_task = None
    if hitomi_plugin:
        hitomi_bg_task = asyncio.create_task(hitomi_plugin.refresh_hitomi_loop())
    yield
    # 清理任务
    if hitomi_bg_task:
        hitomi_bg_task.cancel()
        try:
            await hitomi_bg_task
        except Exception as le:
            print(str(le))


# noinspection PyTypeChecker
app_kwargs["lifespan"] = lifespan

app = fastapi.FastAPI(**app_kwargs)
if hitomi_router:
    app.include_router(hitomi_router, prefix="/comic")


@app.get("/openapi.json",
         include_in_schema=False,
         dependencies=[fastapi.Depends(RequireCookies())])
async def get_open_api_endpoint():
    return fastapi.responses.JSONResponse(get_openapi(title="DocumentManagerAPI", version="1.0.0", routes=app.routes))


# 4. 手动实现 /docs，并加上依赖保护
@app.get("/docs",
         include_in_schema=False,
         dependencies=[fastapi.Depends(RequireCookies())])
async def get_documentation():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


# noinspection PyUnusedLocal
@app.get("/admin/{subpath:path}", include_in_schema=False)
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


@app.get('/HayaseYuuka', include_in_schema=False)
async def get_auth():
    resp = fastapi.responses.RedirectResponse(status_code=fastapi.status.HTTP_302_FOUND, url='/')
    resp.set_cookie(key='password', value=DEFAULT_AUTH_TOKEN, max_age=3600 * 24 * 365 * 10)
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


@app.get('/add_document',
         responses={
             fastapi.status.HTTP_307_TEMPORARY_REDIRECT: {
                 "description": "重定向到添加模块",
                 "content": {}
             }
         },
         status_code=fastapi.status.HTTP_307_TEMPORARY_REDIRECT,
         dependencies=[fastapi.Depends(RequireCookies())])
async def add_document_gateway(source_document_id: str, source_id: int):
    if hitomi_router is None:
        # 如果没加载插件，返回 501 Not Implemented
        raise fastapi.HTTPException(
            status_code=fastapi.status.HTTP_501_NOT_IMPLEMENTED,
            detail="Hitomi module is not loaded."
        )

    return fastapi.responses.RedirectResponse(url=f'/comic/add?source_id={source_id}&source_document_id={source_document_id}')


@app.get('/get_document/{source_document_id}',
         status_code=fastapi.status.HTTP_307_TEMPORARY_REDIRECT,
         dependencies=[fastapi.Depends(RequireCookies())])
async def get_document(source_document_id: str, db: document_db.DocumentDB = fastapi.Depends(get_db)):
    db_result = db.search_by_source(source_document_id=source_document_id)
    if db_result:
        return fastapi.responses.RedirectResponse(url=f'/show_document/{db_result.document_id}')
    raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)


@app.get('/show_status',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(RequireCookies())])
async def get_download_status():
    return fastapi.responses.FileResponse('templates/show_download_status.html')


@app.get('/download_status',
         dependencies=[fastapi.Depends(RequireCookies())])
async def get_status() -> dict[str, TaskStatus]:
    return task_status


@app.delete('/delete_document', dependencies=[fastapi.Depends(RequireCookies())])
def delete_document(document_id: int, auth_token: str, db: document_db.DocumentDB = fastapi.Depends(get_db)):
    if auth_token != 'MisonoMika':
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_403_FORBIDDEN, detail='你只能看')
    result = db.delete_document(document_id)
    if result != 0:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail='文档不存在')


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
        document_authors={document.document_id: [author.name for author in document.authors] for document in
                          documents_info},
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


def create_content_response(request: fastapi.Request, document: Document,
                            file_index: int) -> fastapi.responses.Response:
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
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST, detail='自己输了啥心里有数')
    document = db.get_document_by_id(document_id)
    if document is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='数据库中不存在此文件')
    file_path = archived_document_path / document.file_path
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail='数据库有, 本地不存在')
    pic_list = get_zip_namelist(file_path)
    if isinstance(pic_list, str):
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=pic_list)
    if document.title in task_status:
        task_status.pop(document.title)
    return [f'/document_content/{document_id}/{i}' for i in range(len(pic_list))]


@app.get('/show_document/{document_id}',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(RequireCookies())])
def show_document():
    return fastapi.responses.FileResponse('templates/gallery.html')


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
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    return create_content_response(request, document, content_index)


@app.get('/get_tags/{group_id}', dependencies=[fastapi.Depends(RequireCookies())])
def get_tags(db: document_db.DocumentDB = fastapi.Depends(get_db), group_id: int = -1):
    if group_id < 0:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_400_BAD_REQUEST)
    db_result = db.get_tags_by_group(group_id)
    return {t.name: t.tag_id for t in db_result}


@app.get('/get_tag_groups', dependencies=[fastapi.Depends(RequireCookies())])
def get_tag_groups(db: document_db.DocumentDB = fastapi.Depends(get_db)):
    return {tag_group.tag_group_id: tag_group.group_name for tag_group in db.get_tag_groups()}


@app.get('/exploror',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(RequireCookies())])
def exploror():
    return fastapi.responses.FileResponse(path='templates/exploror.html')


@app.get('/', dependencies=[fastapi.Depends(RequireCookies())])
async def root():
    return fastapi.responses.RedirectResponse(url='/exploror', status_code=fastapi.status.HTTP_303_SEE_OTHER)
