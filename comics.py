import pydantic
import sqlite3
import tags
from typing import Literal, Sequence
from sites import SourceSite
from handlers import SITE_HANDLERS


def _text_match_sql(column: str, match: Literal["exact", "prefix", "contains"]) -> str:
    # column 只由内部常量指定；搜索文本通过参数绑定，区分大小写且不解释通配符。
    if match == "exact":
        return f"{column} = ?"
    if match == "prefix":
        return f"instr({column}, ?) = 1"
    if match == "contains":
        return f"instr({column}, ?) > 0"
    raise ValueError(f"Unsupported text match: {match}")


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
    series_name: str | None = None
    volume_number: int | None = None
    updated_at: str | None = None

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

    def add_comic(self, comic: Comic, allow_override: bool = False) -> None:
        with self.conn:
            if allow_override:
                self.conn.execute("DELETE FROM comic_tags WHERE comic_id = ?", (comic.id,))
                self.conn.execute("DELETE FROM comic_authors WHERE comic_id = ?", (comic.id,))
                self.conn.execute("DELETE FROM comics WHERE id = ?", (comic.id,))
            try:
                self.conn.execute("INSERT INTO comics (id, title, series_name, volume_number) VALUES (?, ?, ?, ?)", (comic.id, comic.title, comic.series_name, comic.volume_number))
            except sqlite3.IntegrityError as error:
                # 由主键约束处理并发录入，避免先查后写的竞争。
                if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
                    raise ComicIDExistsError(comic) from error
                raise
            for author in dict.fromkeys(comic.authors):
                self.conn.execute("INSERT INTO comic_authors (comic_id, author_name) VALUES (?, ?)", (comic.id, author))
            linked_tag_ids = set()
            for specific_tag in comic.comic_tags:
                specific_tag_id = self.tag_manager.get_specific_tag_id(specific_tag)
                if specific_tag_id in linked_tag_ids:
                    continue
                self.conn.execute("INSERT INTO comic_tags (comic_id, specific_tag_id) VALUES (?, ?)", (comic.id, specific_tag_id))
                linked_tag_ids.add(specific_tag_id)

    def get_comic(self, comic_id: int) -> Comic | None:
        # 主记录和关联信息使用同一快照，也不提交调用者已有的事务。
        self.conn.execute("SAVEPOINT comic_get")
        try:
            row = self.conn.execute(
                "SELECT id, title, series_name, volume_number, updated_at FROM comics WHERE id = ?",
                (comic_id,),
            ).fetchone()
            return self._comic_from_row(row) if row is not None else None
        finally:
            self.conn.execute("RELEASE SAVEPOINT comic_get")

    def list_comics(self, *, limit: int = 50, offset: int = 0) -> tuple[list[Comic], int]:
        """按 ID 升序分页读取已入库漫画，返回原始模型和分页前总数。"""
        return self.query_comics(limit=limit, offset=offset)

    def query_comics(
        self, *, generic_tag_ids: Sequence[int] = (),
        tag_match: Literal["all", "any"] = "all",
        author_name: str | None = None,
        author_match: Literal["exact", "prefix", "contains"] = "exact",
        title: str | None = None,
        title_match: Literal["exact", "prefix", "contains"] = "contains",
        order: Literal["ASC", "DESC"] = "ASC",
        limit: int = 50, offset: int = 0,
    ) -> tuple[list[Comic], int]:
        """组合筛选本地漫画，按指定 ID 顺序返回原始模型和筛选后的分页前总数。"""
        if tag_match not in ("all", "any"):
            raise ValueError(f"Unsupported tag match: {tag_match}")
        if order not in ("ASC", "DESC"):
            raise ValueError(f"Unsupported comic order: {order}")
        conditions = []
        params: list[str | int] = []
        if title is not None:
            conditions.append(_text_match_sql("c.title", title_match))
            params.append(title)
        if author_name is not None:
            conditions.append(
                "EXISTS (SELECT 1 FROM comic_authors ca WHERE ca.comic_id = c.id AND "
                + _text_match_sql("ca.author_name", author_match) + ")"
            )
            params.append(author_name)

        tag_ids = list(dict.fromkeys(generic_tag_ids))
        if tag_ids:
            # EXISTS 避免同一本漫画的多个来源标签或作者造成重复行、重复计数。
            tag_query = (
                "SELECT 1 FROM comic_tags ct "
                "JOIN specific_tags st ON st.id = ct.specific_tag_id "
                "WHERE ct.comic_id = c.id AND "
            )
            if tag_match == "all":
                conditions.extend(f"EXISTS ({tag_query}st.generic_tag_id = ?)" for _ in tag_ids)
            else:
                placeholders = ", ".join("?" for _ in tag_ids)
                conditions.append(f"EXISTS ({tag_query}st.generic_tag_id IN ({placeholders}))")
            params.extend(tag_ids)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        # 总数、漫画字段及关联数据使用同一读取快照；也可嵌套于调用方的事务。
        self.conn.execute("SAVEPOINT comic_query")
        try:
            total = self.conn.execute(f"SELECT COUNT(*) FROM comics c{where}", params).fetchone()[0]
            rows = self.conn.execute(
                "SELECT c.id, c.title, c.series_name, c.volume_number, c.updated_at "
                f"FROM comics c{where} ORDER BY c.id {order} LIMIT ? OFFSET ?", [*params, limit, offset],
            ).fetchall()
            return [self._comic_from_row(row) for row in rows], total
        finally:
            self.conn.execute("RELEASE SAVEPOINT comic_query")

    def _comic_from_row(self, row: tuple) -> Comic:
        comic_id, title, series_name, volume_number, updated_at = row
        cursor = self.conn.execute("SELECT author_name FROM comic_authors WHERE comic_id = ?", (comic_id,))
        authors = [row[0] for row in cursor.fetchall()]
        cursor = self.conn.execute("SELECT specific_tag_id FROM comic_tags WHERE comic_id = ?", (comic_id,))
        specific_tag_ids = [row[0] for row in cursor.fetchall()]

        specific_tags = []
        for specific_tag_id in specific_tag_ids:
            specific_tag = self.tag_manager.get_specific_tag(specific_tag_id)
            if specific_tag is None:
                # 如果找不到站点特定标签，可能是因为标签已被删除或未正确添加到数据库中。
                # 这里可以选择记录日志或采取其他措施。
                raise ValueError(f"SpecificTag with id {specific_tag_id} not found in the database.")
            else:
                specific_tags.append(specific_tag)
        return Comic(id=comic_id, title=title, authors=authors, comic_tags=specific_tags, series_name=series_name, volume_number=volume_number, updated_at=updated_at)

    def get_missing_tags(self, comic: Comic) -> Sequence[tags.SpecificTagUnion]:
        missing_tags = []
        for specific_tag in comic.comic_tags:
            try:
                self.tag_manager.generalize(specific_tag)
            except tags.SpecificTagNotFoundError:
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
