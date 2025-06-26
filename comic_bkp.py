import datetime
from cf_r2 import uploadFile, listFiles
from lanzou_api import listComics, uploadComic
import os
from site_utils import archived_comic_path

local_comics_path = archived_comic_path + '/'
backup_comic_path = 'comic/'


def getBackupComics():
    r2_files = {os.path.basename(backup_file) for backup_file in listFiles(backup_comic_path)}
    lanzou_files = listComics()
    return r2_files | lanzou_files


def uploadLocalComic(comic_path):
    lz_upload_stat = uploadComic(comic_path)
    if lz_upload_stat == 0:
        print('')
        return 0
    print('\nToo big, go to R2')
    if uploadFile(comic_path, backup_comic_path + os.path.basename(comic_path)):
        return 0
    return 1

if __name__ == '__main__':
    print('---------------------------Comic Backup Manager---------------------------')
    print(f'Now is {datetime.datetime.now()}')
    print('Backing up Database')
    if uploadFile('Comics.db', recovery=True):
        print('Backing up Database Complete')
    else:
        print('Backing up Database Failed')
    print('Getting backuped comics')
    backuped_files = getBackupComics()
    local_files = set(os.listdir(local_comics_path))
    non_backup_files = local_files - backuped_files
    print(f'Need backup: {non_backup_files}')
    print('Start upload for backup comics')
    for index, local_file in enumerate(non_backup_files):
        if uploadLocalComic(local_comics_path + local_file) == 0:
            print(f"Now {index + 1}/{len(non_backup_files)} Done")
        else:
            print(f"Failed to upload {index + 1}")
    print('End upload for backup comics')
