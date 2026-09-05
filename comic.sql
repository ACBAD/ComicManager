PRAGMA foreign_keys = ON;


-- ============================================================
-- Generic Tags
-- ============================================================

-- 对应 GenericTag
CREATE TABLE tags (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    tag_group   TEXT NOT NULL,

    UNIQUE (tag_group, name),

    CHECK (length(trim(name)) > 0),
    CHECK (length(trim(tag_group)) > 0)
);


-- ============================================================
-- Specific Tags
-- ============================================================

-- 对应 SpecificTagMetaUnion
--
-- 公共且用于查询、关联、唯一性判断的字段单独保存；
-- 不稳定的站点特有字段统一保存在 meta_json 中。
-- 只要还有 specific_tags 记录指向某个 GenericTag，
-- 该 GenericTag 就不能被删除。
CREATE TABLE specific_tags (
    id              INTEGER PRIMARY KEY,

    -- 指向且只能指向一个 GenericTag
    generic_tag_id  INTEGER NOT NULL,

    -- 稳定的类型判别字段，例如：
    -- hitomi.la
    -- nhentai.net
    site            TEXT NOT NULL,

    -- SpecificTag 公共字段
    origin_name     TEXT NOT NULL,

    -- 只保存站点特有字段，例如：
    -- {"url": "/character/xxx.html", "tag_sex": "female"}
    --
    -- 不应再次保存 site、origin_name，
    -- 避免同一数据出现两个互相冲突的来源。
    --
    -- origin_name 和 meta_json 作为一个整体参与唯一性判断，
    -- 因此 meta_json 必须 canonicalize。
    meta_json       TEXT NOT NULL,

    FOREIGN KEY (generic_tag_id)
        REFERENCES tags(id)
        ON DELETE RESTRICT,

    CHECK (length(trim(site)) > 0),
    CHECK (length(trim(origin_name)) > 0),

    CHECK (
        json_valid(meta_json)
        AND json_type(meta_json) = 'object'
    )
);


CREATE TABLE meta_schema_version (
    site        TEXT PRIMARY KEY,
    schema_hash TEXT NOT NULL,

    UNIQUE (site, schema_hash)
);


-- 一个来源站点中的一个标签只能映射到一个 GenericTag。
CREATE UNIQUE INDEX uq_specific_tags_identity
ON specific_tags (
    site,
    origin_name,
    meta_json
);


-- 查询某个 GenericTag 对应的全部 specific metas。
CREATE INDEX idx_specific_tags_tag_id
ON specific_tags (generic_tag_id);


-- ============================================================
-- Comics
-- ============================================================

CREATE TABLE IF NOT EXISTS comics (
    -- 直接映射 DMB 后端的 ID，方便后续数据同步和关联
    id              INTEGER PRIMARY KEY,

    title           TEXT NOT NULL,
    series_name     TEXT,
    volume_number   INTEGER,

    -- 业务 INSERT 不指定时由 SQLite 自动填充。
    --
    -- 使用 UTC ISO-8601 风格时间，并保留毫秒：
    -- 2026-09-05T13:04:23.417Z
    updated_at      TEXT NOT NULL DEFAULT (
        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    )
);


-- 为 comics 表中经常用于检索的字段创建索引
CREATE INDEX IF NOT EXISTS idx_comics_title
ON comics (title);

CREATE INDEX IF NOT EXISTS idx_comics_series
ON comics (series_name, volume_number);


-- ============================================================
-- Comic -> SpecificTag
-- ============================================================

-- comic_tags 表直接存储站点特定 tag。
--
-- 需要归一化 tag 时可以实时计算，
-- 这样还能保留所有原有的站点特定 tag 信息，
-- 方便后续分析和处理。
CREATE TABLE comic_tags (
    comic_id        INTEGER NOT NULL,
    specific_tag_id INTEGER NOT NULL,

    PRIMARY KEY (comic_id, specific_tag_id),

    FOREIGN KEY (comic_id)
        REFERENCES comics(id)
        ON DELETE CASCADE,

    FOREIGN KEY (specific_tag_id)
        REFERENCES specific_tags(id)
        ON DELETE CASCADE
);


-- ============================================================
-- Comic -> Authors
-- ============================================================

CREATE TABLE IF NOT EXISTS comic_authors (
    comic_id     INTEGER NOT NULL,
    author_name  TEXT NOT NULL,

    PRIMARY KEY (comic_id, author_name),

    FOREIGN KEY (comic_id)
        REFERENCES comics(id)
        ON DELETE CASCADE
);


-- 为连接表中的外键创建索引，
-- 以优化反向查询（例如查询某作者的所有文献）
CREATE INDEX IF NOT EXISTS idx_comic_author_name
ON comic_authors (author_name);


-- ============================================================
-- updated_at Triggers
-- ============================================================


-- ------------------------------------------------------------
-- 1. comics 自身业务字段发生实际变化时，
--    自动刷新 updated_at。
--
-- Trigger 只监听 title / series_name / volume_number，
-- 内部 UPDATE 只修改 updated_at，因此不会递归触发自己。
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comics_updated_at
AFTER UPDATE OF title, series_name, volume_number
ON comics
FOR EACH ROW
WHEN
       OLD.title         IS NOT NEW.title
    OR OLD.series_name   IS NOT NEW.series_name
    OR OLD.volume_number IS NOT NEW.volume_number
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = NEW.id;
END;


-- ------------------------------------------------------------
-- 2. comic_tags 新增关联：
--    对应 comic 发生逻辑变化，刷新 updated_at。
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_tags_insert
AFTER INSERT
ON comic_tags
FOR EACH ROW
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = NEW.comic_id;
END;


-- ------------------------------------------------------------
-- 3. comic_tags 删除关联：
--    对应 comic 发生逻辑变化，刷新 updated_at。
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_tags_delete
AFTER DELETE
ON comic_tags
FOR EACH ROW
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = OLD.comic_id;
END;


-- ------------------------------------------------------------
-- 4. comic_tags 更新：
--
--    如果只修改 specific_tag_id：
--      -> 刷新当前 comic
--
--    如果 comic_id 发生变化：
--      -> 旧 comic 和新 comic 都发生了逻辑变化
--      -> 两边都刷新
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_tags_update
AFTER UPDATE
ON comic_tags
FOR EACH ROW
BEGIN
    -- 原来的 comic 被修改
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = OLD.comic_id;

    -- 如果关联被移动到了另一个 comic，
    -- 新 comic 也需要刷新。
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = NEW.comic_id
      AND OLD.comic_id IS NOT NEW.comic_id;
END;


-- ------------------------------------------------------------
-- 5. comic_authors 新增作者：
--    对应 comic 发生逻辑变化。
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_authors_insert
AFTER INSERT
ON comic_authors
FOR EACH ROW
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = NEW.comic_id;
END;


-- ------------------------------------------------------------
-- 6. comic_authors 删除作者：
--    对应 comic 发生逻辑变化。
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_authors_delete
AFTER DELETE
ON comic_authors
FOR EACH ROW
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = OLD.comic_id;
END;


-- ------------------------------------------------------------
-- 7. comic_authors 更新：
--
--    author_name 修改时：
--      -> 当前 comic 刷新
--
--    comic_id 修改时：
--      -> 原 comic 与新 comic 都刷新
-- ------------------------------------------------------------

CREATE TRIGGER IF NOT EXISTS trg_comic_authors_update
AFTER UPDATE
ON comic_authors
FOR EACH ROW
BEGIN
    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = OLD.comic_id;

    UPDATE comics
    SET updated_at = strftime(
        '%Y-%m-%dT%H:%M:%fZ',
        'now'
    )
    WHERE id = NEW.comic_id
      AND OLD.comic_id IS NOT NEW.comic_id;
END;