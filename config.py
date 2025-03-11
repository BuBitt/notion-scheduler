import os
from dotenv import load_dotenv
import pytz

load_dotenv()


class Config:
    # Credenciais do Notion
    NOTION_API_KEY = os.getenv("NOTION_API_KEY")
    TASKS_DB_ID = os.getenv("NOTION_DB_TAREFAS_ID")
    TOPICS_DB_ID = os.getenv("NOTION_DB_TOPICS_ID")
    TIME_SLOTS_DB_ID = os.getenv("NOTION_DB_TIME_SLOTS_ID")
    SCHEDULES_DB_ID = os.getenv("NOTION_DB_SCHEDULES_ID")

    # Validação
    REQUIRED_ENV_VARS = {
        "NOTION_API_KEY": NOTION_API_KEY,
        "NOTION_DB_TAREFAS_ID": TASKS_DB_ID,
        "NOTION_DB_TOPICS_ID": TOPICS_DB_ID,
        "NOTION_DB_TIME_SLOTS_ID": TIME_SLOTS_DB_ID,
        "NOTION_DB_SCHEDULES_ID": SCHEDULES_DB_ID,
    }
    for var_name, var_value in REQUIRED_ENV_VARS.items():
        if not var_value:
            raise ValueError(
                f"Variável de ambiente obrigatória '{var_name}' não configurada no .env"
            )

    # Timezone
    LOCAL_TZ = pytz.timezone("America/Sao_Paulo")

    # Logging
    LOG_LEVEL = "DEBUG"
    LOG_TO_FILE = True
    LOG_TO_CONSOLE = True
    LOG_FILE_MAX_SIZE_MB = 5
    LOG_BACKUP_COUNT = 5

    # Cache
    USE_CACHE = False
    CACHE_MAX_AGE_DAYS = 1

    # Scheduling
    SCHEDULE_CLEAR_DB = True
    SCHEDULE_BATCH_SIZE = 15
    MAX_PART_DURATION_HOURS = 2
    REST_DURATION_HOURS = 1
    DAYS_TO_SCHEDULE = 30

    # Day mapping (English as standard)
    DAY_MAP = {
        "segunda": "Monday",
        "terça": "Tuesday",
        "quarta": "Wednesday",
        "quinta": "Thursday",
        "sexta": "Friday",
        "sábado": "Saturday",
        "domingo": "Sunday",
    }
