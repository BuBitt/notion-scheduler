import os
from dotenv import load_dotenv
import pytz

# Carrega variáveis de ambiente do .env
load_dotenv()


# Configurações gerais
class Config:
    # Credenciais do Notion (obtidas do .env)
    NOTION_API_KEY = os.getenv("NOTION_API_KEY")
    TASKS_DB_ID = os.getenv("NOTION_DB_TAREFAS_ID")
    TOPICS_DB_ID = os.getenv("NOTION_DB_TOPICS_ID")
    TIME_SLOTS_DB_ID = os.getenv("NOTION_DB_TIME_SLOTS_ID")
    SCHEDULES_DB_ID = os.getenv("NOTION_DB_SCHEDULES_ID")

    # Fuso horário
    LOCAL_TZ = pytz.timezone("America/Sao_Paulo")

    # Configurações de logging
    LOG_LEVEL = "DEBUG"  # Opções: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    LOG_TO_FILE = True  # Ativar/desativar log em arquivo
    LOG_TO_CONSOLE = True  # Ativar/desativar log no console
    LOG_FILE_MAX_SIZE_MB = 5  # Tamanho máximo do arquivo de log em MB
    LOG_BACKUP_COUNT = 5  # Número de arquivos de backup

    # Configurações de cache
    USE_CACHE = False  # Ativar/desativar uso de cache
    CACHE_MAX_AGE_DAYS = 1  # Tempo máximo que o cache é considerado válido (em dias)

    # Configurações de agendamento
    SCHEDULE_CLEAR_DB = (
        True  # Ativar/desativar limpeza da base de cronogramas no início
    )
    SCHEDULE_BATCH_SIZE = 15  # Tamanho do lote para inserções no Notion
    MAX_PART_DURATION_HOURS = 2  # Duração máxima de cada parte (em horas)
    REST_DURATION_HOURS = 1  # Duração do descanso entre partes (em horas)
    DAYS_TO_SCHEDULE = 30  # Número de dias para gerar slots disponíveis

    # Mapeamento de dias
    DAY_MAP = {
        "segunda": "Monday",
        "terça": "Tuesday",
        "quarta": "Wednesday",
        "quinta": "Thursday",
        "sexta": "Friday",
        "sábado": "Saturday",
        "domingo": "Sunday",
    }
