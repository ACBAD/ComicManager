import datetime
import lanzou_api
from site_utils import archived_comic_path
import cf_comic
import os
from typing import Set

local_comics_path = archived_comic_path + '/'


def getBackupComics() -> Set[str]:
    r2_files = cf_comic.listComics()
    lanzou_files = lanzou_api.listComics()
    return r2_files | lanzou_files


def getLocalComics() -> Set[str]:
    local_files_ = set()
    for file in os.listdir(local_comics_path):
        if not file.endswith('.zip'):
            continue
        local_files_.add(file)
    return local_files_


def uploadLocalComic(comic_path):
    lz_upload_stat = lanzou_api.uploadComic(comic_path)
    if lz_upload_stat == 0:
        print('')
        return 0
    print('\nToo big, go to R2')
    if cf_comic.uploadComic(comic_path):
        return 0
    return 1

if __name__ == '__main__':
    print('---------------------------Comic Backup Manager---------------------------')
    print(f'Now is {datetime.datetime.now()}')
    print('Backing up Database')
    if cf_comic.uploadComic('old_Comics.db', recovery=True):
        print('Backing up Database Complete')
    else:
        print('Backing up Database Failed')
    print('Getting backuped comics')
    backuped_files = getBackupComics()
    local_files = getLocalComics()
    non_backup_files = local_files - backuped_files
    print(f'Need backup: {non_backup_files}')
    print('Start upload for backup comics')
    for index, local_file in enumerate(non_backup_files):
        if uploadLocalComic(local_comics_path + local_file) == 0:
            print(f"Now {index + 1}/{len(non_backup_files)} Done")
        else:
            print(f"Failed to upload {index + 1}")
    print('End upload for backup comics')
