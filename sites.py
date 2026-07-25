import enum


class SourceSite(str, enum.Enum):
    Hitomi = "hitomi"
    NHentai = "nhentai"
    JmComic = "jmcomic"