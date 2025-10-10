import os
from Comic_DB import ComicDB
from hitomiv2 import Hitomi
import sys

base_path = 'archived_comics'

if len(sys.argv) > 1 and sys.argv[1] == 'no_proxy':
    hitomi = Hitomi()
else:
    hitomi = Hitomi(proxy_settings={'http': 'http://127.0.0.1:10809', 'https': 'http://127.0.0.1:10809'})

with ComicDB() as db:
    all_comics_query = db.getAllComics()
    all_comics = all_comics_query.submit()
    for comic_row in all_comics:
        comic_id = comic_row[0]
        comic_info = db.getComicInfo(comic_id)
        if not comic_info:
            print(f"无此ID: {comic_id}")
            continue
        file_path = comic_info[2]
        local_path = os.path.join(base_path, file_path)
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
                os.rename(download_path, local_path)
                print(f"ID:{comic_id} 文件还原成功: {file_path}")
            else:
                print(f"ID:{comic_id} 文件还原失败, 源ID:{source_comic_id}")
        except Exception as e:
            print(f"An error occurred while downloading comic with source ID {source_comic_id}: {e}")
print("文件还原完成")
