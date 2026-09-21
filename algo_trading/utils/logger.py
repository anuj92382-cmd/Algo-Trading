"""
logger.py - Logging Setup
Color-coded logs terminal mein aur file mein bhi save hote hain
"""

import logging
import logging.handlers
import os
from pathlib import Path

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False


def setup_logger(log_level: str = "INFO", log_file: str = "logs/trading.log"):
    """
    Application-wide logger setup karo.
    Terminal mein colorful aur file mein plain text.
    """
    # Log directory banao
    log_dir = Path(log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Pehle existing handlers hata do (duplicate avoid karo)
    if root_logger.handlers:
        root_logger.handlers.clear()

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # ── Console Handler (colorful) ──
    if HAS_COLORLOG:
        color_formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s | %(levelname)-8s%(reset)s | %(cyan)s%(name)s%(reset)s | %(message)s",
            datefmt=date_format,
            log_colors={
                "DEBUG":    "white",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red,bg_white",
            }
        )
    else:
        color_formatter = logging.Formatter(log_format, datefmt=date_format)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(color_formatter)
    console_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)

    # ── File Handler (rotating - max 10MB, 5 backups) ──
    file_formatter = logging.Formatter(log_format, datefmt=date_format)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    # Noisy libraries ko quiet karo
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websocket").setLevel(logging.WARNING)
    logging.getLogger("kiteconnect").setLevel(logging.WARNING)

    logging.info("✅ Logger initialized")
    return root_logger
