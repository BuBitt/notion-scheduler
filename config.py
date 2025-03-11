import os
from dotenv import load_dotenv
import pytz
from typing import Dict, Optional
from enum import Enum

load_dotenv()


class DayOfWeek(Enum):
    SEGUNDA = "Monday"
    TERCA = "Tuesday"
    QUARTA = "Wednesday"
    QUINTA = "Thursday"
    SEXTA = "Friday"
    SABADO = "Saturday"
    DOMINGO = "Sunday"


class Config:
    # Credenciais do Notion
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY")
    TASKS_DB_ID: str = os.getenv("NOTION_DB_TAREFAS_ID")
    TOPICS_DB_ID: str = os.getenv("NOTION_DB_TOPICS_ID")
    TIME_SLOTS_DB_ID: str = os.getenv("NOTION_DB_TIME_SLOTS_ID")
    SCHEDULES_DB_ID: str = os.getenv("NOTION_DB_SCHEDULES_ID")

    # Validação
    @staticmethod
    def validate_env_vars() -> None:
        required_vars: Dict[str, Optional[str]] = {
            "NOTION_API_KEY": Config.NOTION_API_KEY,
            "NOTION_DB_TAREFAS_ID": Config.TASKS_DB_ID,
            "NOTION_DB_TOPICS_ID": Config.TOPICS_DB_ID,
            "NOTION_DB_TIME_SLOTS_ID": Config.TIME_SLOTS_DB_ID,
            "NOTION_DB_SCHEDULES_ID": Config.SCHEDULES_DB_ID,
        }
        missing_vars = [name for name, value in required_vars.items() if not value]
        if missing_vars:
            raise ValueError(
                f"Variáveis de ambiente obrigatórias não configuradas no .env: {', '.join(missing_vars)}"
            )

    # Timezone
    LOCAL_TZ = pytz.timezone("America/Sao_Paulo")

    # Logging
    LOG_LEVEL: str = "DEBUG"
    LOG_TO_FILE: bool = True
    LOG_TO_CONSOLE: bool = True
    LOG_FILE_MAX_SIZE_MB: int = 5
    LOG_BACKUP_COUNT: int = 5

    # Cache
    USE_CACHE: bool = False
    CACHE_MAX_AGE_DAYS: int = 1

    # Scheduling
    SCHEDULE_CLEAR_DB: bool = True
    SCHEDULE_BATCH_SIZE: int = 15
    MAX_PART_DURATION_HOURS: int = 2
    REST_DURATION_HOURS: int = 1
    DAYS_TO_SCHEDULE: int = 30

    # Day mapping
    DAY_MAP: Dict[str, str] = {day.name.lower(): day.value for day in DayOfWeek}


Config.validate_env_vars()
