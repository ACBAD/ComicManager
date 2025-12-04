-- DDL for the database file

-- ----------------------------
-- Table structure for documents
-- ----------------------------
CREATE TABLE IF NOT EXISTS documents(
    document_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL,
    file_path     TEXT    NOT NULL UNIQUE,
    series_name   TEXT,
    volume_number INTEGER
);

-- 为 documents 表中经常用于检索的字段创建索引
CREATE INDEX IF NOT EXISTS idx_documents_title ON documents (title);
CREATE INDEX IF NOT EXISTS idx_documents_series ON documents (series_name, volume_number); -- 复合索引，便于按系列和卷号排序/查找

-- ----------------------------
-- Table structure for authors
-- ----------------------------
CREATE TABLE IF NOT EXISTS authors (
    author_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

-- ----------------------------
-- Table structure for document_authors (Linking Table)
-- ----------------------------
CREATE TABLE IF NOT EXISTS document_authors (
    document_id  INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    PRIMARY KEY (document_id, author_id),
    FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES authors (author_id) ON DELETE CASCADE
);

-- 为连接表中的外键创建索引，以优化反向查询（例如：查询某作者的所有文献）
CREATE INDEX IF NOT EXISTS idx_document_author_id ON document_authors (author_id);

-- ----------------------------
-- Table structure for sources
-- ----------------------------
CREATE TABLE IF NOT EXISTS sources (
    source_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT    NOT NULL UNIQUE,
    base_url TEXT
);

-- ----------------------------
-- Table structure for document_sources (Linking Table)
-- ----------------------------
CREATE TABLE IF NOT EXISTS document_sources (
    document_id       INTEGER NOT NULL,
    source_id      INTEGER NOT NULL,
    source_document_id TEXT    NOT NULL,
    PRIMARY KEY (document_id, source_id),
    FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources (source_id) ON DELETE CASCADE
);

-- 为 document_sources 表中的 source_id 创建索引
CREATE INDEX IF NOT EXISTS idx_document_source_id ON document_sources (source_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_document_document_source_id ON document_sources (source_document_id);

-- ----------------------------
-- The rest of the tables (tags, tag_groups, document_tags)
-- with added indexes for foreign keys.
-- ----------------------------
CREATE TABLE IF NOT EXISTS tag_groups (
    tag_group_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tags (
    tag_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    group_id     INTEGER,
    hitomi_alter TEXT,
    FOREIGN KEY (group_id) REFERENCES tag_groups (tag_group_id)
);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id INTEGER NOT NULL,
    tag_id   INTEGER NOT NULL,
    PRIMARY KEY (document_id, tag_id),
    FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (tag_id) ON DELETE CASCADE
);

-- 为 document_tags 表中的 tag_id 创建索引，以优化反向查询（例如：查询使用某标签的所有文献）
CREATE INDEX IF NOT EXISTS idx_document_tags_tag_id ON document_tags (tag_id);