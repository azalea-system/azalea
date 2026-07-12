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

_connections = set()


def register(send_func):
    _connections.add(send_func)


def unregister(send_func):
    _connections.discard(send_func)


async def broadcast(message: dict):
    payload = json.dumps(message)
    dead = set()
    for send in _connections:
        try:
            await send(payload)
        except Exception:
            dead.add(send)
    for d in dead:
        _connections.discard(d)
