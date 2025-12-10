import asyncio
import shutil
import os.path
import sys
import re
from typing import Union
from hitomiv2 import Hitomi
import document_db
from document_sql import *
from site_utils import archived_document_path, get_file_hash
from pathlib import Path

RAW_PATH = Path('raw_document')
if not RAW_PATH.exists():
    RAW_PATH.mkdir()


def log_tag(db_obj: document_db.DocumentDB, group_id: Union[None, int], hitomi_name: str) -> int:
    db_query_result = db_obj.get_tag_by_hitomi(hitomi_name)
    if not db_query_result:
        print(f'hitomi name: {hitomi_name}')
        if not group_id:
            while True:
                group_id = input('输入tag组id')
                if group_id.isdigit():
                    group_id = int(group_id)
                    break
                print('请输入纯数字id')
        tag_name = input('tag 原名')
        add_result = db_obj.add_tag(Tag(name=tag_name, group_id=group_id, hitomi_alter=hitomi_name))
        if add_result is None:
            print(add_result)
        return add_result
    else:
        return db_query_result.tag_id  # getTagByHitomi returns a tuple


def extract_hitomi_id(hitomi_url: str) -> Optional[str]:
    __match = re.search(r'(\d+)\.html$', hitomi_url)
    if __match:
        print('检测到HitomiURL')
        print(f'提取出的目标ID为:{__match.group(1)}')
        return __match.group(1)
    return None


async def log_comic(hitomi: Hitomi, db: document_db.DocumentDB, hitomi_id: int):
    comic_tags_list = []
    if db.search_by_source(str(hitomi_id)):
        print('已存在')
        return
    comic = await hitomi.get_comic(hitomi_id)
    print(f'本子名: {comic.title}')
    print('开始录入大类tag')
    ip_names = comic.parodys
    if ip_names:
        for ip_name in ip_names:
            tag_id = log_tag(db, 1, ip_name['parody'])
            if tag_id > 0:
                comic_tags_list.append(tag_id)
                print(f'世界观: {ip_name["parody"]}')
            else:
                print(f'tag添加失败: {tag_id}，请手动添加 {ip_name["parody"]}')
    else:
        print('没有世界观tag')

    if comic.characters:
        for char_name in comic.characters:
            tag_id = log_tag(db, 2, char_name['character'])
            if tag_id > 0:
                comic_tags_list.append(tag_id)
                print(f'角色: {char_name["character"]}')
            else:
                print(f'tag添加失败: {tag_id}，请手动添加 {char_name["character"]}')
    else:
        print('没有角色tag')

    for tag in comic.tags:
        tag_id = log_tag(db, None, tag['tag'])
        if tag_id > 0:
            comic_tags_list.append(tag_id)
        else:
            print(f'tag添加失败: {tag_id}，请手动添加 {tag["tag"]}')

    comic_authors_raw = comic.authors
    comic_authors_list = []
    if not comic_authors_raw:
        comic_authors_list.append('佚名')
    else:
        for author in comic_authors_raw:
            comic_authors_list.append(author['artist'])

    print('信息录入完成，开始获取源文件')
    raw_comic_path = RAW_PATH / Path(f'{hitomi_id}.zip')
    dl_result = True
    if raw_comic_path.exists():
        print('检测到源文件已存在，跳过下载')
    else:
        with open(raw_comic_path, 'wb') as cf:
            dl_result = await comic.download(cf, max_threads=5)

    if not dl_result:
        print('下载失败')
        return

    comic_hash = get_file_hash(raw_comic_path)
    hash_name = f'{comic_hash}.zip'
    final_path = archived_document_path / Path(hash_name)
    if final_path.exists():
        raise FileExistsError(f'文件 {final_path} 已存在')

    comic_id = db.add_document(comic.title, final_path, authors=comic_authors_list, check_file=False)
    if not comic_id or comic_id < 0:
        print(f'无法添加本子: {comic_id}')
        raw_comic_path.unlink()
        return
    print('开始链接tags')
    for tag in comic_tags_list:
        link_result = db.link_document_tag(comic_id, tag)
        if link_result < 0:
            print(f'tag {tag}链接失败，错误id: {link_result}')
    print('开始链接源')
    link_result = db.link_document_source(comic_id, 1, str(hitomi_id))
    if link_result:
        print(f'成功将本子与源ID{hitomi_id}链接')
    else:
        print('链接失败')
    print('录入完成，移入完成文件夹')
    shutil.move(raw_comic_path, final_path)


async def init_hitomi(hitomi: Hitomi):
    await hitomi.refresh_version()


if __name__ == '__main__':
    hitomi_instance = Hitomi(debug_fmt=False)
    asyncio.run(init_hitomi(hitomi_instance))
    id_iter = None
    task_list = []
    raw_file_list = os.listdir(RAW_PATH)
    if len(sys.argv) > 1:
        task_list += sys.argv
        del task_list[0]
    if raw_file_list:
        print('检测到有未完成录入，加入任务列表')
        for raw_file in raw_file_list:
            hitomi_id_g = raw_file.split('.')[0]
            task_list.append(hitomi_id_g)
    if len(task_list) > 0:
        id_iter = iter(task_list)
    while True:
        try:
            user_input = input('输入hitomi id: ') if id_iter is None else next(id_iter)
        except StopIteration:
            print('任务列表结束')
            id_iter = None
            continue
        if not user_input:
            print('结束录入')
            break
        if user_input.isdigit():
            hitomi_id_g = user_input
        else:
            extract_result = extract_hitomi_id(user_input)
            if not extract_result:
                print('输入错误')
                continue
            hitomi_id_g = extract_result
        with document_db.DocumentDB() as db_g:
            asyncio.run(log_comic(hitomi_instance, db_g, hitomi_id_g))
    print('录入完成')
