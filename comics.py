import pydantic
import sqlite3
import tags
from typing import Sequence
from sites import SourceSite
from handlers import SITE_HANDLERS

class ComicIDExistsError(Exception):
    """当尝试添加已存在的漫画ID时抛出此异常。"""
    def __init__(self, comic: 'Comic') -> None:
        self.comic = comic
        message = f"Comic with ID {comic} already exists."
        super().__init__(message)

class Comic(pydantic.BaseModel):
    id: int
    title: str
    authors: list[str]
    comic_tags: Sequence[tags.SpecificTagUnion]

    def get_generic_tags(self, manager: tags.TagManager) -> list[tags.GenericTag]:
        """
        获取漫画的通用标签列表。对于每个站点特定标签，调用其 generalize 方法将其转换为通用标签。
        Args:
            manager: 用于管理标签的 TagManager 实例。
        Returns:
            list[tags.GenericTag]: 漫画的通用标签列表。
        Raises:
            tags.NoGenericTagError: 如果某个站点特定标签没有对应的通用标签，则抛出此异常。
        """
        generic_tags = []
        for specific_tag in self.comic_tags:
            generic_tag = manager.generalize(specific_tag)
            generic_tags.append(generic_tag)
        return generic_tags
    

class ComicManager:
    def __init__(self, conn: sqlite3.Connection, tag_manager: tags.TagManager | None = None):
        if tag_manager is None:
            tag_manager = tags.TagManager(conn)
        self.conn = conn
        self.tag_manager = tag_manager

    def add_comic(self, comic: Comic):
        # Check if comic with same ID already exists
        cursor = self.conn.execute("SELECT id FROM comics WHERE id = ?", (comic.id,))
        if cursor.fetchone():
            raise ComicIDExistsError(comic)
        try:
            
            self.conn.execute("INSERT INTO comics (id, title, authors) VALUES (?, ?, ?)", (comic.id, comic.title, ",".join(comic.authors)))
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            self.conn.rollback()

    def get_missing_tags(self, comic: Comic) -> Sequence[tags.SpecificTagUnion]:
        missing_tags = []
        for specific_tag in comic.comic_tags:
            try:
                self.tag_manager.generalize(specific_tag)
            except tags.NoSpecificTagError:
                missing_tags.append(specific_tag)
        return missing_tags

    def create_comic(self, site: SourceSite, comic_id: int, source_meta: dict) -> Comic:
        """
        根据指定的站点和漫画ID创建一个新的Comic对象。
        Args:
            site (SourceSite): 漫画来源站点。
            comic_id (str): 漫画的唯一标识符。
            source_meta (dict): 包含漫画元数据的字典。
        Returns:
            Comic: 创建的Comic对象。
        Raises:
            ValueError: 如果提供的站点不受支持，则抛出此异常。
        """
        if site not in SITE_HANDLERS:
            raise ValueError(f"Unsupported site: {site}")
        handler = SITE_HANDLERS[site]()
        authors = handler.get_authors(source_meta)
        comic_tags = handler.extract_tags(source_meta)
        title = handler.get_title(source_meta)
        return Comic(id=comic_id, title=title, authors=authors, comic_tags=comic_tags)
        ...
