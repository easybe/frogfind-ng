import asyncio
import io
from typing import Tuple

import httpx
from PIL import Image

from app.config import get_settings

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FrogFindNG/1.0)",
    "Accept": "image/*,*/*;q=0.8",
}

_MAX_W = 300
_MAX_H = 200
_JPEG_Q = 80
_PNG_COMPRESS = 8


def _process(data: bytes, content_type: str) -> Tuple[bytes, str]:
    img = Image.open(io.BytesIO(data))

    # Normalise mode for JPEG output
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        converted = img.convert("RGBA") if img.mode == "P" else img
        bg.paste(converted, mask=converted.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Proportional resize — identical to original PHP logic
    w, h = img.size
    if w > h:
        if w > _MAX_W:
            img = img.resize((_MAX_W, int(h * _MAX_W / w)), Image.LANCZOS)
    else:
        if h > _MAX_H:
            img = img.resize((int(w * _MAX_H / h), _MAX_H), Image.LANCZOS)

    use_png = "png" in content_type.lower()
    out = io.BytesIO()

    if use_png:
        img.save(out, format="PNG", compress_level=_PNG_COMPRESS, optimize=True)
        return out.getvalue(), "image/png"
    else:
        img.save(out, format="JPEG", quality=_JPEG_Q, optimize=True)
        return out.getvalue(), "image/jpeg"


async def fetch_and_compress(url: str) -> Tuple[bytes, str]:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=settings.request_timeout,
        follow_redirects=True,
    ) as client:
        resp = await client.get(url, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.content
        ct = resp.headers.get("content-type", "image/jpeg")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _process, data, ct)
