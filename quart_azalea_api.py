# Copyright (C) 2026 Ethan Martin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
import asyncio
import json
import logging
import re
import subprocess
import tempfile
import urllib.parse
from collections import defaultdict
from pathlib import Path

import aiohttp
import toml
from quart import Response, redirect, request, websocket
from quart_cors import websocket_cors
from sqlalchemy import text

import db
import downloader
import library
import subsonic
import ws
from config import config, core, get_ytdlp_path, save_config

logger = logging.getLogger(__name__)


def hash_password_pbkdf2(password: str, iterations: int = 200_000) -> str:
    """Helper duplicated or imported for configuration updates."""
    import hashlib
    import os

    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def add_routes(app):
    @app.route("/auth-config", methods=["GET", "POST"])
    async def auth_config():
        if request.method == "GET":
            return {
                "auth": config.get("auth", False),
                "auth_username": config.get("auth_username", "admin"),
                "has_password": bool(config.get("auth_password")),
            }

        data = await request.get_json()
        cfg_path = Path("config.toml")
        cfg = toml.load(cfg_path) if cfg_path.exists() else {}

        cfg["auth"] = bool(data.get("auth", False))
        if "auth_username" in data:
            cfg["auth_username"] = data["auth_username"]
        if "auth_password" in data and data["auth_password"]:
            import hashlib

            cfg["auth_password"] = hash_password_pbkdf2(data["auth_password"])
            cfg["auth_token"] = hashlib.md5(
                data["auth_password"].encode("utf-8")
            ).hexdigest()

        with open(cfg_path, "w") as f:
            toml.dump(cfg, f)

        config["auth"] = cfg["auth"]
        if "auth_username" in cfg:
            config["auth_username"] = cfg["auth_username"]
        if "auth_password" in cfg:
            config["auth_password"] = cfg["auth_password"]
        if "auth_token" in cfg:
            config["auth_token"] = cfg["auth_token"]

        return {"status": "ok"}

    @app.route("/update/manifest", methods=["GET"])
    async def update_manifest():
        update_server_url = config.get(
            "update_server_url", "https://azalea-updates.vercel.app"
        )
        update_channel = config.get("update_channel", "special-pre-release")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{update_server_url}/manifest.json") as resp:
                if resp.status != 200:
                    return {"error": "Failed to fetch manifest"}, 502
                manifest = await resp.json()
        manifest["serverChannel"] = update_channel
        manifest["serverUrl"] = update_server_url
        return manifest

    @app.route("/update/channel", methods=["POST"])
    async def update_channel():
        data = await request.get_json()
        channel = data.get("channel")
        if not channel:
            return {"error": "channel is required"}, 400
        save_config({"update_channel": channel})
        return {"status": "ok", "channel": channel}

    @app.route("/update/trigger", methods=["POST"])
    async def update_trigger():
        app.update_status = None
        update_server_url = config.get(
            "update_server_url", "https://azalea-updates.vercel.app"
        )
        update_channel = config.get("update_channel", "special-pre-release")
        current_version = core.get("version", "")

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{update_server_url}/manifest.json") as resp:
                if resp.status != 200:
                    return {"error": "Failed to fetch manifest"}, 502
                manifest = await resp.json()

        channel_info = manifest.get("channels", {}).get(update_channel)
        if not channel_info:
            return {"error": f"Channel '{update_channel}' not found in manifest"}, 404

        versions = channel_info.get("versions", [])
        if versions:
            latest_version = max(versions, key=_parse_version)
        else:
            latest_version = _bump_version(current_version)

        if not latest_version or _parse_version(latest_version) <= _parse_version(current_version):
            return {
                "error": "Already on the latest version",
                "current": current_version,
                "latest": latest_version or "",
            }, 400

        channel_passwords = config.get("update_channel_passwords", {})
        password = channel_passwords.get(update_channel) if channel_info.get("password") else None

        filename = f"Azalea {latest_version} Setup.exe"
        encoded_filename = urllib.parse.quote(filename)
        encoded_channel = urllib.parse.quote(update_channel)
        if password:
            encoded_password = urllib.parse.quote(password)
            download_url = f"{update_server_url}/{encoded_channel}/{encoded_password}/{encoded_filename}"
        else:
            download_url = f"{update_server_url}/{encoded_channel}/{encoded_filename}"

        app.update_status = {
            "status": "downloading",
            "version": latest_version,
            "message": f"Downloading Azalea {latest_version}..."
        }
        await ws.broadcast({
            "type": "update_status",
            "status": "downloading",
            "version": latest_version,
            "message": f"Downloading Azalea {latest_version}..."
        })

        tmp_dir = tempfile.gettempdir()
        exe_path = Path(tmp_dir) / f"Azalea {latest_version} Setup.exe"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as resp:
                    if resp.status != 200:
                        app.update_status = {
                            "status": "failed",
                            "version": latest_version,
                            "message": f"Download failed: update server returned HTTP {resp.status}"
                        }
                        await ws.broadcast({
                            "type": "update_status",
                            "status": "failed",
                            "version": latest_version,
                            "message": f"Download failed: update server returned HTTP {resp.status}"
                        })
                        app.update_status = None
                        return {"error": f"Failed to download update (HTTP {resp.status})"}, 502
                    with open(exe_path, "wb") as f:
                        f.write(await resp.read())
        except Exception as e:
            app.update_status = {
                "status": "failed",
                "version": latest_version,
                "message": f"Download failed: {e}"
            }
            await ws.broadcast({
                "type": "update_status",
                "status": "failed",
                "version": latest_version,
                "message": f"Download failed: {e}"
            })
            app.update_status = None
            raise

        subprocess.Popen(
            [
                "powershell",
                "-Command",
                f"Start-Process -FilePath '{exe_path}' -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'",
            ]
        )

        app.update_status = {
            "status": "completed",
            "version": latest_version,
            "message": "Update complete, restart azalea to apply."
        }
        await ws.broadcast({
            "type": "update_status",
            "status": "completed",
            "version": latest_version,
            "message": "Update complete, restart azalea to apply."
        })
        app.update_status = None

        return {
            "status": "ok",
            "message": f"Downloading Azalea {latest_version}",
            "version": latest_version,
        }

    @app.route("/rest/importPlaylist", methods=["POST"])
    async def import_playlist():
        data = await request.get_json()
        if not data:
            return {"error": "Request body must be JSON"}, 400

        name = (data.get("name") or "Imported Playlist").strip()
        import_type = data.get("type", "link")
        content = (data.get("content") or "").strip()

        if not content:
            return {"error": "No content provided"}, 400

        lines = [line.strip() for line in content.split("\n") if line.strip()]
        if not lines:
            return {"error": "No content provided"}, 400

        conn = db.get_conn()
        if conn is None:
            return {"error": "Database unavailable"}, 500

        existing_names = {
            row["name"] for row in conn.execute(
                text("select name from playlists")
            ).mappings()
        }
        if name in existing_names:
            counter = 2
            while f"{name} #{counter}" in existing_names:
                counter += 1
            name = f"{name} #{counter}"

        try:
            collections = library.get_collections()
            if not collections:
                return {"error": "No music collections configured"}, 500

            first_coll_id = list(collections.keys())[0]
            collection = collections[first_coll_id]

            download_path = Path(
                config.get("download_path", "~/Azalea Library/Downloads")
            ).expanduser()
            download_path.mkdir(parents=True, exist_ok=True)

            all_tracks = []
            for line in lines:
                query = f"ytsearch1:{line}" if import_type == "textual" else line
                tracks = await _resolve_ytdlp_items(query)
                all_tracks.extend(tracks)

            if not all_tracks:
                return {"error": "No tracks could be resolved from the provided input"}, 400

            tracks_by_uploader: dict[str, list[dict]] = defaultdict(list)
            for track in all_tracks:
                uploader = track.get("uploader") or "Unknown Artist"
                tracks_by_uploader[uploader].append(track)

            song_ids = []
            for uploader, tracks in tracks_by_uploader.items():
                artist_id, mbid = library.add_artist(uploader, collection, conn)
                album_id, _ = library.add_album(
                    mbid or "", artist_id, name, collection, conn, folder_name=artist_id
                )

                for i, track in enumerate(tracks):
                    title = track.get("title", "Unknown")
                    duration_ms = (track.get("duration") or 0) * 1000
                    track_url = track.get("webpage_url", "")

                    base_slug = library.slugify_name(title) or "unknown"
                    song_id = base_slug
                    counter = 1
                    while conn.execute(
                        text("select song_id from songs where song_id = :sid"),
                        {"sid": song_id},
                    ).first():
                        song_id = f"{base_slug}-{counter}"
                        counter += 1

                    conn.execute(
                        text(
                            "insert into songs "
                            "(song_id, name, artist_id, album_id, collection_id, track, disc, duration) "
                            "values (:sid, :name, :artist_id, :album_id, :coll_id, :track, 1, :dur)"
                        ),
                        {
                            "sid": song_id,
                            "name": title,
                            "artist_id": artist_id,
                            "album_id": album_id,
                            "coll_id": collection["id"],
                            "track": i + 1,
                            "dur": duration_ms,
                        },
                    )

                    song_ids.append(song_id)

                    asyncio.create_task(
                        _download_imported_track(song_id, track_url, download_path)
                    )

                conn.execute(
                    text("update albums set song_count = :count where album_id = :aid"),
                    {"count": len(tracks), "aid": album_id},
                )

            conn.commit()

            playlist_id = library.create_playlist(conn, name)
            library.add_to_playlist(conn, playlist_id, song_ids)

            playlist_data = library.get_playlist(conn, playlist_id)
            if playlist_data is None:
                return {"error": "Failed to create playlist"}, 500

            subsonic_playlist = subsonic.library_playlist_to_subsonic(playlist_data)

            return {
                "status": "ok",
                "playlist": subsonic_playlist,
            }

        except Exception as e:
            logger.exception("Import playlist failed")
            return {"error": str(e)}, 500
        finally:
            conn.close()


async def _resolve_ytdlp_items(url: str) -> list[dict]:
    """Resolve a URL or search query to a list of track metadata dicts using yt-dlp."""
    proc = await asyncio.create_subprocess_exec(
        get_ytdlp_path(),
        "--dump-json",
        "--no-download",
        "--skip-download",
        "--no-warnings",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("yt-dlp resolve failed for %s: %s", url, stderr.decode(errors="replace").strip())
        return []

    tracks = []
    for line in stdout.decode(errors="replace").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
            tracks.append({
                "title": info.get("title", "Unknown"),
                "uploader": info.get("uploader", info.get("channel", "Imported Music")),
                "duration": info.get("duration") or 0,
                "webpage_url": info.get("webpage_url") or info.get("url") or url,
            })
        except json.JSONDecodeError:
            continue
    return tracks


async def _download_imported_track(song_id: str, url: str, download_path: Path):
    """Download audio from a URL using yt-dlp and update the song path in DB."""
    output_template = str(download_path / "%(title)s.%(ext)s")

    await ws.broadcast({
        "type": "download_status",
        "song_id": song_id,
        "status": "starting",
        "progress": 0,
    })

    proc = await asyncio.create_subprocess_exec(
        get_ytdlp_path(),
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", output_template,
        "--newline",
        "--no-warnings",
        "--print", "after_move:filepath",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    await ws.broadcast({
        "type": "download_status",
        "song_id": song_id,
        "status": "downloading",
        "progress": 0,
    })

    output_lines = []
    progress_pattern = re.compile(r"\[download\]\s+(\d+\.?\d*)%")
    downloaded_path = None

    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        output_lines.append(line)

        p = Path(line)
        if p.suffix == ".mp3" and p.exists():
            downloaded_path = p

        m = progress_pattern.search(line)
        if m:
            progress = float(m.group(1))
            msg: dict = {
                "type": "download_status",
                "song_id": song_id,
                "status": "downloading",
                "progress": progress,
            }
            speed_m = re.search(r"at\s+([\d.]+.?B/s)", line)
            if speed_m:
                msg["speed"] = speed_m.group(1)
            eta_m = re.search(r"ETA\s+(\S+)", line)
            if eta_m:
                msg["eta"] = eta_m.group(1)
            await ws.broadcast(msg)

    await proc.wait()

    if proc.returncode != 0:
        logger.error("yt-dlp import download failed for %s", url)
        await ws.broadcast({
            "type": "download_status",
            "song_id": song_id,
            "status": "failed",
            "progress": 0,
        })
        return False

    if not downloaded_path:
        for line in output_lines:
            p = Path(line)
            if p.suffix == ".mp3" and p.exists():
                downloaded_path = p
                break

    if not downloaded_path:
        files = sorted(download_path.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            if f.suffix == ".mp3" and f.is_file():
                downloaded_path = f
                break

    if downloaded_path and downloaded_path.exists():
        conn = db.get_conn()
        if conn is not None:
            try:
                song_row = conn.execute(
                    text(
                        "select s.artist_id, a.name as artist_name, s.album_id, "
                        "al.name as album_name, s.collection_id "
                        "from songs s "
                        "left join artists a on s.artist_id = a.artist_id "
                        "left join albums al on s.album_id = al.album_id "
                        "where s.song_id = :sid"
                    ),
                    {"sid": song_id},
                ).mappings().first()

                if song_row:
                    collections = library.get_collections()
                    coll = collections.get(song_row["collection_id"])
                    if coll and coll.get("paths"):
                        collection_root = Path(coll["paths"][0]).expanduser()
                        artist_name = song_row.get("artist_name") or "Unknown Artist"
                        album_name = song_row.get("album_name") or "Unknown Album"
                        target_dir = collection_root / artist_name / album_name
                        target_dir.mkdir(parents=True, exist_ok=True)
                        target_path = target_dir / downloaded_path.name
                        counter = 1
                        while target_path.exists():
                            stem = target_path.stem
                            ext = target_path.suffix
                            target_path = target_dir / f"{stem}_{counter}{ext}"
                            counter += 1
                        downloaded_path.rename(target_path)
                        downloaded_path = target_path

                conn.execute(
                    text("update songs set path = :path where song_id = :song_id"),
                    {"path": str(downloaded_path), "song_id": song_id},
                )

                try:
                    import mutagen
                    mf = mutagen.File(str(downloaded_path))
                    if mf is not None:
                        if hasattr(mf.info, "bitrate"):
                            conn.execute(
                                text("update songs set bitrate = :bitrate where song_id = :song_id"),
                                {"bitrate": int(mf.info.bitrate), "song_id": song_id},
                            )
                        if hasattr(mf.info, "length"):
                            conn.execute(
                                text("update songs set duration = :duration where song_id = :song_id"),
                                {"duration": int(mf.info.length * 1000), "song_id": song_id},
                            )
                except Exception:
                    pass

                conn.commit()
            finally:
                conn.close()

        await ws.broadcast({
            "type": "download_status",
            "song_id": song_id,
            "status": "completed",
            "progress": 100,
            "path": str(downloaded_path),
        })

        logger.info("Imported: %s -> %s", url, downloaded_path)
        return True

    await ws.broadcast({
        "type": "download_status",
        "song_id": song_id,
        "status": "failed",
        "progress": 0,
    })
    logger.error("No downloaded file found for %s", url)
    return False


def _parse_version(v: str):
    match = re.match(r"(\d+(?:\.\d+)*)([a-z]?)", v.strip())
    if not match:
        return (0,)
    nums = tuple(int(x) for x in match.group(1).split("."))
    suffix = match.group(2)
    suffix_val = {"a": 0, "b": 1}.get(suffix, 2)
    return nums + (suffix_val,)


def _split_version(v: str):
    match = re.match(r"(\d+(?:\.\d+)*)([a-z]?)", v.strip())
    if not match:
        return None, None
    nums = [int(x) for x in match.group(1).split(".")]
    suffix = match.group(2)
    return nums, suffix


def _bump_version(v: str):
    nums, suffix = _split_version(v)
    if nums is None:
        return None
    nums[-1] += 1
    version_str = ".".join(str(n) for n in nums)
    if suffix:
        version_str += suffix
    return version_str
