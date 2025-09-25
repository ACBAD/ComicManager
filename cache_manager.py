import asyncio
from contextlib import asynccontextmanager
import diskcache
import fastapi
from pydantic import BaseModel
from site_utils import archived_comic_path
import cf_comic
import lanzou_api
import enum
from typing import List, Dict, Optional, Callable
import os
import time
import tempfile

# --- 缓存配置 ---
CACHE_SIZE_LIMIT = 10 * 1024 ** 3  # 10GB
CACHE_DIRECTORY = archived_comic_path
CONCURRENT_DOWNLOADS = 3  # 最多同时下载3个文件


# --- 缓存管理器 ---
class CacheManager:
    def __init__(self, directory, size_limit):
        self._cache = diskcache.Cache(directory, size_limit=size_limit)
        self.cleanup_temp_files()

    def get(self, key: str):
        """获取缓存项，这会自动刷新其LRU状态"""
        return self._cache.get(key)

    def set(self, key: str, value):
        """设置缓存项"""
        return self._cache.set(key, value)

    def open(self, key: str):
        """
        以文件句柄的方式打开一个缓存项。
        使用 `read=False` 获取文件路径，然后打开它。
        diskcache 会将这次访问记录为一次命中，并刷新LRU。
        """
        raw_file = self._cache.get(key, read=False)
        if raw_file:
            return open(raw_file.name, 'rb')
        return None

    def cleanup_temp_files(self):
        """清理启动时可能残留的 .temp 文件"""
        # 这个逻辑现在由临时目录处理，但保留以防万一
        for filename in os.listdir(CACHE_DIRECTORY):
            if filename.endswith(".temp"):
                try:
                    os.remove(os.path.join(CACHE_DIRECTORY, filename))
                    print(f"Removed stale temp file: {filename}")
                except OSError as e:
                    print(f"Error removing temp file {filename}: {e}")

    @property
    def cache_instance(self):
        return self._cache


# --- 下载任务管理 ---
class DownloadStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class AvailableOSSPlatform(str, enum.Enum):
    Lanzou = 'lanzou'
    Cloudflare = 'r2'


class DownloadTask(BaseModel):
    task_id: str
    comic_name: str
    source: AvailableOSSPlatform
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    error_message: Optional[str] = None


class DownloadManager:
    def __init__(self):
        self._tasks: Dict[str, DownloadTask] = {}
        self._task_queue = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._download_semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

    async def submit_task(self, comic_name: str, source: AvailableOSSPlatform) -> DownloadTask:
        task_id = f"{comic_name}_{source.value}_{int(time.time())}"
        async with self._lock:
            if any(t for t in self._tasks.values() if
                   t.comic_name == comic_name and t.status in [DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING]):
                raise ValueError("Task for this comic is already in progress.")

            task = DownloadTask(task_id=task_id, comic_name=comic_name, source=source)
            self._tasks[task_id] = task
            await self._task_queue.put(task)
            return task

    async def get_task_status(self, task_id: str) -> Optional[DownloadTask]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def get_all_tasks(self) -> List[DownloadTask]:
        async with self._lock:
            return list(self._tasks.values())

    async def _update_progress(self, task_id: str, progress: float):
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].progress = progress

    async def worker(self):
        loop = asyncio.get_running_loop()
        while True:
            task: DownloadTask = await self._task_queue.get()

            async with self._download_semaphore:
                try:
                    async with self._lock:
                        task.status = DownloadStatus.DOWNLOADING

                    def progress_callback(total_size, now_size):
                        if total_size > 0:
                            progress = (now_size / total_size) * 100
                            asyncio.run_coroutine_threadsafe(
                                self._update_progress(task.task_id, progress),
                                loop
                            )

                    with tempfile.TemporaryDirectory() as temp_dir:
                        if task.source == AvailableOSSPlatform.Lanzou:
                            ret_code = await asyncio.to_thread(
                                lanzou_api.downloadComic,
                                file_name=task.comic_name,
                                path=temp_dir,
                                callback=progress_callback
                            )
                            if ret_code != lanzou_api.LanZouCloud.SUCCESS:
                                raise Exception(f"Lanzou download failed with code: {ret_code}")

                        elif task.source == AvailableOSSPlatform.Cloudflare:
                            await asyncio.to_thread(
                                cf_comic.downloadComic,
                                files=task.comic_name,
                                dl_dir=temp_dir,
                                catch_output=progress_callback
                            )
                        else:
                            raise NotImplementedError(f"Unsupported download source: {task.source}")

                        downloaded_file_path = os.path.join(temp_dir, task.comic_name)
                        with open(downloaded_file_path, 'rb') as f:
                            comic_cache.set(task.comic_name, f.read())

                    async with self._lock:
                        task.status = DownloadStatus.COMPLETED
                        task.progress = 100.0

                except Exception as e:
                    print(f"Task {task.task_id} failed: {e}")
                    async with self._lock:
                        task.status = DownloadStatus.FAILED
                        task.error_message = str(e)
                finally:
                    self._task_queue.task_done()


# --- 全局实例 ---
comic_cache = CacheManager(CACHE_DIRECTORY, CACHE_SIZE_LIMIT)
download_manager = DownloadManager()

# --- FastAPI 应用 ---
app = fastapi.FastAPI()


@asynccontextmanager
async def lifespan(_: fastapi.FastAPI):
    worker_task = asyncio.create_task(download_manager.worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        print("Downloader worker stopped.")


app.router.lifespan_context = lifespan


class TaskRequest(BaseModel):
    comic_name: str
    source: AvailableOSSPlatform


class TaskResponse(BaseModel):
    task_id: str
    message: str


class AllTasksResponse(BaseModel):
    tasks: List[DownloadTask]


@app.post("/download", response_model=TaskResponse, status_code=fastapi.status.HTTP_202_ACCEPTED)
async def request_download(request: TaskRequest):
    try:
        task = await download_manager.submit_task(request.comic_name, request.source)
        return TaskResponse(task_id=task.task_id, message="Task accepted.")
    except ValueError as e:
        raise fastapi.HTTPException(status_code=409, detail=str(e))


@app.get("/tasks", response_model=AllTasksResponse)
async def query_all_tasks_status():
    tasks = await download_manager.get_all_tasks()
    return AllTasksResponse(tasks=tasks)


@app.get("/tasks/{task_id}", response_model=DownloadTask)
async def query_task_status(task_id: str):
    task = await download_manager.get_task_status(task_id)
    if not task:
        raise fastapi.HTTPException(status_code=404, detail="Task not found.")
    return task


@app.get("/cache/{comic_name}")
async def get_comic_from_cache(comic_name: str):
    content = comic_cache.get(comic_name)
    if content:
        return {"status": "found_in_cache"}

    try:
        task = await download_manager.submit_task(comic_name, AvailableOSSPlatform.Cloudflare)  # 默认从R2下载
        return fastapi.responses.JSONResponse(
            status_code=202,
            content={"status": "not_in_cache_download_started", "task_id": task.task_id}
        )
    except ValueError as e:  # 任务已在进行中
        return fastapi.responses.JSONResponse(
            status_code=200,
            content={"status": "not_in_cache_download_in_progress", "detail": str(e)}
        )
