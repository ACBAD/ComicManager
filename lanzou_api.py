import json
import os
from io import BytesIO
from typing import Tuple, Set, Union, Optional, Dict, Callable
import pyzipper
from lanzou.api import LanZouCloud
from lanzou.api.models import FileList

comics_folder_id = 12172568
DEFAULT_PASSWORD = b'anti-censor'
comic_file_id_matches: Optional[Dict[str, int]] = None

lzy = LanZouCloud()
with open('lanzou.json') as lz_conf_f:
    lzy_cookie = json.load(lz_conf_f)
code = lzy.login_by_cookie(lzy_cookie)
if code != LanZouCloud.SUCCESS:
    raise RuntimeError(f'Login failed: {code}')


def encryptComicZip(file_buf: BytesIO) -> BytesIO:
    files = []
    with pyzipper.ZipFile(file_buf) as zf:
        for name in zf.namelist():
            assert isinstance(name, str)
            with zf.open(name) as f:
                content = BytesIO(f.read())
            files.append((name, content))
    buf = BytesIO()
    with pyzipper.AESZipFile(
            buf,
            mode="w",
            compression=pyzipper.ZIP_STORED,
            encryption=pyzipper.WZ_AES
    ) as zf:
        zf.setpassword(DEFAULT_PASSWORD)
        for name, content in files:
            content.seek(0)
            zf.writestr(name, content.read())
    buf.seek(0)
    return buf


def decryptComicZip(encrypted_buf: BytesIO) -> BytesIO:
    extracted_files: list[Tuple[str, BytesIO]] = []
    with pyzipper.AESZipFile(encrypted_buf) as encrypted_zip:
        encrypted_zip.setpassword(DEFAULT_PASSWORD)
        for name in encrypted_zip.namelist():
            if name.endswith('/'):
                continue
            with encrypted_zip.open(name) as f:
                content = BytesIO(f.read())
                extracted_files.append((name, content))
    plain_buf = BytesIO()
    with pyzipper.ZipFile(plain_buf, mode='w', compression=pyzipper.ZIP_STORED) as plain_zip:
        for name, content in extracted_files:
            content.seek(0)
            plain_zip.writestr(name, content.read())
    plain_buf.seek(0)
    return plain_buf


def listComics(ret_raw=False) -> Union[Set[str], FileList]:
    if ret_raw:
        return lzy.get_file_list(comics_folder_id)
    return {file.name for file in lzy.get_file_list(comics_folder_id)}


def uploadComic(comic_path) -> int:
    def callback(file_name, total_size, now_size):
        print(f"\r文件名:{file_name}, 进度: {now_size / total_size * 100 :.2f}%", end='')

    return lzy.upload_buffer(os.path.basename(comic_path),
                             encryptComicZip(comic_path),
                             folder_id=comics_folder_id,
                             callback=callback)


def updateFileIdMatches() -> bool:
    global comic_file_id_matches
    comic_file_id_matches = lzy.get_file_list(comics_folder_id).name_id
    if not comic_file_id_matches:
        return False
    return True


def downloadComic(file_name: str, path: Optional[str] = None, callback: Optional[Union[str, Callable]] = 'def') -> int:
    def cb_maker(filename):
        def dl_cb(total_size, now_size):
            print(f'\rFile: {filename} Progress: {now_size / total_size * 100 :.2f}%', end='')
        return dl_cb

    if not comic_file_id_matches:
        if not updateFileIdMatches():
            return LanZouCloud.FAILED
    encrypted_buf = BytesIO()
    if file_name not in comic_file_id_matches:
        if not updateFileIdMatches():
            return LanZouCloud.FAILED
        if file_name not in comic_file_id_matches:
            return LanZouCloud.ID_ERROR
    if callback == 'def':
        encrypted_buf_stat = lzy.download2buffer(comic_file_id_matches[file_name],
                                                 encrypted_buf,
                                                 callback=cb_maker(file_name))
    else:
        assert isinstance(callback, Callable)
        encrypted_buf_stat = lzy.download2buffer(comic_file_id_matches[file_name],
                                                 encrypted_buf,
                                                 callback=callback)
    if encrypted_buf_stat:
        return encrypted_buf_stat
    decrypted_buf = decryptComicZip(encrypted_buf)
    if path:
        with open(os.path.join(path, file_name), 'wb') as f:
            f.write(decrypted_buf.read())
    else:
        with open(file_name, 'wb') as f:
            f.write(decrypted_buf.read())
    return LanZouCloud.SUCCESS


if __name__ == '__main__':
    print(downloadComic('ba6d4c2d86f66bc43c8e4edc8b3e341c.zip'))
