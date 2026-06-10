import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Resolve at import time via env var directly (Settings not yet available)
_use_fake = os.environ.get("USE_FAKEREDIS", "").lower() in ("1", "true", "yes")
_storage_uri = "memory://" if _use_fake else None

_kwargs: dict = {"key_func": get_remote_address}
if _storage_uri:
    _kwargs["storage_uri"] = _storage_uri

limiter = Limiter(**_kwargs)
