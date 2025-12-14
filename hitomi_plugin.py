import asyncio
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from fastapi import status

import document_sql
import hitomiv2
import log_comic
from pathlib import Path
from shared import AddComicRequest, AddComicResponse, RequireCookies, get_db, task_status, TaskStatus
import document_db
import shutil

# 初始化 Router
router = APIRouter(tags=["Hitomi"])

# 初始化核心对象
hitomi = hitomiv2.Hitomi(proxy_settings=hitomiv2.HTTP_PROXY)


# --- 后台任务逻辑 ---
async def refresh_hitomi_loop():
    print("Hitomi 后台刷新任务已启动")
    while True:
        try:
            try:
                await hitomi.refresh_version()
            except Exception as e:
                print(f"Hitomi 刷新失败，将在下个周期重试。错误: {e}")
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            break


async def implement_document(comic: hitomiv2.Comic, tags: list[document_sql.Tag]):
    comic_authors_raw = comic.artists
    comic_authors_list = []
    if not comic_authors_raw:
        comic_authors_list.append('佚名')
    else:
        for author in comic_authors_raw:
            comic_authors_list.append(author.artist)
    raw_comic_path = log_comic.RAW_PATH / Path(f'{comic.id}.zip')

    if raw_comic_path.exists():
        task_status[comic.title] = TaskStatus(percent=0, message='预下载文件已存在, 请求人工接管')
        return
    task_status[comic.title] = TaskStatus(percent=0)
    total_files_num = len(comic.files)
    done_nums = 0

    # noinspection PyUnusedLocal
    async def phase_callback(url: str):
        nonlocal done_nums
        done_nums += 1
        task_status[comic.title].percent = round(done_nums / total_files_num * 100, ndigits=2)
    with open(raw_comic_path, 'wb') as cf:
        dl_result = await hitomiv2.download_comic(comic, cf, max_threads=5, phase_callback=phase_callback)
    if not dl_result:
        task_status[comic.title].message = '下载失败'

    comic_hash = await log_comic.get_file_hash(raw_comic_path)
    hash_name = f'{comic_hash}.zip'
    final_path = log_comic.archived_document_path / Path(hash_name)
    if final_path.exists():
        task_status[comic.title] = TaskStatus(percent=0, message='最终文件已存在, 请求人工接管')
        return
    with document_db.DocumentDB() as db:
        comic_id = db.add_document(comic.title, final_path, authors=comic_authors_list, check_file=False)
        if not comic_id or comic_id < 0:
            task_status[comic.title] = TaskStatus(percent=0, message=f'无法添加本子: {comic_id}')
            raw_comic_path.unlink()
            return
        for tag in tags:
            db.link_document_tag(comic_id, tag)
        link_result = db.link_document_source(comic_id, 1, str(comic.id))
        if not link_result:
            task_status[comic.title] = TaskStatus(percent=0, message='hitomi链接失败, 请求人工接管')
            return
    shutil.move(raw_comic_path, final_path)


# noinspection PyUnusedLocal
@router.get('/add', dependencies=[Depends(RequireCookies())])
async def add_comic(source_id: int, source_document_id: str):
    return FileResponse('templates/add_comic.html')


@router.post('/add', dependencies=[Depends(RequireCookies())])
async def add_comic_post(request: AddComicRequest,
                         bg_tasks: BackgroundTasks,
                         db: document_db.DocumentDB = Depends(get_db)) -> AddComicResponse:
    if request.source_id != 1:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
    try:
        hitomi_result = await hitomi.get_comic(request.source_document_id)
    except Exception as e:
        return AddComicResponse(success=False, message=str(e))
    db_result = db.search_by_source(source_document_id=request.source_document_id)
    if db_result:
        task_status.pop(hitomi_result.title, None)
        return AddComicResponse(success=True, redirect_url=f'/show_document/{db_result.document_id}')
    raw_document_tags = log_comic.extract_generic_tags(hitomi_result)
    document_tags = []
    for tag in raw_document_tags:
        db_result = tag.query_db(db)
        if db_result:
            document_tags.append(db_result)
            continue
        tag_info_by_req = request.inexistent_tags.get(tag.hitomi_name, None)
        if tag_info_by_req is None:
            return AddComicResponse(success=False, message=f'tag {tag.hitomi_name} not found')
        if tag.group_id is None:
            tag.group_id = tag_info_by_req[0]
        if tag.group_id is None:
            return AddComicResponse(success=False, message=f'group {tag.hitomi_name} not found')
        if not tag_info_by_req[1]:
            return AddComicResponse(success=False, message=f'tag {tag.hitomi_name} name not found')
        tag.name = tag_info_by_req[1]
        try:
            db_result = tag.add_db(db)
        except Exception as e:
            return AddComicResponse(success=False, message=f'tag {tag.hitomi_name} db add failed: {str(e)}')
        document_tags.append(db_result)
    bg_tasks.add_task(implement_document, hitomi_result, document_tags)
    return AddComicResponse(success=True, redirect_url='/show_status')


@router.get('/get_missing_tags', dependencies=[Depends(RequireCookies())])
async def get_missing_tags(source_id: int,
                           source_document_id: str,
                           db: document_db.DocumentDB = Depends(get_db)):
    if source_id != 1:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
    db_result = db.search_by_source(source_document_id=source_document_id)
    if db_result:
        return []
    try:
        hitomi_result = await hitomi.get_comic(source_document_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    plain_tags = log_comic.extract_generic_tags(hitomi_result)
    tags: list[dict[str, str]] = []
    for tag in plain_tags:
        if tag.query_db(db):
            continue
        tags.append({'name': tag.hitomi_name, 'need_group': False if tag.group_id else True})
    return tags
