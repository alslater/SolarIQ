import logging
import sys

_configured = False


def setup_logging(log_file: str = "", log_level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    level = getattr(logging, log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")

    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(fmt)

    logger = logging.getLogger("solariq")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False  # don't bleed into Reflex/uvicorn root logger

    _configured = True
