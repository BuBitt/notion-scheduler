import os
import logging
import colorlog
from logging.handlers import RotatingFileHandler
from config import Config
import datetime  # Adicionado para usar datetime.now()


def setup_logger():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    logs_dir = os.path.join(current_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Usar timestamp atual no formato AAAAMMDD_HHMMSS
    log_file = os.path.join(
        logs_dir, f"scheduler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )

    # Configuração do logger
    logger = logging.getLogger("SchedulerLogger")
    logger.setLevel(getattr(logging, Config.LOG_LEVEL))

    # Formato comum
    log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Handler para arquivo
    if Config.LOG_TO_FILE:
        handler = RotatingFileHandler(
            log_file,
            maxBytes=Config.LOG_FILE_MAX_SIZE_MB * 1024 * 1024,
            backupCount=Config.LOG_BACKUP_COUNT,
        )
        handler.setFormatter(log_formatter)
        logger.addHandler(handler)

    # Handler para console
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
