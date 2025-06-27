import os
from typing import Union, Optional
import natsort
import zipfile
import io
from Comic_DB import ComicDB
archived_comic_path = 'archived_comics'
thumbnail_folder = 'thumbnail'

if not os.path.exists(archived_comic_path):
    os.makedirs(archived_comic_path)

if not os.path.exists(thumbnail_folder):
    os.makedirs(thumbnail_folder)


def getZipNamelist(zip_path) -> Union[str, list]:
    if not os.path.exists(zip_path):
        return f"{os.listdir(archived_comic_path)}"
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        return natsort.natsorted(zip_ref.namelist())


def getZipImage(zip_path, pic_name) -> Union[str, io.BytesIO]:
    # 检查 zip 文件是否存在
    if not os.path.exists(zip_path):
        return f"文件 {zip_path} 不存在"
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # 读取图片文件内容并加载到内存
        with zip_ref.open(pic_name) as img_file:
            # 使用 BytesIO 将文件内容转为内存字节流
            img_data = img_file.read()
            img_bytes = io.BytesIO(img_data)
            return img_bytes


def getComicContent(comic_id: int, pic_index: int) -> Optional[io.BytesIO]:
    with ComicDB() as db:
        filename = db.getComicInfo(comic_id)
        if filename is None:
            return None
        filename = filename[3]
    file_path = os.path.join(archived_comic_path, filename)
    pic_list = getZipNamelist(file_path)
    assert isinstance(pic_list, list)
    return getZipImage(file_path, pic_list[pic_index])


def generateThumbnail(comic_id: int):
    with ComicDB() as db:
        filename = db.getComicInfo(comic_id)[3]
    file_path = os.path.join(archived_comic_path, filename)
    pic_list = getZipNamelist(file_path)
    assert isinstance(pic_list, list)
    thumbnail_content = getZipImage(file_path, pic_list[0])
    with open(os.path.join(thumbnail_folder, f'{comic_id}.webp'), "wb") as f:
        f.write(thumbnail_content.read())


def checkThumbnails():
    if not os.path.exists(thumbnail_folder):
        os.mkdir(thumbnail_folder)
    with ComicDB() as db:
        comics = {comic_id[0] for comic_id in db.getAllComics().submit()}
    for comic_id in comics:
        if os.path.exists(f'{thumbnail_folder}/{comic_id}.webp'):
            continue
        print(f'comic {comic_id} has no thumbnail')
        generateThumbnail(comic_id)


if __name__ == '__main__':
    checkThumbnails()
