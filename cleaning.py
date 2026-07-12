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
import re

from config import config


def extract_track_from_name(name: str) -> tuple[int | None, str]:
    match = re.match(r'^(\d{1,2})\s*[-.]\s+(.*)', name)
    if match:
        return int(match.group(1)), match.group(2)
    return None, name


def clean_song_name(name: str) -> str:
    if config["hide_track_number"]:
        _, extracted = extract_track_from_name(name)
        if extracted != name:
            name = extracted
    if config["hide_mix_year"]:
        # Regex created using an LLM - beware, it is unchecked!
        pattern = re.compile(
            r"\s*(?:\((?:\d{4} (?:Mono|Stereo)? ?(?:Mix|Remix|Remaster|Remastered|Master)|Remastered \d{4})\)|- \d{4} (?:Mono|Stereo)? ?(?:Mix|Master))$"
        )
        name = re.sub(pattern, "", name)
    return name

def milliseconds_to_hours_minutes_seconds(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    minutes = seconds // 60
    hours = minutes // 60
    if hours == 0:
        return f"{minutes}:{seconds % 60:02}"
    return f"{hours}:{minutes % 60:02}:{seconds % 60:02}"
