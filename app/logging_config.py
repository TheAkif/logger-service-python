import json
import logging
import sys
from datetime import datetime, timezone

_SKIP_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
})


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key not in _SKIP_ATTRS:
                log[key] = val
        return json.dumps(log, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]
    # silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
