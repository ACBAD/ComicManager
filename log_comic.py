import shutil
import hashlib
import os.path
import sys
from typing import Union
from hitomiv2 import Hitomi
import Comic_DB

raw_path = 'raw_comic'
archive_path = 'archived_comics'
hitomi = Hitomi(proxy_settings={'http': 'http://127.0.0.1:10809', 'https': 'http://127.0.0.1:10809'},
                storage_path_fmt=raw_path, debug_fmt=False)


def get_file_hash(file_path):
    return hashlib.md5(open(file_path, 'rb').read()).hexdigest()


def log_tag(db_obj: Comic_DB.ComicDB, igroup_id: Union[None, int], hitomi_name) -> int:
    db_query_result = db_obj.get_tag_by_hitomi(hitomi_name)
    if not db_query_result:
        print(f'hitomi name: {hitomi_name}')
        if not igroup_id:
            while True:
                igroup_id = input('输入tag组id')
                if igroup_id.isdigit():
                    igroup_id = int(igroup_id)
                    break
                print('请输入纯数字id')
        tag_name = input('tag 原名')
        add_result = db_obj.add_tag(igroup_id, tag_name, hitomi_name)
        if add_result < 0:
            print(add_result)
        return add_result
    else:
        return db_query_result

id_iter = None
task_list = []
raw_file_list = os.listdir(raw_path)
if len(sys.argv) > 1:
    task_list += sys.argv
    del task_list[0]
if raw_file_list:
    print('检测到有未完成录入，加入任务列表')
    for raw_file in raw_file_list:
        hitomi_id = raw_file.split('.')[0]
        task_list.append(hitomi_id)
if len(task_list) > 0:
    id_iter = iter(task_list)
while True:
    try:
        hitomi_id = input('输入hitomi id: ') if id_iter is None else next(id_iter)
    except StopIteration:
        print('任务列表结束')
        id_iter = None
        continue
    if not hitomi_id:
        print('结束录入')
        break
    if not hitomi_id.isdigit():
        print('输入错误，重新输入')
        continue
    comic = hitomi.get_comic(hitomi_id)
    print(f'本子名: {comic.title}')
    comic_tags_list = []
    with Comic_DB.ComicDB() as db:
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

        comic_authors = comic.authors
        if not comic_authors:
            comic_author = '佚名'
        elif len(comic_authors) == 1:
            comic_author = comic_authors[0]['artist']
        else:
            comic_author = ''
            for author in comic_authors:
                comic_author += author['artist']
                comic_author += ', '

        print('信息录入完成，开始获取源文件')
        if os.path.exists(os.path.join(raw_path, f'{hitomi_id}.zip')):
            print('检测到源文件已存在，跳过下载')
            download_name = f'{hitomi_id}.zip'
        else:
            download_name = comic.download(max_threads=5)

        if not download_name:
            print('下载失败')
        comic_hash = get_file_hash(os.path.join(raw_path, download_name))
        hash_name = f'{comic_hash}.zip'
        comp_path = os.path.join(raw_path, hash_name)
        shutil.move(os.path.join(raw_path, download_name),
                  os.path.join(raw_path, hash_name))

        comic_id = db.add_comic(comic.title, comp_path, comic_author)
        if comic_id < 0:
            print(f'无法添加本子: {comic_id}')
            os.remove(comp_path)
            continue
        print('开始链接tags')
        for tag in comic_tags_list:
            link_result = db.link_tag_to_comic(comic_id, tag)
            if link_result < 0:
                print(f'tag {tag}链接失败，错误id: {link_result}')
        print('录入完成，移入完成文件夹')
        shutil.move(comp_path, os.path.join(archive_path, hash_name))
print('录入完成')
