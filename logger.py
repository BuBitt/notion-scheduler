import os
import logging
import colorlog
from logging.handlers import RotatingFileHandler
from config import Config
import datetime
from pathlib import Path


def setup_logger() -> logging.Logger:
    """Configura o logger com saída para arquivo e console.

    Returns:
        Objeto Logger configurado.
    """
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = (
        logs_dir / f"scheduler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    logger = logging.getLogger("SchedulerLogger")
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))
    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    if Config.LOG_TO_FILE:
        handler = RotatingFileHandler(
            log_file,
            maxBytes=Config.LOG_FILE_MAX_SIZE_MB * 1024 * 1024,
            backupCount=Config.LOG_BACKUP_COUNT,
        )
        handler.setFormatter(log_formatter)
        logger.addHandler(handler)

    if Config.LOG_TO_CONSOLE:
        color_formatter = colorlog.ColoredFormatter(
            "%(bold)s%(asctime)s%(reset)s - %(log_color)s%(levelname)s%(reset)s - %(message)s",
            log_colors={
                "DEBUG": "purple",
                "INFO": "blue",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(color_formatter)
        logger.addHandler(console_handler)

    return logger
