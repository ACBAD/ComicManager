import io
import shutil
import sys
from pathlib import Path

import document_sql
import os
import sqlmodel
from typing import Optional, Union, List, Iterable, Sequence

try:
    from site_utils import getFileHash, archived_comic_path, getZipNamelist, getZipImage, thumbnail_folder


    def generate_thumbnail(document_id: int):
        with DocumentDB() as idb:
            doc = idb.get_document_by_id(document_id)
            if not doc:
                return
            filename = doc.file_path

        file_path = os.path.join(archived_comic_path, filename)
        pic_list = getZipNamelist(file_path)
        assert isinstance(pic_list, list)
        if not pic_list:
            return

        thumbnail_content = getZipImage(file_path, pic_list[0])
        if not os.path.exists(thumbnail_folder):
            os.makedirs(thumbnail_folder)

        with open(os.path.join(thumbnail_folder, f'{document_id}.webp'), "wb") as fu:
            fu.write(thumbnail_content.read())


    def check_thumbnails():
        if not os.path.exists(thumbnail_folder):
            os.makedirs(thumbnail_folder)
        with DocumentDB() as idb:
            # 获取所有 ID
            ids = idb.session.exec(sqlmodel.select(document_sql.Document.document_id)).all()

        for doc_id in ids:
            if os.path.exists(f'{thumbnail_folder}/{doc_id}.webp'):
                continue
            print(f'Document {doc_id} has no thumbnail')
            try:
                generate_thumbnail(int(doc_id))
            except Exception as e:
                print(f"Failed to generate thumbnail for {doc_id}: {e}")


    def get_document_content(document_id: int, pic_index: int) -> Optional[io.BytesIO]:
        with DocumentDB() as idb:
            doc = idb.get_document_by_id(document_id)
            if not doc:
                return None
            filename = doc.file_path

        file_path = os.path.join(archived_comic_path, filename)
        pic_list = getZipNamelist(file_path)
        assert isinstance(pic_list, list)
        if pic_index >= len(pic_list):
            return None
        return getZipImage(file_path, pic_list[pic_index])

except ImportError:
    print('非网站环境,哈希函数fallback至默认,comic路径,thumbnail目录,zip相关函数置空')
    import hashlib


    def getFileHash(file_path: Union[str, Path], chunk_size: int = 8192):
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as fi:
            while chunk := fi.read(chunk_size):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()


    archived_comic_path = Path(".")  # Fallback path
    thumbnail_folder = Path("thumbnails")
    getZipNamelist = None
    getZipImage = None


# ==========================================
# 核心数据库管理类
# ==========================================

class DocumentDB:
    def __init__(self, db_file_name: str = "documents.db"):
        sqlite_url = f"sqlite:///{db_file_name}"
        self.engine = sqlmodel.create_engine(sqlite_url)
        # 自动创建表结构（如果是新库）
        sqlmodel.SQLModel.metadata.create_all(self.engine)
        self.session = sqlmodel.Session(self.engine)
        # 启用外键约束
        self.session.connection().execute(sqlmodel.text("PRAGMA foreign_keys=ON"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()

    # --- 查询方法 ---

    def get_all_documents(self) -> Sequence[document_sql.Document]:
        return self.session.exec(
            sqlmodel.select(document_sql.Document).order_by(sqlmodel.desc(document_sql.Document.document_id))).all()

    def search_by_tags(self, tag_ids: List[int]):
        """返回包含指定所有标签的文档ID列表"""
        statement = (
            sqlmodel.select(document_sql.DocumentTagLink.document_id)
            .where(sqlmodel.col(document_sql.DocumentTagLink.tag_id).in_(tag_ids))
            .distinct()
        )
        return self.session.exec(statement).all()

    def search_by_name(self, name: str, exact_match: bool = False):
        statement = sqlmodel.select(document_sql.Document)
        if exact_match:
            statement = statement.where(document_sql.Document.title == name)
        else:
            statement = statement.where(sqlmodel.col(document_sql.Document.title).contains(name))
        return self.session.exec(statement).all()

    def search_by_author(self, author_name: str):
        statement = (
            sqlmodel.select(document_sql.Document.document_id)
            .join(document_sql.DocumentAuthorLink)
            .join(document_sql.Author)
            .where(document_sql.Author.name == author_name)
            .order_by(sqlmodel.desc(document_sql.Document.document_id))
        )
        return self.session.exec(statement).all()

    def search_by_source(self, source_document_id: str, source_id: int = None) -> Optional[int]:
        statement = sqlmodel.select(document_sql.DocumentSourceLink.document_id).where(
            document_sql.DocumentSourceLink.source_document_id == source_document_id
        )
        if source_id:
            statement = statement.where(document_sql.DocumentSourceLink.source_id == source_id)
        return self.session.exec(statement).first()

    def search_by_file(self, filename: Union[str, Path]) -> Optional[int]:
        fname = filename.name if isinstance(filename, Path) else filename
        statement = sqlmodel.select(document_sql.Document.document_id).where(document_sql.Document.file_path == fname)
        return self.session.exec(statement).first()

    def get_document_by_id(self, doc_id: int) -> Optional[document_sql.Document]:
        return self.session.get(document_sql.Document, doc_id)

    def get_document_info_tuple(self, doc_id: int) -> Optional[document_sql.Document]:
        """为了兼容旧代码逻辑，返回 tuple 格式: (ID, Title, FilePath, Series, Volume, AuthorsStr, TagsTuple)"""
        doc = self.get_document_by_id(doc_id)
        if not doc:
            return None
        return doc

    def get_range_documents(self, count=10, end: Optional[int] = None):
        statement = sqlmodel.select(document_sql.Document).order_by(
            sqlmodel.desc(document_sql.Document.document_id)).limit(count)
        if end is not None:
            offset_val = max(0, end - count)
            statement = statement.offset(offset_val)
        return self.session.exec(statement).all()

    # --- 标签与元数据管理 ---

    def get_tag_groups(self) -> dict:
        groups = self.session.exec(sqlmodel.select(document_sql.TagGroup)).all()
        return {g.group_name: g.tag_group_id for g in groups}

    def get_tag_by_name(self, name: str) -> Optional[document_sql.Tag]:
        return self.session.exec(sqlmodel.select(document_sql.Tag).where(document_sql.Tag.name == name)).first()

    def get_tags_by_group(self, group_id: int) -> dict:
        tags = self.session.exec(sqlmodel.select(document_sql.Tag).where(document_sql.Tag.group_id == group_id)).all()
        return {t.name: t.tag_id for t in tags}

    # --- 写入与修改方法 ---

    def add_source(self, name: str, base_url: Optional[str] = None) -> Optional[int]:
        try:
            source = document_sql.Source(name=name, base_url=base_url)
            self.session.add(source)
            self.session.commit()
            self.session.refresh(source)
            return source.source_id
        except Exception as ie:
            print(ie)
            self.session.rollback()
            return None

    def add_document(self, title: str, filepath: Union[str, Path],
                     authors: Optional[Iterable[str]] = None,
                     series: Optional[str] = None,
                     volume: Optional[int] = None,
                     source: Optional[dict] = None,  # {'source_id': int, 'source_comic_id': str}
                     given_id: int = None,
                     check_file=True) -> int:

        # 验证
        if series and not volume:
            return -1
        if volume and not str(volume).isdigit():
            return -2

        filepath_str = os.path.basename(filepath)
        if check_file and not os.path.exists(filepath):
            return -3

        try:
            doc = document_sql.Document(
                document_id=given_id,
                title=title,
                file_path=filepath_str,
                series_name=series,
                volume_number=volume
            )
            self.session.add(doc)
            self.session.commit()
            self.session.refresh(doc)  # 获取生成的 ID

            # 处理作者
            if authors:
                for author_name in authors:
                    # 查找或创建作者
                    auth = self.session.exec(
                        sqlmodel.select(document_sql.Author).where(document_sql.Author.name == author_name)).first()
                    if not auth:
                        auth = document_sql.Author(name=author_name)
                        self.session.add(auth)
                        self.session.commit()
                        self.session.refresh(auth)

                    # 建立关联
                    link = document_sql.DocumentAuthorLink(document_id=doc.document_id, author_id=auth.author_id)
                    self.session.add(link)

            # 处理来源
            if source:
                self.link_document_source(doc.document_id, source['source_id'], source['source_comic_id'])

            self.session.commit()
            return doc.document_id

        except Exception as e:
            print(f"Error adding document: {e}")
            self.session.rollback()
            return -4

    def edit_document(self, doc_id: int,
                      title: Optional[str] = None,
                      filepath: Optional[Union[str, Path]] = None,
                      authors: Optional[List[str]] = None,
                      series: Optional[str] = None,
                      volume: Optional[int] = None,
                      verify_file: bool = True) -> int:

        doc = self.session.get(document_sql.Document, doc_id)
        if not doc:
            return -1

        if title is not None:
            doc.title = title
        if series is not None:
            doc.series_name = series
        if volume is not None:
            doc.volume_number = volume
        if filepath is not None:
            if verify_file and not os.path.exists(filepath):
                return -1
            doc.file_path = os.path.basename(filepath)

        # 更新作者 (全量替换逻辑)
        if authors is not None:
            # 清除旧关联
            existing_links = self.session.exec(
                sqlmodel.select(document_sql.DocumentAuthorLink).where(
                    document_sql.DocumentAuthorLink.document_id == doc_id)
            ).all()
            for link in existing_links:
                self.session.delete(link)

            # 添加新关联
            for author_name in authors:
                auth = self.session.exec(
                    sqlmodel.select(document_sql.Author).where(document_sql.Author.name == author_name)).first()
                if not auth:
                    auth = document_sql.Author(name=author_name)
                    self.session.add(auth)
                    self.session.commit()
                    self.session.refresh(auth)

                new_link = document_sql.DocumentAuthorLink(document_id=doc_id, author_id=auth.author_id)
                self.session.add(new_link)

        try:
            self.session.add(doc)
            self.session.commit()
            return 0
        except Exception as e:
            self.session.rollback()
            print(e)
            return -5

    def delete_document(self, doc_id: int) -> int:
        doc = self.session.get(document_sql.Document, doc_id)
        if doc:
            self.session.delete(doc)
            self.session.commit()
            return 0
        return -1

    def link_document_source(self, doc_id: int, source_id: int, source_document_id: str) -> bool:
        try:
            link = document_sql.DocumentSourceLink(document_id=doc_id, source_id=source_id,
                                                   source_document_id=source_document_id)
            self.session.add(link)
            self.session.commit()
            return True
        except Exception as ie:
            print(ie)
            self.session.rollback()
            return False

    def get_wandering_files(self, base_path: Union[str, Path]) -> set[Path]:
        base_path = Path(base_path)
        if not base_path.exists():
            return set()

        test_files = [fi for fi in base_path.iterdir() if fi.is_file()]
        wandering_files = set()

        # 批量获取数据库中所有文件名以优化性能
        db_files = set(self.session.exec(sqlmodel.select(document_sql.Document.file_path)).all())

        for fi in test_files:
            if fi.name not in db_files:
                wandering_files.add(fi)
        return wandering_files


# ==========================================
# 独立的维护逻辑 (CLI Operations)
# ==========================================

def fix_file_hash(idb: DocumentDB, base_path: Union[str, Path]):
    base_path = Path(base_path)
    test_files = [file for file in base_path.iterdir() if file.is_file()]

    for test_file in test_files:
        file_hash = getFileHash(test_file)
        name_hash = test_file.stem  # 假设文件名就是 hash.ext

        if file_hash == name_hash:
            continue

        print(f'文件 {test_file.name} 实际哈希 {file_hash} 不匹配')

        new_filename = f"{file_hash}{test_file.suffix}"
        new_file_path = base_path / new_filename

        if new_file_path.exists():
            print(f'哈希冲突：目标文件 {new_filename} 已存在，跳过')
            continue

        # 查找旧文件在数据库中的记录
        doc_id = idb.search_by_file(test_file)
        if not doc_id:
            print(f'文件 {test_file.name} 未在数据库记录，跳过')
            continue

        shutil.move(test_file, new_file_path)
        print(f'Moved: {test_file.name} -> {new_filename}')

        res = idb.edit_document(doc_id, filepath=new_file_path)
        if res == 0:
            print(f'数据库已更新为 {new_filename}')
        else:
            print(f'数据库更新失败 Code: {res}')


def update_hitomi_file_hash(hitomi_id_list: list[int], idb: DocumentDB):
    try:
        import hitomiv2
    except ImportError:
        print('请先安装 hitomiv2 模块')
        hitomiv2 = None
        sys.exit(4)

    hitomi = hitomiv2.Hitomi(proxy_settings={
        'http': os.environ.get('HTTP_PROXY', None),
        'https': os.environ.get('HTTPS_PROXY', None)
    })

    for ihid in hitomi_id_list:
        # 查找数据库中关联了该 source_id 的文档
        # 假设 hitomi 的 source_id 在数据库中是已知的，这里简化处理，只按 source_document_id 查
        doc_id = idb.search_by_source(str(ihid))
        if not doc_id:
            print(f'Hitomi ID {ihid} 未在数据库中找到')
            continue

        print(f'Downloading {ihid}...')
        try:
            comic = hitomi.get_comic(ihid)
            dl_path = comic.download(max_threads=5)  # 假设返回文件路径字符串
            if not dl_path:
                raise RuntimeError("Download failed")

            dl_path = Path(dl_path)
            file_hash = getFileHash(dl_path)
            new_name = f"{file_hash}.zip"
            target_path = archived_comic_path / new_name

            # 检查此哈希是否已存在于其他文档
            exist_doc = idb.search_by_file(new_name)
            if exist_doc:
                print(f'Hash {new_name} 已经存在于 ID {exist_doc}')
                os.remove(dl_path)
                continue

            shutil.move(dl_path, target_path)
            idb.edit_document(doc_id, filepath=target_path)
            print(f'Updated {ihid} -> {new_name}')

        except Exception as e:
            print(f'Error processing {ihid}: {e}')


if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print('Usage: python Document_DB.py [clean|fix_hash|hitomi_update|test] [args...]')
        sys.exit(1)

    cmd = sys.argv[1]

    with DocumentDB() as db:
        if cmd == 'clean':
            if not archived_comic_path:
                print("Archived path not set")
                sys.exit(1)
            wandering = db.get_wandering_files(archived_comic_path)
            print(f"Found {len(wandering)} unlinked files.")
            if input("Delete them? (y/n): ") == 'y':
                for f in wandering:
                    os.remove(f)
                    print(f"Deleted {f.name}")

        elif cmd == 'fix_hash':
            if not archived_comic_path:
                print("Archived path not set")
                sys.exit(1)
            fix_file_hash(db, archived_comic_path)

        elif cmd == 'hitomi_update':
            try:
                hid = int(sys.argv[2])
                update_hitomi_file_hash([hid], db)
            except (IndexError, ValueError):
                print("Invalid Hitomi ID")

        elif cmd == 'test':
            # 简单的测试逻辑
            cnt = len(db.get_all_documents())
            print(f"Database connected. Total documents: {cnt}")
