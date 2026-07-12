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
import logging
import re
from pathlib import Path

import mutagen
from sqlalchemy import text

import db
import library
import ws
from config import config, get_ytdlp_path

logger = logging.getLogger(__name__)

_downloads: dict[str, dict] = {}


def get_download_status(song_id: str) -> dict | None:
    return _downloads.get(song_id)


async def download_song(song_id: str, song_name: str, artist_name: str) -> bool:
    if song_id in _downloads and _downloads[song_id].get("status") in ("downloading",):
        logger.warning("Download already in progress for %s", song_id)
        return False

    download_path = Path(
        config.get("download_path", "~/Azalea Library/Downloads")
    ).expanduser()
    download_path.mkdir(parents=True, exist_ok=True)

    output_template = str(download_path / "%(title)s.%(ext)s")
    search_query = f"ytsearch1:{artist_name} - {song_name}"

    _downloads[song_id] = {
        "song_id": song_id,
        "status": "downloading",
        "progress": 0,
        "speed": None,
        "eta": None,
    }

    await ws.broadcast(
        {
            "type": "download_status",
            "song_id": song_id,
            "status": "downloading",
            "progress": 0,
        }
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            get_ytdlp_path(),
            "--cookies-from-browser",
            "firefox",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "-o",
            output_template,
            "--newline",
            search_query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        progress_pattern = re.compile(r"\[download\]\s+(\d+\.?\d*)%")
        output_lines = []

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            output_lines.append(line)

            m = progress_pattern.search(line)
            if m:
                progress = float(m.group(1))
                _downloads[song_id]["progress"] = progress
                _downloads[song_id]["speed"] = None
                _downloads[song_id]["eta"] = None

                speed_m = re.search(r"at\s+([\d.]+.?B/s)", line)
                if speed_m:
                    _downloads[song_id]["speed"] = speed_m.group(1)
                eta_m = re.search(r"ETA\s+(\S+)", line)
                if eta_m:
                    _downloads[song_id]["eta"] = eta_m.group(1)

                await ws.broadcast(
                    {
                        "type": "download_status",
                        "song_id": song_id,
                        "status": "downloading",
                        "progress": progress,
                        "speed": _downloads[song_id]["speed"],
                        "eta": _downloads[song_id]["eta"],
                    }
                )

        await proc.wait()

        if proc.returncode != 0:
            _downloads[song_id]["status"] = "failed"
            await ws.broadcast(
                {
                    "type": "download_status",
                    "song_id": song_id,
                    "status": "failed",
                }
            )
            logger.error("yt-dlp failed for %s - %s", artist_name, song_name)
            return False

        downloaded_file = None
        for line in output_lines:
            if "Destination" in line:
                m2 = re.search(r"Destination:\s+(.+)", line)
                if m2:
                    p = Path(m2.group(1).strip())
                    if p.suffix == ".mp3" and p.exists():
                        downloaded_file = p
                        break

        if not downloaded_file:
            files = sorted(
                download_path.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True
            )
            for f in files:
                if f.suffix == ".mp3" and f.is_file():
                    downloaded_file = f
                    break

        if downloaded_file and downloaded_file.exists():
            conn = db.get_conn()
            if conn is not None:
                song_info = (
                    conn.execute(
                        text(
                            "select album_id, collection_id from songs where song_id = :sid"
                        ),
                        {"sid": song_id},
                    )
                    .mappings()
                    .first()
                )

                if song_info:
                    album_id = song_info["album_id"]
                    collection_id = song_info["collection_id"]

                    album_name = None
                    collections = library.get_collections()
                    collection = collections.get(collection_id)

                    if collection and collection.get("paths"):
                        collection_root = Path(collection["paths"][0]).expanduser()
                        album_row = (
                            conn.execute(
                                text("select name from albums where album_id = :aid"),
                                {"aid": album_id},
                            )
                            .mappings()
                            .first()
                        )
                        if album_row:
                            album_name = album_row["name"]

                        if album_name:
                            target_dir = collection_root / artist_name / album_name
                            target_dir.mkdir(parents=True, exist_ok=True)
                            target_path = target_dir / downloaded_file.name
                            counter = 1
                            while target_path.exists():
                                stem = target_path.stem
                                ext = target_path.suffix
                                target_path = target_dir / f"{stem}_{counter}{ext}"
                                counter += 1
                            downloaded_file.rename(target_path)
                            downloaded_file = target_path

                conn.execute(
                    text("update songs set path = :path where song_id = :song_id"),
                    {"path": str(downloaded_file), "song_id": song_id},
                )
                try:
                    mf = mutagen.File(str(downloaded_file))
                    if mf is not None:
                        if hasattr(mf.info, "bitrate"):
                            conn.execute(
                                text(
                                    "update songs set bitrate = :bitrate where song_id = :song_id"
                                ),
                                {"bitrate": int(mf.info.bitrate), "song_id": song_id},
                            )
                        if hasattr(mf.info, "length"):
                            conn.execute(
                                text(
                                    "update songs set duration = :duration where song_id = :song_id"
                                ),
                                {
                                    "duration": int(mf.info.length * 1000),
                                    "song_id": song_id,
                                },
                            )
                except Exception:
                    pass
                conn.commit()
                conn.close()

            _downloads[song_id]["status"] = "completed"
            _downloads[song_id]["progress"] = 100
            _downloads[song_id]["path"] = str(downloaded_file)

            await ws.broadcast(
                {
                    "type": "download_status",
                    "song_id": song_id,
                    "status": "completed",
                    "progress": 100,
                    "path": str(downloaded_file),
                }
            )

            logger.info(
                "Downloaded: %s - %s -> %s", artist_name, song_name, downloaded_file
            )
            return True
        else:
            _downloads[song_id]["status"] = "failed"
            await ws.broadcast(
                {
                    "type": "download_status",
                    "song_id": song_id,
                    "status": "failed",
                    "error": "Downloaded file not found",
                }
            )
            return False

    except Exception as e:
        logger.exception("Download failed for %s - %s", artist_name, song_name)
        _downloads[song_id]["status"] = "failed"
        await ws.broadcast(
            {
                "type": "download_status",
                "song_id": song_id,
                "status": "failed",
                "error": str(e),
            }
        )
        return False
