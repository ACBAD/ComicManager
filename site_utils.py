import hashlib
import os
from typing import Optional
import natsort
import zipfile
import io
from pathlib import Path
archived_document_path = Path('archived_comics')
thumbnail_folder = Path('thumbnail')

if not os.path.exists(archived_document_path):
    os.makedirs(archived_document_path)

if not os.path.exists(thumbnail_folder):
    os.makedirs(thumbnail_folder)


def getZipNamelist(zip_path) -> str | list:
    if not os.path.exists(zip_path):
        return f"{os.listdir(archived_document_path)}"
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        return natsort.natsorted(zip_ref.namelist())


def getZipImage(zip_path, pic_name) -> Optional[io.BytesIO]:
    # 检查 zip 文件是否存在
    if not os.path.exists(zip_path):
        return None
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # 读取图片文件内容并加载到内存
        with zip_ref.open(pic_name) as img_file:
            # 使用 BytesIO 将文件内容转为内存字节流
            img_data = img_file.read()
            img_bytes = io.BytesIO(img_data)
            return img_bytes


def getFileHash(file_path: str | Path, chunk_size: int = 8192):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
