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
from pathlib import Path

import toml

default_config = toml.load("default_config.toml")

if Path("config.toml").exists():
    user_config = toml.load("config.toml")
    config = default_config.copy()
    for key in user_config.keys():
        if key == "collections":
            config["collections"].update(user_config["collections"])
        else:
            config[key] = user_config[key]
else:
    config = default_config

core = toml.load("core.toml")


def get_ytdlp_path() -> str:
    cfg_path = config.get("ytdlp_path", "")
    if cfg_path:
        p = Path(cfg_path)
        if p.exists():
            return str(p)

    app_dir = Path(__file__).resolve().parent
    for name in ("yt-dlp.exe", "yt-dlp"):
        p = app_dir / name
        if p.exists():
            return str(p)

    return "yt-dlp"


def save_config(updates: dict):
    cfg_path = Path("config.toml")
    if cfg_path.exists():
        user_cfg = toml.load(cfg_path)
    else:
        user_cfg = {}

    for key, value in updates.items():
        if key == "collections":
            user_cfg.setdefault("collections", {}).update(value)
        else:
            user_cfg[key] = value
        config[key] = value

    with open(cfg_path, "w") as f:
        toml.dump(user_cfg, f)
