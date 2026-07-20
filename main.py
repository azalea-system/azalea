#!/usr/bin/env python3
import sys
sys.modules["main"] = sys.modules[__name__]
import argparse
import asyncio
import ctypes
import json
import logging
import logging.handlers
import os
import subprocess
import time
from pathlib import Path

import toml
from quart import Quart, websocket
from quart_cors import cors, websocket_cors
from sqlalchemy import text

import db
import discord_rpc
import library
import quart_azalea_api
import quart_management_ui
import quart_subsonic_api
from config import config, core

parser = argparse.ArgumentParser(description=f"{core['name']} Media Server")

parser.add_argument(
    "-c",
    "--config",
    type=str,
    default=None,
    help="Path to config file",
)

parser.add_argument(
    "-r", "--rescan", action="store_true", help="Rescan media library on startup"
)
parser.add_argument(
    "-n",
    "--no-management-ui",
    action="store_true",
    help="Disable the web-based management UI",
)

parser.add_argument(
    "--console", action="store_true", help="Disable Qt UI and use console output"
)
parser.add_argument("--no-qt-ui", action="store_true", help=argparse.SUPPRESS)
parser.add_argument("--tray", action="store_true", help=argparse.SUPPRESS)
parser.add_argument(
    "--console-window",
    action="store_true",
    help="Show a console window (requires --console or qt_ui=false)",
)

parser.add_argument(
    "-p", "--port", type=int, default=None, help="Port to bind the server to"
)
parser.add_argument("--host", type=str, default=None, help="Host address to bind to")

parser.add_argument(
    "--database-uri", type=str, default=None, help="Database connection URI"
)
parser.add_argument(
    "--library-path", type=str, default=None, help="Path to the media library"
)
parser.add_argument("--log-dir", type=str, default=None, help="Directory for log files")
parser.add_argument(
    "--download-path", type=str, default=None, help="Directory for downloads"
)
parser.add_argument(
    "--ytdlp-path", type=str, default=None, help="Path to yt-dlp binary"
)

parser.add_argument(
    "-v", "--verbose", action="store_true", help="Enable verbose logging"
)
parser.add_argument("--debug", action="store_true", help="Enable Quart debug mode")

parser.add_argument(
    "--no-web-ui", action="store_true", help="Disable the bundled web UI"
)
parser.add_argument(
    "--no-subsonic", action="store_true", help="Disable the Subsonic API"
)
parser.add_argument("--no-discord", action="store_true", help="Disable Discord RPC")
parser.add_argument(
    "--no-musicbrainz", action="store_true", help="Disable MusicBrainz metadata lookup"
)
parser.add_argument(
    "--no-verify-ssl", action="store_true", help="Disable SSL certificate verification"
)
parser.add_argument(
    "--no-hide-track-number", action="store_true", help="Show track numbers in titles"
)
parser.add_argument(
    "--no-hide-mix-year", action="store_true", help="Show mix/remix year in titles"
)

args = parser.parse_args()

if args.config:
    custom_path = Path(args.config)
    if custom_path.exists():
        custom_cfg = toml.load(str(custom_path))
        for key in custom_cfg.keys():
            if key == "collections":
                config["collections"].update(custom_cfg["collections"])
            else:
                config[key] = custom_cfg[key]
    else:
        print(f"Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

if args.port is not None:
    config["port"] = args.port
if args.host is not None:
    config["host"] = args.host
if args.database_uri is not None:
    config["custom_database_uri"] = args.database_uri
if args.library_path is not None:
    config["library_path"] = args.library_path
if args.log_dir is not None:
    config["log_dir"] = args.log_dir
if args.download_path is not None:
    config["download_path"] = args.download_path
if args.ytdlp_path is not None:
    config["ytdlp_path"] = args.ytdlp_path

if args.verbose:
    config["verbose_logging"] = True
if args.debug:
    config["quart_debug"] = True
if args.no_web_ui:
    config["start_web_ui"] = False
if args.no_subsonic:
    config["subsonic_api"] = False
if args.no_discord:
    config["discord_rpc"] = False
if args.no_musicbrainz:
    config["musicbrainz_metadata"] = False
if args.no_verify_ssl:
    config["verify_ssl"] = False
if args.no_hide_track_number:
    config["hide_track_number"] = False
if args.no_hide_mix_year:
    config["hide_mix_year"] = False

rescan = True if args.rescan else config["rescan_library_on_startup"]
management_ui = False if args.no_management_ui else config["management_ui"]
qt_ui = False if (args.console or args.no_qt_ui) else config.get("qt_ui", True)
console_window = (
    False
    if qt_ui
    else (True if args.console_window else config.get("console_window", False))
)


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers[:]:
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = config.get("log_dir", "logs")
    if os.path.isabs(log_dir):
        log_path = log_dir
    elif sys.platform == "win32":
        log_path = os.path.join(
            os.environ.get("APPDATA", ""), "AzaleaMediaServer", log_dir
        )
    else:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), log_dir)
    os.makedirs(log_path, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_path, f"azalea-{timestamp}.log")
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    backup_count = config.get("log_backup_count", 10)
    existing = sorted(
        p
        for p in os.listdir(log_path)
        if p.startswith("azalea-") and p.endswith(".log")
    )
    while len(existing) >= backup_count:
        os.remove(os.path.join(log_path, existing.pop(0)))


app = Quart(__name__)
if config["allow_cors"]:
    app = cors(
        app,
        allow_origin=config["allow_origin"],
        allow_methods=config["allow_methods"],
        allow_headers=config["allow_headers"],
    )

app.config["PROPAGATE_EXCEPTIONS"] = False
logger = logging.getLogger(__name__)

_web_ui_process: subprocess.Popen | None = None


@app.after_request
async def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, Range"
    )
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.errorhandler(500)
async def handle_500(error):
    logger.exception("Unhandled exception")
    response = {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": {"code": 0, "message": str(error)},
        }
    }
    from quart import jsonify

    resp = jsonify(response)
    resp.status_code = 500
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Range"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


_nowplaying: dict | None = None
_nowplaying_connections: set = set()
_last_activity_time: float = 0
_stale_check_task: asyncio.Task | None = None
STALE_TIMEOUT = 15
_tracked_song_key: tuple = ()
_tracked_start_time: float | None = None


@app.websocket("/nowplaying")
@websocket_cors(allow_origin=config["allow_origin"])
async def nowplaying_ws():
    global _last_activity_time, _nowplaying
    send = websocket.send
    _nowplaying_connections.add(send)
    try:
        while True:
            raw = await websocket.receive()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            t = msg.get("type")
            if t == "nowplaying":
                logger.info(
                    "Discord: received nowplaying: %s - %s",
                    msg.get("title"),
                    msg.get("artist"),
                )
                _nowplaying = {
                    "title": msg.get("title", "Unknown"),
                    "artist": msg.get("artist", "Unknown"),
                    "album": msg.get("album", "Unknown"),
                    "coverArt": msg.get("coverArt", ""),
                    "song_id": msg.get("songId") or msg.get("song_id"),
                    "album_id": msg.get("albumId") or msg.get("album_id"),
                    "startTime": msg.get("startTime"),
                    "duration": msg.get("duration", 0),
                }
                _last_activity_time = time.time()
                await _update_discord()
                try:
                    import metadata as _metadata

                    _metadata.ensure_fetch_for_nowplaying(
                        _nowplaying.get("title", ""),
                        _nowplaying.get("artist", ""),
                        _nowplaying.get("album", None),
                        _nowplaying.get("duration", None),
                    )
                except Exception:
                    logger.exception("Failed to start background lyrics fetch")
            elif t == "ping":
                _last_activity_time = time.time()
            elif t == "stopped":
                logger.info("Discord: received stopped")
                _nowplaying = None
                await _update_discord()
    except Exception:
        pass
    finally:
        logger.info("Discord: nowplaying websocket disconnected")
        _nowplaying_connections.discard(send)
        if not _nowplaying_connections:
            logger.info("Discord: no more connections, clearing nowplaying")
            _nowplaying = None
            await _update_discord()


async def _update_discord():
    global _tracked_song_key, _tracked_start_time
    if _nowplaying:
        song_key = (
            _nowplaying.get("song_id"),
            _nowplaying.get("title"),
            _nowplaying.get("artist"),
        )

        start_time = _nowplaying.get("startTime")
        if start_time and start_time > 100000000000:
            start_time //= 1000

        if song_key != _tracked_song_key:
            _tracked_song_key = song_key
            _tracked_start_time = start_time if start_time else time.time()
        else:
            start_time = _tracked_start_time

        duration = _nowplaying.get("duration", 0)
        if duration and duration > 36000:
            duration //= 1000
        title = _nowplaying.get("title", "Unknown")[:128]
        artist = _nowplaying.get("artist", "Unknown Artist")[:128]
        activity = {
            "name": "Azalea",
            "type": 2,
            "details": title,
            "state": artist,
        }
        timestamps = {}
        if start_time:
            timestamps["start"] = start_time
        if start_time and duration:
            timestamps["end"] = start_time + duration
        if timestamps:
            activity["timestamps"] = timestamps
        try:
            conn = db.get_conn()
            album_id = _nowplaying.get("album_id")
            album_name = _nowplaying.get("album")
            if conn is not None and (album_id or album_name):
                if album_id:
                    res = (
                        conn.execute(
                            text(
                                "select image_url from album_images where album_id = :album_id limit 1"
                            ),
                            {"album_id": album_id},
                        )
                        .mappings()
                        .first()
                    )
                else:
                    res = (
                        conn.execute(
                            text(
                                "select ai.image_url from album_images ai join albums a on ai.album_id = a.album_id where a.name = :name limit 1"
                            ),
                            {"name": album_name},
                        )
                        .mappings()
                        .first()
                    )
                if res and res.get("image_url"):
                    activity["large_image"] = res.get("image_url")
                activity["large_text"] = album_name
                activity["album_id"] = album_id
                conn.close()
        except Exception:
            logger.exception("Failed to fetch album image for discord")
        logger.info(
            "Discord: updating RPC with %s - %s", activity["details"], activity["state"]
        )
        await discord_rpc.rpc.set_activity(activity)
    else:
        _tracked_song_key = ()
        _tracked_start_time = None
        logger.info("Discord: clearing RPC (no nowplaying)")
        await discord_rpc.rpc.set_activity(None)


async def _stale_check_loop():
    global _nowplaying
    while True:
        await asyncio.sleep(10)
        now = time.time()
        if _nowplaying and (now - _last_activity_time) > STALE_TIMEOUT:
            _nowplaying = None
            await _update_discord()


async def get_nowplaying_state():
    return _nowplaying


@app.before_serving
async def startup() -> None:
    logger.info("Starting application")
    try:
        conn = db.get_conn()
        if conn is None:
            raise Exception("No database connection available.")

        if rescan:
            app.scanning = True
            asyncio.create_task(quart_subsonic_api.run_scan(app))
        else:
            library.init_db(rescan=False, conn=conn)
            library.fetch_missing_artist_images(conn)
            library.fetch_missing_lyrics(conn)
            conn.close()

        logger.info("Database initialised")

        if config.get("discord_rpc", False):
            asyncio.create_task(discord_rpc.rpc.connect())

        _stale_check_task = asyncio.create_task(_stale_check_loop())
    except Exception as e:
        logger.error("Database initialisation failed: %s", e)


_shutdown_event: asyncio.Event | None = None
_loop_reference: asyncio.AbstractEventLoop | None = None


async def _main():
    global _shutdown_event, _loop_reference
    _loop_reference = asyncio.get_running_loop()
    _shutdown_event = asyncio.Event()

    server_task = asyncio.create_task(
        app.run_task(
            host=config["host"],
            port=config["port"],
            debug=config["quart_debug"],
        )
    )
    wait_tasks = [server_task, asyncio.create_task(_shutdown_event.wait())]
    try:
        done, _ = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
        if _shutdown_event.is_set():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown requested, shutting down...")
    try:
        await app.shutdown()
    except Exception:
        pass
    if config.get("discord_rpc", False):
        try:
            await discord_rpc.rpc.disconnect()
        except Exception:
            pass


def _run_tray(management_ui_url: str | None = None):
    import threading

    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd != 0:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    from qt_ui import run_tray

    root = logging.getLogger()
    for h in root.handlers[:]:
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)

    def _start_server():
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_main())

    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    def stop_server():
        global _shutdown_event, _loop_reference
        if _loop_reference is not None and _shutdown_event is not None:
            _loop_reference.call_soon_threadsafe(_shutdown_event.set)

    try:
        run_tray(stop_server, management_ui_url)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, exiting")
    finally:
        stop_server()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    try:
        if sys.platform == "win32" and qt_ui:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        setup_logging(config["quart_debug"])

        if qt_ui:
            root = logging.getLogger()
            for h in root.handlers[:]:
                if isinstance(h, logging.StreamHandler):
                    root.removeHandler(h)

        if sys.platform == "win32":
            _kernel32 = ctypes.windll.kernel32

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
            def _console_handler(ctrl_type):
                if ctrl_type == 2:
                    proc = _web_ui_process
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except Exception:
                            try:
                                proc.kill()
                                proc.wait()
                            except Exception:
                                pass
                    return False
                return False

            _kernel32.SetConsoleCtrlHandler(_console_handler, 1)

        _script_dir = os.path.dirname(os.path.abspath(__file__))
        _node_exe = os.path.join(_script_dir, "node", "node.exe")
        if not os.path.exists(_node_exe):
            _node_exe = os.path.join(_script_dir, "node", "node")
            if not os.path.exists(_node_exe):
                _node_exe = "node"

        _web_ui_process = None

        if config.get("start_web_ui", True):
            _web_ui_path = os.path.join(_script_dir, "build", "index.js")
            if os.path.exists(_web_ui_path):
                try:
                    custom_env = os.environ.copy()
                    custom_env["PORT"] = str(config.get("web_ui_port", 3000))

                    _web_ui_process = subprocess.Popen(
                        [_node_exe, _web_ui_path],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=custom_env,
                    )
                    logger.info(
                        "Started web UI (PID: %s on port %s)",
                        _web_ui_process.pid,
                        custom_env["PORT"],
                    )
                except Exception as e:
                    logger.error("Failed to start web UI: %s", e)
            else:
                logger.error("Web UI startup skipped: %s not found", _web_ui_path)

        if config["subsonic_api"]:
            quart_subsonic_api.add_routes(app)
            if config["azalea_subsonic_extensions"]:
                quart_azalea_api.add_routes(app)
        if management_ui:
            quart_management_ui.add_routes(app)

        logger.info(
            "Running server on %s:%s",
            config["host"],
            config["port"],
        )

        if qt_ui:
            mgmt_url = (
                f"http://{config['host']}:{config['port']}" if management_ui else None
            )
            _run_tray(mgmt_url)
        elif console_window:
            if sys.platform == "win32":
                try:
                    ctypes.windll.kernel32.AllocConsole()
                except Exception:
                    logger.error("Failed to open console window")
                    sys.exit(1)
            try:
                asyncio.run(_main())
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, exiting")
        else:
            try:
                asyncio.run(_main())
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, exiting")
    except Exception as e:
        logger.exception(f"{core['name'].upper()} CRASHED!\nFatal error: %s", e)
        sys.exit(1)
    finally:
        if _web_ui_process is not None:
            logger.info("Stopping web UI...")
            _web_ui_process.terminate()
            try:
                _web_ui_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _web_ui_process.kill()
                _web_ui_process.wait()
        if console_window:
            input(f"Press [ENTER] to stop {core['name']} and close this window...")
