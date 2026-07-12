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
import json

from quart import make_response, render_template, request, websocket
from quart_cors import websocket_cors
from sqlalchemy import text

import db
import library
import utils
import ws
from config import config, core, save_config

commit_reference = utils.get_command_output("git log -n 1 --pretty=format:'%H'")
commit_date_str = utils.get_command_output(
    "git log -1 --format=%cd --date=format:'%a %-d %B %H:%M'"
)
quart_debug = config["quart_debug"]
with open("static/favicon.svg", "r") as f:
    logo_svg = f.read()
    f.close()

defaults = {
    "name": core["name"],
    "tagline": core["tagline"],
    "author": core["author"],
    "author_link": core["author_link"],
    "github_link": core["github_link"],
    "copyright_year_range": core["copyright_year_range"],
    "version": core["version"],
    "collections": library.get_collections(),
    "collections_including_disabled": library.get_collections(
        only_include_enabled_collections=False
    ),
    "logo_svg": logo_svg,
}

defaults["cfg"] = config
defaults["auth_enabled"] = config.get("auth", False)
defaults["auth_username"] = config.get("auth_username", "admin")
defaults["has_password"] = bool(config.get("auth_password"))

for cid in defaults["collections"]:
    defaults["collections"][cid]["nav_entities"] = library.get_nav_entities(
        defaults["collections"][cid]
    )
for cid in defaults["collections_including_disabled"]:
    defaults["collections_including_disabled"][cid]["nav_entities"] = (
        library.get_nav_entities(defaults["collections_including_disabled"][cid])
    )


async def send_error(message: str, http_status_code: int):
    return await make_response(
        await render_template(
            "Error.html", **defaults, message=message, http_status_code=http_status_code
        ),
        http_status_code,
    )


async def run_fetch_metadata(app):
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _fetch_metadata_sync)
    finally:
        app.fetching_metadata = False
        await ws.broadcast({"type": "fetch_status", "fetching": False})

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


def _fetch_metadata_sync():
    conn = db.get_conn()
    if conn is None:
        return
    library.fetch_missing_metadata(conn)


def add_routes(app):
    app.fetching_metadata = False
    collections = defaults["collections"]

    @app.route("/")
    async def index():
        return await render_template(
            "Status.html",
            **defaults,
            commit_reference=commit_reference,
            commit_date_str=commit_date_str,
            quart_debug=quart_debug,
            apps=core["apps"],
        )

    @app.route("/browse")
    async def browse():
        return await render_template(
            "Collections.html",
            **defaults,
            crumbs=[{"name": "Home", "link": "/"}, {"name": "Collections"}],
        )

    @app.route("/browse/<collection_id>")
    async def browse_collection(collection_id: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        nav_entities = library.get_nav_entities(collection)
        return await render_template(
            "Collection.html",
            **defaults,
            collection=collection,
            nav_entities=nav_entities,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"]},
            ],
        )

    @app.route("/browse/<collection_id>/artists")
    async def artists(collection_id: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        artists = library.get_artists(conn=conn, collection_id=collection_id)
        conn.close()
        return await render_template(
            "Artists.html",
            **defaults,
            artists=artists,
            collection=collection,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Artists"},
            ],
        )

    @app.route("/browse/<collection_id>/albums")
    async def albums(collection_id: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        albums = library.get_albums(
            conn=conn,
            collection_id=collection_id,
            include_songs=False,
            include_artists=True,
        )
        conn.close()
        return await render_template(
            "Albums.html",
            **defaults,
            albums=albums,
            collection=collection,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Albums"},
            ],
        )

    @app.route("/browse/<collection_id>/songs")
    async def songs(collection_id: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        songs = library.get_songs(conn=conn, collection_id=collection_id)
        conn.close()
        return await render_template(
            "Songs.html",
            **defaults,
            songs=songs,
            show_album_column=True,
            collection=collection,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Songs"},
            ],
        )

    @app.route("/browse/<collection_id>/folders")
    async def folders(collection_id: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        folder_list = library.get_folders(conn=conn, collection_id=collection_id)
        conn.close()
        return await render_template(
            "Folders.html",
            **defaults,
            folders=folder_list,
            collection=collection,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Folders"},
            ],
        )

    @app.route("/browse/<collection_id>/folder/<path:folder_name>")
    async def folder(collection_id: str, folder_name: str):
        collection = collections.get(collection_id, None)
        if collection is None:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)

        nav_entities = library.get_nav_entities(collection)
        folder_idx = next(
            (i for i, e in enumerate(nav_entities) if e["name"] == "Folder"), -1
        )
        show_albums = (
            folder_idx >= 0
            and folder_idx + 1 < len(nav_entities)
            and nav_entities[folder_idx + 1]["name"] == "Album"
        )

        if show_albums:
            items = library.get_albums(
                conn=conn,
                collection_id=collection_id,
                folder_name=folder_name,
                include_songs=False,
                include_artists=True,
            )
            conn.close()
            return await render_template(
                "Folder.html",
                **defaults,
                item_limit_on_multi_table_pages=config[
                    "item_limit_on_multi_table_pages"
                ],
                folder_name=folder_name,
                albums=items,
                collection=collection,
                crumbs=[
                    {"name": "Home", "link": "/"},
                    {"name": "Collections", "link": "/browse"},
                    {
                        "name": collection["name"],
                        "link": f"/browse/{collection['id']}",
                    },
                    {
                        "name": "Folders",
                        "link": f"/browse/{collection['id']}/folders",
                    },
                    {"name": folder_name},
                ],
            )
        else:
            items = library.get_songs(
                conn=conn,
                collection_id=collection_id,
                folder_name=folder_name,
            )
            conn.close()
            return await render_template(
                "Folder.html",
                **defaults,
                item_limit_on_multi_table_pages=config[
                    "item_limit_on_multi_table_pages"
                ],
                folder_name=folder_name,
                songs=items,
                show_album_column=True,
                collection=collection,
                crumbs=[
                    {"name": "Home", "link": "/"},
                    {"name": "Collections", "link": "/browse"},
                    {
                        "name": collection["name"],
                        "link": f"/browse/{collection['id']}",
                    },
                    {
                        "name": "Folders",
                        "link": f"/browse/{collection['id']}/folders",
                    },
                    {"name": folder_name},
                ],
            )

    @app.route("/browse/<collection_id>/artist/<artist_id>")
    async def artist(collection_id: str, artist_id: str):
        collection = collections.get(collection_id, None)
        if not collection:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        artists = library.get_artists(
            conn=conn, collection_id=collection_id, artist_id=artist_id
        )
        conn.close()
        if not artists:
            return await send_error("Artist not found", 404)
        artist = artists[0]
        return await render_template(
            "Artist.html",
            **defaults,
            artist=artist,
            collection=collection,
            item_limit_on_multi_table_pages=config["item_limit_on_multi_table_pages"],
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Artists", "link": f"/browse/{collection['id']}/artists"},
                {"name": artist["name"]},
            ],
        )

    @app.route("/browse/<collection_id>/album/<album_id>")
    async def album(collection_id: str, album_id: str):
        collection = collections.get(collection_id, None)
        if not collection:
            return await send_error("Collection not found", 404)
        conn = db.get_conn()
        if conn is None:
            return await send_error("Database connection failed", 500)
        albums = library.get_albums(
            conn=conn,
            collection_id=collection_id,
            album_id=album_id,
            include_artists=False,
        )
        conn.close()
        if not albums:
            return await send_error("Album not found", 404)
        album = albums[0]
        return await render_template(
            "Album.html",
            **defaults,
            album=album,
            show_album_column=False,
            collection=collection,
            crumbs=[
                {"name": "Home", "link": "/"},
                {"name": "Collections", "link": "/browse"},
                {"name": collection["name"], "link": f"/browse/{collection['id']}"},
                {"name": "Albums", "link": f"/browse/{collection['id']}/albums"},
                {"name": album["name"]},
            ],
        )

    @app.websocket("/ws")
    @websocket_cors(allow_origin=config["allow_origin"])
    async def ws_handler():
        send_func = websocket.send
        ws.register(send_func)

        await send_func(json.dumps({"type": "scan_status", "scanning": app.scanning}))
        await send_func(
            json.dumps({"type": "fetch_status", "fetching": app.fetching_metadata})
        )

        def _get_stats():
            conn = db.get_conn()
            if conn is None:
                return {"songs": 0, "songs_with_metadata": 0, "artists": 0, "albums": 0}
            stats = library.get_stats(conn)
            conn.close()
            return stats

        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(None, _get_stats)
        await send_func(json.dumps({"type": "stats", "data": stats}))

        try:
            while True:
                await websocket.receive()
        except Exception:
            pass
        finally:
            ws.unregister(send_func)

    @app.route("/fetch-metadata")
    async def fetch_metadata():
        if app.fetching_metadata:
            return {"status": "already_running"}
        app.fetching_metadata = True
        await ws.broadcast({"type": "fetch_status", "fetching": True})
        asyncio.create_task(run_fetch_metadata(app))
        return {"status": "started"}

    @app.route("/get-metadata-status")
    async def get_metadata_status():
        return {"fetching": app.fetching_metadata}

    @app.route("/reset-metadata")
    async def reset_metadata():
        loop = asyncio.get_event_loop()

        def _reset():
            conn = db.get_conn()
            if conn is None:
                return
            library.reset_metadata(conn)

        await loop.run_in_executor(None, _reset)

        def _get_stats():
            conn = db.get_conn()
            if conn is None:
                return {}
            stats = library.get_stats(conn)
            conn.close()
            return stats

        stats = await loop.run_in_executor(None, _get_stats)
        if stats:
            await ws.broadcast({"type": "stats", "data": stats})
        return {"status": "ok"}

    @app.route("/add-placeholder-tracks")
    async def add_placeholder_tracks():
        loop = asyncio.get_event_loop()

        def _add():
            conn = db.get_conn()
            if conn is None:
                return 0
            try:
                added = library.add_placeholder_tracks(conn)
                conn.commit()
                return added
            except Exception:
                return -1
            finally:
                conn.close()

        added = await loop.run_in_executor(None, _add)

        def _get_stats():
            conn = db.get_conn()
            if conn is None:
                return {}
            stats = library.get_stats(conn)
            conn.close()
            return stats

        stats = await loop.run_in_executor(None, _get_stats)
        if stats:
            await ws.broadcast({"type": "stats", "data": stats})
        return {"status": "ok", "placeholders_added": added}

    @app.route("/stats")
    async def stats():
        conn = db.get_conn()
        if conn is None:
            return {"songs": 0, "songs_with_metadata": 0, "artists": 0, "albums": 0}
        result = library.get_stats(conn)
        conn.close()
        return result

    @app.route("/config", methods=["GET", "POST"])
    async def config_route():
        if request.method == "GET":
            safe = dict(config)
            safe.pop("auth_password", None)
            safe.pop("auth_token", None)
            return safe

        data = await request.get_json()
        save_config(data)
        return {"status": "ok"}
