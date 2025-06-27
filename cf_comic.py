import cf_r2
import os
from typing import *

r2_comic_path = 'comic/'


def downloadComic(files: Union[Iterable[str], str], dl_dir, catch_output=True):
    return cf_r2.download([r2_comic_path + file for file in files], dl_dir, catch_output=catch_output)


def listComics():
    return {os.path.basename(backup_file) for backup_file in cf_r2.listFiles(r2_comic_path)}


def uploadComic(local_path, recovery=False):
    return cf_r2.uploadFile(local_path, r2_comic_path + os.path.basename(local_path), recovery=recovery)
