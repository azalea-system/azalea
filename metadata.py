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
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_in_progress: set = set()

import musicbrainzngs
from musicbrainzngs.musicbrainz import NetworkError
from sqlalchemy import text
from sqlalchemy.engine import Connection

from config import config, core

logger = logging.getLogger(__name__)


if not config["verify_ssl"]:
    import ssl

    ssl._create_default_https_context = ssl._create_unverified_context

musicbrainzngs.set_useragent(
    f"{core['name']}MetadataFetcher", core["version"], core["contact_email"]
)

cache_path = Path(config["library_path"], ".metadata_cache").expanduser()
cache_file = Path(cache_path, "musicbrainz_cache.json")


result_types = {
    "artist": [musicbrainzngs.search_artists, "artist-list"],
    "album": [musicbrainzngs.search_release_groups, "release-group-list"],
}


def get_cached_musicbrainz_response(
    result_type: str, query: str, limit: int, conn: Connection
) -> dict | None:
    result = conn.execute(
        text(
            "select result from musicbrainz_cache where type = :type and query = :query and result_limit = :result_limit"
        ),
        {"type": result_type, "query": query, "result_limit": limit},
    ).fetchone()
    if result:
        serialized_response = result[0]
        response = json.loads(serialized_response)
        return response
    return None


def cache_musicbrainz_response(
    result_type: str, query: str, result_limit: int, response: dict, conn: Connection
):
    serialized_response = json.dumps(response)
    logger.debug("Caching MusicBrainz response for %s %s", result_type, query)
    conn.execute(
        text(
            "insert into musicbrainz_cache (type, query, result_limit, result) values (:type, :query, :result_limit, :result)"
        ),
        {
            "type": result_type,
            "query": query,
            "result_limit": result_limit,
            "result": serialized_response,
        },
    )
    conn.commit()


def search_musicbrainz(
    result_type: str,
    query: str,
    conn: Connection,
    limit: int = 1,
    **fields,
):
    if not config["musicbrainz_metadata"]:
        return None
    existing_cache_item = get_cached_musicbrainz_response(
        result_type, query, limit, conn
    )
    if existing_cache_item:
        return existing_cache_item, result_types[result_type][1]
    successful = False
    tries = 0
    while not successful and tries < 5:
        tries += 1
        try:
            result = result_types[result_type][0](query, limit, **fields)
        except NetworkError:
            result = None
        if result:
            if result_types[result_type][1] in result.keys():
                successful = True
                if config["cache_musicbrainz_responses"]:
                    cache_musicbrainz_response(result_type, query, limit, result, conn)
                return result, result_types[result_type][1]
    return None, None


def artist_to_musicbrainz_data(artist_name: str, conn: Connection) -> dict | None:
    if not config["musicbrainz_metadata"]:
        return None
    result, contingent_key = search_musicbrainz("artist", artist_name, conn=conn)
    if result and contingent_key and result.get(contingent_key):
        artist_data = result[contingent_key][0]
        return artist_data


def artist_to_musicbrainz_id(artist_name: str, conn: Connection) -> str | None:
    if not config["musicbrainz_metadata"]:
        return None
    artist_data = artist_to_musicbrainz_data(artist_name, conn)
    if artist_data:
        artist_id = artist_data["id"]
        return artist_id


def artist_to_inception_year(artist_name: str, conn: Connection) -> str | None:
    if not config["musicbrainz_metadata"]:
        return None
    artist_data = artist_to_musicbrainz_data(artist_name, conn)
    if artist_data:
        life_span = artist_data.get("life-span", {})
        begin = life_span.get("begin")
        if begin and len(begin) >= 4:
            return begin[:4]
    return None


def album_to_musicbrainz_data(
    artist_musicbrainz_id: str, album_name: str, conn: Connection
):
    if not config["musicbrainz_metadata"]:
        return None
    result, contingent_key = search_musicbrainz(
        "album", album_name, artist=artist_musicbrainz_id, conn=conn
    )
    if result and contingent_key and result.get(contingent_key):
        rg_data = result[contingent_key][0]
        if rg_data.get("first-release-date"):
            rg_data["date"] = rg_data["first-release-date"]
        image_url = None
        if rg_data.get("id"):
            image_url = f"https://coverartarchive.org/release-group/{rg_data['id']}/front-250.jpg"
        rg_data["image_url"] = image_url
        return rg_data


def fetch_artist_image_url(artist_name: str) -> str | None:
    """Fetch artist profile image URL from Deezer public API (no key needed)."""
    url = f"https://api.deezer.com/search/artist?q={urllib.parse.quote(artist_name)}&limit=1"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0].get("picture_medium")
    except Exception:
        pass
    return None


def download_artist_image(artist_id: str, image_url: str) -> str | None:
    """Download artist image to local cache. Returns cache path or None."""
    from imaging import transcode_image

    cache_dir = Path(config["library_path"]).expanduser() / ".artist_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{artist_id}.jpg"
    try:
        _download_image(image_url, dest)
        transcode_image(source_path=str(dest), cache_dir=cache_dir, image_id=artist_id)
        return str(dest)
    except Exception:
        return None


def download_album_image(album_id: str, image_url: str) -> str | None:
    """Download album cover to local cache. Returns cache path or None."""
    from imaging import transcode_image

    cache_dir = Path(config["library_path"]).expanduser() / ".album_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{album_id}.jpg"
    try:
        _download_image(image_url, dest)
        transcode_image(source_path=str(dest), cache_dir=cache_dir, image_id=album_id)
        return str(dest)
    except Exception:
        return None


def _download_image(url: str, dest: Path) -> None:
    """Download a URL to a file path using urllib with a proper User-Agent."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Azalea/1.0 (music player)"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        with open(dest, "wb") as f:
            f.write(resp.read())


def fetch_artist_biography(artist_mbid: str, conn: Connection) -> str | None:
    """Fetch a short artist biography from Wikipedia via MusicBrainz URL relationships."""
    if not config["musicbrainz_metadata"]:
        return None

    result_type = "artist_bio"
    query = artist_mbid

    cached = get_cached_musicbrainz_response(result_type, query, 1, conn)
    if cached:
        bio = cached.get("biography")
        return bio if bio else None

    wiki_title = None
    tries = 0
    while not wiki_title and tries < 3:
        tries += 1
        try:
            artist_data = musicbrainzngs.get_artist_by_id(
                artist_mbid, includes=["url-rels"]
            )
        except NetworkError:
            artist_data = None
        if artist_data and artist_data.get("artist"):
            for rel in artist_data["artist"].get("relation-list", []):
                for r in rel.get("relation", []):
                    url = r.get("target", "")
                    if "wikipedia.org/wiki/" in url:
                        wiki_title = url.split("/wiki/")[-1]
                        break
                if wiki_title:
                    break

    if not wiki_title:
        if config["cache_musicbrainz_responses"]:
            cache_musicbrainz_response(result_type, query, 1, {"biography": ""}, conn)
        return None

    bio = None
    try:
        encoded_title = urllib.parse.quote(wiki_title.replace(" ", "_"), safe="")
        api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Azalea/1.0 (music server)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            bio = data.get("extract", "")
    except Exception:
        logger.debug("Wikipedia fetch failed for %s", wiki_title)

    if config["cache_musicbrainz_responses"]:
        cache_musicbrainz_response(
            result_type, query, 1, {"biography": bio or ""}, conn
        )
    return bio or None


def fetch_album_extra_images(
    album_musicbrainz_id: str, conn: Connection
) -> list[dict] | None:
    """Fetch extra album images (back cover, booklet) from CoverArtArchive.

    Returns a list of dicts like [{"image_url": "...", "image_type": "back"}, ...]
    or None if nothing found.
    """
    if not config["musicbrainz_metadata"]:
        return None

    result_type = "album_extra_images"
    query = album_musicbrainz_id

    cached = get_cached_musicbrainz_response(result_type, query, 1, conn)
    if cached:
        images = cached.get("images")
        return images if images else None

    images_result = []
    tries = 0
    while tries < 3:
        tries += 1
        try:
            url = f"https://coverartarchive.org/release-group/{album_musicbrainz_id}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Azalea/1.0 (music server)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                for img in data.get("images", []):
                    if img.get("front") and not img.get("approved", True):
                        continue
                    if img.get("back"):
                        images_result.append(
                            {
                                "image_url": img.get("image", ""),
                                "image_type": "back",
                            }
                        )
                    elif img.get("booklet"):
                        images_result.append(
                            {
                                "image_url": img.get("image", ""),
                                "image_type": "booklet",
                            }
                        )
                break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
        except Exception:
            pass

    if config["cache_musicbrainz_responses"]:
        cache_musicbrainz_response(
            result_type, query, 1, {"images": images_result}, conn
        )
    return images_result if images_result else None


def download_album_extra_image(
    album_id: str, image_url: str, image_type: str, index: int
) -> str | None:
    """Download an extra album image (back cover, booklet page) to local cache."""
    from imaging import transcode_image

    cache_dir = Path(config["library_path"]).expanduser() / ".album_images"
    cache_dir.mkdir(parents=True, exist_ok=True)
    image_id = f"{album_id}-{image_type}-{index}"
    dest = cache_dir / f"{image_id}.jpg"
    try:
        _download_image(image_url, dest)
        transcode_image(
            source_path=str(dest), cache_dir=cache_dir, image_id=image_id
        )
        return str(dest)
    except Exception:
        return None


def fetch_lyrics(
    track_name: str | None,
    artist_name: str | None,
    album_name: str | None = None,
    duration: int | None = None,
) -> dict | None:
    """Fetch synced lyrics from LRCLIB. Returns dict with plain_lyrics and synced_lyrics or None."""
    if not track_name or not artist_name:
        return None
    query = f"?artist_name={urllib.parse.quote(artist_name)}&track_name={urllib.parse.quote(track_name)}"
    if album_name:
        query += f"&album_name={urllib.parse.quote(album_name)}"
    url = f"https://lrclib.net/api/get{query}"
    logger.info("Fetching lyrics from LRCLIB: %s", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Azalea/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data and isinstance(data, dict):
                has_plain = bool(data.get("plainLyrics"))
                has_synced = bool(data.get("syncedLyrics"))
                logger.info(
                    "LRCLIB exact match: plain=%s synced=%s", has_plain, has_synced
                )
                return {
                    "plain_lyrics": data.get("plainLyrics") or "",
                    "synced_lyrics": data.get("syncedLyrics") or "",
                }
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info(
                "LRCLIB exact match returned 404 for: %s - %s", artist_name, track_name
            )
        else:
            logger.warning("LRCLIB HTTP error %d: %s", e.code, url)
    except Exception as e:
        logger.warning("LRCLIB exact match exception: %s", e)

    search_url = f"https://lrclib.net/api/search?artist_name={urllib.parse.quote(artist_name)}&track_name={urllib.parse.quote(track_name)}"
    if album_name:
        search_url += f"&album_name={urllib.parse.quote(album_name)}"
    logger.info("LRCLIB search fallback: %s", search_url)
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "Azalea/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
            if results and isinstance(results, list) and len(results) > 0:
                best = results[0]
                if duration and best.get("duration"):
                    for r in results:
                        if abs(r.get("duration", 0) - duration) < abs(
                            best.get("duration", 0) - duration
                        ):
                            best = r
                has_plain = bool(best.get("plainLyrics"))
                has_synced = bool(best.get("syncedLyrics"))
                logger.info(
                    "LRCLIB search found %d results, picked: plain=%s synced=%s",
                    len(results),
                    has_plain,
                    has_synced,
                )
                return {
                    "plain_lyrics": best.get("plainLyrics") or "",
                    "synced_lyrics": best.get("syncedLyrics") or "",
                }
            logger.info(
                "LRCLIB search returned 0 results for: %s - %s", artist_name, track_name
            )
    except Exception as e:
        logger.warning("LRCLIB search exception: %s", e)
    return None


def _fetch_and_store(
    track_name: str,
    artist_name: str,
    album_name: str | None,
    duration: int | None,
    song_id: str | None = None,
):
    """Background worker: fetch lyrics and persist to DB if found. Marks attempts to avoid retries."""
    key = song_id or f"{artist_name}\x00{track_name}\x00{album_name}"
    if key in _in_progress:
        return
    _in_progress.add(key)
    try:
        conn = None
        try:
            from db import get_conn

            conn = get_conn()
            if conn is None:
                return
            if song_id:
                result = conn.execute(
                    text("select song_id from lyrics where song_id = :song_id"),
                    {"song_id": song_id},
                ).fetchone()
                if result:
                    return
            lyrics = fetch_lyrics(track_name, artist_name, album_name, duration)
            if lyrics:
                conn.execute(
                    text(
                        "insert into lyrics (song_id, plain_lyrics, synced_lyrics) values (:song_id, :plain_lyrics, :synced_lyrics)"
                    ),
                    {
                        "song_id": song_id,
                        "plain_lyrics": lyrics["plain_lyrics"],
                        "synced_lyrics": lyrics["synced_lyrics"],
                    },
                )
                conn.commit()
            else:
                # mark attempted so we don't repeatedly try
                if song_id:
                    conn.execute(
                        text(
                            "insert into lyrics (song_id, plain_lyrics, synced_lyrics) values (:song_id, '', '')"
                        ),
                        {"song_id": song_id},
                    )
                    conn.commit()
        finally:
            if conn:
                conn.close()
    finally:
        _in_progress.discard(key)


def ensure_fetch_for_nowplaying(
    track_name: str,
    artist_name: str,
    album_name: str | None = None,
    duration: int | None = None,
):
    """Public helper: start a background fetch for the given track if not already in progress.
    This runs a thread and returns immediately."""
    key = f"{artist_name}\x00{track_name}\x00{album_name}"
    if key in _in_progress:
        return
    conn = None
    try:
        from db import get_conn

        conn = get_conn()
        if conn is not None:
            try:
                result = conn.execute(
                    text(
                        "select s.song_id from songs s "
                        "left join artists a on s.artist_id = a.artist_id "
                        "left join albums al on s.album_id = al.album_id "
                        "left join lyrics l on s.song_id = l.song_id "
                        "where l.song_id is null "
                        "and s.name = :name "
                        "and a.name = :artist_name "
                        "and al.name = :album_name"
                    ),
                    {
                        "name": track_name,
                        "artist_name": artist_name,
                        "album_name": album_name,
                    },
                ).fetchone()
                if result:
                    return
            except Exception:
                pass
    finally:
        if conn:
            conn.close()
    t = threading.Thread(
        target=_fetch_and_store,
        args=(track_name, artist_name, album_name, duration, None),
        daemon=True,
    )
    t.start()


def _get_release_from_release_group(release_group_mbid: str, conn: Connection) -> str | None:
    if not config["musicbrainz_metadata"]:
        return None

    result_type = "release_group_releases"
    query = release_group_mbid

    cached = get_cached_musicbrainz_response(result_type, query, 1, conn)
    if cached:
        release_list = cached.get("release-list")
        if release_list:
            return release_list[0].get("id")

    tries = 0
    while tries < 5:
        tries += 1
        try:
            result = musicbrainzngs.browse_releases(
                release_group=release_group_mbid,
                limit=100,
            )
        except NetworkError:
            result = None
        if result and result.get("release-list"):
            releases = result["release-list"]
            if releases:
                release_id = releases[0]["id"]
                result_data = {"release-list": [{"id": release_id}]}
                if config["cache_musicbrainz_responses"]:
                    try:
                        cache_musicbrainz_response(
                            result_type, query, 1, result_data, conn
                        )
                    except Exception:
                        pass
                return release_id
    return None


def album_to_track_listing(release_group_mbid: str, conn: Connection) -> list[dict] | None:
    if not config["musicbrainz_metadata"]:
        return None

    result_type = "release_group_tracks"
    query = release_group_mbid

    cached = get_cached_musicbrainz_response(result_type, query, 1, conn)
    if cached:
        track_list = cached.get("track-list")
        if track_list:
            return track_list

    release_mbid = _get_release_from_release_group(release_group_mbid, conn)
    if not release_mbid:
        return None

    tries = 0
    while tries < 5:
        tries += 1
        try:
            release = musicbrainzngs.get_release_by_id(
                release_mbid, includes=["recordings"]
            )
        except NetworkError:
            release = None
        if release and release.get("release"):
            medium_list = release["release"].get("medium-list", [])
            tracks: list[dict] = []
            for medium in medium_list:
                try:
                    disc_number = int(medium.get("position", 1))
                except (ValueError, TypeError):
                    disc_number = 1
                raw_track_list = medium.get("track-list") or []
                if isinstance(raw_track_list, dict):
                    track_entries = raw_track_list.get("track", [])
                else:
                    track_entries = raw_track_list
                for track_entry in track_entries:
                    try:
                        track_number = int(track_entry.get("number", 0))
                    except (ValueError, TypeError):
                        track_number = 0
                    recording = track_entry.get("recording", {})
                    title = recording.get("title") or "Unknown Track"
                    try:
                        duration = int(recording.get("length", 0))
                    except (ValueError, TypeError):
                        duration = 0
                    tracks.append(
                        {
                            "disc": disc_number,
                            "track": track_number,
                            "title": title,
                            "duration": duration,
                        }
                    )
            result_data = {"track-list": tracks}
            if config["cache_musicbrainz_responses"]:
                try:
                    cache_musicbrainz_response(result_type, query, 1, result_data, conn)
                except Exception:
                    pass
            return tracks
    return None


def get_artist_releases(artist_mbid: str, conn: Connection) -> list[dict] | None:
    if not config["musicbrainz_metadata"]:
        return None

    result_type = "artist_release_groups"
    query = artist_mbid

    cached = get_cached_musicbrainz_response(result_type, query, 100, conn)
    if cached:
        rg_list = cached.get("release-group-list")
        if rg_list:
            return rg_list

    tries = 0
    while tries < 5:
        tries += 1
        try:
            result = musicbrainzngs.browse_release_groups(
                artist=artist_mbid,
                limit=100,
                release_type=["album"],
            )
        except NetworkError:
            result = None
        if result and result.get("release-group-list"):
            rgs = result["release-group-list"]
            result_data = {"release-group-list": rgs}
            if config["cache_musicbrainz_responses"]:
                try:
                    cache_musicbrainz_response(
                        result_type, query, 100, result_data, conn
                    )
                except Exception:
                    pass
            return rgs
    return None


def album_to_musicbrainz_id(
    artist_musicbrainz_id: str, album_name: str, conn: Connection
):
    if not config["musicbrainz_metadata"]:
        return None
    album_data = album_to_musicbrainz_data(artist_musicbrainz_id, album_name, conn)
    if album_data:
        album_id = album_data["id"]
        return album_id
