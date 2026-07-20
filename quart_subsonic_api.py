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
import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import xml.etree.ElementTree as ET
from base64 import b64decode
from pathlib import Path

import mutagen
import toml
from quart import Response, jsonify, redirect, request, send_file, websocket
from quart.wrappers.response import Response
from quart_cors import websocket_cors
from sqlalchemy import text

import db
import downloader
import imaging
import library
import metadata
import subsonic
import ws
from config import config, core, get_ytdlp_path


def hash_password_pbkdf2(password: str, iterations: int = 200_000) -> str:
    """Return a string of form pbkdf2_sha256$iterations$salt_hex$hash_hex"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password_hash(stored: str, provided: str) -> bool:
    """Verify a stored hash in pbkdf2_sha256 format against provided password."""
    try:
        if stored.startswith("pbkdf2_sha256$"):
            parts = stored.split("$")
            if len(parts) != 4:
                return False
            _, iter_s, salt_hex, hash_hex = parts
            iterations = int(iter_s)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(hash_hex)
            dk = hashlib.pbkdf2_hmac(
                "sha256", provided.encode("utf-8"), salt, iterations
            )
            return hmac.compare_digest(dk, expected)
        else:
            return hmac.compare_digest(stored, provided)
    except Exception:
        return False


def dict_to_xml_response(data: dict, root_name: str) -> Response:
    def build(parent, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    child = ET.SubElement(parent, k)
                    build(child, v)
                else:
                    parent.set(k, str(v).lower() if isinstance(v, bool) else str(v))
        elif isinstance(obj, list):
            for item in obj:
                child = ET.SubElement(parent, parent.tag)
                build(child, item)

    root_data = data[root_name]
    root = ET.Element(root_name)
    build(root, root_data)

    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(xml_bytes, mimetype="application/xml")


async def make_response(data: dict = {}, format: str = "") -> Response:
    if not format:
        format = request.args.get("f", "xml").lower()
    response = {
        "subsonic-response": {
            "status": "ok",
            "version": core["subsonic_version"],
            "type": core["name"],
            "serverVersion": core["version"],
            "openSubsonic": True,
        }
    }
    for key in data.keys():
        response["subsonic-response"][key] = data[key]
    if format == "json":
        response = jsonify(response)
    else:
        response = dict_to_xml_response(response, "subsonic-response")
    return response


async def make_error(error_code: int, message: str = ""):
    return await make_response({"error": {"code": error_code, "message": message}})


logger = logging.getLogger(__name__)


def _scan_library():
    conn = db.get_conn()
    if conn is None:
        return
    library.init_library(conn=conn, rescan=True)


async def run_scan(app):
    try:
        await ws.broadcast({"type": "scan_status", "scanning": True})
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _scan_library)
    finally:
        app.scanning = False
        await ws.broadcast({"type": "scan_status", "scanning": False})
        await broadcast_stats()


async def broadcast_stats():
    def _get_stats():
        conn = db.get_conn()
        if conn is None:
            return {}
        stats = library.get_stats(conn)
        conn.close()
        return stats

    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, _get_stats)
    if stats:
        await ws.broadcast({"type": "stats", "data": stats})


def _save_auth_token(token: str):
    cfg_path = Path("config.toml")
    try:
        cfg = toml.load(cfg_path) if cfg_path.exists() else {}
        cfg["auth_token"] = token
        with open(cfg_path, "w") as f:
            toml.dump(cfg, f)
    except Exception:
        pass


def add_routes(app):
    app.scanning = False

    @app.before_request
    async def _require_auth():
        if request.method == "OPTIONS":
            return None

        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None

        path = request.path or ""

        if not config.get("auth", False):
            return None

        if path == "/rest/ping" or path == "/auth-config":
            return None

        cfg_user = config.get("auth_username", "admin")
        cfg_pass = config.get("auth_password", "admin")
        cfg_token = config.get("auth_token")

        username_ok = False

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Basic "):
            try:
                decoded = b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
                user, pwd = decoded.split(":", 1)
                if hmac.compare_digest(user, cfg_user) and verify_password_hash(
                    cfg_pass, pwd
                ):
                    return None
            except Exception:
                pass

        u = request.args.get("u")
        if u and hmac.compare_digest(u, cfg_user):
            username_ok = True

        if username_ok:
            p = request.args.get("p")
            if p:
                if p.startswith("enc:"):
                    try:
                        p = bytes.fromhex(p[4:]).decode("utf-8")
                    except Exception:
                        p = None
                if p and verify_password_hash(cfg_pass, p):
                    if not cfg_token:
                        cfg_token = hashlib.md5(p.encode("utf-8")).hexdigest()
                        config["auth_token"] = cfg_token
                        try:
                            _save_auth_token(cfg_token)
                        except Exception:
                            pass
                    return None

            t = request.args.get("t")
            s = request.args.get("s")
            if t and s and cfg_token:
                expected = hashlib.md5((cfg_token + s).encode("utf-8")).hexdigest()
                if hmac.compare_digest(expected, t):
                    return None

        logger.info(
            "Auth failed: path=%s args=%s headers=%s",
            path,
            dict(request.args),
            dict(request.headers),
        )
        return Response(
            "Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="Azalea"'}
        )

    async def strip_view_suffix():
        if request.path.endswith(".view"):
            new_path = request.path[:-5]
            query = request.query_string.decode()
            if query:
                new_path += "?" + query
            return redirect(new_path)

    @app.route("/rest/ping")
    async def ping():
        return await make_response()

    @app.route("/rest/getLicense")
    async def getLicense():
        return await make_response(
            {
                "license": {
                    "valid": True,
                    "email": "",
                    "licenseExpires": "",
                    "trialExpires": "",
                    "features": [],
                }
            }
        )

    @app.route("/rest/getMusicFolders")
    async def getMusicFolders():
        folders = []
        for cid, collection in library.get_collections().items():
            for path_str in collection.get("paths", []):
                folders.append(
                    {
                        "id": cid,
                        "name": collection.get("name", cid),
                    }
                )
                break
        return await make_response({"musicFolders": {"musicFolder": folders}})

    @app.route("/rest/getIndexes")
    async def getIndexes():
        conn = db.get_conn()
        if conn is None:
            return await make_response(
                {
                    "indexes": {
                        "ignoredArticles": config["ignored_articles"],
                        "index": [],
                        "shortcut": [],
                        "child": [],
                    }
                }
            )
        library_artists = library.get_artists(
            conn=conn, include_albums=False, include_songs=False
        )
        conn.close()

        def _first_letter(s: str) -> str:
            if not s:
                return "#"
            for ch in s:
                if ch.isalnum():
                    return ch.upper()
            return "#"

        groups: dict[str, list] = {}
        for a in library_artists:
            letter = _first_letter(a.get("name", ""))
            groups.setdefault(letter, []).append(
                {
                    "id": a["artist_id"],
                    "title": a["name"],
                    "artist": a["name"],
                    "coverArt": a["artist_id"],
                }
            )

        indexes = [
            {"name": letter, "artist": artists}
            for letter, artists in sorted(groups.items())
        ]
        return await make_response(
            {
                "indexes": {
                    "ignoredArticles": config["ignored_articles"],
                    "index": indexes,
                    "shortcut": [],
                    "child": [],
                }
            }
        )

    @app.route("/rest/getArtists")
    async def getArtists():
        conn = db.get_conn()
        if conn is None:
            return await make_response(
                {
                    "artists": {
                        "ignoredArticles": config["ignored_articles"],
                        "index": [],
                    }
                }
            )
        library_artists = library.get_artists(conn=conn, include_songs=False)
        conn.close()

        def _first_letter(s: str) -> str:
            if not s:
                return "#"
            for ch in s:
                if ch.isalnum():
                    return ch.upper()
            return "#"

        groups: dict[str, list] = {}
        for la in library_artists:
            letter = _first_letter(la.get("name", ""))
            groups.setdefault(letter, []).append(
                subsonic.library_artist_to_subsonic(la)
            )

        indexes = [
            {"name": letter, "artist": artists}
            for letter, artists in sorted(groups.items())
        ]
        return await make_response(
            {
                "artists": {
                    "ignoredArticles": config["ignored_articles"],
                    "index": indexes,
                }
            }
        )

    @app.route("/rest/getArtist")
    async def getArtist():
        artist_id = request.args.get("id")
        if not artist_id:
            return await make_error(10, "Artist ID missing")
        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Artist not found")
        artists = library.get_artists(conn=conn, artist_id=artist_id)
        conn.close()
        if not artists:
            return await make_error(70, "Artist not found")
        return await make_response(
            {"artist": subsonic.library_artist_to_subsonic(artists[0])}
        )

    @app.route("/rest/getAlbum")
    async def getAlbum():
        album_id = request.args.get("id")
        if not album_id:
            return await make_error(10, "Album ID missing")
        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Album not found")
        library_albums = library.get_albums(
            conn=conn, album_id=album_id, include_artists=True
        )
        conn.close()
        if not library_albums:
            return await make_error(70, "Album not found")
        return await make_response(
            {
                "album": subsonic.library_album_to_subsonic(
                    library_albums[0], include_songs=True
                )
            }
        )

    @app.route("/rest/getAlbumList")
    async def getAlbumList():
        return await _get_album_list(use_v2=False)

    @app.route("/rest/getAlbumList2")
    async def getAlbumList2():
        return await _get_album_list(use_v2=True)

    async def _get_album_list(use_v2: bool):
        list_type = request.args.get("type", "alphabeticalByName")
        offset = int(request.args.get("offset", 0))
        size = int(request.args.get("size", 10))

        conn = db.get_conn()
        if conn is None:
            albums = []
        else:
            library_albums = library.get_albums(conn=conn, include_songs=False)
            conn.close()
            if list_type == "newest":
                albums = sorted(
                    library_albums,
                    key=lambda a: a.get("release_date") or "",
                    reverse=True,
                )
            elif list_type == "random":
                random.shuffle(library_albums)
                albums = library_albums
            elif list_type == "alphabeticalByArtist":
                albums = sorted(
                    library_albums,
                    key=lambda a: a.get("artist_name") or a.get("name") or "",
                )
            elif list_type == "starred":
                albums = [a for a in library_albums if a.get("starred")]
            else:
                albums = sorted(library_albums, key=lambda a: a.get("name") or "")

        albums = albums[offset : offset + size]
        subsonic_albums = subsonic.library_albums_to_subsonic(
            albums, include_songs=False
        )

        key = "albumList2" if use_v2 else "albumList"
        return await make_response({key: {"album": subsonic_albums}})

    @app.route("/rest/getSong")
    async def getSong():
        song_id = request.args.get("id")
        if not song_id:
            return await make_error(10, "Song ID missing")
        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Song not found")
        songs = library.get_songs(conn=conn, song_id=song_id)
        conn.close()
        if not songs:
            return await make_error(70, "Song not found")
        return await make_response(
            {"song": subsonic.library_song_to_subsonic(songs[0])}
        )

    @app.route("/rest/getMusicDirectory")
    async def getMusicDirectory():
        dir_id = request.args.get("id")
        if not dir_id:
            return await make_error(10, "Directory ID missing")

        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Directory not found")

        children = []
        try:
            albums = library.get_albums(
                conn=conn, album_id=dir_id, include_artists=True
            )
            if albums:
                album = albums[0]
                songs = library.get_songs(conn=conn, album_id=dir_id)
                for s in songs:
                    children.append(subsonic.library_song_to_subsonic(s))
                conn.close()
                folder_name = album.get("name", "Unknown")
                parent_id = album.get("artist_id", "")
                return await make_response(
                    {
                        "directory": {
                            "id": dir_id,
                            "name": folder_name,
                            "parent": parent_id,
                            "child": children,
                        }
                    }
                )

            artists = library.get_artists(conn=conn, artist_id=dir_id)
            if artists:
                artist = artists[0]
                for alb in artist.get("albums", []):
                    children.append(
                        {
                            "id": alb["album_id"],
                            "title": alb.get("name", "Unknown"),
                            "isDir": True,
                            "parent": dir_id,
                            "coverArt": alb["album_id"],
                            "artist": artist.get("name", "Unknown Artist"),
                            "artistId": dir_id,
                        }
                    )
                conn.close()
                return await make_response(
                    {
                        "directory": {
                            "id": dir_id,
                            "name": artist.get("name", "Unknown"),
                            "parent": "",
                            "child": children,
                        }
                    }
                )

            song = library.get_songs(conn=conn, song_id=dir_id)
            if song:
                s = song[0]
                children.append(subsonic.library_song_to_subsonic(s))
                conn.close()
                return await make_response(
                    {
                        "directory": {
                            "id": dir_id,
                            "name": s.get("name", "Unknown"),
                            "parent": s.get("album_id", ""),
                            "child": children,
                        }
                    }
                )
        except Exception:
            conn.close()
            return await make_error(70, "Directory not found")

        conn.close()
        return await make_error(70, "Directory not found")

    @app.route("/rest/stream")
    async def stream():
        conn = db.get_conn()
        if conn is None:
            return "Song not found", 404
        songs = library.get_songs(conn=conn, song_id=request.args["id"])
        conn.close()
        if not songs:
            return "Song not found", 404
        song_path = songs[0].get("path")
        if not song_path:
            song_name = songs[0].get("name", "Unknown")
            artist_name = songs[0].get("artist_name", "Unknown Artist")
            search_query = f"ytsearch1:{artist_name} - {song_name}"
            proc = await asyncio.create_subprocess_exec(
                get_ytdlp_path(),
                "--get-url",
                "--cookies-from-browser",
                "firefox",
                "--format",
                "bestaudio[ext=m4a]/bestaudio",
                search_query,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            url = stdout.decode("utf-8", errors="replace").strip()
            if url:
                return redirect(url)
            return "Song not found", 404
        filepath = Path(song_path)
        if not filepath.exists():
            return "Song not found", 404

        file_size = filepath.stat().st_size
        range_header = request.headers.get("Range")
        if range_header:
            try:
                units, rng = range_header.split("=", 1)
                if units.strip() != "bytes":
                    raise ValueError("Unsupported units")
                start_s, end_s = rng.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else file_size - 1
                if start < 0:
                    start = 0
                if end >= file_size:
                    end = file_size - 1
            except Exception:
                start = 0
                end = file_size - 1
            length = end - start + 1
            data = filepath.open("rb").read()[start : end + 1]
            headers = {
                "Content-Type": "audio/mpeg",
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            }
            return Response(data, status=206, headers=headers)
        else:
            data = filepath.open("rb").read()
            headers = {
                "Content-Type": "audio/mpeg",
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            }
            return Response(data, headers=headers)

    @app.route("/rest/download")
    async def download():
        return await stream()

    _cover_cache: dict = {}

    def _extract_cover(filepath: str):
        try:
            audio = mutagen.File(filepath, easy=False)
            if audio is None:
                return None
            if hasattr(audio, "pictures") and audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime
            if hasattr(audio, "tags") and audio.tags:
                if hasattr(audio.tags, "get"):
                    vals = audio.tags.get("METADATA_BLOCK_PICTURE")
                    if vals:
                        for val in vals:
                            try:
                                pic = mutagen.flac.Picture(b64decode(val))
                                return pic.data, pic.mime
                            except Exception:
                                continue
                if hasattr(audio.tags, "get"):
                    covr = audio.tags.get("covr")
                    if covr:
                        data = covr[0]
                        mime = "image/jpeg"
                        if hasattr(data, "imageformat"):
                            fmt = data.imageformat
                            if fmt == data.FORMAT_PNG:
                                mime = "image/png"
                            elif fmt == data.FORMAT_BMP:
                                mime = "image/bmp"
                        if hasattr(data, "picture"):
                            return data.picture, mime
                        return bytes(data), mime
                if hasattr(audio.tags, "values"):
                    for tag in audio.tags.values():
                        if isinstance(tag, mutagen.id3.APIC):
                            return tag.data, tag.mime
        except Exception:
            pass
        return None

    def _resolve_image(cache_dir: Path, image_id: str, size: int | None = None):
        """Look up a cached image in sized subdirectories, picking the best match."""
        if not cache_dir.exists():
            return None
        if size is not None:
            for s in imaging.SIZES:
                if s >= size:
                    cached = cache_dir / str(s) / f"{image_id}.jpg"
                    if cached.exists():
                        return cached.read_bytes(), "image/jpeg"
            for s in reversed(imaging.SIZES):
                cached = cache_dir / str(s) / f"{image_id}.jpg"
                if cached.exists():
                    return cached.read_bytes(), "image/jpeg"
            return None
        for s in reversed(imaging.SIZES):
            cached = cache_dir / str(s) / f"{image_id}.jpg"
            if cached.exists():
                return cached.read_bytes(), "image/jpeg"
        return None

    def _resolve_artist_cover(artist_id: str, size: int | None = None):
        """Serve a sized artist image from .artist_images subdirectories."""
        cache_dir = Path(config["library_path"]).expanduser() / ".artist_images"
        return _resolve_image(cache_dir, artist_id, size)

    def _resolve_album_cover(album_id: str, size: int | None = None):
        """Serve a sized album image from .album_images subdirectories."""
        cache_dir = Path(config["library_path"]).expanduser() / ".album_images"
        return _resolve_image(cache_dir, album_id, size)

    @app.route("/rest/getCoverArt")
    async def getCoverArt():
        cover_id = request.args.get("id")
        if not cover_id:
            return await make_error(10, "Cover ID missing")
        size_param = request.args.get("size")
        size = int(size_param) if size_param else None

        cache_key = f"{cover_id}:{size}" if size else cover_id
        if cache_key in _cover_cache:
            data, mime = _cover_cache[cache_key]
            return Response(data, mimetype=mime)

        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Cover art not found")
        try:
            album_result = _resolve_album_cover(cover_id, size)
            if album_result:
                data, mime = album_result
                _cover_cache[cache_key] = (data, mime)
                conn.close()
                return Response(data, mimetype=mime)

            artist_result = _resolve_artist_cover(cover_id, size)
            if artist_result:
                data, mime = artist_result
                _cover_cache[cache_key] = (data, mime)
                conn.close()
                return Response(data, mimetype=mime)

            songs = library.get_songs(conn=conn, song_id=cover_id)
            filepath = None
            if songs:
                filepath = songs[0]["path"]
            else:
                album_songs = library.get_songs(conn=conn, album_id=cover_id)
                if album_songs:
                    filepath = album_songs[0]["path"]
                else:
                    artists = library.get_artists(
                        conn=conn,
                        artist_id=cover_id,
                        include_albums=True,
                        include_songs=False,
                    )
                    if artists and artists[0].get("albums"):
                        first_album_id = artists[0]["albums"][0]["album_id"]
                        album_songs = library.get_songs(
                            conn=conn, album_id=first_album_id
                        )
                        if album_songs:
                            filepath = album_songs[0]["path"]
            if not filepath:
                conn.close()
                return await make_error(70, "Cover art not found")
            result = _extract_cover(filepath)
            if result:
                data, mime = result
                try:
                    album_cache_dir = (
                        Path(config["library_path"]).expanduser() / ".album_images"
                    )
                    imaging.transcode_image(
                        image_bytes=data, cache_dir=album_cache_dir, image_id=cover_id
                    )
                except Exception:
                    pass
                if size is not None:
                    best = imaging.pick_best_size(size)
                    if best is not None:
                        sized = _resolve_album_cover(cover_id, size)
                        if sized:
                            _cover_cache[cache_key] = sized
                            conn.close()
                            return Response(sized[0], mimetype=sized[1])
                _cover_cache[cache_key] = (data, mime)
                conn.close()
                return Response(data, mimetype=mime)
            conn.close()
            return await make_error(0, "No cover art found in file")
        except Exception:
            conn.close()
            return await make_error(0, "Error extracting cover art")

    @app.route("/rest/getLyrics")
    async def getLyrics():
        song_id = request.args.get("id")
        if not song_id:
            return await make_error(10, "Song ID missing")
        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Lyrics not found")
        try:
            row = (
                conn.execute(
                    text(
                        "select plain_lyrics, synced_lyrics from lyrics where song_id = :song_id"
                    ),
                    {"song_id": song_id},
                )
                .mappings()
                .first()
            )

            if row:
                if not (row.get("plain_lyrics") or row.get("synced_lyrics")):
                    conn.close()
                    return await make_error(70, "Lyrics not found")
                res = {
                    "songId": song_id,
                    "plainLyrics": row.get("plain_lyrics") or "",
                    "syncedLyrics": row.get("synced_lyrics") or "",
                }
                conn.close()
                return await make_response({"lyrics": res})

            try:
                song_row = (
                    conn.execute(
                        text(
                            "select s.song_id, s.name, a.name as artist_name, al.name as album_name, s.duration "
                            "from songs s "
                            "left join artists a on s.artist_id = a.artist_id "
                            "left join albums al on s.album_id = al.album_id "
                            "where s.song_id = :song_id"
                        ),
                        {"song_id": song_id},
                    )
                    .mappings()
                    .first()
                )

                if not song_row:
                    conn.close()
                    return await make_error(70, "Lyrics not found")

                loop = asyncio.get_event_loop()
                lyrics_data = await loop.run_in_executor(
                    None,
                    lambda: metadata.fetch_lyrics(
                        track_name=song_row["name"],
                        artist_name=song_row.get("artist_name") or "Unknown Artist",
                        album_name=song_row.get("album_name"),
                        duration=song_row.get("duration"),
                    ),
                )

                if lyrics_data:
                    conn.execute(
                        text(
                            "insert into lyrics (song_id, plain_lyrics, synced_lyrics) values (:song_id, :plain_lyrics, :synced_lyrics)"
                        ),
                        {
                            "song_id": song_id,
                            "plain_lyrics": lyrics_data["plain_lyrics"],
                            "synced_lyrics": lyrics_data["synced_lyrics"],
                        },
                    )
                    conn.commit()
                    conn.close()
                    return await make_response(
                        {
                            "lyrics": {
                                "songId": song_id,
                                "plainLyrics": lyrics_data.get("plain_lyrics") or "",
                                "syncedLyrics": lyrics_data.get("synced_lyrics") or "",
                            }
                        }
                    )

                conn.execute(
                    text(
                        "insert into lyrics (song_id, plain_lyrics, synced_lyrics) values (:song_id, '', '')"
                    ),
                    {"song_id": song_id},
                )
                conn.commit()
                conn.close()
                return await make_error(70, "Lyrics not found")

            except Exception as e:
                logger.error("On-demand lyrics fetch error for song %s: %s", song_id, e)
                try:
                    conn.execute(
                        text(
                            "insert into lyrics (song_id, plain_lyrics, synced_lyrics) values (:song_id, '', '')"
                        ),
                        {"song_id": song_id},
                    )
                    conn.commit()
                except Exception:
                    pass
                conn.close()
                return await make_error(70, "Lyrics not found")
        except Exception as e:
            logger.error("getLyrics error for song %s: %s", song_id, e)
            conn.close()
            return await make_error(0, f"Error fetching lyrics: {e}")

    @app.route("/rest/getSongsWithLyrics")
    async def getSongsWithLyrics():
        conn = db.get_conn()
        if conn is None:
            return await make_response({"songsWithLyrics": {"songId": []}})
        try:
            result = conn.execute(text("select song_id from lyrics")).mappings().all()
            conn.close()
            song_ids = [r["song_id"] for r in result]
            return await make_response({"songsWithLyrics": {"songId": song_ids}})
        except Exception as e:
            logger.error("getSongsWithLyrics error: %s", e)
            conn.close()
            return await make_response({"songsWithLyrics": {"songId": []}})

    @app.route("/rest/getRandomSongs")
    async def getRandomSongs():
        size = int(request.args.get("size", 10))
        conn = db.get_conn()
        if conn is None:
            return await make_response({"randomSongs": {"song": []}})
        songs = library.get_songs(conn=conn)
        conn.close()
        random.shuffle(songs)
        songs = songs[:size]
        return await make_response(
            {"randomSongs": {"song": subsonic.library_songs_to_subsonic(songs)}}
        )

    @app.route("/rest/getGenres")
    async def getGenres():
        return await make_response({"genres": {"genre": []}})

    @app.route("/rest/getSongsByGenre")
    async def getSongsByGenre():
        return await make_response({"songsByGenre": {"song": []}})

    @app.route("/rest/getCounts")
    async def getCounts():
        conn = db.get_conn()
        if conn is None:
            return await make_response(
                {"counts": {"songCount": 0, "albumCount": 0, "artistCount": 0}}
            )
        stats = library.get_stats(conn)
        conn.close()
        return await make_response(
            {
                "counts": {
                    "songCount": stats["songs"],
                    "albumCount": stats["albums"],
                    "artistCount": stats["artists"],
                }
            }
        )

    @app.route("/rest/getNowplaying")
    async def getNowplaying():
        from main import get_nowplaying_state

        nowplaying = await get_nowplaying_state()

        if not nowplaying:
            return await make_response({"nowplaying": None})

        start_time = nowplaying.get("startTime")
        if start_time and start_time > 100000000000:
            start_time //= 1000

        nowplaying_data = {
            "songId": nowplaying.get("song_id"),
            "title": nowplaying.get("title", ""),
            "artist": nowplaying.get("artist", ""),
            "album": nowplaying.get("album", ""),
            "duration": nowplaying.get("duration", 0),
            "startTime": start_time,
            "albumId": nowplaying.get("album_id"),
        }
        album_id = nowplaying.get("album_id")
        if album_id:
            try:
                conn = db.get_conn()
                if conn is not None:
                    res = conn.execute(
                        text(
                            "select image_url from album_images where album_id = :album_id limit 1"
                        ),
                        {"album_id": album_id},
                    ).mappings().first()
                    if res and res.get("image_url"):
                        nowplaying_data["imageUrl"] = res.get("image_url")
                    conn.close()
            except Exception:
                pass
        return await make_response({"nowplaying": nowplaying_data})

    @app.route("/rest/getStarred")
    async def getStarred():
        return await _get_starred(use_v2=False)

    @app.route("/rest/getStarred2")
    async def getStarred2():
        return await _get_starred(use_v2=True)

    async def _get_starred(use_v2: bool):
        conn = db.get_conn()
        if conn is None:
            empty = {"song": [], "album": [], "artist": []}
            key = "starred2" if use_v2 else "starred"
            return await make_response({key: empty})
        songs = library.get_songs(conn=conn)
        conn.close()
        starred_songs = [s for s in songs if s.get("starred")]
        key = "starred2" if use_v2 else "starred"
        return await make_response(
            {
                key: {
                    "song": subsonic.library_songs_to_subsonic(starred_songs),
                    "album": [],
                    "artist": [],
                }
            }
        )

    @app.route("/rest/star")
    async def star():
        ids = []
        song_id = request.args.get("id")
        if song_id:
            ids.append(song_id)
        for key in ("albumId", "artistId"):
            val = request.args.get(key)
            if val:
                ids.append(val)

        if ids:
            conn = db.get_conn()
            if conn is not None:
                try:
                    for sid in ids:
                        library.star_song(sid, conn)
                    conn.commit()
                except Exception as e:
                    conn.close()
                    logger.exception("Failed to star song(s)")
                    return await make_error(0, str(e))
                conn.close()
        return await make_response()

    @app.route("/rest/unstar")
    async def unstar():
        ids = []
        song_id = request.args.get("id")
        if song_id:
            ids.append(song_id)
        for key in ("albumId", "artistId"):
            val = request.args.get(key)
            if val:
                ids.append(val)

        if ids:
            conn = db.get_conn()
            if conn is not None:
                try:
                    for sid in ids:
                        library.star_song(sid, conn, False)
                    conn.commit()
                except Exception as e:
                    conn.close()
                    logger.exception("Failed to unstar song(s)")
                    return await make_error(0, str(e))
                conn.close()
        return await make_response()

    @app.route("/rest/removeSong")
    async def remove_song():
        song_id = request.args.get("id")
        if not song_id:
            return await make_error(10, "Song ID missing")

        conn = db.get_conn()
        songs = library.get_songs(conn=conn, song_id=song_id)
        if not songs:
            conn.close()
            return await make_error(70, "Song not found")

        song = songs[0]
        file_path = song.get("path")
        if file_path:
            try:
                path_obj = Path(file_path)
                if path_obj.exists():
                    path_obj.unlink()
            except Exception:
                pass

        library.remove_song(song_id, conn)
        conn.close()
        return await make_response()

    @app.route("/rest/scrobble")
    async def scrobble():
        return await make_response()

    @app.route("/rest/getNowPlaying")
    async def getNowPlaying():
        return await make_response({"nowPlaying": {"entry": []}})

    @app.route("/rest/setRating")
    async def setRating():
        return await make_response()

    @app.route("/rest/search")
    async def search():
        return await _search(use_v3=False)

    @app.route("/rest/search2")
    async def search2():
        return await _search(use_v3=False)

    @app.route("/rest/search3")
    async def search3():
        return await _search(use_v3=True)

    async def _search(use_v3: bool):
        query = request.args.get("query", "")
        artistCount = int(request.args.get("artistCount", 20))
        albumCount = int(request.args.get("albumCount", 20))
        songCount = int(request.args.get("songCount", 20))
        artistOffset = int(request.args.get("artistOffset", 0))
        albumOffset = int(request.args.get("albumOffset", 0))
        songOffset = int(request.args.get("songOffset", 0))

        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "No results.")
        library_results = library.search(query, conn)
        conn.close()
        if not library_results:
            return await make_error(70, "No results.")

        songs = subsonic.library_songs_to_subsonic(library_results["songs"])[
            songOffset:
        ][:songCount]
        albums = subsonic.library_albums_to_subsonic(
            library_results["albums"], include_songs=False
        )[albumOffset:][:albumCount]
        artists = subsonic.library_artists_to_subsonic(library_results["artists"])[
            artistOffset:
        ][:artistCount]

        if use_v3:
            result = {
                "searchResult3": {"artist": artists, "album": albums, "song": songs}
            }
        else:
            result = {
                "searchResult2": {"artist": artists, "album": albums, "song": songs}
            }
        return await make_response(result)

    @app.route("/rest/getPlaylists")
    async def getPlaylists():
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            playlists = library.get_playlists(conn)
            return await make_response(
                {
                    "playlists": {
                        "playlist": subsonic.library_playlists_to_subsonic(playlists)
                    }
                }
            )
        finally:
            conn.close()

    @app.route("/rest/getPlaylist")
    async def getPlaylist():
        playlist_id = request.args.get("id", "")
        if not playlist_id:
            return await make_error(10, "Missing playlist id")
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            playlist = library.get_playlist(conn, playlist_id)
            if not playlist:
                return await make_error(70, "Playlist not found")
            return await make_response(
                {
                    "playlist": subsonic.library_playlist_to_subsonic(
                        playlist, playlist["entries"]
                    )
                }
            )
        finally:
            conn.close()

    @app.route("/rest/createPlaylist", methods=["GET", "POST"])
    async def createPlaylist():
        playlist_id = request.args.get("playlistId", "")
        name = request.args.get("name", "New Playlist")
        song_ids_str = request.args.get("songId", "")
        song_ids = song_ids_str.split(",") if song_ids_str else []
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            if playlist_id:
                library.update_playlist(conn, playlist_id, name=name, song_ids=song_ids)
                playlist = library.get_playlist(conn, playlist_id)
            else:
                pid = library.create_playlist(conn, name)
                if song_ids:
                    library.add_to_playlist(conn, pid, song_ids)
                playlist = library.get_playlist(conn, pid)
            if not playlist:
                return await make_error(70, "Playlist not found")
            return await make_response(
                {
                    "playlist": subsonic.library_playlist_to_subsonic(
                        playlist, playlist["entries"]
                    )
                }
            )
        finally:
            conn.close()

    @app.route("/rest/updatePlaylist", methods=["GET", "POST"])
    async def updatePlaylist():
        playlist_id = request.args.get("playlistId", "")
        if not playlist_id:
            return await make_error(10, "Missing playlist id")
        name = request.args.get("name", None)
        comment = request.args.get("comment", None)
        public_str = request.args.get("public", None)
        public = (public_str.lower() == "true") if public_str else None
        song_ids_str = request.args.get("songId", "")
        song_ids = song_ids_str.split(",") if song_ids_str else None
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            library.update_playlist(
                conn,
                playlist_id,
                name=name,
                comment=comment,
                public=public,
                song_ids=song_ids,
            )
            return await make_response({})
        finally:
            conn.close()

    @app.route("/rest/deletePlaylist", methods=["GET", "POST"])
    async def deletePlaylist():
        playlist_id = request.args.get("id", "")
        if not playlist_id:
            return await make_error(10, "Missing playlist id")
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            library.delete_playlist(conn, playlist_id)
            return await make_response({})
        finally:
            conn.close()

    @app.route("/rest/addToPlaylist", methods=["GET", "POST"])
    async def addToPlaylist():
        playlist_id = request.args.get("playlistId", "")
        song_ids_str = request.args.get("songId", "")
        song_ids = song_ids_str.split(",") if song_ids_str else []
        if not playlist_id:
            return await make_error(10, "Missing playlist id")
        if not song_ids:
            return await make_error(10, "Missing song id")
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            library.add_to_playlist(conn, playlist_id, song_ids)
            return await make_response({})
        finally:
            conn.close()

    @app.route("/rest/removeFromPlaylist", methods=["GET", "POST"])
    async def removeFromPlaylist():
        playlist_id = request.args.get("playlistId", "")
        indices_str = request.args.get("index", "")
        indices = [int(i) for i in indices_str.split(",") if i.strip()]
        if not playlist_id:
            return await make_error(10, "Missing playlist id")
        if not indices:
            return await make_error(10, "Missing index")
        conn = db.get_conn()
        if conn is None:
            return await make_error(0, "Database unavailable")
        try:
            library.remove_from_playlist(conn, playlist_id, indices)
            return await make_response({})
        finally:
            conn.close()

    @app.route("/rest/getUser")
    async def getUser():
        username = request.args.get("username", "admin")
        return await make_response(
            {
                "user": {
                    "username": username,
                    "email": "",
                    "scrobblingEnabled": True,
                    "maxBitRate": 0,
                    "adminRole": True,
                    "settingsRole": True,
                    "downloadRole": True,
                    "uploadRole": False,
                    "playlistRole": True,
                    "coverArtRole": False,
                    "commentRole": False,
                    "podcastRole": False,
                    "streamRole": True,
                    "jukeboxRole": False,
                    "shareRole": False,
                    "videoConversionRole": False,
                    "folder": [cid for cid in library.get_collections()],
                }
            }
        )

    @app.route("/rest/getScanStatus")
    async def getScanStatus():
        return await make_response(
            {
                "scanStatus": {
                    "scanning": app.scanning,
                    "count": 1 if app.scanning else 0,
                }
            }
        )

    @app.route("/rest/startScan")
    async def startScan():
        if not app.scanning:
            app.scanning = True
            asyncio.create_task(run_scan(app))
        return await make_response(
            {
                "scanStatus": {
                    "scanning": app.scanning,
                    "count": 1 if app.scanning else 0,
                }
            }
        )

    @app.route("/rest/getOpenSubsonicExtensions")
    async def getOpenSubsonicExtensions():
        return await make_response({"openSubsonicExtensions": {"extension": []}})

    @app.route("/rest/getVideos")
    async def getVideos():
        return await make_response({"videos": {"video": []}})

    @app.route("/rest/getVideoInfo")
    async def getVideoInfo():
        return await make_error(70, "Video not found")

    @app.route("/rest/getBookmarks")
    async def getBookmarks():
        return await make_response({"bookmarks": {"bookmark": []}})

    @app.route("/rest/createBookmark")
    async def createBookmark():
        return await make_response()

    @app.route("/rest/deleteBookmark")
    async def deleteBookmark():
        return await make_response()

    @app.route("/rest/getPlayQueue")
    async def getPlayQueue():
        return await make_response(
            {
                "playQueue": {
                    "current": "",
                    "position": 0,
                    "changedBy": "",
                    "changed": "",
                    "entry": [],
                }
            }
        )

    @app.route("/rest/savePlayQueue")
    async def savePlayQueue():
        return await make_response()

    @app.route("/rest/getShares")
    async def getShares():
        return await make_response({"shares": {"share": []}})

    @app.route("/rest/getInternetRadioStations")
    async def getInternetRadioStations():
        return await make_response(
            {"internetRadioStations": {"internetRadioStation": []}}
        )

    @app.route("/rest/getChatMessages")
    async def getChatMessages():
        return await make_response({"chatMessages": {"chatMessage": []}})

    @app.route("/rest/jukeboxControl")
    async def jukeboxControl():
        return await make_response(
            {
                "jukeboxStatus": {
                    "currentIndex": 0,
                    "playing": False,
                    "gain": 0,
                    "position": 0,
                }
            }
        )

    @app.route("/rest/restart")
    async def restart():
        logger.info("Restarting server...")

        async def _delayed_shutdown():
            await asyncio.sleep(1)
            await app.shutdown()

        asyncio.create_task(_delayed_shutdown())
        return await make_response()

    @app.route("/rest/getDiscordStatus")
    async def get_discord_status():
        connected = bool(config.get("discord_access_token"))
        return await make_response({"discordStatus": {"connected": connected}})

    @app.route("/rest/disconnectDiscord", methods=["POST", "OPTIONS"])
    async def disconnect_discord():
        if request.method == "OPTIONS":
            return Response("", status=204)
        config.pop("discord_access_token", None)
        config.pop("discord_refresh_token", None)
        logger.info("Discord disconnected by user")
        return await make_response({"discordStatus": {"connected": False}})

    @app.route("/rest/getArtistMusicBrainzAlbums")
    async def getArtistMusicBrainzAlbums():
        artist_id = request.args.get("id")
        if not artist_id:
            return await make_error(10, "Artist ID missing")
        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Database unavailable")
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: library.add_artist_musicbrainz_albums(artist_id, conn),
            )
            conn.close()
            return await make_response({"artistMusicBrainzAlbums": result})
        except Exception as e:
            conn.close()
            logger.exception("getArtistMusicBrainzAlbums failed")
            return await make_error(0, str(e))

    @app.route("/rest/downloadOnServer")
    async def download_on_server():
        song_id = request.args.get("id")
        if not song_id:
            return await make_error(10, "Song ID missing")

        status = downloader.get_download_status(song_id)
        if status and status.get("status") == "downloading":
            return await make_response(
                {
                    "downloadStatus": {
                        "songId": song_id,
                        "status": "downloading",
                        "progress": status.get("progress", 0),
                    }
                }
            )

        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Song not found")
        songs = library.get_songs(conn=conn, song_id=song_id)
        conn.close()

        if not songs:
            return await make_error(70, "Song not found")

        song = songs[0]
        song_name = song.get("name", "Unknown")
        artist_name = song.get("artist_name", "Unknown Artist")

        asyncio.create_task(downloader.download_song(song_id, song_name, artist_name))

        return await make_response(
            {
                "downloadStatus": {
                    "songId": song_id,
                    "status": "started",
                }
            }
        )

    @app.route("/rest/downloadAlbumOnServer")
    async def download_album_on_server():
        album_id = request.args.get("id")
        if not album_id:
            return await make_error(10, "Album ID missing")

        conn = db.get_conn()
        if conn is None:
            return await make_error(70, "Database unavailable")
        songs = library.get_songs(conn=conn, album_id=album_id)
        conn.close()

        placeholder_songs = [s for s in songs if not s.get("path")]
        if not placeholder_songs:
            return await make_response(
                {
                    "downloadStatus": {
                        "albumId": album_id,
                        "status": "no_placeholders",
                    }
                }
            )

        started = 0
        for song in placeholder_songs:
            song_id = song["song_id"]
            status = downloader.get_download_status(song_id)
            if status and status.get("status") == "downloading":
                continue
            asyncio.create_task(
                downloader.download_song(
                    song_id,
                    song.get("name", "Unknown"),
                    song.get("artist_name", "Unknown Artist"),
                )
            )
            started += 1

        return await make_response(
            {
                "downloadStatus": {
                    "albumId": album_id,
                    "status": "started",
                    "started": started,
                    "total": len(placeholder_songs),
                }
            }
        )

    @app.websocket("/rest/downloadEvents")
    @websocket_cors(allow_origin=config["allow_origin"])
    async def download_events():
        send_func = websocket.send
        ws.register(send_func)
        update_status = getattr(app, "update_status", None)
        if update_status:
            try:
                await send_func(json.dumps({
                    "type": "update_status",
                    **update_status
                }))
            except Exception:
                pass
        try:
            while True:
                await websocket.receive()
        except Exception:
            pass
        finally:
            ws.unregister(send_func)

    @app.route("/rest/<path:subsonic_path>")
    async def subsonic_fallback(subsonic_path: str):
        return await make_error(0, f"Unknown endpoint: {subsonic_path}")
