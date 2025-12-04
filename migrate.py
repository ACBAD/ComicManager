import sqlite3
import os
import sys

# 配置路径
OLD_DB_PATH = "Comics.db"  # 这里填入你旧数据库的文件名
NEW_DB_PATH = "documents.db"  # 这里填入你想生成的新数据库文件名

# 新 Schema 定义 (确保新库结构存在)
with open('document_schema.sql', 'r', encoding='utf-8') as sql_f:
    NEW_SCHEMA_SQL = sql_f.read()


def migrate_data():
    if not os.path.exists(OLD_DB_PATH):
        print(f"[Error] 旧数据库文件不存在: {OLD_DB_PATH}")
        sys.exit(1)

    # 连接到新数据库（如果不存在则自动创建）
    conn = sqlite3.connect(NEW_DB_PATH)
    cursor = conn.cursor()

    # 1. 性能优化：关闭写同步，开启内存模式临时存储，极大提升插入速度
    cursor.execute("PRAGMA synchronous = OFF;")
    cursor.execute("PRAGMA journal_mode = MEMORY;")

    try:
        # 2. 挂载旧数据库
        print(f"[*] 正在挂载旧数据库: {OLD_DB_PATH}...")
        # 注意：ATTACH 语句中文件名如果包含特殊字符可能需要转义，这里假设文件名标准
        cursor.execute(f"ATTACH DATABASE '{OLD_DB_PATH}' AS old_db;")

        print("[*] 开始迁移数据...")

        # ==========================================
        # 实体表迁移 (Entities)
        # ==========================================

        # 3.1 迁移 Documents (Comics -> documents)
        print("  -> Migrating: Comics -> documents")
        cursor.execute("""
                       INSERT INTO documents (document_id, title, file_path, series_name, volume_number)
                       SELECT ID, Title, FilePath, SeriesName, VolumeNumber
                       FROM old_db.Comics;
                       """)

        # 3.2 迁移 Authors (Authors -> authors)
        print("  -> Migrating: Authors -> authors")
        cursor.execute("""
                       INSERT INTO authors (author_id, name)
                       SELECT ID, Name
                       FROM old_db.Authors;
                       """)

        # 3.3 迁移 Sources (Sources -> sources)
        print("  -> Migrating: Sources -> sources")
        cursor.execute("""
                       INSERT INTO sources (source_id, name, base_url)
                       SELECT ID, Name, BaseUrl
                       FROM old_db.Sources;
                       """)

        # 3.4 迁移 TagGroups (TagGroups -> tag_groups)
        print("  -> Migrating: TagGroups -> tag_groups")
        cursor.execute("""
                       INSERT INTO tag_groups (tag_group_id, group_name)
                       SELECT ID, GroupName
                       FROM old_db.TagGroups;
                       """)

        # 3.5 迁移 Tags (Tags -> tags)
        print("  -> Migrating: Tags -> tags")
        cursor.execute("""
                       INSERT INTO tags (tag_id, name, group_id, hitomi_alter)
                       SELECT ID, Name, GroupID, HitomiAlter
                       FROM old_db.Tags;
                       """)

        # ==========================================
        # 关联表迁移 (Link Tables)
        # ==========================================

        # 3.6 迁移 DocumentAuthors (ComicAuthors -> document_authors)
        print("  -> Migrating: ComicAuthors -> document_authors")
        cursor.execute("""
                       INSERT INTO document_authors (document_id, author_id)
                       SELECT ComicID, AuthorID
                       FROM old_db.ComicAuthors;
                       """)

        # 3.7 迁移 DocumentTags (ComicTags -> document_tags)
        print("  -> Migrating: ComicTags -> document_tags")
        cursor.execute("""
                       INSERT INTO document_tags (document_id, tag_id)
                       SELECT ComicID, TagID
                       FROM old_db.ComicTags;
                       """)

        # 3.8 迁移 DocumentSources (ComicSources -> document_sources)
        # 注意字段映射: SourceComicID -> source_document_id
        print("  -> Migrating: ComicSources -> document_sources")
        cursor.execute("""
                       INSERT INTO document_sources (document_id, source_id, source_document_id)
                       SELECT ComicID, SourceID, SourceComicID
                       FROM old_db.ComicSources;
                       """)

        conn.commit()
        print(f"[Success] 迁移完成。数据已写入 {NEW_DB_PATH}")

        # 简单验证
        print("\n[Audit] 数据行数核对:")
        tables = [
            ("Comics", "documents"),
            ("Authors", "authors"),
            ("Tags", "tags"),
            ("ComicTags", "document_tags")
        ]

        for old_tbl, new_tbl in tables:
            old_count = cursor.execute(f"SELECT COUNT(*) FROM old_db.{old_tbl}").fetchone()[0]
            new_count = cursor.execute(f"SELECT COUNT(*) FROM {new_tbl}").fetchone()[0]
            status = "OK" if old_count == new_count else "MISMATCH"
            print(f"  - {old_tbl.ljust(12)} -> {new_tbl.ljust(15)}: {old_count} vs {new_count} [{status}]")

    except sqlite3.IntegrityError as e:
        print(f"\n[Error] 完整性约束错误 (可能是ID冲突或唯一性校验失败): \n{e}")
        conn.rollback()
    except Exception as e:
        print(f"\n[Error] 发生未知错误: \n{e}")
        conn.rollback()
    finally:
        # 解除挂载并关闭
        try:
            cursor.execute("DETACH DATABASE old_db;")
        except Exception as e:
            print(e)
        conn.close()


if __name__ == "__main__":
    # 在运行前，请确保新数据库已经创建了表结构（运行第一个Prompt中的SQL）
    # 如果新库是空的，取消下面这行的注释来初始化表结构
    # init_new_db_structure()

    migrate_data()
