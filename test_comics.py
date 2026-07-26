import comics
import tags
import sqlite3
import json
from typing import Sequence

def test_add_hitomi_comic():
    with sqlite3.connect('comics.db') as conn, sqlite3.connect("document-archive.db") as source_conn:
        tag_manager = tags.TagManager(conn)
        comic_manager = comics.ComicManager(conn, tag_manager)
        cursor = source_conn.cursor()
        res = cursor.execute('SELECT id, source_meta FROM documents').fetchall()
        print(f"Found {len(res)} documents in source database.")
        for document_id, row in res:
            meta = json.loads(row if row else '{}')
            if not meta:
                print(f"Document {document_id}: source_meta is empty, skipping")
                continue
            comic = comic_manager.create_comic(comics.SourceSite.Hitomi, document_id, meta)
            # hitomi来的comic当然全是hitomi的标签了
            missing_tags: Sequence[tags.SpecificTagHitomi] = comic_manager.get_missing_tags(comic) # type: ignore
            for missing_tag in missing_tags:
                print(f"Document {document_id}: Missing tag {missing_tag.origin_name}")
                tag_group = missing_tag.inference_group()
                if tag_group:
                    print(f"Document {document_id}: Inferred {tag_group} for missing tag {missing_tag.origin_name}")
                else:
                    tag_group = tags.TagGroup(input("Enter tag group: "))
                # 组类型标签之前未曾录入过, 则直接创建通用标签并关联站点特定标签
                if tag_group == tags.TagGroup.Group:
                    generic_tag_name = missing_tag.origin_name
                    generic_tags = tag_manager.query_generic_tag(tag_group, generic_tag_name)
                    if generic_tags:
                        generic_tag = generic_tags[0]
                    else:
                        generic_tag = tag_manager.create_generic_tag(generic_tag_name, tag_group)
                    print(f"Document {document_id}: Created generic tag {generic_tag.name} for missing tag {missing_tag.origin_name}")
                    tag_manager.create_specific_tag(missing_tag, generic_tag)
                else:
                    # 由于所有数据都是基于hitomi的标签数据创建的, 因此hitomi的标签置信度比较高, 此处就直接使用hitomi的标签数据来创建通用标签, 而不需要用户手动输入
                    similar_specific_tags = tag_manager.query_similar_tag(missing_tag)
                    if not similar_specific_tags:
                        print(f"Document {document_id}: No similar specific tags found for missing tag {missing_tag.origin_name}")
                        generic_tag_name = input(f"Enter generic tag name for missing tag {missing_tag.origin_name}: ")
                        generic_tag = tag_manager.create_generic_tag(generic_tag_name, tag_group)
                    else:
                        if len(similar_specific_tags) > 1:
                            print(f"Document {document_id}: Found multiple similar specific tags for missing tag {missing_tag.origin_name}, select one")
                            for similar_specific_tag in similar_specific_tags:
                                print(f"Generic Tag: {tag_manager.generalize(similar_specific_tag)}")
                                print(f"  Hitomi Group: {similar_specific_tag.group}")
                                print(f"  Tag Sex: {similar_specific_tag.tag_sex}")
                                print(f"  URL: {similar_specific_tag.url}")
                            selected_index = int(input(f"Select similar specific tag index (0-{len(similar_specific_tags)-1}): "))
                            generic_tag = tag_manager.generalize(similar_specific_tags[selected_index])
                        else:
                            generic_tag = tag_manager.generalize(similar_specific_tags[0])
                    tag_manager.create_specific_tag(missing_tag, generic_tag)
            try:
                comic_manager.add_comic(comic)
            except comics.ComicIDExistsError:
                print(f"Comic {comic.id} already exists, skipping")

test_add_hitomi_comic()