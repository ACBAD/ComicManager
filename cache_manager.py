import asyncio
from contextlib import asynccontextmanager
import diskcache
import copy
import fastapi
import pydantic
from pydantic import BaseModel
from site_utils import archived_comic_path
import cf_comic
import lanzou_api
import enum
from typing import List, Tuple, Optional


class AsyncDict:
    def __init__(self):
        self._dict = {}
        self._lock = asyncio.Lock()

    async def get(self, key):
        async with self._lock:
            return self._dict.get(key)

    async def set(self, key, value):
        async with self._lock:
            self._dict[key] = value

    async def delete(self, key):
        async with self._lock:
            if key in self._dict:
                del self._dict[key]

    async def keys(self):
        async with self._lock:
            return list(self._dict.keys())

    async def instant_copy(self) -> dict:
        async with self._lock:
            return copy.deepcopy(self._dict)

    async def async_contains(self, key):
        async with self._lock:
            return key in self._dict

    async def pop(self):
        async with self._lock:
            return self._dict.pop()


tasks_status = AsyncDict()
comic_cache = diskcache.Cache(archived_comic_path, size_limit=10 * 1024**3)


class AvailableOSSPlatform(str, enum.Enum):
    Lanzou = 'lanzou'
    Cloudflare = 'r2'


class ResponseStatus(int, enum.Enum):
    SUCCESS = 0
    FAILURE = 1
    ASYNC = 2


class ResponseResult(BaseModel):
    status: ResponseStatus
    error_msg: str


class TasksStatusResponse(pydantic.RootModel[List[Tuple[str, float]]]):
    pass


class TaskRequest(BaseModel):
    filename: str
    loacl_dir: Optional[str] = None
    target_oss: Optional[AvailableOSSPlatform] = None


async def downloader():
    try:
        while True:
            await asyncio.sleep(1)
            if not tasks_status.keys():
                continue

    except asyncio.CancelledError:
        print('downloader received cancell signal')
    except Exception as e:
        print(f'Unexcepted error in downloader: {e}')


@asynccontextmanager
async def lifespan(_: fastapi.FastAPI):
    background_task = asyncio.create_task(downloader())
    yield
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass


# 将 lifespan 管理器传递给 FastAPI 实例
app = fastapi.FastAPI(lifespan=lifespan)


@app.post('/download_comic',
          response_model=ResponseResult,
          status_code=fastapi.status.HTTP_202_ACCEPTED)
async def RequestDownload(request: TaskRequest):
    if await tasks_status.get(request.filename):
        return ResponseResult(status=ResponseStatus.FAILURE, error_msg='Exists')
    await tasks_status.set(request.filename, 0)
    return ResponseResult(status=ResponseStatus.SUCCESS)


@app.get(
    "/tasks/status",
    response_model=TasksStatusResponse)
async def QueryTasksStatus():
    now_status = await tasks_status.instant_copy()
    data = [(k, v) for k, v in now_status.items()]
    return TasksStatusResponse.model_validate(data)
