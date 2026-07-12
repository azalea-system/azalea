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
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from config import config

logger = logging.getLogger(__name__)


def create_and_get_engine():
    try:
        if config["custom_database_uri"]:
            engine = create_engine(config["custom_database_uri"])
        else:
            db_path = Path(config["database_path"]).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 5})
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("SELECT 1"))
        return engine
    except Exception as e:
        logger.error("Failed to connect to database: %s", e)
        return None


engine = create_and_get_engine()


def get_conn() -> Connection | None:
    try:
        return engine.connect()
    except Exception as e:
        logger.error("Failed to get database connection: %s", e)
        return None


def init_db(rescan: bool, conn: Connection):
    if rescan:
        conn.execute(text("drop table if exists songs"))
        conn.execute(text("drop table if exists artists"))
        conn.execute(text("drop table if exists albums"))
        conn.execute(text("drop table if exists id3_frames"))
    conn.execute(
        text(
            "create table if not exists songs (song_id text, name text, artist_id text, album_id text, collection_id text, path text, bitrate smallint, bitrate_mode smallint, channels smallint, duration int, starred boolean, track smallint)"
        )
    )
    try:
        conn.execute(text("alter table songs add column starred boolean"))
    except Exception:
        pass
    try:
        conn.execute(text("alter table songs add column disc smallint default 1"))
    except Exception:
        pass
    conn.execute(
        text(
            "create table if not exists artists (artist_id text, name text, collection_id text, musicbrainz_id text, cover_art text, song_count int default 0, album_count int default 0)"
        )
    )
    try:
        conn.execute(text("alter table artists add column cover_art text"))
    except Exception:
        pass
    try:
        conn.execute(text("alter table artists add column inception_year text"))
    except Exception:
        pass
    conn.execute(
        text(
            "create table if not exists albums (album_id text, artist_id text, name text, collection_id text, musicbrainz_id text, song_count int default 0, release_date text, folder_name text)"
        )
    )
    conn.execute(
        text(
            "create table if not exists album_images (album_id text primary key, image_url text)"
        )
    )
    conn.execute(
        text(
            "create table if not exists musicbrainz_cache (type text, query text, result_limit smallint, result text)"
        )
    )
    conn.execute(
        text(
            "create table if not exists id3_frames (frame_id, song_id, frame_name text, frame_bytes blob)"
        )
    )
    conn.execute(
        text(
            "create table if not exists lyrics (song_id text, plain_lyrics text, synced_lyrics text)"
        )
    )
    try:
        conn.execute(text("alter table lyrics add column synced_lyrics text"))
    except Exception:
        pass
    conn.execute(
        text(
            "create table if not exists playlists (playlist_id text primary key, name text, comment text, owner text, public boolean, created text, changed text, song_count int default 0, duration int default 0)"
        )
    )
    conn.execute(
        text(
            "create table if not exists playlist_songs (id integer primary key autoincrement, playlist_id text, song_id text, sort_order int)"
        )
    )
