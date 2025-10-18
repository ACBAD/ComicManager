import os
from Comic_DB import ComicDB
from hitomiv2 import Hitomi
from log_comic import log_comic
import sys
import shutil
import requests

BASE_PATH = 'archived_comics'

HTTP_PROXY = os.environ.get('HTTP_PROXY', None)
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', None)

REMOTE_FILE = None

if len(sys.argv) > 1:
    print('检测到命令行参数')
    if sys.argv[1].startswith('http'):
        print('成功解析命令行参数为URL')
        REMOTE_FILE = sys.argv[1]


def recoveryFromLocalDB(db: ComicDB):
    all_comics_query = db.getAllComicsSQL()
    all_comics = all_comics_query.submit()
    for comic_row in all_comics:
        comic_id = comic_row[0]
        comic_info = db.getComicInfo(comic_id)
        if not comic_info:
            print(f"无此ID: {comic_id}")
            continue
        file_path = comic_info[2]
        local_path = os.path.join(BASE_PATH, file_path)
        if os.path.exists(local_path):
            continue
        print(f"ID:{comic_id} 本地文件不存在: {file_path}")
        source_comic_id = db.getComicSource(comic_id)
        if not source_comic_id:
            print(f'ID:{comic_id} 无源ID')
            continue
        print(f"检索到ID:{comic_id} 的源ID: {source_comic_id}.")
        try:
            comic = hitomi.get_comic(source_comic_id)
            download_path = comic.download(max_threads=5)
            if download_path:
                # Rename and move the downloaded file
                shutil.move(download_path, local_path)
                print(f"ID:{comic_id} 文件还原成功: {file_path}")
            else:
                print(f"ID:{comic_id} 文件还原失败, 源ID:{source_comic_id}")
        except Exception as e:
            print(f"An error occurred while downloading comic with source ID {source_comic_id}: {e}")


def updateLocalDB(remote_db: ComicDB, local_db: ComicDB):
    local_comic_ids = {result[0] for result in local_db.getAllComicsSQL().submit()}
    remote_comic_ids = {result[0] for result in remote_db.getAllComicsSQL().submit()}
    diff_ids = remote_comic_ids - local_comic_ids
    for comic_id in diff_ids:
        hitomi_id = remote_db.getComicSource(comic_id)
        log_comic(hitomi, local_db, hitomi_id)

hitomi = Hitomi(storage_path_fmt='raw_comic', proxy_settings={'http': HTTPS_PROXY, 'https': HTTPS_PROXY})

REMOTE_TEMPFILE = None
if REMOTE_FILE:
    print('检测到远程文件已定义')
    REMOTE_TEMPFILE = '.remote_comic.db'
    response = requests.get(REMOTE_FILE)
    with open(REMOTE_TEMPFILE, 'wb') as f:
        f.write(response.content)
    print('数据库下载完成')
    with ComicDB(REMOTE_TEMPFILE) as rdb, ComicDB() as ldb:
        updateLocalDB(rdb, ldb)
    print(f'数据库更新完成, 删除临时文件')
    os.remove(REMOTE_TEMPFILE)
    exit(0)


with ComicDB() as comic_db:
    recoveryFromLocalDB(comic_db)
print("文件还原完成")
