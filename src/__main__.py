"""Entry point: python -m pulse"""

import logging
import os
import sys
from pathlib import Path

from pulse.src.core.config import PulseConfig
from pulse.src.core.daemon import PulseDaemon


class StructuredFormatter(logging.Formatter):
    """Formatter that appends structured extra fields as JSON when present."""
    def format(self, record):
        base = super().format(record)
        event = getattr(record, 'event', None)
        if event:
            import json
            extras = {k: v for k, v in record.__dict__.items()
                      if k in ('event', 'turn', 'reason', 'pressure', 'top_drive',
                               'mutation_type', 'target', 'before', 'after')}
            base += f" | {json.dumps(extras, default=str)}"
        return base


def setup_logging(config: PulseConfig):
    """Configure logging with file + console handlers."""
    log_path = Path(config.logging.file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = StructuredFormatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)

    # Only add console handler if stdout is a TTY (avoid duplicates when nohup redirects to file)
    handlers = [file_handler]
    if sys.stdout.isatty():
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(fmt)
        handlers.append(console_handler)

    logging.basicConfig(
        level=getattr(logging, os.environ.get("PULSE_LOG_LEVEL", config.logging.level).upper(), logging.INFO),
        handlers=handlers,
    )


def main():
    config = PulseConfig.load()
    setup_logging(config)
    daemon = PulseDaemon(config=config)
    daemon.run()


if __name__ == "__main__":
    main()
