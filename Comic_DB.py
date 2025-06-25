import os.path
import sqlite3
from token import OP
from typing import Optional
import pypika


class SuspendSQLQuery:
    def __init__(self, cursor: sqlite3.Cursor, builder: pypika.dialects.SQLLiteQueryBuilder): # type: ignore
        self.cursor = cursor
        self.builder = builder

    def submit(self):
        self.cursor.execute(self.builder.get_sql())
        return self.cursor.fetchall()


class ComicDB:
    def __init__(self):
        self.conn = sqlite3.connect('Comics.db')
        self.cursor = self.conn.cursor()
        self.init_db()
        self.conn.commit()
        self.conn.execute('PRAGMA foreign_keys = ON;')

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()

    def init_db(self):
        # 创建漫画表
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Comics (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    Title TEXT NOT NULL,
                    Author TEXT NOT NULL,
                    FilePath TEXT NOT NULL UNIQUE ,
                    SeriesName TEXT,
                    VolumeNumber INTEGER
                )
                ''')
        # 创建标签组表
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS TagGroups (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    GroupName TEXT NOT NULL UNIQUE 
                )
                ''')
        # 创建标签表
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS Tags (
                    ID INTEGER PRIMARY KEY AUTOINCREMENT,
                    Name TEXT NOT NULL UNIQUE ,
                    GroupID INTEGER,
                    HitomiAlter TEXT default NULL,
                    FOREIGN KEY (GroupID) REFERENCES TagGroups(ID)
                )
                ''')
        # 创建漫画与标签关联表
        self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS ComicTags (
                    ComicID INTEGER,
                    TagID INTEGER,
                    FOREIGN KEY (ComicID) REFERENCES Comics(ID) ON DELETE CASCADE,
                    FOREIGN KEY (TagID) REFERENCES Tags(ID),
                    PRIMARY KEY (ComicID, TagID)
                )
                ''')

    def get_all_comics(self) -> SuspendSQLQuery:
        builder = pypika.SQLLiteQuery.from_('Comics').select('ID').orderby('ID', order=pypika.Order.desc)
        return SuspendSQLQuery(self.cursor, builder)

    def search_comic_by_tags(self, *tags) -> SuspendSQLQuery:
        # 创建查询语句
        builder = (pypika.SQLLiteQuery.from_('ComicTags')
                   .select('ComicID')
                   .where(pypika.Field('TagID').isin(tags))
                   .orderby('ComicID', order=pypika.Order.desc))
        return SuspendSQLQuery(self.cursor, builder)

    def search_comic_by_name(self, name, total_match=False):
        if not total_match:
            # 使用 LIKE 进行模糊搜索，% 表示任意数量的字符
            query = 'SELECT * FROM Comics WHERE Title LIKE ?'
            # 为查询的关键词添加 % 通配符，表示标题包含关键词
            self.cursor.execute(query, ('%' + name + '%',))
        else:
            query = 'SELECT * FROM Comics WHERE Title = ?'
            self.cursor.execute(query, (name,))
        results = self.cursor.fetchall()
        return results

    def search_comic_by_author(self, author) -> SuspendSQLQuery:
        builder = (pypika.SQLLiteQuery
                   .from_('Comics')
                   .select('ID')
                   .where(pypika.Field('Author') == author)
                   .orderby('ID', order=pypika.Order.desc))
        return SuspendSQLQuery(self.cursor, builder)

    def get_comic_info(self, comic_id):
        query = 'SELECT * FROM Comics WHERE ID = ?'
        self.cursor.execute(query, (comic_id,))
        comic_result = self.cursor.fetchone()
        query = 'SELECT Name FROM Tags t JOIN ComicTags ct ON t.ID = ct.TagID WHERE ct.ComicID = ?'
        self.cursor.execute(query, (comic_id,))
        tags = self.cursor.fetchall()
        if comic_result is None:
            comic_result = tuple()
        if tags is None:
            tags = tuple()
        return comic_result + (tuple(tag[0] for tag in tags),)

    def search_comic_by_file(self, filename):
        query = 'SELECT * FROM Comics WHERE FilePath = ?'
        self.cursor.execute(query, (filename,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        else:
            return None

    def get_tag_groups(self):
        # 查询所有标签组
        query = 'SELECT ID, GroupName FROM TagGroups'
        self.cursor.execute(query)
        results = self.cursor.fetchall()
        result_dict = {}
        for group_id, group_name in results:
            result_dict[group_name] = group_id
        return result_dict

    def get_tag_by_name(self, tag_name):
        query = 'SELECT * FROM Tags WHERE Name = ?'
        self.cursor.execute(query, (tag_name,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        return None

    def get_tag_by_hitomi(self, hitomi_name):
        query = 'SELECT * FROM Tags WHERE HitomiAlter = ?'
        self.cursor.execute(query, (hitomi_name,))
        results = self.cursor.fetchone()
        if results:
            return results[0]
        return None

    def get_tags_by_group(self, group_id):
        # 查询某个标签组内的所有标签
        query = '''
            SELECT ID, Name
            FROM Tags
            WHERE GroupID = ?
            '''
        # 执行查询
        self.cursor.execute(query, (group_id,))
        results = self.cursor.fetchall()
        result_dict = {}
        for tag_id, tag_name in results:
            result_dict[tag_name] = tag_id
        return result_dict

    def add_comic(self, title, filepath, author=None, series=None, volume=None, check_file=True) -> Optional[int]:
        # 校验输入合法性
        """
        retval:
        -1: No volume specified
        -2: Volume must be an integer
        -3: File does not exist
        """
        if series:
            if not volume:
                return -1
            if not volume.isdigit():
                return -2
        if (not os.path.exists(filepath)) and check_file:
            return -3
        filepath = os.path.basename(filepath)
        # 插入新漫画
        query = '''
            INSERT INTO Comics (Title, Author, FilePath, SeriesName, VolumeNumber)
            VALUES (?, ?, ?, ?, ?)
            '''
        self.cursor.execute(query, (title, author, filepath, series, volume))
        # 提交事务
        self.conn.commit()
        return self.cursor.lastrowid

    def edit_comic(self, comic_id,
                   title=None,
                   filepath=None,
                   author=None,
                   series=None,
                   volume=None,
                   sinicization=None,
                   cm_id=None) -> str:
        # 构建更新语句
        query = 'UPDATE Comics SET '
        parameters = []

        if title:
            query += 'Title = ?, '
            parameters.append(title)
        if author:
            query += 'Author = ?, '
            parameters.append(author)
        if filepath:
            if not os.path.exists(filepath):
                return 'File does not exist'
            query += 'FilePath = ?, '
            parameters.append(filepath)
        if series:
            query += 'SeriesName = ?, '
            parameters.append(series)
        if volume is not None:  # 允许卷号为 0
            if not volume.isdigit():
                return 'Volume must be an integer'
            query += 'VolumeNumber = ?, '
            parameters.append(volume)
        if sinicization:
            query += 'SinicizationGroup = ?, '
            parameters.append(sinicization)
        if cm_id:
            if not cm_id.isdigit():
                return 'Comic ID must be an integer'
            query += 'ComicMarket = ?, '
            parameters.append(cm_id)
        # 删除最后一个逗号并加上 WHERE 子句
        query = query.rstrip(', ') + ' WHERE ID = ?'
        parameters.append(comic_id)
        # 执行更新
        self.cursor.execute(query, parameters)
        # 提交事务
        self.conn.commit()
        return ''

    def delete_comic(self, comic_id: int) -> int:
        """
        retval
        -1: No Comics found
        """
        # 执行删除操作
        query = 'DELETE FROM Comics WHERE ID = ?'
        self.cursor.execute(query, (comic_id,))
        # 提交事务
        self.conn.commit()
        # 检查受影响的行数，确认是否成功删除
        if self.cursor.rowcount > 0:
            return 0
        return -1

    def add_tag_group(self, group_name) -> Optional[int]:
        insert_str = f'INSERT INTO TagGroups (GroupName) VALUES (?)'
        try:
            self.cursor.execute(insert_str, (group_name,))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return -1

    def delete_tag_group(self, group_id) -> int:
        delete_str = f'DELETE FROM TagGroups WHERE ID = ?'
        self.cursor.execute(delete_str, (group_id,))
        # 提交事务
        self.conn.commit()
        # 检查受影响的行数，确认是否成功删除
        if self.cursor.rowcount > 0:
            return 0
        return -1

    def add_tag(self, group_id: int, tag_name: str, hitomi_alter=None) -> Optional[int]:
        """
        retval:
        -1: Group ID not found
        -2: Tag has exists
        -3: Unknown Integrity Error
        """
        if not isinstance(group_id, int):
            return -1
        if group_id < 1:
            return -1
        try:
            # 插入新标签
            self.cursor.execute('INSERT INTO Tags (Name, GroupID, HitomiAlter) VALUES (?, ?, ?)',
                                (tag_name, group_id, hitomi_alter))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            self.cursor.execute('SELECT ID FROM TagGroups WHERE ID = ?', (group_id,))
            group = self.cursor.fetchone()
            if group is None:
                return -1
            self.cursor.execute('SELECT ID FROM Tags WHERE Name = ?', (tag_name,))
            if self.cursor.fetchone():
                return -2
            return -3

    def delete_tag(self, tag_id) -> int:
        delete_str = f'DELETE FROM Tags WHERE ID = ?'
        self.cursor.execute(delete_str, (tag_id,))
        self.conn.commit()
        if self.cursor.rowcount > 0:
            return 0
        return -1

    def get_range_comics(self, count=10, end: Optional[int] = None) -> list:
        query = 'SELECT ID FROM Comics ORDER BY ID DESC LIMIT ? OFFSET ?'
        if end:
            if count < 1:
                return []
            if end < count:
                return []
            self.cursor.execute(query, (end - count, count - 1))
        else:
            self.cursor.execute(query, (count, 0))
        comics = self.cursor.fetchall()
        return comics

    def link_tag_to_comic(self, comic_id, tag_id):
        """
        retval
        -1: Link has been Established
        -2: Tag not found
        -3: Comic not found
        -4: Unknown Integrity Error
        """
        try:
            # 插入漫画和标签的关联
            self.cursor.execute('INSERT INTO ComicTags (ComicID, TagID) VALUES (?, ?)', (comic_id, tag_id))
            self.conn.commit()
            return 0
        except sqlite3.IntegrityError:
            self.conn.rollback()
            # 检查漫画和标签关联是否已存在
            self.cursor.execute('SELECT * FROM ComicTags WHERE ComicID = ? AND TagID = ?', (comic_id, tag_id))
            if self.cursor.fetchone():
                return -1
            # 查找标签ID
            self.cursor.execute('SELECT ID FROM Tags WHERE ID = ?', (tag_id,))
            if not self.cursor.fetchone():
                return -2
            self.cursor.execute('SELECT ID FROM Comics WHERE ID = ?', (comic_id,))
            if not self.cursor.fetchone():
                return -3
            return -4

    def verify_file(self, base_path):
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

    def get_wandering_file(self, base_path):
        files = os.listdir(base_path)
        wandering_files = []
        for file in files:
            result = self.search_comic_by_file(file)
            if not result:
                wandering_files.append(file)
        return wandering_files


if __name__ == '__main__':
    with ComicDB() as db:
        print(db.get_wandering_file('archived_comics'))

