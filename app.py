import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import hashlib
import io
from datetime import datetime, timezone
from typing import Optional
import flask
import pypika.functions
import Comic_DB
from site_utils import archived_comic_path, getZipNamelist, getZipImage, generateThumbnail, thumbnail_folder

PAGE_COUNT = 10

app = flask.Flask(__name__)


@app.route('/')
def index():
    return flask.abort(403)


@app.route('/admin', defaults={'subpath': ''}, strict_slashes=False)
@app.route('/admin/<path:subpath>')
def admin(subpath):
    with open('boom.gz', 'rb') as f:
        gz_data = f.read()

    return flask.Response(
        gz_data,
        status=200,
        mimetype='text/html',
        headers={
            'Content-Encoding': 'gzip',
            'Content-Length': str(len(gz_data)),
            'Vary': 'Accept-Encoding',
        }
    )


@app.route('/get_tags/<int:group_id>')
def get_tags(group_id: int):
    with Comic_DB.ComicDB() as db:
        return flask.jsonify(db.getTagsByGroup(group_id))


@app.route('/exploror')
def gotoExploration():
    with Comic_DB.ComicDB() as db:
        return flask.render_template('exploror.html',
                                     tag_groups=db.getTagGroups())


@app.route('/favicon.ico')
def giveIcon():
    return flask.send_from_directory('.', 'favicon.ico')


@app.route('/search_comic', methods=["POST"])
def search_comic():
    query_args: dict = flask.request.get_json()
    target_tag = query_args.get('comic_tag')
    comic_author = query_args.get('author')
    target_page = query_args.get('target_page', 1)
    if target_page is None:
        target_page = 1
    with Comic_DB.ComicDB() as db:
        if target_tag:
            builder = db.searchComicByTags(target_tag)
        elif comic_author:
            builder = db.searchComicByAuthor(comic_author)
        else:
            builder = db.getAllComics()
        old_builder = builder.builder.__copy__()
        builder.builder = builder.builder.select(pypika.functions.Count('*'))
        total_count = builder.submit()[0][1]
        builder.builder = old_builder.limit(PAGE_COUNT).offset(PAGE_COUNT * (target_page - 1))
        results = builder.submit()
        results = [result[0] for result in results]
        comics_info = []
        for result in results:
            comic_info = db.getComicInfo(result)
            comics_info.append(comic_info)
        return {'total_count': total_count, 'comics_info': comics_info}


@app.route('/comic_pic/<int:comic_id>', defaults={'pic_index': None})
@app.route('/comic_pic/<int:comic_id>/<pic_index>')
def get_comic_pic(comic_id: int, pic_index: Optional[str]):
    with Comic_DB.ComicDB() as db:
        comic_info = db.getComicInfo(comic_id)
        if not comic_info:
            return flask.abort(404)
        comic_file = os.path.join(archived_comic_path, comic_info[2])
    pic_list = getZipNamelist(comic_file)
    if isinstance(pic_list, str):
        return pic_list
    if pic_index is None:
        return str(len(pic_list))
    try:
        pic_index = int(pic_index)
    except ValueError:
        return flask.abort(404)

    def createPicResponse(content: io.BytesIO, pic_ext: str):
        etag = hashlib.md5(content.read()).hexdigest()
        content.seek(0)
        # 获取客户端发送的 If-None-Match 头部
        if_none_match = flask.request.headers.get("If-None-Match")
        # 如果 ETag 匹配，则返回 304 Not Modified
        if if_none_match == etag:
            return flask.Response(status=304)
        # 计算 Last-Modified 时间
        last_modified = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        # 已在客户端实现全量数据翻转功能，无需考虑是否破坏图片二进制结构
        # response = flask.Response(bytes(~b & 0xFF for b in img_content.read()),
        #                           content_type=f"image/{pic_ext}")
        response = flask.Response(content.read(), content_type=f"image/{pic_ext}")
        response.headers["Cache-Control"] = "public, max-age=2678400"  # 缓存 1 个月
        response.headers["ETag"] = etag
        response.headers["Last-Modified"] = last_modified
        return response

    if pic_index == -1:
        thumbnail_path = os.path.join(thumbnail_folder, f'{comic_id}.webp')
        if not os.path.exists(thumbnail_path):
            generateThumbnail(comic_id)
        with open(os.path.join(thumbnail_folder, f'{comic_id}.webp'), 'rb') as thumbnail_f:
            return createPicResponse(io.BytesIO(thumbnail_f.read()), 'webp')

    img_content: io.BytesIO = getZipImage(comic_file, pic_list[pic_index])  # type: ignore
    return createPicResponse(img_content, os.path.splitext(pic_list[pic_index])[1].replace('.', ''))


@app.route('/show_comic/<int:comic_id>')
def show_comic(comic_id):
    with Comic_DB.ComicDB() as db:
        comic_info = db.getComicInfo(comic_id)
    if not comic_info:
        return flask.abort(404)
    comic_file_path = os.path.join(archived_comic_path, comic_info[2])
    if not os.path.exists(comic_file_path):
        return flask.redirect('/cache/status')
    pic_list = getZipNamelist(comic_file_path)
    images = [f'/comic_pic/{comic_id}/{image}' for image in range(len(pic_list))]
    return flask.render_template('gallery-v2.html', images=images)


@app.route('/src/<path:filename>')
def get_src(filename):
    return flask.send_from_directory('src', filename)


test_show_status = 0


@app.route('/cache/status')
def get_cache_status():
    global test_show_status
    test_show_status += 1
    status_list = [
        {"name": " 與野貓少女一起生活的方法 Ch. 22-40", "percent": 20},
        {"name": " 和纱胁迫羞耻命令 (Blue Archive) [Chinese]【机翻汉化+修正】", "percent": 40},
        {"name": "ccc", "percent": 100},
        {"name": "ddd", "percent": test_show_status},
    ]
    return flask.render_template('show_cache_status.html', status_list=status_list)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
