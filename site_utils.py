import hashlib
import os
from typing import Optional
import natsort
import zipfile
import io
from pathlib import Path
import aiofiles
archived_document_path = Path('archived_documents')
thumbnail_folder = Path('thumbnail')

if not os.path.exists(archived_document_path):
    os.makedirs(archived_document_path)

if not os.path.exists(thumbnail_folder):
    os.makedirs(thumbnail_folder)


def get_zip_namelist(zip_path: Path) -> str | list[str]:
    if not zip_path.exists():
        return f"{os.listdir(archived_document_path)}"
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        return natsort.natsorted(zip_ref.namelist())


def get_zip_image(zip_path: Path, pic_name: str) -> Optional[io.BytesIO]:
    # 检查 zip 文件是否存在
    if not zip_path.exists():
        return None
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # 检查图片文件是否存在
        if pic_name not in zip_ref.namelist():
            return None
        # 读取图片文件内容并加载到内存
        with zip_ref.open(pic_name) as img_file:
            # 使用 BytesIO 将文件内容转为内存字节流
            img_data = img_file.read()
            img_bytes = io.BytesIO(img_data)
            return img_bytes


async def get_file_hash(file_path: Path, chunk_size: int = 65536) -> str:
    hash_md5 = hashlib.md5()
    # 必须使用 async with 来打开文件
    async with aiofiles.open(file_path, 'rb') as f:
        while chunk := await f.read(chunk_size):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()
