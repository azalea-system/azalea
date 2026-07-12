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
import io
from pathlib import Path

from PIL import Image

SIZES = [64, 128, 256, 512, 1024, 2048]


def _ensure_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (0, 0, 0))
        bg.paste(img, mask=img.split()[3])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def transcode_image(
    image_bytes: bytes | None = None,
    cache_dir: Path | None = None,
    image_id: str | None = None,
    *,
    source_path: str | None = None,
) -> None:
    if image_bytes is None and source_path is None:
        return
    if cache_dir is None or image_id is None:
        return

    if image_bytes is not None:
        img = Image.open(io.BytesIO(image_bytes))
    else:
        img = Image.open(source_path)

    img = _ensure_rgb(img)
    min_dim = min(img.size)

    max_size = SIZES[-1]
    for s in SIZES:
        if s >= min_dim:
            max_size = s
            break

    for size in SIZES:
        if size > max_size:
            break
        size_dir = cache_dir / str(size)
        size_dir.mkdir(parents=True, exist_ok=True)
        dest = size_dir / f"{image_id}.jpg"
        if not dest.exists():
            resized = img.resize((size, size), Image.LANCZOS)
            resized.save(dest, "JPEG", quality=90)


def pick_best_size(size: int | None = None) -> int | None:
    if size is None:
        return None
    for s in SIZES:
        if s >= size:
            return s
    return SIZES[-1]
