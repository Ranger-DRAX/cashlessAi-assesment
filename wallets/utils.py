import hashlib
import json
from typing import Any


def compute_request_hash(data: dict[str, Any], **kwargs: Any) -> str:
    payload = {**data, **kwargs}
    serialized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
