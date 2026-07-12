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
import traceback

from pypresence import Presence as SyncPresence
from pypresence.exceptions import DiscordNotFound, PipeClosed
from pypresence.types import ActivityType, StatusDisplayType
from sqlalchemy import text

import db
from config import config

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 10

CLIENT_ID = "1518808576184025209"


class DiscordRPC:
    def __init__(self):
        self._rpc: SyncPresence | None = None
        self._connected = False
        self._activity: dict | None = None
        self._reconnect_task: asyncio.Task | None = None

    async def connect(self):
        if self._rpc:
            await self.disconnect()
        try:
            rpc = SyncPresence(CLIENT_ID)
            await asyncio.to_thread(rpc.connect)
            self._rpc = rpc
            self._connected = True
            logger.info("Discord RPC connected")

            if self._activity:
                await self._send_activity(self._activity)
        except DiscordNotFound:
            logger.warning(
                "Discord client not running, will retry in %ss", RECONNECT_DELAY
            )
            self._schedule_reconnect()
        except Exception as e:
            logger.error("Discord RPC connect failed: %s", e)
            traceback.print_exc()
            self._schedule_reconnect()

    async def disconnect(self):
        self._connected = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._rpc:
            try:
                await asyncio.to_thread(self._rpc.close)
            except Exception:
                pass
            self._rpc = None
        logger.info("Discord RPC disconnected")

    def _schedule_reconnect(self):
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        while not self._connected:
            await asyncio.sleep(RECONNECT_DELAY)
            await self.connect()

    async def _send_activity(self, activity: dict | None):
        if not self._connected or not self._rpc:
            return
        try:
            if activity:
                timestamps = activity.get("timestamps", {})
                start = timestamps.get("start")
                end = timestamps.get("end")
                large_image = activity.get("large_image")
                large_text = activity.get("large_text") or activity.get("details")

                if not large_image or not large_image.startswith("http"):
                    album_id = activity.get("album_id")
                    album_name = activity.get("large_text")
                    try:
                        conn = db.get_conn()
                        if conn and (album_id or album_name):
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
                                large_image = res.get("image_url")
                            conn.close()
                    except Exception:
                        logger.exception("Failed to fetch album image url for discord")

                await asyncio.to_thread(
                    self._rpc.update,
                    state=activity.get("state"),
                    status_display_type={
                        "artist": StatusDisplayType.STATE,
                        "song": StatusDisplayType.DETAILS,
                        "azalea": StatusDisplayType.NAME,
                    }.get(
                        config.get("discord_rpc_display", "artist"),
                        StatusDisplayType.STATE,
                    ),
                    details=activity.get("details"),
                    start=start,
                    end=end,
                    large_image=large_image if large_image else "album",
                    large_text=large_text,
                    small_image="https://cdn.discordapp.com/app-icons/1518808576184025209/2b2194e52ae780559f36d30b8ea229b4.png?size=512",
                    small_text="Listening on Azalea",
                    # small_url="https://azalea-website-ecru.vercel.app",
                    activity_type=ActivityType.LISTENING,
                    buttons=[
                        {
                            "label": "About Azalea",
                            "url": "https://azalea-website-ecru.vercel.app",
                        }
                    ],
                )
                logger.info(
                    "Discord RPC: presence updated (detail=%s)", activity.get("details")
                )
            else:
                await asyncio.to_thread(self._rpc.clear)
                logger.info("Discord RPC: presence cleared")
        except (DiscordNotFound, PipeClosed, ConnectionError, OSError) as e:
            logger.warning("Discord RPC: connection lost (%s), reconnecting", e)
            self._connected = False
            if self._rpc:
                try:
                    self._rpc.close()
                except Exception:
                    pass
                self._rpc = None
            self._schedule_reconnect()
        except Exception as e:
            logger.error("Discord RPC: set_activity failed: %s", e)
            traceback.print_exc()

    async def set_activity(self, activity: dict | None):
        self._activity = activity
        await self._send_activity(activity)


rpc = DiscordRPC()
