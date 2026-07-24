# Copyright (C) 2026 Ethan Martin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import logging
import re
import unicodedata
import uuid
from pathlib import Path
from sqlite3 import OperationalError

import mutagen
from mutagen.id3 import ID3
from sqlalchemy import text
from sqlalchemy.engine import Connection

import cleaning
import metadata
from config import config, core
from db import engine, get_conn, init_db

logger = logging.getLogger(__name__)


def get_first_tag_value(tags: dict | None, keys: list[str] | str) -> str | None:
    if tags is None:
        return None
    if isinstance(keys, str):
        keys = [keys]
    for key in keys:
        if key not in tags:
            continue
        value = tags[key]
        try:
            if isinstance(value, (list, tuple)):
                if not value:
                    continue
                text = str(value[0]).strip()
            else:
                text = str(value).strip()
            if text:
                try:
                    repaired = text.encode("latin-1").decode("utf-8")
                    if repaired != text:
                        text = repaired
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                return text
        except (IndexError, TypeError, ValueError):
            continue
    return None


def get_collections(only_include_enabled_collections=True) -> dict:
    collections_in_config = config["collections"]
    processed_collections = {}
    for collection_id in collections_in_config.keys():
        if (
            only_include_enabled_collections
            and not collections_in_config[collection_id]["enabled"]
        ):
            continue
        processed_collections[collection_id] = collections_in_config[
            collection_id
        ].copy()
        processed_collections[collection_id]["id"] = collection_id
        for path in processed_collections[collection_id]["paths"]:
            collection_path = Path(path).expanduser()
            collection_path.mkdir(parents=True, exist_ok=True)
    return processed_collections


def add_album(
    artist_musicbrainz_id: str,
    artist_id: str,
    album_name: str,
    collection: dict,
    conn: Connection,
    folder_name: str | None = None,
) -> tuple:
    result = conn.execute(
        text(
            "select album_id, musicbrainz_id from albums "
            "where name = :name and collection_id = :collection_id "
            "and (folder_name = :folder_name or (folder_name is null and :folder_name is null))"
        ),
        {
            "name": album_name,
            "collection_id": collection["id"],
            "folder_name": folder_name,
        },
    )
    existing_album = result.mappings().first()
    if existing_album:
        # If the existing album looks like a single (only one song and the
        # album name equals the song name), prefer creating a distinct album
        # for a later full release. This avoids the case where a track that is
        # both a single and also part of a larger album ends up attached only
        # to the single record, leaving the album incomplete.
        try:
            is_single_like = (
                (existing_album.get("song_count") or 0) == 1
                and existing_album.get("name", "").strip().lower()
                == album_name.strip().lower()
                and (
                    existing_album.get("folder_name") is None
                    or existing_album.get("folder_name") == ""
                )
            )
        except Exception:
            is_single_like = False

        if not is_single_like:
            conn.execute(
                text(
                    "update albums set song_count = song_count + 1 where album_id = :album_id"
                ),
                {"album_id": existing_album["album_id"]},
            )
            aid = existing_album["album_id"]
            mb = existing_album["musicbrainz_id"]
            if mb and aid not in _processed_placeholder_albums:
                _processed_placeholder_albums.add(aid)
                add_placeholder_tracks_for_album(aid, conn)
            return aid, mb
    conn.execute(
        text(
            "update artists set album_count = album_count + 1 where artist_id = :artist_id"
        ),
        {"artist_id": artist_id},
    )
    try:
        repaired = album_name.encode("latin-1").decode("utf-8")
        if repaired and repaired != album_name:
            album_name = repaired
    except Exception:
        pass

    base_slug = slugify_name(album_name)
    album_id = base_slug
    existing = (
        conn.execute(
            text("select album_id from albums where album_id = :aid"),
            {"aid": album_id},
        )
        .mappings()
        .first()
    )
    if existing:
        counter = 1
        while True:
            candidate = f"{base_slug}-{counter}"
            existing = (
                conn.execute(
                    text("select album_id from albums where album_id = :aid"),
                    {"aid": candidate},
                )
                .mappings()
                .first()
            )
            if not existing:
                album_id = candidate
                break
            counter += 1
    musicbrainz_data = None
    if album_name != "Unknown Album" and artist_musicbrainz_id:
        musicbrainz_data = metadata.album_to_musicbrainz_data(
            artist_musicbrainz_id, album_name, conn
        )
    musicbrainz_id = musicbrainz_data.get("id") if musicbrainz_data else None
    musicbrainz_date = musicbrainz_data.get("date") if musicbrainz_data else None
    conn.execute(
        text(
            "insert into albums (album_id, artist_id, name, collection_id, musicbrainz_id, song_count, release_date, folder_name) values (:album_id, :artist_id, :name, :collection_id, :musicbrainz_id, :song_count, :release_date, :folder_name)"
        ),
        {
            "album_id": album_id,
            "artist_id": artist_id,
            "name": album_name,
            "collection_id": collection["id"],
            "musicbrainz_id": musicbrainz_id,
            "song_count": 1,
            "release_date": musicbrainz_date,
            "folder_name": folder_name,
        },
    )
    if musicbrainz_id and album_id not in _processed_placeholder_albums:
        _processed_placeholder_albums.add(album_id)
        add_placeholder_tracks_for_album(album_id, conn)
    return album_id, musicbrainz_id


def slugify_name(name: str) -> str:
    """Convert an artist name to a URL-friendly slug identifier."""
    normalized = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    slug = normalized.lower()
    slug = slug.replace("'", "").replace("’", "").replace("ʻ", "")
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unknown"


def _make_unique_slug(base_slug: str, existing_ids: set[str]) -> str:
    """Ensure slug is unique by appending a counter if needed."""
    slug = base_slug
    counter = 1
    while slug in existing_ids:
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def add_artist(artist_name: str, collection: dict, conn: Connection) -> tuple:
    result = conn.execute(
        text(
            "select artist_id, musicbrainz_id from artists where name = :name and collection_id = :collection_id"
        ),
        {"name": artist_name, "collection_id": collection["id"]},
    )
    existing_artist = result.mappings().first()
    if existing_artist:
        return existing_artist["artist_id"], existing_artist["musicbrainz_id"]
    artist_id = slugify_name(artist_name)
    existing = (
        conn.execute(
            text("select artist_id from artists where artist_id = :aid"),
            {"aid": artist_id},
        )
        .mappings()
        .first()
    )
    if existing:
        counter = 1
        while True:
            candidate = f"{artist_id}-{counter}"
            existing = (
                conn.execute(
                    text("select artist_id from artists where artist_id = :aid"),
                    {"aid": candidate},
                )
                .mappings()
                .first()
            )
            if not existing:
                artist_id = candidate
                break
            counter += 1
    try:
        repaired = artist_name.encode("latin-1").decode("utf-8")
        if repaired and repaired != artist_name:
            artist_name = repaired
    except Exception:
        pass
    musicbrainz_id = None
    inception_year = None
    if artist_name != "Unknown Artist":
        musicbrainz_data = metadata.artist_to_musicbrainz_data(artist_name, conn)
        if musicbrainz_data:
            musicbrainz_id = musicbrainz_data.get("id")
            life_span = musicbrainz_data.get("life-span", {})
            begin = life_span.get("begin")
            if begin and len(begin) >= 4:
                inception_year = begin[:4]
    conn.execute(
        text(
            "insert into artists (artist_id, name, collection_id, musicbrainz_id, inception_year) values (:artist_id, :name, :collection_id, :musicbrainz_id, :inception_year)"
        ),
        {
            "artist_id": artist_id,
            "name": artist_name,
            "collection_id": collection["id"],
            "musicbrainz_id": musicbrainz_id,
            "inception_year": inception_year,
        },
    )
    return artist_id, musicbrainz_id


def add_tag(song_id: str, frame_name: str, frame_bytes: bytes, conn: Connection) -> str:
    frame_id = str(uuid.uuid4())
    conn.execute(
        text(
            "insert into id3_frames (frame_id, song_id, frame_name, frame_bytes) values (:frame_id, :song_id, :frame_name, :frame_bytes)"
        ),
        {
            "frame_id": frame_id,
            "song_id": song_id,
            "frame_name": frame_name,
            "frame_bytes": frame_bytes,
        },
    )
    return frame_id


def tags_to_raw_tags(mutagen_info: dict) -> dict[str, bytes]:
    """Returns a dictionary with frame names as keys and frame bytes as values."""
    if not isinstance(mutagen_info.tags, ID3):
        raise TypeError("File does not have ID3 tags")

    id3 = mutagen_info.tags

    raw_frames: dict[str, bytes] = {}

    for frame in id3.values():
        frame_id = frame.FrameID
        raw_data = frame._writeData(None)
        raw_frames[frame_id] = raw_data
    return raw_frames


def add_tags_to_song(song_id: str, mutagen_info: dict, conn: Connection):
    try:
        raw_tags = tags_to_raw_tags(mutagen_info)
    except (TypeError, Exception):
        return
    for frame_name, frame_bytes in raw_tags.items():
        add_tag(song_id, frame_name, frame_bytes, conn)


def get_track_number_from_tags(mutagen_info) -> int | None:
    if not getattr(mutagen_info, "tags", None):
        return None
    track_str = get_first_tag_value(
        mutagen_info.tags, ["TRCK", "tracknumber", "TRACK", "track"]
    )
    if track_str:
        parts = track_str.split("/")
        try:
            return int(parts[0])
        except (ValueError, IndexError):
            pass
    return None


def get_disc_number_from_tags(mutagen_info) -> int:
    if not getattr(mutagen_info, "tags", None):
        return 1
    disc_str = get_first_tag_value(
        mutagen_info.tags, ["TPOS", "discnumber", "DISCNUMBER", "disc"]
    )
    if disc_str:
        parts = disc_str.split("/")
        try:
            return max(int(parts[0]), 1)
        except (ValueError, IndexError):
            pass
    return 1


def add_name_to_song(
    song_id: str, mutagen_info: dict, song_fields: list, conn: Connection
):
    name = get_first_tag_value(
        mutagen_info.tags, ["TIT2", "TITLE", "TITLETAG", "title"]
    )
    if not name:
        result = conn.execute(
            text("select path from songs where song_id = :song_id"),
            {"song_id": song_id},
        )
        name = Path(result.mappings().first()["path"]).stem
        if not name:
            name = "Unknown Title"
    name = cleaning.clean_song_name(name)
    try:
        repaired = name.encode("latin-1").decode("utf-8")
        if repaired and repaired != name:
            name = repaired
    except Exception:
        pass
    conn.execute(
        text("update songs set name = :value where song_id = :song_id"),
        {"value": name, "song_id": song_id},
    )


def get_artist_name_from_song(
    song_id: str, mutagen_info: dict, song_fields: list, conn: Connection
) -> str:
    artist_name = get_first_tag_value(
        mutagen_info.tags,
        ["TPE1", "ARTIST", "ALBUMARTIST", "TPE2", "artist", "albumartist"],
    )
    if not artist_name:
        artist_name = "Unknown Artist"
    return artist_name


def get_assume_structure_names(
    file_path: Path, collection_root: Path, assume_structure: str | None
) -> dict[str, str]:
    """Parse file path according to assume_structure pattern (e.g. \"Artist/Album/Song\")
    to extract artist, album, and song names from directory structure."""
    if not assume_structure:
        return {}

    rel_path = file_path.relative_to(collection_root)
    parts = rel_path.parts
    structure = assume_structure.split("/")

    result: dict[str, str] = {}

    for i, part in enumerate(reversed(parts)):
        if i >= len(structure):
            break
        label = structure[-(i + 1)]
        if label == "Song":
            result["song_name"] = Path(part).stem
        elif label == "Artist":
            result["artist_name"] = part
        elif label == "Album":
            result["album_name"] = part
        elif label == "Folder":
            result["folder_name"] = part
            if "Album" not in structure:
                result["album_name"] = part

    return result


def _placeholder_match(
    album_id: str, track_number: int | None, name: str, conn: Connection
) -> str | None:
    if track_number is not None:
        existing = (
            conn.execute(
                text(
                    "select song_id from songs where album_id = :album_id and track = :track and (path is null or path = '')"
                ),
                {"album_id": album_id, "track": track_number},
            )
            .mappings()
            .first()
        )
        if existing:
            return existing["song_id"]
    if name:
        existing = (
            conn.execute(
                text(
                    "select song_id from songs where album_id = :album_id and lower(name) = lower(:name) and (path is null or path = '')"
                ),
                {"album_id": album_id, "name": name},
            )
            .mappings()
            .first()
        )
        if existing:
            return existing["song_id"]
    return None


def scan_song_file(
    file_name: str,
    file_path: Path,
    collection_root: Path,
    collection: dict,
    song_fields: list,
    conn: Connection,
):
    if file_name in core["garbage_files"]:
        return

    assumed_names = get_assume_structure_names(
        file_path, collection_root, collection.get("assume_structure")
    )

    path = str(file_path)
    try:
        mutagen_info = mutagen.File(file_path)
    except Exception as e:
        mutagen_info = None
        logger.warning("Failed to read metadata for file: '%s' due to %s", file_path, e)
    if mutagen_info is None:
        return

    name = "Unknown Title"
    if getattr(mutagen_info, "tags", None):
        name = get_first_tag_value(
            mutagen_info.tags, ["TIT2", "TITLE", "TITLETAG", "title"]
        )
    if not name and "song_name" in assumed_names:
        name = assumed_names["song_name"]
    if not name:
        name = Path(path).stem
    name = cleaning.clean_song_name(name)
    try:
        repaired = name.encode("latin-1").decode("utf-8")
        if repaired and repaired != name:
            name = repaired
    except Exception:
        pass

    track_number = get_track_number_from_tags(mutagen_info)
    if track_number is None:
        track_number, _ = cleaning.extract_track_from_name(file_path.stem)

    disc_number = get_disc_number_from_tags(mutagen_info)

    artist_name = get_artist_name_from_song(None, mutagen_info, song_fields, conn)
    if artist_name == "Unknown Artist" and "artist_name" in assumed_names:
        artist_name = assumed_names["artist_name"]
    artist_id, artist_musicbrainz_id = add_artist(artist_name, collection, conn)

    album_name = None
    if getattr(mutagen_info, "tags", None):
        album_name = get_first_tag_value(mutagen_info.tags, ["TALB", "ALBUM", "album"])
    if not album_name and "album_name" in assumed_names:
        album_name = assumed_names["album_name"]

    album_id = album_musicbrainz_id = None
    if album_name:
        album_id, album_musicbrainz_id = add_album(
            artist_musicbrainz_id,
            artist_id,
            album_name,
            collection,
            conn,
            folder_name=assumed_names.get("folder_name"),
        )

    song_id = _placeholder_match(album_id, track_number, name, conn) if album_id else None

    if song_id:
        conn.execute(
            text(
                "update songs set path = :path, collection_id = :collection_id where song_id = :song_id"
            ),
            {"path": path, "collection_id": collection["id"], "song_id": song_id},
        )
    else:
        base_id = slugify_name(name) or "unknown"
        song_id = base_id
        counter = 1
        while conn.execute(
            text("select song_id from songs where song_id = :song_id"),
            {"song_id": song_id},
        ).first():
            song_id = f"{base_id}-{counter}"
            counter += 1

        conn.execute(
            text(
                "insert into songs (song_id, collection_id, path) values (:song_id, :collection_id, :path)"
            ),
            {"song_id": song_id, "collection_id": collection["id"], "path": path},
        )

        conn.execute(
            text(
                "update artists set song_count = song_count + 1 where artist_id = :artist_id"
            ),
            {"artist_id": artist_id},
        )

    conn.execute(
        text("update songs set name = :name where song_id = :song_id"),
        {"name": name, "song_id": song_id},
    )

    add_tags_to_song(song_id, mutagen_info, conn)

    if track_number is not None:
        conn.execute(
            text("update songs set track = :track where song_id = :song_id"),
            {"track": track_number, "song_id": song_id},
        )

    conn.execute(
        text("update songs set disc = :disc where song_id = :song_id"),
        {"disc": disc_number, "song_id": song_id},
    )

    conn.execute(
        text("update songs set artist_id = :artist_id where song_id = :song_id"),
        {"artist_id": artist_id, "song_id": song_id},
    )

    if album_id:
        conn.execute(
            text("update songs set album_id = :album_id where song_id = :song_id"),
            {"album_id": album_id, "song_id": song_id},
        )

    if hasattr(mutagen_info.info, "bitrate"):
        bitrate = int(mutagen_info.info.bitrate) if mutagen_info.info.bitrate else 0
        conn.execute(
            text("update songs set bitrate = :bitrate where song_id = :song_id"),
            {"bitrate": bitrate, "song_id": song_id},
        )

    if hasattr(mutagen_info.info, "bitrate_mode"):
        bitrate_mode = (
            mutagen_info.info.bitrate_mode if mutagen_info.info.bitrate_mode else None
        )
        if bitrate_mode:
            conn.execute(
                text(
                    "update songs set BITRATE_MODE = :bitrate_mode where song_id = :song_id"
                ),
                {"bitrate_mode": bitrate_mode, "song_id": song_id},
            )

    if hasattr(mutagen_info.info, "channels"):
        channels = mutagen_info.info.channels if mutagen_info.info.channels else 0
        conn.execute(
            text("update songs set CHANNELS = :channels where song_id = :song_id"),
            {"channels": channels, "song_id": song_id},
        )

    if hasattr(mutagen_info.info, "length"):
        duration = (
            int(mutagen_info.info.length * 1000) if mutagen_info.info.length else 0
        )
        conn.execute(
            text("update songs set duration = :duration where song_id = :song_id"),
            {"duration": duration, "song_id": song_id},
        )


def scan_path_for_songs(
    collection_root: Path, collection: dict, song_fields: list, conn: Connection
):
    for root, dirs, files in collection_root.walk():
        for file in files:
            file_path = Path(root, file)
            file_name = file
            scan_song_file(
                file_name, file_path, collection_root, collection, song_fields, conn
            )


def scan_songs(collection: dict, conn: Connection):
    song_fields = [
        col["name"] for col in conn.execute(text("PRAGMA table_info(songs)")).mappings()
    ]
    for collection_path_str in collection["paths"]:
        collection_path = Path(collection_path_str).expanduser()
        scan_path_for_songs(collection_path, collection, song_fields, conn)
    conn.commit()


def get_artists(
    conn: Connection,
    *,
    collection_id: str | None = None,
    artist_id: str | None = None,
    include_albums: bool = True,
    include_songs: bool = True,
) -> list[dict]:
    where_clauses: list[str] = []
    params: dict[str, str] = {}
    if collection_id is not None:
        where_clauses.append("collection_id = :collection_id")
        params["collection_id"] = collection_id
    if artist_id is not None:
        where_clauses.append("artist_id = :artist_id")
        params["artist_id"] = artist_id
    where_sql = ""
    if where_clauses:
        where_sql = " where " + " and ".join(where_clauses)
    result = conn.execute(
        text(f"select * from artists{where_sql}"),
        params,
    )
    artists: list[dict] = []
    for row in result:
        artist = row._asdict()
        # Fetch biography from artist_metadata if present
        bio_row = (
            conn.execute(
                text("select biography from artist_metadata where artist_id = :artist_id"),
                {"artist_id": artist["artist_id"]},
            )
            .mappings()
            .first()
        )
        if bio_row and bio_row.get("biography"):
            artist["biography"] = bio_row["biography"]
        if include_albums:
            albums = get_albums(
                collection_id=collection_id,
                artist_id=artist["artist_id"],
                include_artists=False,
                include_songs=include_songs,
                conn=conn,
            )
            if albums:
                artist["albums"] = albums
        if include_songs:
            songs = get_songs(
                collection_id=collection_id,
                artist_id=artist["artist_id"],
                conn=conn,
            )
            if songs:
                artist["songs"] = songs
        artists.append(artist)
    return artists


ENTITY_PLURALS: dict[str, str] = {
    "Folder": "folders",
    "Artist": "artists",
    "Album": "albums",
    "Song": "songs",
}
ENTITY_SINGULARS: dict[str, str] = {
    "Folder": "folder",
    "Artist": "artist",
    "Album": "album",
    "Song": "song",
}
_ENTITY_INFO: dict[str, dict] = {
    "Folder": {"plural": "folders", "singular": "folder"},
    "Artist": {"plural": "artists", "singular": "artist"},
    "Album": {"plural": "albums", "singular": "album"},
    "Song": {"plural": "songs", "singular": "song"},
}


def get_nav_entities(collection: dict) -> list[dict]:
    """Return list of entity dicts based on assume_structure,
    each with name, plural, singular, url_path (relative to collection base)."""
    structure = collection.get("assume_structure", "Artist/Album/Song").split("/")
    entities: list[dict] = []
    for name in structure:
        info = _ENTITY_INFO.get(name)
        if info:
            entities.append(
                {
                    "name": name,
                    "plural": info["plural"],
                    "singular": info["singular"],
                }
            )
    return entities


def get_folders(
    conn: Connection,
    *,
    collection_id: str,
) -> list[str]:
    result = conn.execute(
        text(
            "select distinct folder_name from albums "
            "where collection_id = :collection_id and folder_name is not null "
            "order by folder_name"
        ),
        {"collection_id": collection_id},
    )
    return [row[0] for row in result]


def get_albums(
    conn: Connection,
    *,
    collection_id: str | None = None,
    album_id: str | None = None,
    artist_id: str | None = None,
    folder_name: str | None = None,
    include_artists: bool = True,
    include_songs: bool = True,
) -> list[dict]:
    where_clauses: list[str] = []
    params: dict[str, str] = {}
    if collection_id is not None:
        where_clauses.append("a.collection_id = :collection_id")
        params["collection_id"] = collection_id
    if album_id is not None:
        where_clauses.append("a.album_id = :album_id")
        params["album_id"] = album_id
    if artist_id is not None:
        where_clauses.append("a.artist_id = :artist_id")
        params["artist_id"] = artist_id
    if folder_name is not None:
        where_clauses.append("a.folder_name = :folder_name")
        params["folder_name"] = folder_name
    where_sql = ""
    if where_clauses:
        where_sql = " where " + " and ".join(where_clauses)
    result = conn.execute(
        text(
            f"select a.*, coalesce(s.total_duration, 0) as duration "
            f"from albums a "
            f"left join ("
            f"  select album_id, sum(duration) as total_duration "
            f"  from songs where album_id is not null group by album_id"
            f") s on a.album_id = s.album_id"
            f"{where_sql}"
        ),
        params,
    )
    albums: list[dict] = []
    for row in result.mappings():
        album = dict(row)
        album["duration_human"] = cleaning.milliseconds_to_hours_minutes_seconds(
            int(album["duration"])
        )
        # Fetch extra cover art images
        extra_rows = (
            conn.execute(
                text(
                    "select image_type, local_path, sort_order from album_extra_images "
                    "where album_id = :album_id order by sort_order"
                ),
                {"album_id": album["album_id"]},
            )
            .mappings()
            .all()
        )
        if extra_rows:
            album["extra_images"] = [
                {
                    "image_type": r["image_type"],
                    "image_id": f"{album['album_id']}-{r['image_type']}-{r['sort_order']}",
                }
                for r in extra_rows
            ]
        if include_artists and album.get("artist_id"):
            artists = get_artists(
                collection_id=collection_id,
                artist_id=album["artist_id"],
                include_songs=False,
                conn=conn,
            )
            if artists:
                album["artist"] = artists[0]
                album["artist_name"] = artists[0]["name"]
        if include_songs:
            songs = get_songs(
                collection_id=collection_id,
                album_id=album["album_id"],
                conn=conn,
            )
            if songs:
                album["songs"] = songs
        albums.append(album)
    return albums


def get_songs(
    conn: Connection,
    *,
    collection_id: str | None = None,
    artist_id: str | None = None,
    album_id: str | None = None,
    song_id: str | None = None,
    folder_name: str | None = None,
    include_albums: bool = True,
    include_artists: bool = True,
) -> list[dict]:
    from_sql = "songs"
    where_clauses: list[str] = []
    params: dict[str, str] = {}
    if collection_id is not None:
        where_clauses.append("songs.collection_id = :collection_id")
        params["collection_id"] = collection_id
    if artist_id is not None:
        where_clauses.append("songs.artist_id = :artist_id")
        params["artist_id"] = artist_id
    if album_id is not None:
        where_clauses.append("songs.album_id = :album_id")
        params["album_id"] = album_id
    if song_id is not None:
        where_clauses.append("songs.song_id = :song_id")
        params["song_id"] = song_id
    if folder_name is not None:
        from_sql = "songs join albums on songs.album_id = albums.album_id"
        where_clauses.append("albums.folder_name = :folder_name")
        params["folder_name"] = folder_name
    where_sql = ""
    if where_clauses:
        where_sql = " where " + " and ".join(where_clauses)
    result = conn.execute(
        text(f"select songs.* from {from_sql}{where_sql}"),
        params,
    ).mappings()
    songs: list[dict] = []
    for song in result:
        song = dict(song)
        if song.get("bitrate_mode") is not None:
            song["bitrate_mode_human"] = {
                0: "CBR",
                1: "VBR",
                2: "ABR",
            }.get(song["bitrate_mode"], "unknown")
        if song.get("bitrate") is not None:
            song["bitrate_human"] = str(song["bitrate"] // 1000)
        if song.get("duration") is not None:
            song["duration_human"] = cleaning.milliseconds_to_hours_minutes_seconds(
                song["duration"]
            )
        if include_artists and song.get("artist_id"):
            artist = (
                conn.execute(
                    text("select name from artists where artist_id = :artist_id"),
                    {"artist_id": song["artist_id"]},
                )
                .mappings()
                .first()
            )
            if artist:
                song["artist_name"] = artist["name"]
                song["artist"] = artist
        if include_albums and song.get("album_id"):
            album = (
                conn.execute(
                    text("select name, release_date from albums where album_id = :album_id"),
                    {"album_id": song["album_id"]},
                )
                .mappings()
                .first()
            )
            if album:
                song["album_name"] = album["name"]
                song["album"] = album
                if album.get("release_date"):
                    song["year"] = album["release_date"][:4]
        songs.append(song)
    songs.sort(
        key=lambda x: (
            x.get("track") is None,
            x.get("track") or 0,
            x.get("name") is None,
            x.get("name"),
        )
    )
    return songs


def search(query: str, conn: Connection):
    if query:
        song_result = conn.execute(
            text(
                "select songs.*, a.name as artist_name, al.name as album_name from songs "
                "left join artists a on songs.artist_id = a.artist_id "
                "left join albums al on songs.album_id = al.album_id "
                "where songs.name like :query"
            ),
            {"query": f"%{query}%"},
        ).mappings()
        songs = [dict(row) for row in song_result]

        album_result = conn.execute(
            text(
                "select albums.*, a.name as artist_name from albums "
                "left join artists a on albums.artist_id = a.artist_id "
                "where albums.name like :query"
            ),
            {"query": f"%{query}%"},
        ).mappings()
        albums = [dict(row) for row in album_result]

        artist_result = conn.execute(
            text("select * from artists where name like :query"),
            {"query": f"%{query}%"},
        ).mappings()
        artists = [dict(row) for row in artist_result]
    else:
        songs = get_songs(conn=conn)
        albums = get_albums(conn=conn, include_songs=False)
        artists = get_artists(conn=conn, include_albums=False, include_songs=False)
    results = {"songs": songs, "albums": albums, "artists": artists}
    return results


def star_song(song_id: str, conn: Connection, star: bool = True):
    conn.execute(
        text("update songs set starred = :starred where song_id = :song_id"),
        {"starred": star, "song_id": song_id},
    )


def remove_song(song_id: str, conn: Connection):
    conn.execute(
        text("delete from songs where song_id = :song_id"),
        {"song_id": song_id},
    )


def get_artists_from_folders() -> list:
    artists = []
    for collection in get_collections().values():
        if collection.get("type", None) != "music":
            continue
        for collection_path_str in collection["paths"]:
            collection_path = Path(collection_path_str).expanduser()
            for file in collection_path.iterdir():
                if not file.is_dir():
                    continue
                artists.append(
                    {
                        "id": file.name,
                        "name": file.name,
                        "coverArt": file.name,
                    }
                )
    return artists


def fetch_missing_metadata(conn: Connection):
    original_setting = config.get("musicbrainz_metadata", False)
    config["musicbrainz_metadata"] = True
    try:
        result = conn.execute(
            text("select * from artists where musicbrainz_id is null")
        ).mappings()
        artists_missing = [dict(row) for row in result]
        for artist in artists_missing:
            if artist["name"] == "Unknown Artist":
                continue
            musicbrainz_id = metadata.artist_to_musicbrainz_id(artist["name"], conn)
            if musicbrainz_id:
                conn.execute(
                    text(
                        "update artists set musicbrainz_id = :musicbrainz_id where artist_id = :artist_id"
                    ),
                    {
                        "musicbrainz_id": musicbrainz_id,
                        "artist_id": artist["artist_id"],
                    },
                )

        result = conn.execute(
            text("select * from artists where musicbrainz_id is not null and (inception_year is null or inception_year = '')")
        ).mappings()
        for artist in [dict(row) for row in result]:
            inception_year = metadata.artist_to_inception_year(artist["name"], conn)
            if inception_year:
                conn.execute(
                    text("update artists set inception_year = :inception_year where artist_id = :artist_id"),
                    {"inception_year": inception_year, "artist_id": artist["artist_id"]},
                )

        result = conn.execute(
            text("select * from albums where musicbrainz_id is null")
        ).mappings()
        albums_missing = [dict(row) for row in result]
        for album in albums_missing:
            if not album.get("artist_id") or album.get("name") == "Unknown Album":
                continue
            artist_result = (
                conn.execute(
                    text(
                        "select musicbrainz_id from artists where artist_id = :artist_id"
                    ),
                    {"artist_id": album["artist_id"]},
                )
                .mappings()
                .first()
            )
            if not artist_result:
                continue
            artist_mb_id = artist_result["musicbrainz_id"]
            if not artist_mb_id:
                continue
            musicbrainz_data = metadata.album_to_musicbrainz_data(
                artist_mb_id, album["name"], conn
            )
            if musicbrainz_data and musicbrainz_data.get("id"):
                conn.execute(
                    text(
                        "update albums set musicbrainz_id = :musicbrainz_id, release_date = :release_date where album_id = :album_id"
                    ),
                    {
                        "musicbrainz_id": musicbrainz_data["id"],
                        "release_date": musicbrainz_data.get("date"),
                        "album_id": album["album_id"],
                    },
                )
                aid = album["album_id"]
                if aid not in _processed_placeholder_albums:
                    _processed_placeholder_albums.add(aid)
                    add_placeholder_tracks_for_album(aid, conn)
                try:
                    img = musicbrainz_data.get("image_url")
                    if img:
                        conn.execute(
                            text(
                                "insert or replace into album_images (album_id, image_url) values (:album_id, :image_url)"
                            ),
                            {"album_id": album["album_id"], "image_url": img},
                        )
                        try:
                            metadata.download_album_image(
                                album["album_id"], img
                            )
                        except Exception:
                            logger.exception(
                                "Failed to download cover for album '%s' (%s)",
                                album["name"],
                                album["album_id"],
                            )
                except Exception:
                    pass
        conn.commit()
        fetch_missing_artist_images(conn)
        fetch_missing_artist_bios(conn)
        fetch_missing_album_extra_images(conn)
        fetch_missing_lyrics(conn)
    finally:
        config["musicbrainz_metadata"] = original_setting


def fetch_missing_artist_images(conn: Connection):
    """Fetch artist profile images for artists missing cover_art."""
    result = conn.execute(
        text("select artist_id, name from artists where cover_art is null")
    ).mappings()
    artists = [dict(row) for row in result]
    fetched = 0
    for artist in artists:
        image_url = metadata.fetch_artist_image_url(artist["name"])
        if image_url:
            local_path = metadata.download_artist_image(artist["artist_id"], image_url)
            if local_path:
                fetched += 1
    logger.info("Fetched artist images for %d/%d artists", fetched, len(artists))


def fetch_missing_artist_bios(conn: Connection):
    """Fetch Wikipedia biographies for artists missing a biography."""
    result = conn.execute(
        text(
            "select a.artist_id, a.musicbrainz_id from artists a "
            "left join artist_metadata am on a.artist_id = am.artist_id "
            "where a.musicbrainz_id is not null and am.artist_id is null"
        )
    ).mappings()
    artists = [dict(row) for row in result]
    fetched = 0
    for artist in artists:
        bio = metadata.fetch_artist_biography(artist["musicbrainz_id"], conn)
        if bio is not None:
            conn.execute(
                text(
                    "insert or replace into artist_metadata (artist_id, biography) "
                    "values (:artist_id, :biography)"
                ),
                {"artist_id": artist["artist_id"], "biography": bio},
            )
            fetched += 1
    if fetched:
        conn.commit()
    logger.info("Fetched artist bios for %d/%d artists", fetched, len(artists))


def fetch_missing_album_extra_images(conn: Connection):
    """Fetch extra album images (back covers, booklets) from CoverArtArchive."""
    result = conn.execute(
        text(
            "select a.album_id, a.musicbrainz_id from albums a "
            "left join album_extra_images ae on a.album_id = ae.album_id "
            "where a.musicbrainz_id is not null and ae.album_id is null"
        )
    ).mappings()
    albums = [dict(row) for row in result]
    fetched = 0
    for album in albums:
        images = metadata.fetch_album_extra_images(album["musicbrainz_id"], conn)
        if images:
            for i, img in enumerate(images):
                local_path = metadata.download_album_extra_image(
                    album["album_id"], img["image_url"], img["image_type"], i
                )
                conn.execute(
                    text(
                        "insert into album_extra_images "
                        "(album_id, image_type, image_url, local_path, sort_order) "
                        "values (:album_id, :image_type, :image_url, :local_path, :sort_order)"
                    ),
                    {
                        "album_id": album["album_id"],
                        "image_type": img["image_type"],
                        "image_url": img["image_url"],
                        "local_path": local_path,
                        "sort_order": i,
                    },
                )
                fetched += 1
    if fetched:
        conn.commit()
    logger.info("Fetched %d extra album images for %d albums", fetched, len(albums))


def fetch_missing_lyrics(conn: Connection):
    """Fetch synced lyrics for songs that don't have lyrics yet.

    Each lyrics fetch runs in its own daemon thread so this returns
    immediately without blocking.
    """
    conn.execute(
        text("delete from lyrics where song_id not in (select song_id from songs)")
    )
    conn.commit()
    result = conn.execute(
        text(
            "select s.song_id, s.name, a.name as artist_name, al.name as album_name, s.duration "
            "from songs s "
            "left join artists a on s.artist_id = a.artist_id "
            "left join albums al on s.album_id = al.album_id "
            "left join lyrics l on s.song_id = l.song_id "
            "where l.song_id is null and s.path is not null and s.path != ''"
        )
    ).mappings()
    songs = [dict(row) for row in result]
    logger.info("fetch_missing_lyrics: %d songs without lyrics", len(songs))
    for song in songs:
        metadata._fetch_and_store(
            track_name=song["name"],
            artist_name=song.get("artist_name") or "Unknown Artist",
            album_name=song.get("album_name"),
            duration=song.get("duration"),
            song_id=song["song_id"],
        )


def reset_metadata(conn: Connection):
    conn.execute(text("update artists set musicbrainz_id = null"))
    conn.execute(text("update albums set musicbrainz_id = null, release_date = null"))
    conn.execute(text("delete from musicbrainz_cache"))
    conn.execute(text("delete from artist_metadata"))
    conn.execute(text("delete from album_extra_images"))
    conn.commit()


def get_stats(conn: Connection) -> dict:
    total_songs = (
        conn.execute(
            text("select count(*) from songs where path is not null and path != ''")
        ).scalar()
        or 0
    )

    songs_with_artist_mb = (
        conn.execute(
            text(
                "select count(*) from songs s "
                "inner join artists a on s.artist_id = a.artist_id "
                "where a.musicbrainz_id is not null "
                "and s.path is not null and s.path != ''"
            )
        ).scalar()
        or 0
    )

    songs_with_album_mb = (
        conn.execute(
            text(
                "select count(*) from songs s "
                "inner join albums a on s.album_id = a.album_id "
                "where a.musicbrainz_id is not null "
                "and s.path is not null and s.path != ''"
            )
        ).scalar()
        or 0
    )

    total_artists = conn.execute(text("select count(*) from artists")).scalar() or 0

    artists_with_mb = (
        conn.execute(
            text("select count(*) from artists where musicbrainz_id is not null")
        ).scalar()
        or 0
    )

    total_albums = conn.execute(text("select count(*) from albums")).scalar() or 0

    albums_with_mb = (
        conn.execute(
            text("select count(*) from albums where musicbrainz_id is not null")
        ).scalar()
        or 0
    )

    albums_with_date = (
        conn.execute(
            text("select count(*) from albums where release_date is not null")
        ).scalar()
        or 0
    )

    song_pieces_possible = total_songs * 2
    song_pieces_actual = songs_with_artist_mb + songs_with_album_mb
    artist_pieces_possible = total_artists
    artist_pieces_actual = artists_with_mb
    album_pieces_possible = total_albums * 2
    album_pieces_actual = albums_with_mb + albums_with_date

    total_pieces_possible = (
        song_pieces_possible + artist_pieces_possible + album_pieces_possible
    )
    total_pieces_actual = (
        song_pieces_actual + artist_pieces_actual + album_pieces_actual
    )

    return {
        "songs": total_songs,
        "songs_with_lyrics": conn.execute(
            text(
                "select count(distinct l.song_id) from lyrics l inner join songs s on l.song_id = s.song_id where l.song_id is not null and s.path is not null and s.path != ''"
            )
        ).scalar()
        or 0,
        "songs_with_synced_lyrics": conn.execute(
            text(
                "select count(distinct l.song_id) from lyrics l inner join songs s on l.song_id = s.song_id where l.song_id is not null and s.path is not null and s.path != '' and l.synced_lyrics is not null and l.synced_lyrics != ''"
            )
        ).scalar()
        or 0,
        "songs_with_artist_mb": songs_with_artist_mb,
        "songs_with_album_mb": songs_with_album_mb,
        "artists": total_artists,
        "artists_with_mb": artists_with_mb,
        "albums": total_albums,
        "albums_with_mb": albums_with_mb,
        "albums_with_date": albums_with_date,
        "metadata_pieces_possible": total_pieces_possible,
        "metadata_pieces_actual": total_pieces_actual,
    }


def migrate_artist_ids_to_slugs(conn: Connection):
    """Convert existing UUID artist IDs to name-based slugs."""
    result = (
        conn.execute(text("select artist_id, name from artists limit 1"))
        .mappings()
        .first()
    )
    if not result:
        return
    has_uuid = (
        conn.execute(
            text("select artist_id from artists where artist_id like '%-%' limit 1")
        )
        .mappings()
        .first()
    )
    if not has_uuid:
        return
    rows = (
        conn.execute(
            text(
                "select artist_id, name, collection_id from artists order by collection_id, name"
            )
        )
        .mappings()
        .all()
    )
    slug_map: dict[str, str] = {}
    used_slugs: set[str] = set()
    for row in rows:
        old_id = row["artist_id"]
        base = slugify_name(row["name"])
        slug = _make_unique_slug(base, used_slugs)
        used_slugs.add(slug)
        slug_map[old_id] = slug
    for old_id, new_id in slug_map.items():
        conn.execute(
            text("update artists set artist_id = :new where artist_id = :old"),
            {"new": new_id, "old": old_id},
        )
        conn.execute(
            text("update albums set artist_id = :new where artist_id = :old"),
            {"new": new_id, "old": old_id},
        )
        conn.execute(
            text("update songs set artist_id = :new where artist_id = :old"),
            {"new": new_id, "old": old_id},
        )
    cache_dir = Path(config.get("library_path", "")).expanduser() / ".artist_images"
    if cache_dir.exists():
        for old_id, new_id in slug_map.items():
            old_path = cache_dir / f"{old_id}.jpg"
            if old_path.exists():
                old_path.rename(cache_dir / f"{new_id}.jpg")
    conn.execute(text("update artists set cover_art = null"))
    conn.commit()


def migrate_album_ids_to_slugs(conn: Connection):
    """Convert existing UUID album IDs to name-based slugs."""
    result = (
        conn.execute(text("select album_id, name from albums limit 1"))
        .mappings()
        .first()
    )
    if not result:
        return
    has_uuid = (
        conn.execute(
            text("select album_id from albums where album_id like '%-%' limit 1")
        )
        .mappings()
        .first()
    )
    if not has_uuid:
        return
    rows = (
        conn.execute(
            text(
                "select album_id, name, collection_id from albums order by collection_id, name"
            )
        )
        .mappings()
        .all()
    )
    slug_map: dict[str, str] = {}
    used_slugs: set[str] = set()
    for row in rows:
        old_id = row["album_id"]
        base = slugify_name(row["name"])
        slug = _make_unique_slug(base, used_slugs)
        used_slugs.add(slug)
        slug_map[old_id] = slug
    for old_id, new_id in slug_map.items():
        conn.execute(
            text("update albums set album_id = :new where album_id = :old"),
            {"new": new_id, "old": old_id},
        )
        conn.execute(
            text("update songs set album_id = :new where album_id = :old"),
            {"new": new_id, "old": old_id},
        )
        conn.execute(
            text("update album_images set album_id = :new where album_id = :old"),
            {"new": new_id, "old": old_id},
        )
    cache_dir = Path(config.get("library_path", "")).expanduser() / ".album_images"
    if cache_dir.exists():
        for old_id, new_id in slug_map.items():
            old_path = cache_dir / f"{old_id}.jpg"
            if old_path.exists():
                old_path.rename(cache_dir / f"{new_id}.jpg")
    conn.commit()


_processed_placeholder_albums: set[str] = set()


def add_placeholder_tracks_for_album(album_id: str, conn: Connection) -> int:
    album = (
        conn.execute(
            text(
                "select album_id, artist_id, collection_id, name, musicbrainz_id "
                "from albums where album_id = :album_id"
            ),
            {"album_id": album_id},
        )
        .mappings()
        .first()
    )
    if not album or not album["musicbrainz_id"] or not config["musicbrainz_metadata"]:
        return 0

    tracks = metadata.album_to_track_listing(album["musicbrainz_id"], conn)
    if not tracks:
        return 0

    existing = (
        conn.execute(
            text("select track, name, song_id, path from songs where album_id = :aid"),
            {"aid": album_id},
        )
        .mappings()
        .all()
    )
    existing_by_track: dict[int, dict] = {}
    existing_by_name: dict[str, dict] = {}
    for row in existing:
        existing_by_track[row["track"]] = row
        if row["name"]:
            existing_by_name[row["name"].strip().lower()] = row

    added = 0
    for track_info in tracks:
        disc = track_info["disc"]
        track_num = track_info["track"]
        title = track_info["title"]
        combined = disc * 1000 + track_num

        if combined in existing_by_track:
            continue
        if disc == 1 and track_num in existing_by_track:
            continue
        if title:
            key = title.strip().lower()
            if key in existing_by_name:
                continue

        base_id = slugify_name(title) or "unknown"
        song_id = base_id
        counter = 1
        while conn.execute(
            text("select song_id from songs where song_id = :song_id"),
            {"song_id": song_id},
        ).first():
            song_id = f"{base_id}-{counter}"
            counter += 1
        duration = track_info.get("duration") or 0
        conn.execute(
            text(
                "insert into songs "
                "(song_id, name, artist_id, album_id, collection_id, track, disc, duration) "
                "values (:song_id, :name, :artist_id, :album_id, "
                ":collection_id, :track, :disc, :duration)"
            ),
            {
                "song_id": song_id,
                "name": title,
                "artist_id": album["artist_id"],
                "album_id": album["album_id"],
                "collection_id": album["collection_id"],
                "track": track_num,
                "disc": disc,
                "duration": duration,
            },
        )
        added += 1

    if added:
        conn.execute(
            text(
                "update albums set song_count = ("
                "  select count(*) from songs "
                "  where songs.album_id = albums.album_id"
                ")"
            )
        )
        conn.commit()
        logger.info(
            "Added %d placeholder track(s) for album '%s'",
            added,
            album["name"],
        )

    return added


def add_placeholder_tracks(conn: Connection) -> int:
    """Add placeholder songs for album tracks listed on MusicBrainz that the
    user does not have in their collection.  Placeholder rows have no `path`
    (no audio source) so they show up in the library but cannot be played.

    Returns the number of placeholders inserted.
    """
    if not config["musicbrainz_metadata"]:
        return 0

    albums = (
        conn.execute(
            text(
                "select album_id from albums where musicbrainz_id is not null"
            )
        )
        .mappings()
        .all()
    )

    added = 0
    for album in albums:
        added += add_placeholder_tracks_for_album(album["album_id"], conn)

    if added:
        logger.info(
            "Added %d placeholder song(s) from MusicBrainz track listings", added
        )
    return added


def add_artist_musicbrainz_albums(artist_id: str, conn: Connection) -> dict:
    """Fetch all albums from MusicBrainz for an artist and add missing ones to the database.

    Returns a dict with 'added' (list of album ids that were added) and
    'skipped' (list of album names already in the database).
    """
    original_setting = config.get("musicbrainz_metadata", False)
    config["musicbrainz_metadata"] = True
    try:
        artists = get_artists(
            conn=conn, artist_id=artist_id, include_albums=False, include_songs=False
        )
        if not artists:
            return {"error": "Artist not found"}
        artist = artists[0]
        artist_name = artist["name"]
        artist_mbid = artist.get("musicbrainz_id")

        if not artist_mbid:
            artist_mbid = metadata.artist_to_musicbrainz_id(artist_name, conn)
            if artist_mbid:
                conn.execute(
                    text(
                        "update artists set musicbrainz_id = :mbid where artist_id = :aid"
                    ),
                    {"mbid": artist_mbid, "aid": artist_id},
                )

        if not artist_mbid:
            return {"error": "No MusicBrainz ID for this artist"}

        releases = metadata.get_artist_releases(artist_mbid, conn)
        if not releases:
            return {"error": "Could not fetch releases from MusicBrainz"}

        collections = get_collections()
        collection = list(collections.values())[0] if collections else None
        if not collection:
            return {"error": "No collection configured"}

        existing = (
            conn.execute(
                text("select name from albums where artist_id = :aid"),
                {"aid": artist_id},
            )
            .mappings()
            .all()
        )
        existing_names: set[str] = {r["name"].strip().lower() for r in existing}

        added: list[str] = []
        skipped: list[str] = []

        for release in releases:
            title = release.get("title", "")
            if not title:
                continue

            title_lower = title.strip().lower()
            if title_lower in existing_names:
                skipped.append(title)
                continue

            rg_mbid = release.get("id")
            release_date = release.get("first-release-date", "")

            base_slug = slugify_name(title)
            album_id = base_slug
            counter = 1
            while conn.execute(
                text("select album_id from albums where album_id = :aid"),
                {"aid": album_id},
            ).first():
                album_id = f"{base_slug}-{counter}"
                counter += 1

            conn.execute(
                text(
                    "insert into albums (album_id, artist_id, name, collection_id, musicbrainz_id, song_count, release_date) "
                    "values (:album_id, :artist_id, :name, :collection_id, :musicbrainz_id, 0, :release_date)"
                ),
                {
                    "album_id": album_id,
                    "artist_id": artist_id,
                    "name": title,
                    "collection_id": collection["id"],
                    "musicbrainz_id": rg_mbid,
                    "release_date": release_date,
                },
            )
            conn.commit()

            try:
                image_url = (
                    f"https://coverartarchive.org/release-group/{rg_mbid}/front-250.jpg"
                )
                conn.execute(
                    text(
                        "insert or ignore into album_images (album_id, image_url) values (:album_id, :image_url)"
                    ),
                    {"album_id": album_id, "image_url": image_url},
                )
            except Exception:
                pass
            conn.commit()

            try:
                metadata.download_album_image(album_id, image_url)
            except Exception:
                logger.exception(
                    "Failed to download cover for album '%s' (%s)", title, album_id
                )

            tracks = metadata.album_to_track_listing(rg_mbid, conn)
            if tracks:
                track_added = 0
                for track_info in tracks:
                    disc = track_info.get("disc", 1)
                    track_num = track_info.get("track", 0)
                    track_title = track_info.get("title", "Unknown Track")
                    duration = track_info.get("duration", 0)

                    base_id = slugify_name(track_title) or "unknown"
                    song_id = base_id
                    counter = 1
                    while conn.execute(
                        text("select song_id from songs where song_id = :song_id"),
                        {"song_id": song_id},
                    ).first():
                        song_id = f"{base_id}-{counter}"
                        counter += 1

                    conn.execute(
                        text(
                            "insert into songs (song_id, name, artist_id, album_id, collection_id, track, disc, duration) "
                            "values (:song_id, :name, :artist_id, :album_id, :collection_id, :track, :disc, :duration)"
                        ),
                        {
                            "song_id": song_id,
                            "name": track_title,
                            "artist_id": artist_id,
                            "album_id": album_id,
                            "collection_id": collection["id"],
                            "track": track_num,
                            "disc": disc,
                            "duration": duration,
                        },
                    )
                    track_added += 1

                conn.execute(
                    text("update albums set song_count = :count where album_id = :aid"),
                    {"count": track_added, "aid": album_id},
                )

            conn.execute(
                text(
                    "update artists set album_count = album_count + 1 where artist_id = :aid"
                ),
                {"aid": artist_id},
            )

            conn.commit()
            added.append(album_id)

            existing_names.add(title_lower)

        return {"added": added, "skipped": skipped}
    finally:
        config["musicbrainz_metadata"] = original_setting


def get_playlists(conn: Connection) -> list[dict]:
    result = conn.execute(
        text("select * from playlists order by name collate nocase")
    ).mappings()
    return [dict(row) for row in result]


def get_playlist(conn: Connection, playlist_id: str) -> dict | None:
    row = (
        conn.execute(
            text("select * from playlists where playlist_id = :id"),
            {"id": playlist_id},
        )
        .mappings()
        .first()
    )
    if not row:
        return None
    playlist = dict(row)
    entries = conn.execute(
        text(
            "select s.*, a.name as artist_name, al.name as album_name "
            "from playlist_songs ps "
            "join songs s on ps.song_id = s.song_id "
            "left join artists a on s.artist_id = a.artist_id "
            "left join albums al on s.album_id = al.album_id "
            "where ps.playlist_id = :id order by ps.sort_order"
        ),
        {"id": playlist_id},
    ).mappings()
    playlist["entries"] = [dict(row) for row in entries]
    return playlist


def create_playlist(conn: Connection, name: str, comment: str = "") -> str:
    import uuid

    playlist_id = str(uuid.uuid4())
    from datetime import datetime

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        text(
            "insert into playlists (playlist_id, name, comment, owner, public, created, changed, song_count, duration) "
            "values (:id, :name, :comment, :owner, :public, :created, :changed, 0, 0)"
        ),
        {
            "id": playlist_id,
            "name": name,
            "comment": comment,
            "owner": "admin",
            "public": False,
            "created": now,
            "changed": now,
        },
    )
    conn.commit()
    return playlist_id


def update_playlist(
    conn: Connection,
    playlist_id: str,
    name: str | None = None,
    comment: str | None = None,
    public: bool | None = None,
    song_ids: list[str] | None = None,
):
    from datetime import datetime

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    updates = ["changed = :now"]
    params: dict = {"id": playlist_id, "now": now}
    if name is not None:
        updates.append("name = :name")
        params["name"] = name
    if comment is not None:
        updates.append("comment = :comment")
        params["comment"] = comment
    if public is not None:
        updates.append("public = :public")
        params["public"] = public
    conn.execute(
        text(f"update playlists set {', '.join(updates)} where playlist_id = :id"),
        params,
    )
    if song_ids is not None:
        conn.execute(
            text("delete from playlist_songs where playlist_id = :id"),
            {"id": playlist_id},
        )
        for i, song_id in enumerate(song_ids):
            conn.execute(
                text(
                    "insert into playlist_songs (playlist_id, song_id, sort_order) values (:pid, :sid, :ord)"
                ),
                {"pid": playlist_id, "sid": song_id, "ord": i},
            )
    _recalc_playlist_stats(conn, playlist_id)
    conn.commit()


def delete_playlist(conn: Connection, playlist_id: str):
    conn.execute(
        text("delete from playlist_songs where playlist_id = :id"),
        {"id": playlist_id},
    )
    conn.execute(
        text("delete from playlists where playlist_id = :id"),
        {"id": playlist_id},
    )
    conn.commit()


def add_to_playlist(conn: Connection, playlist_id: str, song_ids: list[str]):
    result = (
        conn.execute(
            text(
                "select coalesce(max(sort_order), -1) + 1 as next from playlist_songs where playlist_id = :id"
            ),
            {"id": playlist_id},
        )
        .mappings()
        .first()
    )
    start = result["next"] if result else 0
    for i, song_id in enumerate(song_ids):
        conn.execute(
            text(
                "insert into playlist_songs (playlist_id, song_id, sort_order) values (:pid, :sid, :ord)"
            ),
            {"pid": playlist_id, "sid": song_id, "ord": start + i},
        )
    _recalc_playlist_stats(conn, playlist_id)
    conn.commit()


def remove_from_playlist(conn: Connection, playlist_id: str, indices: list[int]):
    for idx in sorted(indices, reverse=True):
        conn.execute(
            text(
                "delete from playlist_songs where playlist_id = :id and sort_order = :ord"
            ),
            {"id": playlist_id, "ord": idx},
        )
    remaining = conn.execute(
        text(
            "select rowid from playlist_songs where playlist_id = :id order by sort_order"
        ),
        {"id": playlist_id},
    ).mappings()
    for i, row in enumerate(remaining):
        conn.execute(
            text("update playlist_songs set sort_order = :ord where rowid = :rid"),
            {"ord": i, "rid": row["rowid"]},
        )
    _recalc_playlist_stats(conn, playlist_id)
    conn.commit()


def _recalc_playlist_stats(conn: Connection, playlist_id: str):
    stats = (
        conn.execute(
            text(
                "select count(*) as song_count, coalesce(sum(s.duration), 0) as duration "
                "from playlist_songs ps "
                "join songs s on ps.song_id = s.song_id "
                "where ps.playlist_id = :id"
            ),
            {"id": playlist_id},
        )
        .mappings()
        .first()
    )
    if stats:
        conn.execute(
            text(
                "update playlists set song_count = :count, duration = :duration where playlist_id = :id"
            ),
            {
                "count": stats["song_count"],
                "duration": stats["duration"],
                "id": playlist_id,
            },
        )


def init_library(
    conn: Connection,
    rescan: bool = False,
):
    if engine is None:
        raise OperationalError("No database engine available.")
    if conn is None:
        raise OperationalError("No database connection available.")
    init_db(rescan=rescan, conn=conn)
    migrate_artist_ids_to_slugs(conn)
    migrate_album_ids_to_slugs(conn)
    if rescan:
        collections = get_collections()
        for collection in collections:
            if collections[collection].get("type", None) == "music":
                scan_songs(collections[collection], conn)
        conn.commit()
        conn.execute(
            text("""
            insert or ignore into album_images (album_id, image_url)
            select a.album_id, 'https://coverartarchive.org/release-group/' || a.musicbrainz_id || '/front-250.jpg'
            from albums a
            left join album_images ai on a.album_id = ai.album_id
            where a.musicbrainz_id is not null and ai.image_url is null
        """)
        )
        conn.commit()
        fetch_missing_metadata(conn)
        add_placeholder_tracks(conn)
    conn.close()


if __name__ == "__main__":
    conn = get_conn()
    if conn is None:
        raise OperationalError("No database connection available.")
    init_library(rescan=True, conn=conn)
    conn.close()
