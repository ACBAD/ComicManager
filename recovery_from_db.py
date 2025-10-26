import os
try:
    from site_utils import getFileHash
except ImportError:
    print('非网站环境,fallback至默认哈希函数')
    import hashlib

    def getFileHash(file_path: str, chunk_size: int = 8192):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as fi:
            while chunk := fi.read(chunk_size):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
from Comic_DB import ComicDB
from hitomiv2 import Hitomi
import sys
import shutil
import requests
from pathlib import Path

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
        download_path = Path(download_path_str) / Path(hitomi_instance.storage_path)
        download_file_hash = getFileHash(download_path.as_posix())
        if download_file_hash != file_hash:
            raise AssertionError('哈希校验失败')
        if download_path:
            # Rename and move the downloaded file
            shutil.move(download_path, local_path)
            print(f"ID:{comic_id} 文件还原成功: {file_path}")
        else:
            print(f"ID:{comic_id} 文件下载失败, 源ID:{source_comic_id}")


def updateFromRemoteDB(remote_db: ComicDB, local_db: ComicDB):
    local_comic_ids = {result[0] for result in local_db.getAllComicsSQL().submit()}
    remote_comic_ids = {result[0] for result in remote_db.getAllComicsSQL().submit()}
    diff_ids = remote_comic_ids - local_comic_ids
    for comic_id in diff_ids:
        hitomi_id = remote_db.getComicSource(comic_id)
        if not hitomi_id:
            print(f'ID:{comic_id} 无源ID')
            continue
        print(f"检索到ID:{comic_id} 的源ID: {hitomi_id}.")
        comic = hitomi_instance.get_comic(hitomi_id)
        download_filename: str = comic.download(max_threads=5)
        # download_filename = 'test.zip'  # DEBUG

        if not download_filename:
            print('下载失败')
            continue
        raw_comic_path = os.path.join(hitomi_instance.storage_path, download_filename)
        filehash = getFileHash(raw_comic_path)
        hashname = f'{filehash}.zip'
        planning_comic_path = os.path.join(BASE_PATH, hashname)
        shutil.move(raw_comic_path, planning_comic_path)
        comic_info = remote_db.getComicInfo(comic_id)
        comic_authors = remote_db.getComicAuthors(comic_id)
        db_result = local_db.addComic(comic_info[1], planning_comic_path, comic_authors, given_comic_id=comic_id)
        if db_result < 0:
            print(f'添加失败, 错误为{db_result}')
            continue

        db_result = local_db.linkComic2Source(comic_id, 1, hitomi_id)
        if not db_result:
            print(f'源链接失败')
        comic_tags = remote_db.getComicTags(comic_id)
        for tag in comic_tags:
            tag_id = remote_db.getTagByName(tag)
            db_result = local_db.linkTag2Comic(comic_id, tag_id)
            if db_result == -2:
                print(f'tag不存在, 创建')
                tag_id = remote_db.getTagByName(tag)
                tag_info = remote_db.getTagInfo(tag_id)
                db_result = local_db.addTag(tag_info[2], tag_info[1], tag_info[3], given_tag_id=tag_id)
                if db_result < 0:
                    print(f'tag {tag}添加失败，错误号: {db_result}')
                db_result = local_db.linkTag2Comic(comic_id, tag_id)
            if db_result < 0:
                print(f'tag {tag}链接失败，错误号: {db_result}')

hitomi_instance = Hitomi(storage_path_fmt='raw_comic', proxy_settings={'http': HTTPS_PROXY, 'https': HTTPS_PROXY})

REMOTE_TEMPFILE = None
if REMOTE_FILE:
    print('检测到远程文件已定义')
    REMOTE_TEMPFILE = '.remote_comic.db'
    response = requests.get(REMOTE_FILE)
    with open(REMOTE_TEMPFILE, 'wb') as f:
        f.write(response.content)
    print('数据库下载完成')
    with ComicDB(REMOTE_TEMPFILE) as rdb, ComicDB() as ldb:
        updateFromRemoteDB(rdb, ldb)
    print(f'数据库更新完成, 删除临时文件')
    os.remove(REMOTE_TEMPFILE)
else:
    with ComicDB() as comic_db:
        recoveryFromLocalDB(comic_db)
print("文件还原完成")
