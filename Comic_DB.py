import io
import os.path
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Optional, List, Iterable, Tuple, Union
import pypika

try:
    from site_utils import getFileHash, archived_comic_path, getZipNamelist, getZipImage, thumbnail_folder

    def generateThumbnail(comic_id: int):
        with ComicDB() as idb:
            filename = idb.getComicInfo(comic_id)[2]
        file_path = os.path.join(archived_comic_path, filename)
        pic_list = getZipNamelist(file_path)
        assert isinstance(pic_list, list)
        thumbnail_content = getZipImage(file_path, pic_list[0])
        with open(os.path.join(thumbnail_folder, f'{comic_id}.webp'), "wb") as f:
            f.write(thumbnail_content.read())

    def checkThumbnails():
        if not os.path.exists(thumbnail_folder):
            os.mkdir(thumbnail_folder)
        with ComicDB() as idb:
            comics = {comic_id[0] for comic_id in idb.getAllComicsSQL().submit()}
        for comic_id in comics:
            if os.path.exists(f'{thumbnail_folder}/{comic_id}.webp'):
                continue
            print(f'comic {comic_id} has no thumbnail')
            generateThumbnail(comic_id)


    def getComicContent(comic_id: int, pic_index: int) -> Optional[io.BytesIO]:
        with ComicDB() as idb:
            filename = idb.getComicInfo(comic_id)
            if filename is None:
                return None
            filename = filename[2]
        file_path = os.path.join(archived_comic_path, filename)
        pic_list = getZipNamelist(file_path)
        assert isinstance(pic_list, list)
        if pic_index >= len(pic_list):
            return None
        return getZipImage(file_path, pic_list[pic_index])
except ImportError:
    print('非网站环境,哈希函数fallback至默认,comic路径,thumbnail目录,zip相关函数置空')
    import hashlib
    from typing import Union, Optional
    from pathlib import Path

    def getFileHash(file_path: Union[str, Path], chunk_size: int = 8192):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            while chunk := f.read(chunk_size):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    archived_comic_path = None
    thumbnail_folder = None
    getZipNamelist = None
    getZipImage = None


class SuspendSQLQuery:
    def __init__(self, cursor: sqlite3.Cursor, builder: pypika.dialects.SQLLiteQueryBuilder):  # type: ignore
        self.cursor = cursor
        self.builder = builder

    def submit(self):
        self.cursor.execute(self.builder.get_sql())
        return self.cursor.fetchall()


class ComicDB:
    def __init__(self, db_file_name: str = None):  # Changed default to Comics.db
        if not db_file_name:
            db_file_name = 'Comics.db'
        self.conn = sqlite3.connect(db_file_name)
        self.cursor = self.conn.cursor()
        self.init_db()
        self.conn.commit()
        self.conn.execute('PRAGMA foreign_keys = ON;')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()

    def init_db(self):
        # Use executescript to run schema from file, or define it here.
        # For consistency with migrate.py, I'll define them here.
        # This part will be idempotent.
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Comics (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    Title TEXT NOT NULL,
                    FilePath TEXT NOT NULL UNIQUE,
                    SeriesName TEXT,
                    VolumeNumber INTEGER
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Authors (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    Name TEXT NOT NULL UNIQUE
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS ComicAuthors (
                    ComicID INTEGER,
                    AuthorID INTEGER,
                    FOREIGN KEY (ComicID) REFERENCES Comics(ID) ON DELETE CASCADE,
                    FOREIGN KEY (AuthorID) REFERENCES Authors(ID),
                    PRIMARY KEY (ComicID, AuthorID)
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS TagGroups (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    GroupName TEXT NOT NULL UNIQUE
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Tags (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    Name TEXT NOT NULL UNIQUE,
                    GroupID INTEGER,
                    HitomiAlter TEXT DEFAULT NULL,
                    FOREIGN KEY (GroupID) REFERENCES TagGroups(ID)
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS ComicTags (
                    ComicID INTEGER,
                    TagID INTEGER,
                    FOREIGN KEY (ComicID) REFERENCES Comics(ID) ON DELETE CASCADE,
                    FOREIGN KEY (TagID) REFERENCES Tags(ID),
                    PRIMARY KEY (ComicID, TagID)
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Sources (
                    ID      INTEGER PRIMARY KEY AUTOINCREMENT,
                    Name    TEXT    NOT NULL UNIQUE,
                    BaseUrl TEXT
                )
                ''')
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS ComicSources (
                    ComicID       INTEGER NOT NULL,
                    SourceID      INTEGER NOT NULL,
                    SourceComicID TEXT    NOT NULL,
                    PRIMARY KEY (ComicID, SourceID),
                    FOREIGN KEY (ComicID) REFERENCES Comics (ID) ON DELETE CASCADE,
                    FOREIGN KEY (SourceID) REFERENCES Sources (ID) ON DELETE CASCADE
                )
                ''')

    def getAllComicsSQL(self) -> SuspendSQLQuery:
        builder = pypika.SQLLiteQuery.from_('Comics').select('ID').orderby('ID', order=pypika.Order.desc)
        return SuspendSQLQuery(self.cursor, builder)

    def searchComicByTags(self, *tags) -> SuspendSQLQuery:
        ComicTags = pypika.Table('ComicTags')
        builder = (pypika.SQLLiteQuery.from_(ComicTags)
                   .select(ComicTags.ComicID)
                   .where(pypika.Field('TagID').isin(tags))
                   .orderby('ComicID', order=pypika.Order.desc))
        return SuspendSQLQuery(self.cursor, builder)

    def searchBomicByName(self, name, total_match=False):
        if not total_match:
            query = 'SELECT ID, Title, FilePath, SeriesName, VolumeNumber FROM Comics WHERE Title LIKE ?'
            self.cursor.execute(query, ('%' + name + '%',))
        else:
            query = 'SELECT ID, Title, FilePath, SeriesName, VolumeNumber FROM Comics WHERE Title = ?'
            self.cursor.execute(query, (name,))
        results = self.cursor.fetchall()
        return results

    def searchComicByAuthor(self, author_name: str) -> SuspendSQLQuery:
        Authors = pypika.Table('Authors')
        ComicAuthors = pypika.Table('ComicAuthors')
        builder = (pypika.SQLLiteQuery
                   .from_(ComicAuthors)
                   .join(Authors).on(ComicAuthors.AuthorID == Authors.ID)
                   .select(ComicAuthors.ComicID)
                   .where(Authors.Name == author_name)
                   .orderby(ComicAuthors.ComicID, order=pypika.Order.desc))
        return SuspendSQLQuery(self.cursor, builder)

    def searchComicBySource(self, source_comic_id, source_id: int = None):
        if source_id:
            source_query = "SELECT ComicID FROM ComicSources WHERE SourceComicID = ? AND SourceID = ?"
            self.cursor.execute(source_query, (source_comic_id, source_id))
        else:
            source_query = "SELECT ComicID FROM ComicSources WHERE SourceComicID = ?"
            self.cursor.execute(source_query, (source_comic_id,))
        source_result = self.cursor.fetchone()
        if source_result:
            return source_result[0]
        return None

    def getComicInfo(self, comic_id: int) -> tuple:
        # Fetch comic details
        query = 'SELECT ID, Title, FilePath, SeriesName, VolumeNumber FROM Comics WHERE ID = ?'
        self.cursor.execute(query, (comic_id,))
        comic_result = self.cursor.fetchone()
        if comic_result is None:
            return ()
        author_string = ', '.join(self.getComicAuthors(comic_id))
        return comic_result + (author_string, self.getComicTags(comic_id))

    def getComicTags(self, comic_id) -> Tuple[str, ...]:
        tags_query = 'SELECT Name FROM Tags t JOIN ComicTags ct ON t.ID = ct.TagID WHERE ct.ComicID = ?'
        self.cursor.execute(tags_query, (comic_id,))
        tags = self.cursor.fetchall()
        return tuple(tag[0] for tag in tags)

    def getComicAuthors(self, comic_id: int) -> Tuple[str, ...]:
        author_query = 'SELECT a.Name FROM Authors a JOIN ComicAuthors ca ON a.ID = ca.AuthorID WHERE ca.ComicID = ?'
        self.cursor.execute(author_query, (comic_id,))
        authors = self.cursor.fetchall()
        return tuple(author[0] for author in authors)

    def getSourceID(self, comic_id) -> Optional[int]:
        query = 'SELECT SourceID FROM ComicSources WHERE ComicID = ?'
        self.cursor.execute(query, (comic_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        return None

    def getComicSource(self, comic_id):
        query = 'SELECT SourceComicID FROM ComicSources WHERE ComicID = ?'
        self.cursor.execute(query, (comic_id,))
        result = self.cursor.fetchone()
        if result:
            return result[0]
        return None

    def searchComicByFile(self, filename: Union[str, Path]) -> Optional[int]:
        query = 'SELECT * FROM Comics WHERE FilePath = ?'
        self.cursor.execute(query, (filename if isinstance(filename, str) else filename.name,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        else:
            return None

    def getTagGroups(self):
        query = 'SELECT ID, GroupName FROM TagGroups'
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        result_dict = {}
        for group_id, group_name in results:
            result_dict[group_name] = group_id
        return result_dict

    def getTagByName(self, tag_name):
        query = 'SELECT * FROM Tags WHERE Name = ?'
        self.cursor.execute(query, (tag_name,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        return None

    def getTagInfo(self, tag_id):
        query = 'SELECT * FROM Tags WHERE ID = ?'
        self.cursor.execute(query, (tag_id,))
        results = self.cursor.fetchone()
        if results:
            return results
        return None

    def getTagByHitomi(self, hitomi_name):
        query = 'SELECT * FROM Tags WHERE HitomiAlter = ?'
        self.cursor.execute(query, (hitomi_name,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        return None

    def getTagsByGroup(self, group_id):
        query = '''
            SELECT ID, Name
            FROM Tags
            WHERE GroupID = ?
            '''
        self.cursor.execute(query, (group_id,))
        results = self.cursor.fetchall()
        result_dict = {}
        for tag_id, tag_name in results:
            result_dict[tag_name] = tag_id
        return result_dict

    def addSource(self, name: str, base_url: Optional[str] = None) -> Optional[int]:
        try:
            self.cursor.execute("INSERT INTO Sources (Name, BaseUrl) VALUES (?, ?)", (name, base_url))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def linkComic2Source(self, comic_id: int, source_id: int, source_comic_id: str) -> bool:
        try:
            self.cursor.execute("INSERT INTO ComicSources (ComicID, SourceID, SourceComicID) VALUES (?, ?, ?)",
                                (comic_id, source_id, source_comic_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def addComic(self, title, filepath,
                 authors: Optional[Iterable[str]] = None,
                 series: Optional[str] = None,
                 volume: Optional[int] = None,
                 source: Optional[dict] = None,  # {'source_id': int, 'source_comic_id': str}
                 given_comic_id: int = None,
                 check_file=True) -> Optional[int]:
        if series:
            if not volume:
                return -1
            if not str(volume).isdigit():
                return -2
        if (not os.path.exists(filepath)) and check_file:
            return -3
        filepath = os.path.basename(filepath)

        try:
            if not given_comic_id:
                query = 'INSERT INTO Comics (Title, FilePath, SeriesName, VolumeNumber) VALUES (?, ?, ?, ?)'
                self.cursor.execute(query, (title, filepath, series, volume))
                comic_id = self.cursor.lastrowid
            else:
                query = 'INSERT INTO Comics (ID, Title, FilePath, SeriesName, VolumeNumber) VALUES (?, ?, ?, ?, ?)'
                self.cursor.execute(query, (given_comic_id, title, filepath, series, volume))
                comic_id = given_comic_id

            # Handle authors
            if authors and comic_id:
                for author_name in authors:
                    # Insert author if not exists, then get ID
                    self.cursor.execute("INSERT OR IGNORE INTO Authors (Name) VALUES (?)", (author_name,))
                    self.cursor.execute("SELECT ID FROM Authors WHERE Name = ?", (author_name,))
                    author_id_result = self.cursor.fetchone()
                    if author_id_result:
                        author_id = author_id_result[0]
                        # Link author to comic
                        self.cursor.execute("INSERT INTO ComicAuthors (ComicID, AuthorID) VALUES (?, ?)",
                                            (comic_id, author_id))
            if source and comic_id:
                self.linkComic2Source(comic_id, source['source_id'], source['source_comic_id'])

            self.conn.commit()
            return comic_id
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return -4

    def editComic(self, comic_id,
                  title: Optional[str] = None,
                  filepath: Optional[Union[str, Path]] = None,
                  authors: Optional[List[str]] = None,
                  series: Optional[str] = None,
                  volume: Optional[int] = None,
                  verify_file: bool = True) -> int:
        # Update basic comic info
        update_fields = []
        parameters = []
        if title is not None:
            update_fields.append('Title = ?')
            parameters.append(title)
        if filepath is not None:
            if verify_file and not os.path.exists(filepath):
                return -1
            update_fields.append('FilePath = ?')
            parameters.append(os.path.basename(filepath))
        if series is not None:
            update_fields.append('SeriesName = ?')
            parameters.append(series)
        if volume is not None:
            if not str(volume).isdigit():
                return -2
            update_fields.append('VolumeNumber = ?')
            parameters.append(volume)

        if update_fields:
            query = 'UPDATE Comics SET ' + ', '.join(update_fields) + ' WHERE ID = ?'
            parameters.append(comic_id)
            self.cursor.execute(query, parameters)

        # Update authors
        if authors is not None:
            # 1. Delete existing author links
            self.cursor.execute('DELETE FROM ComicAuthors WHERE ComicID = ?', (comic_id,))
            # 2. Add new author links
            for author_name in authors:
                self.cursor.execute("INSERT OR IGNORE INTO Authors (Name) VALUES (?)", (author_name,))
                self.cursor.execute("SELECT ID FROM Authors WHERE Name = ?", (author_name,))
                author_id_result = self.cursor.fetchone()
                if author_id_result:
                    author_id = author_id_result[0]
                    self.cursor.execute("INSERT INTO ComicAuthors (ComicID, AuthorID) VALUES (?, ?)",
                                        (comic_id, author_id))
        self.conn.commit()
        return 0

    def deleteComic(self, comic_id: int) -> int:
        query = 'DELETE FROM Comics WHERE ID = ?'
        self.cursor.execute(query, (comic_id,))
        self.conn.commit()
        if self.cursor.rowcount > 0:
            return 0
        return -1  # No comic found

    def addTagGroup(self, group_name) -> Optional[int]:
        insert_str = f'INSERT INTO TagGroups (GroupName) VALUES (?)'
        try:
            self.cursor.execute(insert_str, (group_name,))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return -1

    def deleteTagTroup(self, group_id) -> int:
        delete_str = f'DELETE FROM TagGroups WHERE ID = ?'
        self.cursor.execute(delete_str, (group_id,))
        self.conn.commit()
        if self.cursor.rowcount > 0:
            return 0
        return -1

    def addTag(self,
               group_id: int,
               tag_name: str,
               hitomi_alter: str = None,
               given_tag_id: int = None) -> Optional[int]:
        if not isinstance(group_id, int) or group_id < 1:
            return -1
        try:
            if not given_tag_id:
                self.cursor.execute('INSERT INTO Tags (Name, GroupID, HitomiAlter) VALUES (?, ?, ?)',
                                    (tag_name, group_id, hitomi_alter))
                self.conn.commit()
                return self.cursor.lastrowid
            else:
                self.cursor.execute('INSERT INTO Tags (ID, Name, GroupID, HitomiAlter) VALUES (?, ?, ?, ?)',
                                    (given_tag_id, tag_name, group_id, hitomi_alter))
                self.conn.commit()
                return given_tag_id
        except sqlite3.IntegrityError:
            self.conn.rollback()
            self.cursor.execute('SELECT ID FROM TagGroups WHERE ID = ?', (group_id,))
            if self.cursor.fetchone() is None:
                return -1
            self.cursor.execute('SELECT ID FROM Tags WHERE Name = ?', (tag_name,))
            if self.cursor.fetchone():
                return -2
            return -3

    def deleteTag(self, tag_id) -> int:
        delete_str = f'DELETE FROM Tags WHERE ID = ?'
        self.cursor.execute(delete_str, (tag_id,))
        self.conn.commit()
        if self.cursor.rowcount > 0:
            return 0
        return -1

    def getRangeComics(self, count=10, end: Optional[int] = None) -> list:
        query = 'SELECT ID FROM Comics ORDER BY ID DESC LIMIT ? OFFSET ?'
        offset = 0
        if end is not None:
            offset = max(0, end - count)
        
        self.cursor.execute(query, (count, offset))
        comics = self.cursor.fetchall()
        return comics

    def linkTag2Comic(self, comic_id, tag_id):
        try:
            self.cursor.execute('INSERT INTO ComicTags (ComicID, TagID) VALUES (?, ?)', (comic_id, tag_id))
            self.conn.commit()
            return 0
        except sqlite3.IntegrityError:
            self.conn.rollback()
            self.cursor.execute('SELECT * FROM ComicTags WHERE ComicID = ? AND TagID = ?', (comic_id, tag_id))
            if self.cursor.fetchone():
                return -1
            self.cursor.execute('SELECT ID FROM Tags WHERE ID = ?', (tag_id,))
            if not self.cursor.fetchone():
                return -2
            self.cursor.execute('SELECT ID FROM Comics WHERE ID = ?', (comic_id,))
            if not self.cursor.fetchone():
                return -3
            return -4

    def verifyComicFile(self, base_path):
        query_str = f'SELECT ID, FilePath FROM Comics'
        self.cursor.execute(query_str)
        results = self.cursor.fetchall()
        not_exist_files = []
        file_match_ids = []
        for comic_id, file_name in results:
            if not os.path.exists(os.path.join(base_path, file_name)):
                not_exist_files.append(file_name)
                file_match_ids.append(comic_id)
        return not_exist_files, file_match_ids

    def getWanderingFile(self, base_path: str) -> set[Path]:
        test_files = [Path(ifile) for ifile in os.listdir(base_path)]
        wandering_files = set()
        for test_file in test_files:
            result = self.searchComicByFile(test_file)
            if not result:
                wandering_files.add(test_file)
        return wandering_files


def fixFileHash(idb: ComicDB, base_path: str):
    test_files = [Path(fi) for fi in os.listdir(base_path)]
    for test_file in test_files:
        file_path = base_path / test_file
        file_hash = getFileHash(file_path)
        name_hash = test_file.stem
        if test_file == name_hash:
            continue
        print(f'文件{test_file}名称与其哈希{file_hash}不匹配')
        if Path(f'{file_hash}').with_suffix(test_file.suffix) in test_files:
            print(f'检测到哈希冲突, 跳过')
            continue
        new_file_path = base_path / Path(f'{file_hash}').with_suffix(test_file.suffix)
        comic_id = idb.searchComicByFile(test_file)
        if not comic_id:
            print(f'文件{test_file}未在数据库记录')
            continue
        shutil.move(file_path, new_file_path)
        print(f'文件{file_path}移动为{new_file_path}')
        db_result = idb.editComic(comic_id, filepath=new_file_path)
        if db_result:
            print(f'更新{comic_id}时发生数据库错误,错误码{db_result}')
        else:
            print(f'数据库文件{test_file}更新为{new_file_path.name}')


def updateHitomiFileHash(hitomi_id_list: list[int], db: ComicDB):
    try:
        import hitomiv2
    except ImportError:
        hitomiv2 = None
        print('请先安装hitomi模块')
        exit(4)
    hitomi_instance = hitomiv2.Hitomi(proxy_settings={'http': os.environ.get('HTTP_PROXY', None),
                                                      'https': os.environ.get('HTTPS_PROXY', None)})
    for hitomi_id in hitomi_id_list:
        source_comic_id = db.searchComicBySource(hitomi_id)
        if not source_comic_id:
            print(f'hitomi id {source_comic_id}未在数据库记录,请前往添加')
            continue
        hitomi_comic = hitomi_instance.get_comic(hitomi_id)
        download_file_name = hitomi_comic.download(max_threads=5)
        if not download_file_name:
            raise RuntimeError('下载失败')
        file_hash = getFileHash(download_file_name)
        hash_name = Path(f'{file_hash}.zip')
        hash_comic_id = db.searchComicByFile(hash_name)
        if hash_comic_id:
            print(f'hitomi id {hitomi_id}的哈希{hash_name}已在数据库记录为id{source_comic_id}的comic')
            os.remove(download_file_name)
            continue
        db_hash = db.getComicInfo(source_comic_id)[2]
        print(f'确认到哈希不匹配: 下载文件哈希{hash_name} 数据库记录哈希{db_hash}')
        shutil.move(download_file_name, archived_comic_path / hash_name)
        print(f'已将{download_file_name}移动到{archived_comic_path / hash_name}')
        db_result = db.editComic(source_comic_id, filepath=archived_comic_path / hash_name)
        if db_result:
            raise RuntimeError(f'数据库修改失败,id为{db_result}')
        print(f'{source_comic_id}处理完成')


def replaceHitomiComicDueHash(db: ComicDB, replace_files: list[Path]):
    for replace_file_path in replace_files:
        replace_file = Path(replace_file_path.name)
        if not replace_file_path.is_file():
            print('非文件')
            continue
        print(f'检索到替换文件{replace_file}')
        source_comic_id = replace_file.stem
        comic_id = db.searchComicBySource(source_comic_id)
        if not comic_id:
            print(f'未搜索到引用该源id{source_comic_id}的comic')
            continue
        print(f'检索到源id{source_comic_id}对应的comic id{comic_id}')
        replace_file_hash = getFileHash(replace_file_path)
        db_file_hash = Path(db.getComicInfo(comic_id)[2]).stem
        if db_file_hash == replace_file_hash:
            print(f'哈希{db_file_hash}匹配,无需替换')
            continue
        print(f'替换文件哈希{replace_file_hash}与数据库记录哈希{db_file_hash}确不匹配')
        new_file_name = Path(f'{replace_file_hash}.zip')
        shutil.move(replace_file_path, archived_comic_path / new_file_name)
        print(f'已将{replace_file}移动到{archived_comic_path / new_file_name}')
        db_result = db.editComic(comic_id, filepath=archived_comic_path / new_file_name)
        if db_result:
            raise RuntimeError(f'数据库修改失败,错误码为{db_result}')
        print(f'{replace_file}处理完成')

if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print('缺少参数')
        exit(1)
    first_arg = sys.argv[1]
    with ComicDB() as gdb:
        if first_arg == 'clean':
            dismatch_files = gdb.getWanderingFile(archived_comic_path)
            user_input_g = input(f'将删除{len(dismatch_files)}个文件, 确定?')
            if user_input_g != 'y':
                exit(0)
            for file in dismatch_files:
                print(f'现在正删除 {file}')
                os.remove(archived_comic_path / file)
        elif first_arg == 'fix_hash':
            if not archived_comic_path:
                print('未定义归档目录')
                exit(1)
            fixFileHash(gdb, archived_comic_path)
        elif first_arg == 'hitomi_update':
            try:
                hitomi_id_g = int(sys.argv[2])
            except IndexError:
                print('需要hitomi id')
                exit(2)
            except ValueError:
                print('id 需为纯数字')
                exit(3)
            updateHitomiFileHash([hitomi_id_g], gdb)
        elif first_arg == 'hitomi_replace':
            try:
                replace_dir = Path(sys.argv[2])
            except IndexError:
                print('需要替换目录')
                exit(2)
            if not replace_dir.exists() or not replace_dir.is_dir():
                print('替换目录不存在或非目录')
                exit(3)
            if not archived_comic_path:
                print(f'未定义归档目录')
                exit(4)
            replaceHitomiComicDueHash(gdb, [replace_dir / Path(file) for file in os.listdir(replace_dir)])
        elif first_arg == 'test':
            print('test')
