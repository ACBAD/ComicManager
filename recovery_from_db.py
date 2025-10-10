import os
from Comic_DB import ComicDB
from hitomiv2 import Hitomi


def recover_comics(idb: ComicDB, base_path: str):
    """
    Recovers comics from Hitomi if they are not present locally.
    """
    print("Starting comic recovery process...")

    # Get all comics with their source information
    all_comics_query = idb.getAllComics()
    all_comics = all_comics_query.submit()

    hitomi = Hitomi()

    for comic_row in all_comics:
        comic_id = comic_row[0]
        comic_info = idb.getComicInfo(comic_id)
        
        if not comic_info:
            print(f"Could not retrieve info for comic ID: {comic_id}")
            continue

        file_path = comic_info[2]
        local_path = os.path.join(base_path, file_path)

        if not os.path.exists(local_path):
            print(f"Comic file not found locally: {file_path}")

            # Get the source ID for the comic
            source_query = "SELECT SourceComicID FROM ComicSources WHERE ComicID = ?"
            idb.cursor.execute(source_query, (comic_id,))
            source_result = idb.cursor.fetchone()

            if source_result:
                source_comic_id = source_result[0]
                print(f"Found source ID: {source_comic_id}. Attempting to download from Hitomi.")

                try:
                    comic = hitomi.get_comic(source_comic_id)
                    download_path = comic.download(max_threads=5)
                    
                    if download_path:
                        # Rename and move the downloaded file
                        os.rename(download_path, local_path)
                        print(f"Successfully downloaded and recovered: {file_path}")
                    else:
                        print(f"Failed to download comic with source ID: {source_comic_id}")

                except Exception as e:
                    print(f"An error occurred while downloading comic with source ID {source_comic_id}: {e}")
            else:
                print(f"No source ID found for comic ID: {comic_id}. Cannot recover.")

    print("Comic recovery process finished.")

if __name__ == '__main__':
    # It's recommended to use a configuration file for the base path
    # For now, we'll use a hardcoded path for demonstration
    ARCHIVED_COMIC_PATH = "D:/path/to/your/comics" 

    with ComicDB() as db:
        recover_comics(db, ARCHIVED_COMIC_PATH)
