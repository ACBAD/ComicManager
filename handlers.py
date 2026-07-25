from abc import ABC, abstractmethod
from tags import SpecificTagUnion, SpecificTagHitomi

class SiteHandler[TagType](ABC):
    @abstractmethod
    def extract_tags(self, source_meta: dict) -> list[TagType]:
        """
        从漫画的源元数据中提取站点特定标签。
        Args:
            source_meta : 包含漫画元数据的字典。
        Returns:
            list: 提取的站点特定标签列表。
        """
        ...

    @abstractmethod
    def get_authors(self, source_meta: dict) -> list[str]:
        """
        从漫画的源元数据中提取作者信息。
        Args:
            source_meta: 包含漫画元数据的字典。
        Returns:
            list: 提取的作者列表。
        """
        ...

    def get_title(self, source_meta: dict) -> str:
        """
        从漫画的源元数据中提取标题。
        Args:
            source_meta: 包含漫画元数据的字典。
        Returns:
            str: 提取的标题。
        """
        return source_meta.get("title", "Unknown Title")

class HitomiHandler(SiteHandler[SpecificTagHitomi]):
    def extract_tags(self, source_meta: dict) -> list[SpecificTagHitomi]:
        tag_metas: list[SpecificTagHitomi] = []
    
        # 提取parody标签
        if "parodys" in source_meta and source_meta["parodys"]:
            for parody in source_meta["parodys"]:
                tag_metas.append(
                    SpecificTagHitomi(
                        group="parodys",
                        origin_name=parody['parody'],
                        url=parody.get('url', None),
                    )
                )
        
        # 提取character标签
        if "characters" in source_meta and source_meta["characters"]:
            for character in source_meta["characters"]:
                tag_metas.append(
                    SpecificTagHitomi(
                        group="characters",
                        origin_name=character['character'],
                        url=character.get('url', None),
                    )
                )
    
        # 提取tag标签
        if "tags" in source_meta and source_meta["tags"]:
            for tag in source_meta["tags"]:
                tag_sex = None
                if tag.get('male', False):
                    tag_sex = 'male'
                elif tag.get('female', False):
                    tag_sex = 'female'
                tag_metas.append(
                    SpecificTagHitomi(
                        group="tags",
                        origin_name=tag['tag'],
                        tag_sex=tag_sex,
                        url=tag.get('url', None),
                    )
                )
    
        # 提取 groups 标签
        if "groups" in source_meta and source_meta["groups"]:
            for group in source_meta["groups"]:
                tag_metas.append(
                    SpecificTagHitomi(
                        group="groups",
                        origin_name=group['group'],
                        url=group.get('url', None),
                    )
                )
    
        return tag_metas

    def get_authors(self, source_meta: dict) -> list[str]:
        authors: list[str] = []
        if "artists" in source_meta and source_meta["artists"]:
            for artist in source_meta["artists"]:
                authors.append(artist['artist'])
        return authors

from sites import SourceSite

SITE_HANDLERS = {
    SourceSite.Hitomi: HitomiHandler,
    # 可以在这里添加其他站点的处理器
}