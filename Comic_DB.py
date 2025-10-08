import os.path
import sqlite3
from typing import Optional, List
import pypika


class SuspendSQLQuery:
    def __init__(self, cursor: sqlite3.Cursor, builder: pypika.dialects.SQLLiteQueryBuilder):  # type: ignore
        self.cursor = cursor
        self.builder = builder

    def submit(self):
        self.cursor.execute(self.builder.get_sql())
        return self.cursor.fetchall()


class ComicDB:
    def __init__(self, db_file_name: str = 'new_Comics.db'):  # Changed default to new_Comics.db
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

    def getAllComics(self) -> SuspendSQLQuery:
        builder = pypika.SQLLiteQuery.from_('Comics').select('ID').orderby('ID', order=pypika.Order.desc)
        return SuspendSQLQuery(self.cursor, builder)

    def searchComicByTags(self, *tags) -> SuspendSQLQuery:
        builder = (pypika.SQLLiteQuery.from_('ComicTags')
                   .select('ComicID')
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

    def getComicInfo(self, comic_id: int) -> tuple:
        # Fetch comic details
        query = 'SELECT ID, Title, FilePath, SeriesName, VolumeNumber FROM Comics WHERE ID = ?'
        self.cursor.execute(query, (comic_id,))
        comic_result = self.cursor.fetchone()
        if comic_result is None:
            return ()

        # Fetch authors
        author_query = '''
            SELECT a.Name FROM Authors a
            JOIN ComicAuthors ca ON a.ID = ca.AuthorID
            WHERE ca.ComicID = ?
        '''
        self.cursor.execute(author_query, (comic_id,))
        authors = self.cursor.fetchall()
        author_string = ', '.join([author[0] for author in authors])

        # Fetch tags
        tags_query = 'SELECT Name FROM Tags t JOIN ComicTags ct ON t.ID = ct.TagID WHERE ct.ComicID = ?'
        self.cursor.execute(tags_query, (comic_id,))
        tags = self.cursor.fetchall()
        tags_tuple = tuple(tag[0] for tag in tags)

        # Combine results: (ID, Title, FilePath, SeriesName, VolumeNumber, Authors, Tags)
        return comic_result + (author_string, tags_tuple)

    def searchComicByFile(self, filename):
        query = 'SELECT * FROM Comics WHERE FilePath = ?'
        self.cursor.execute(query, (filename,))
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

    def add_source(self, name: str, base_url: Optional[str] = None) -> Optional[int]:
        try:
            self.cursor.execute("INSERT INTO Sources (Name, BaseUrl) VALUES (?, ?)", (name, base_url))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None

    def link_comic_to_source(self, comic_id: int, source_id: int, source_comic_id: str) -> bool:
        try:
            self.cursor.execute("INSERT INTO ComicSources (ComicID, SourceID, SourceComicID) VALUES (?, ?, ?)",
                                (comic_id, source_id, source_comic_id))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def addComic(self, title, filepath,
                 authors: Optional[List[str]] = None,
                 series: Optional[str] = None,
                 volume: Optional[int] = None,
                 source: Optional[dict] = None,  # {'source_id': int, 'source_comic_id': str}
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
            # Insert comic
            query = 'INSERT INTO Comics (Title, FilePath, SeriesName, VolumeNumber) VALUES (?, ?, ?, ?)'
            self.cursor.execute(query, (title, filepath, series, volume))
            comic_id = self.cursor.lastrowid

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
                self.link_comic_to_source(comic_id, source['source_id'], source['source_comic_id'])

            self.conn.commit()
            return comic_id
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return None  # Or a specific error code for duplicate file path

    def editComic(self, comic_id,
                  title: Optional[str] = None,
                  filepath: Optional[str] = None,
                  authors: Optional[List[str]] = None,
                  series: Optional[str] = None,
                  volume: Optional[int] = None) -> str:
        # Update basic comic info
        update_fields = []
        parameters = []
        if title is not None:
            update_fields.append('Title = ?')
            parameters.append(title)
        if filepath is not None:
            if not os.path.exists(filepath):
                return 'File does not exist'
            update_fields.append('FilePath = ?')
            parameters.append(os.path.basename(filepath))
        if series is not None:
            update_fields.append('SeriesName = ?')
            parameters.append(series)
        if volume is not None:
            if not str(volume).isdigit():
                return 'Volume must be an integer'
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
        return ''

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

    def addTag(self, group_id: int, tag_name: str, hitomi_alter=None) -> Optional[int]:
        if not isinstance(group_id, int) or group_id < 1:
            return -1
        try:
            self.cursor.execute('INSERT INTO Tags (Name, GroupID, HitomiAlter) VALUES (?, ?, ?)',
                                (tag_name, group_id, hitomi_alter))
            self.conn.commit()
            return self.cursor.lastrowid
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

    def getWanderingFile(self, base_path):
        files = os.listdir(base_path)
        wandering_files = set()
        for file in files:
            result = self.searchComicByFile(file)
            if not result:
                wandering_files.add(file)
        return wandering_files


if __name__ == '__main__':
    with ComicDB() as db:
        print(db.getComicInfo(1000))
