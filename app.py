import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from email.utils import formatdate
import fastapi
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from setup_logger import getLogger
from utils import Authoricator, UserAbilities
import tags
import comics
import sqlite3

logger, setLoggerLevel, _ = getLogger('Site')
comics_api = fastapi.APIRouter(tags=['Comics', 'API'])
tag_router = fastapi.APIRouter(tags=['Tags', 'API'])
site_router = fastapi.APIRouter(tags=['Site', 'API'])

tag_manager = tags.TagManager(sqlite3.connect('comics.db'))
comic_manager = comics.ComicManager(sqlite3.connect('comics.db'), tag_manager)

app_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}


@asynccontextmanager
async def lifespan(app_instance: fastapi.FastAPI):
    # 先留着这堆样板, 之后万一还有其他插件需要后台任务, 就可以直接在这里加

    # 如果插件存在，启动插件的后台任务
    # hitomi_bg_task = None
    # if hitomi_plugin:
    #     hitomi_bg_task = asyncio.create_task(hitomi_plugin.refresh_hitomi_loop())
    yield
    # 清理任务
    # if hitomi_bg_task:
    #     hitomi_bg_task.cancel()
    #     try:
    #         await hitomi_bg_task
    #     except Exception as le:
    #         logger.error(str(le))


app_kwargs["lifespan"] = lifespan # type: ignore

app = fastapi.FastAPI(**app_kwargs) # type: ignore


@app.get("/openapi.json",
         include_in_schema=False,
         dependencies=[fastapi.Depends(Authoricator())])
async def get_open_api_endpoint():
    return fastapi.responses.JSONResponse(get_openapi(title="ComicManagerAPI", version="1.0.0", routes=app.routes))


@app.get("/docs",
         include_in_schema=False,
         dependencies=[fastapi.Depends(Authoricator())])
async def get_documentation():
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


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


@app.get('/auth', include_in_schema=False)
async def get_auth():
    return fastapi.responses.FileResponse(path='templates/auth.html')


@app.get('/favicon.ico', include_in_schema=False)
async def give_icon() -> fastapi.responses.FileResponse:
    return fastapi.responses.FileResponse(path='favicon.ico')


@app.get('/src/{filename}',
         response_class=fastapi.responses.FileResponse,
         dependencies=[fastapi.Depends(Authoricator())],
         name='site.get_src')
async def give_src(filename: str) -> fastapi.responses.FileResponse:
    file_path = Path(f'src/{filename}')
    if not file_path.exists():
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND)
    return fastapi.responses.FileResponse(path=file_path)


@site_router.get('/status/show',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(Authoricator())])
async def get_download_status():
    # 这个接口是给前端直接访问的, 返回html页面, 里面有js轮询status接口来获取下载状态
    return fastapi.responses.FileResponse('templates/show_download_status.html')


@site_router.get('/status',
                 dependencies=[fastapi.Depends(Authoricator())],
                 name='site.get_download_status')
async def get_status() -> dict:
    # 这接口是给前端轮询用的, 直接返回json就行, 不需要返回html
    # 记得加类型提示
    return {}


@tag_router.get('/groups',
                dependencies=[fastapi.Depends(Authoricator())],
                name='tags.get_groups')
async def get_tag_groups() -> list[str]:
    return list(tags.TagGroup)

specific_tag_router = fastapi.APIRouter(tags=['Tags', 'API', 'SpecificTag'])

@specific_tag_router.get('/{tag_id}', 
                         dependencies=[fastapi.Depends(Authoricator())], 
                         name='tags.get_specific_tag')
def get_specific_tag(tag_id: int) -> tags.SpecificTagUnion:
    tag = tag_manager.get_specific_tag(tag_id)
    if tag is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=f"SpecificTag with id {tag_id} not found")
    return tag

@specific_tag_router.get('/{tag_id}/generic', 
                         dependencies=[fastapi.Depends(Authoricator())], 
                         name='tags.get_mapped_generic_tag')
def get_generic_tag(tag_id: int) -> tags.GenericTag:
    specific_tag = tag_manager.get_specific_tag(tag_id)
    if specific_tag is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=f"SpecificTag with id {tag_id} not found")
    tag = tag_manager.generalize(specific_tag)
    if tag is None:
        raise fastapi.HTTPException(status_code=fastapi.status.HTTP_404_NOT_FOUND, detail=f"GenericTag with id {tag_id} not found")
    return tag



generic_tag_router = fastapi.APIRouter(tags=['Tags', 'API', 'GenericTag'])

tag_router.include_router(specific_tag_router, prefix='/specific')
tag_router.include_router(generic_tag_router, prefix='/generic')

@app.get('/exploror',
         response_class=fastapi.responses.HTMLResponse,
         dependencies=[fastapi.Depends(Authoricator())])
def exploror():
    return fastapi.responses.FileResponse(path='templates/exploror.html')


@app.get('/', dependencies=[fastapi.Depends(Authoricator())])
async def root():
    return fastapi.responses.RedirectResponse(url='/exploror', status_code=fastapi.status.HTTP_303_SEE_OTHER)


app.include_router(comics_api, prefix='/api/comics')
app.include_router(tag_router, prefix='/api/tags')
app.include_router(site_router, prefix='/api/site')
