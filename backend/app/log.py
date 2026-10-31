"""JSON logging: one JSON object per line.

Usage:  log.info("message_stored", extra={"event_id": ..., "message_id": ...})
Every key passed in `extra` becomes a top-level field, so logs can be searched
by event_id, message_id or draft_id. Don't use `message` as an extra key:
it is a built-in LogRecord field and Python raises an error.
"""

import json
import logging
import sys
from datetime import datetime, timezone

# Attributes every LogRecord has; anything else on a record came from `extra`.
# `color_message` is uvicorn's terminal-coloured duplicate of the message.
_BUILT_IN_FIELDS = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _BUILT_IN_FIELDS:
                entry[key] = value
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Send uvicorn's own logs through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
