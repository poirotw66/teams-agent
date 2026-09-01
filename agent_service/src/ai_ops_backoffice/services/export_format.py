from __future__ import annotations

import csv
import io
import json
from typing import Any


def flatten_for_csv(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["key", "value"])
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            writer.writerow([key, json.dumps(value, ensure_ascii=False)])
        else:
            writer.writerow([key, value])
    return buffer.getvalue()
