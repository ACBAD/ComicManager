import os
from site_utils import getFileHash
from Comic_DB import ComicDB
from hitomiv2 import Hitomi
import sys
import shutil
import requests
from pathlib import Path

BASE_PATH = Path('archived_comics')

HTTP_PROXY = os.environ.get('HTTP_PROXY', None)
HTTPS_PROXY = os.environ.get('HTTPS_PROXY', None)

REMOTE_FILE = None

if len(sys.argv) > 1:
    print('检测到命令行参数')
    if sys.argv[1].startswith('http'):
        print('成功解析命令行参数为URL')
        REMOTE_FILE = sys.argv[1]


def recoveryFromLocalDB(db: ComicDB):
    remaining_files = os.listdir(hitomi_instance.storage_path)
    if remaining_files:
        print('检测到滞留文件')
        remaining_base_path = Path(hitomi_instance.storage_path)
        with ComicDB() as db:
            for file in remaining_files:
                remaining_file_path = remaining_base_path / Path(file)
                remaining_file_hash = getFileHash(remaining_file_path)
                comic_id = db.searchComicByFile(f'{remaining_file_hash}.zip')
                if comic_id:
                    print(f'文件名:{file},哈希{remaining_file_hash}寻找到匹配的comic,ID为{comic_id}')
                    shutil.move(remaining_file_path, BASE_PATH / Path(file))
                else:
                    print(f'文件名{file},哈希未匹配')
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
        file_hash = file_path.split('.')[0]
        if os.path.exists(local_path):
            continue
        print(f"ID:{comic_id} 本地文件不存在: {file_path}")
        if db.getSourceID(comic_id) != 1:
            print(f'非Hitomi源')
            continue
        source_comic_id = db.getComicSource(comic_id)
        if not source_comic_id:
            print(f'ID:{comic_id} 无源ID')
            continue
        print(f"检索到ID:{comic_id} 的源ID: {source_comic_id}.")
        comic = hitomi_instance.get_comic(source_comic_id)
        download_path_str = comic.download(max_threads=5)
        download_path = Path(hitomi_instance.storage_path) / Path(download_path_str)
        download_file_hash = getFileHash(download_path.as_posix())
        if download_file_hash != file_hash:
            raise AssertionError(f'哈希校验失败,数据库记录:{file_hash},下载文件:{download_file_hash}')
        if download_path:
            # Rename and move the downloaded file
            shutil.move(download_path, local_path)
            print(f"ID:{comic_id} 文件还原成功: {file_path}")
        else:
            print(f"ID:{comic_id} 文件下载失败, 源ID:{source_comic_id}")


hitomi_instance = Hitomi(storage_path_fmt='raw_comic', proxy_settings={'http': HTTPS_PROXY, 'https': HTTPS_PROXY})

REMOTE_TEMPFILE = None
if REMOTE_FILE:
    print('检测到远程文件已定义')
    REMOTE_TEMPFILE = 'Comics.db'
    response = requests.get(REMOTE_FILE)
    with open(REMOTE_TEMPFILE, 'wb') as f:
        f.write(response.content)
    print('数据库下载完成')
    with ComicDB() as comic_db:
        recoveryFromLocalDB(comic_db)
print("文件还原完成")
