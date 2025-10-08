-- DDL for the new, optimized database file (e.g., 'new_database.sqlite')

-- ----------------------------
-- Table structure for Comics
-- ----------------------------
CREATE TABLE IF NOT EXISTS Comics(
    ID           INTEGER PRIMARY KEY AUTOINCREMENT,
    Title        TEXT    NOT NULL,
    FilePath     TEXT    NOT NULL UNIQUE,
    SeriesName   TEXT,
    VolumeNumber INTEGER
);

-- 为 Comics 表中经常用于检索的字段创建索引
CREATE INDEX IF NOT EXISTS idx_comics_title ON Comics (Title);
CREATE INDEX IF NOT EXISTS idx_comics_series ON Comics (SeriesName, VolumeNumber); -- 复合索引，便于按系列和卷号排序/查找

-- ----------------------------
-- Table structure for Authors
-- ----------------------------
CREATE TABLE IF NOT EXISTS Authors (
    ID   INTEGER PRIMARY KEY AUTOINCREMENT,
    Name TEXT    NOT NULL UNIQUE
);

-- ----------------------------
-- Table structure for ComicAuthors (Linking Table)
-- ----------------------------
CREATE TABLE IF NOT EXISTS ComicAuthors (
    ComicID  INTEGER NOT NULL,
    AuthorID INTEGER NOT NULL,
    PRIMARY KEY (ComicID, AuthorID),
    FOREIGN KEY (ComicID) REFERENCES Comics (ID) ON DELETE CASCADE,
    FOREIGN KEY (AuthorID) REFERENCES Authors (ID) ON DELETE CASCADE
);

-- 为连接表中的外键创建索引，以优化反向查询（例如：查询某作者的所有漫画）
CREATE INDEX IF NOT EXISTS idx_comicauthors_author_id ON ComicAuthors (AuthorID);

-- ----------------------------
-- Table structure for Sources
-- ----------------------------
CREATE TABLE IF NOT EXISTS Sources (
    ID      INTEGER PRIMARY KEY AUTOINCREMENT,
    Name    TEXT    NOT NULL UNIQUE,
    BaseUrl TEXT
);

-- ----------------------------
-- Table structure for ComicSources (Linking Table)
-- ----------------------------
CREATE TABLE IF NOT EXISTS ComicSources (
    ComicID       INTEGER NOT NULL,
    SourceID      INTEGER NOT NULL,
    SourceComicID TEXT    NOT NULL,
    PRIMARY KEY (ComicID, SourceID),
    FOREIGN KEY (ComicID) REFERENCES Comics (ID) ON DELETE CASCADE,
    FOREIGN KEY (SourceID) REFERENCES Sources (ID) ON DELETE CASCADE
);

-- 为 ComicSources 表中的 SourceID 创建索引
CREATE INDEX IF NOT EXISTS idx_comicsources_source_id ON ComicSources (SourceID);

-- ----------------------------
-- The rest of the tables (Tags, TagGroups, ComicTags)
-- with added indexes for foreign keys.
-- ----------------------------
CREATE TABLE IF NOT EXISTS TagGroups (
    ID        INTEGER PRIMARY KEY AUTOINCREMENT,
    GroupName TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS Tags (
    ID          INTEGER PRIMARY KEY AUTOINCREMENT,
    Name        TEXT    NOT NULL UNIQUE,
    GroupID     INTEGER,
    HitomiAlter TEXT,
    FOREIGN KEY (GroupID) REFERENCES TagGroups (ID)
);

CREATE TABLE IF NOT EXISTS ComicTags (
    ComicID INTEGER NOT NULL,
    TagID   INTEGER NOT NULL,
    PRIMARY KEY (ComicID, TagID),
    FOREIGN KEY (ComicID) REFERENCES Comics (ID) ON DELETE CASCADE,
    FOREIGN KEY (TagID) REFERENCES Tags (ID) ON DELETE CASCADE
);

-- 为 ComicTags 表中的 TagID 创建索引，以优化反向查询（例如：查询使用某标签的所有漫画）
CREATE INDEX IF NOT EXISTS idx_comictags_tag_id ON ComicTags (TagID);