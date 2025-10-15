import sqlite3
import os

# --- 配置 ---
OLD_DB_PATH = 'old_Comics.db'  # 你的旧数据库文件名
NEW_DB_PATH = 'Comics.db'  # 将要创建的新数据库文件名
SCHEMA_PATH = 'Comics_schema.sql'  # 包含上述优化版 Schema 的 SQL 文件名


def main():
    # 如果新数据库已存在，先删除，确保从零开始
    if os.path.exists(NEW_DB_PATH):
        os.remove(NEW_DB_PATH)

    # 连接数据库
    try:
        old_conn = sqlite3.connect(OLD_DB_PATH)
        old_cursor = old_conn.cursor()

        new_conn = sqlite3.connect(NEW_DB_PATH)
        new_cursor = new_conn.cursor()
    except sqlite3.Error as e:
        print(f"数据库连接失败: {e}")
        return

    print("数据库连接成功。")

    # 1. 在新数据库中创建表结构
    print("正在创建新的表结构...")
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        schema_sql = f.read()
        new_cursor.executescript(schema_sql)
    print("表结构创建完毕。")

    # 2. 迁移简单复制的表 (TagGroups, Tags)
    print("正在迁移 TagGroups 和 Tags...")
    migrate_simple_table(old_cursor, new_cursor, 'TagGroups', ['ID', 'GroupName'])
    migrate_simple_table(old_cursor, new_cursor, 'Tags', ['ID', 'Name', 'GroupID', 'HitomiAlter'])

    # 3. 迁移 Comics 表和作者数据
    print("正在迁移 Comics 和 Authors 数据...")
    old_cursor.execute("SELECT ID, Title, Author, FilePath, SeriesName, VolumeNumber FROM Comics")
    comics_data = old_cursor.fetchall()

    authors_map = {}  # 用于存储 '作者名' -> new_author_id 的映射，避免重复查询

    for comic in comics_data:
        comic_id, title, author_string, file_path, series_name, volume_number = comic

        # 插入优化后的 comic 数据 (不含 author)
        new_cursor.execute(
            "INSERT INTO Comics (ID, Title, FilePath, SeriesName, VolumeNumber) VALUES (?, ?, ?, ?, ?)",
            (comic_id, title, file_path, series_name, volume_number)
        )

        # 处理作者，支持逗号分隔的多个作者
        if author_string:
            author_list = [name.strip() for name in author_string.split(',') if name.strip()]

            for single_author_name in author_list:
                author_id = authors_map.get(single_author_name)

                if not author_id:
                    # 缓存中没有，查询数据库或插入新作者
                    # 使用 INSERT OR IGNORE 可以在作者已存在时静默失败，避免程序因UNIQUE约束而中断
                    new_cursor.execute("INSERT OR IGNORE INTO Authors (Name) VALUES (?)", (single_author_name,))
                    
                    # 无论刚才是否成功插入，作者现在肯定存在于数据库中，我们获取其ID
                    new_cursor.execute("SELECT ID FROM Authors WHERE Name = ?", (single_author_name,))
                    result = new_cursor.fetchone()
                    if result:
                        author_id = result[0]
                        authors_map[single_author_name] = author_id  # 更新缓存

                # 创建关联
                if author_id:
                    new_cursor.execute(
                        "INSERT INTO ComicAuthors (ComicID, AuthorID) VALUES (?, ?)",
                        (comic_id, author_id)
                    )

    print(f"迁移了 {len(comics_data)} 条漫画记录和 {len(authors_map)} 位独立作者。")

    # 4. 迁移 ComicTags 连接表
    print("正在迁移 ComicTags...")
    migrate_simple_table(old_cursor, new_cursor, 'ComicTags', ['ComicID', 'TagID'])

    # 提交事务并关闭连接
    print("迁移完成，正在保存...")
    new_conn.commit()
    old_conn.close()
    new_conn.close()
    print("所有操作成功完成！新的数据库文件已生成: ", NEW_DB_PATH)


def migrate_simple_table(old_cur, new_cur, table_name, columns):
    """一个用于迁移结构相同表的辅助函数"""
    cols_str = ', '.join(columns)
    placeholders = ', '.join(['?'] * len(columns))

    old_cur.execute(f"SELECT {cols_str} FROM {table_name}")
    data = old_cur.fetchall()

    if data:
        new_cur.executemany(f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})", data)
        print(f"成功迁移 {len(data)} 条记录到 {table_name} 表。")
    else:
        print(f"{table_name} 表中无数据可迁移。")


if __name__ == '__main__':
    main()
