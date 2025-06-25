import json
import os
import pyzipper
from typing import Tuple, Set
from io import BytesIO
from lanzou.api import LanZouCloud
from lanzou.api.types import File
import pickle

comics_folder_id = 12172568
DEFAULT_PASSWORD = b'anti-censor'

lzy = LanZouCloud()
lzy_cookie = {
    'ylogin': 'nmsl',
    'phpdisk_info': 'fuck you'
}
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


def listComics() -> Set[str]:
    return {file.name for file in lzy.get_file_list(comics_folder_id)}


def uploadComic(comic_path) -> int:
    def callback(file_name, total_size, now_size):
        print(f"\r文件名:{file_name}, 进度: {now_size / total_size * 100 :.2f}%", end='')

    return lzy.upload_buffer(os.path.basename(comic_path),
                             encryptComicZip(comic_path),
                             folder_id=comics_folder_id,
                             callback=callback)


if __name__ == '__main__':
    with open('lz_files.pkl', 'rb') as lzf:
        print(pickle.load(lzf)[0].name)
