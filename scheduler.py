import os
import pytz
import datetime
import asyncio
import logging
import colorlog
import json

from dotenv import load_dotenv
from notion_client import AsyncClient
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor

# Configuração inicial
load_dotenv()
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
tasks_db_id = os.getenv("NOTION_DB_TAREFAS_ID")
topics_db_id = os.getenv("NOTION_DB_TOPICS_ID")
time_slots_db_id = os.getenv("NOTION_DB_TIME_SLOTS_ID")
schedules_db_id = os.getenv("NOTION_DB_SCHEDULES_ID")

# Fuso horário local
LOCAL_TZ = pytz.timezone("America/Sao_Paulo")

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

# Configuração do logger
if not os.path.exists("logs"):
    os.makedirs("logs")
if not os.path.exists("caches"):
    os.makedirs("caches")

log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
log_file = f"logs/scheduler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
handler.setFormatter(log_formatter)

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

logger = logging.getLogger("SchedulerLogger")
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.addHandler(console_handler)

# Cliente Notion assíncrono
notion = AsyncClient(auth=NOTION_API_KEY)

# Arquivos de cache
TOPICS_CACHE_FILE = "caches/topics_cache.json"
TIME_SLOTS_CACHE_FILE = "caches/time_slots_cache.json"


# Funções de cache
def load_cache(file_path, cache_name, max_age_days=1):
    if os.path.exists(file_path):
        mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        if (datetime.datetime.now() - mod_time).days <= max_age_days:
            try:
                with open(file_path, "r") as f:
                    cache = json.load(f)
                if cache_name == "time_slots_cache":
                    # Converter strings de volta para datetime.time
                    cache["slots"] = [
                        (
                            slot[0],
                            datetime.time.fromisoformat(slot[1]),
                            datetime.time.fromisoformat(slot[2]),
                        )
                        for slot in cache["slots"]
                    ]
                logger.info(
                    f"Cache {cache_name} carregado de {file_path} com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
                )
                return cache
            except Exception as e:
                logger.error(f"Erro ao carregar cache {cache_name}: {e}")
    return {} if cache_name == "topics_cache" else {"slots": []}


def save_cache(cache, file_path, cache_name):
    try:
        if cache_name == "time_slots_cache":
            # Converter datetime.time para strings antes de salvar
            serializable_cache = {
                "slots": [
                    (slot[0], slot[1].isoformat(), slot[2].isoformat())
                    for slot in cache["slots"]
                ]
            }
        else:
            serializable_cache = cache
        with open(file_path, "w") as f:
            json.dump(serializable_cache, f)
        logger.info(
            f"Cache {cache_name} salvo em {file_path} com {len(cache if cache_name == 'topics_cache' else cache['slots'])} itens"
        )
    except Exception as e:
        logger.error(f"Erro ao salvar cache {cache_name}: {e}")


async def clear_schedules_db():
    logger.info("Iniciando limpeza da base de Cronogramas")
    response = await notion.databases.query(schedules_db_id)
    pages = response["results"]
    tasks = [notion.pages.update(page_id=page["id"], archived=True) for page in pages]
    if tasks:
        await asyncio.gather(*tasks)
    logger.info(f"Base de Cronogramas limpa: {len(pages)} entradas removidas")
    return len(pages)


async def get_tasks(topics_cache):
    tasks = []
    skipped_tasks = 0
    logger.debug("Consultando base de Atividades")
    response = await notion.databases.query(tasks_db_id)
    for activity in response["results"]:
        activity_id = activity["id"]
        name_key = "Professor"
        if (
            name_key not in activity["properties"]
            or not activity["properties"][name_key]["title"]
        ):
            logger.error(
                f"Propriedade '{name_key}' não encontrada ou vazia para atividade {activity_id}"
            )
            continue

        name = activity["properties"][name_key]["title"][0]["plain_text"]

        due_date_prop = activity["properties"].get("Data de Entrega", {}).get("date")
        if due_date_prop is None:
            logger.warning(
                f"Data de Entrega não definida para atividade {name} ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        due_date_str = due_date_prop["start"]
        due_date = datetime.datetime.fromisoformat(due_date_str)

        duration_value = activity["properties"]["Duração"]["number"]
        if duration_value is None:
            logger.warning(
                f"Duração não definida para atividade {name} ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        duration = duration_value * 3600

        topics = await get_topics_for_activity(activity_id, topics_cache)
        if not topics:
            task_id = activity_id
            tasks.append(
                {
                    "id": task_id,
                    "name": name,
                    "duration": duration,
                    "due_date": due_date,
                    "is_topic": False,
                }
            )
        else:
            for topic in topics:
                topic_name_key = "Name"
                if (
                    topic_name_key not in topic["properties"]
                    or not topic["properties"][topic_name_key]["title"]
                ):
                    logger.error(
                        f"Propriedade '{topic_name_key}' não encontrada ou vazia para tópico {topic['id']}"
                    )
                    continue
                topic_name = topic["properties"][topic_name_key]["title"][0][
                    "plain_text"
                ]
                topic_duration_value = topic["properties"]["Duração"]["number"]
                if topic_duration_value is None:
                    logger.warning(
                        f"Duração não definida para tópico {topic_name} ({topic['id']}), pulando"
                    )
                    skipped_tasks += 1
                    continue
                duration = topic_duration_value * 3600
                topic_id = topic["id"]
                tasks.append(
                    {
                        "id": topic_id,
                        "name": topic_name,
                        "duration": duration,
                        "due_date": due_date,
                        "is_topic": True,
                        "activity_id": activity_id,
                    }
                )
    logger.info(f"Tarefas carregadas: {len(tasks)}")
    return tasks, skipped_tasks


async def get_topics_for_activity(activity_id, topics_cache):
    if activity_id in topics_cache:
        logger.debug(f"Cache hit para tópicos da atividade {activity_id}")
        return topics_cache[activity_id]

    filter = {
        "property": "ATIVIDADES",
        "relation": {"contains": activity_id},
    }
    logger.debug(f"Consultando tópicos para atividade {activity_id}")
    response = await notion.databases.query(topics_db_id, filter=filter)
    topics = response["results"]
    topics_cache[activity_id] = topics
    return topics


async def get_time_slots(time_slots_cache):
    if time_slots_cache.get("slots"):
        logger.debug("Usando cache para intervalos de tempo")
        return time_slots_cache["slots"]

    logger.debug("Consultando base de Intervalos de Tempo")
    response = await notion.databases.query(time_slots_db_id)
    time_slots_data = []
    for slot in response["results"]:
        day_key = "Dia da Semana"
        if (
            day_key not in slot["properties"]
            or not slot["properties"][day_key]["select"]
        ):
            logger.error(
                f"Propriedade '{day_key}' não encontrada ou vazia para slot {slot['id']}"
            )
            continue
        day_of_week = slot["properties"][day_key]["select"]["name"]

        start_time_rich = slot["properties"]["Hora de Início"]["rich_text"]
        end_time_rich = slot["properties"]["Hora de Fim"]["rich_text"]

        if not start_time_rich or not end_time_rich:
            logger.error(f"Hora de Início ou Fim vazia para slot {slot['id']}")
            continue

        start_time_str = start_time_rich[0]["plain_text"]
        end_time_str = end_time_rich[0]["plain_text"]

        start_time = datetime.time.fromisoformat(start_time_str)
        end_time = datetime.time.fromisoformat(end_time_str)

        time_slots_data.append((day_of_week, start_time, end_time))

    time_slots_cache["slots"] = time_slots_data
    logger.info(f"Intervalos de tempo carregados: {len(time_slots_data)}")
    return time_slots_data


def generate_available_slots(time_slots_data, num_days=14):
    available_slots = []
    current_date = datetime.date.today()
    for day in range(num_days):
        date = current_date + datetime.timedelta(days=day)
        day_name = date.strftime("%A")
        for slot in time_slots_data:
            slot_day_lower = slot[0].lower()
            if slot_day_lower in DAY_MAP and DAY_MAP[slot_day_lower] == day_name:
                start_datetime = datetime.datetime.combine(date, slot[1])
                end_datetime = datetime.datetime.combine(date, slot[2])
                available_slots.append((start_datetime, end_datetime))
    available_slots.sort(key=lambda x: x[0])
    logger.info(f"Slots disponíveis gerados: {len(available_slots)}")
    return available_slots


def schedule_tasks(tasks, available_slots):
    scheduled_parts = []
    original_slots = available_slots.copy()
    for task in tasks:
        remaining_duration = task["duration"]
        due_date_end = task["due_date"].replace(hour=23, minute=59, second=59)
        while remaining_duration > 0:
            scheduled = False
            for i, (slot_start, slot_end) in enumerate(available_slots):
                if slot_start > due_date_end:
                    continue
                if slot_end > due_date_end:
                    slot_end = due_date_end
                available_time = (slot_end - slot_start).total_seconds()
                if available_time <= 0:
                    continue
                part_duration = min(remaining_duration, available_time)
                part_end = slot_start + datetime.timedelta(seconds=part_duration)
                scheduled_parts.append(
                    {
                        "task_id": task["id"],
                        "start_time": slot_start,
                        "end_time": part_end,
                        "is_topic": task["is_topic"],
                        "activity_id": task.get("activity_id"),
                        "name": task["name"],
                    }
                )
                remaining_duration -= part_duration
                if part_end < slot_end:
                    available_slots[i] = (part_end, slot_end)
                else:
                    del available_slots[i]
                scheduled = True
                break
            if not scheduled:
                logger.error(
                    f"Não foi possível agendar a tarefa {task['name']} antes da data limite {task['due_date']}"
                )
                raise Exception(
                    f"Não foi possível agendar a tarefa {task['name']} antes da data limite {task['due_date']}"
                )
    logger.info(f"Partes agendadas: {len(scheduled_parts)}")
    return scheduled_parts, original_slots, available_slots


async def create_schedule_entry(
    task_id, start_time, end_time, is_topic, activity_id, task_name
):
    start_time_local = LOCAL_TZ.localize(start_time)
    end_time_local = LOCAL_TZ.localize(end_time)
    start_time_utc = start_time_local.astimezone(pytz.UTC)
    end_time_utc = end_time_local.astimezone(pytz.UTC)

    short_name = task_name.split(" - ")[0] if " - " in task_name else task_name
    if len(short_name) > 19:
        short_name = short_name[:16] + "..."
    name_with_time = f"{short_name:<19} - {start_time.strftime('%Hh')}"

    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": name_with_time}}]},
        "Agendamento": {
            "date": {
                "start": start_time_utc.isoformat(),
                "end": end_time_utc.isoformat(),
            }
        },
    }

    if is_topic:
        properties["TÓPICOS"] = {"relation": [{"id": task_id}]}
        if activity_id:
            properties["ATIVIDADES"] = {"relation": [{"id": activity_id}]}
    else:
        properties["ATIVIDADES"] = {"relation": [{"id": task_id}]}

    logger.debug(f"Criando entrada no cronograma: {name_with_time}")
    await notion.pages.create(
        parent={"database_id": schedules_db_id},
        properties=properties,
    )


async def create_schedules_in_batches(scheduled_parts, batch_size=10):
    for i in range(0, len(scheduled_parts), batch_size):
        batch = scheduled_parts[i : i + batch_size]
        tasks = [
            create_schedule_entry(
                part["task_id"],
                part["start_time"],
                part["end_time"],
                part["is_topic"],
                part["activity_id"],
                part["name"],
            )
            for part in batch
        ]
        await asyncio.gather(*tasks)
        logger.info(f"Lote de {len(batch)} entradas criado")
    return len(scheduled_parts)


async def main():
    start_time = datetime.datetime.now()
    logger.info("Início da execução do script")

    # Carregar caches
    topics_cache = load_cache(TOPICS_CACHE_FILE, "topics_cache", max_age_days=1)
    time_slots_cache = load_cache(
        TIME_SLOTS_CACHE_FILE, "time_slots_cache", max_age_days=7
    )

    # Limpar a base de Cronogramas
    deleted_entries = await clear_schedules_db()

    # Carregar dados assincronamente
    tasks_coro, time_slots_coro = get_tasks(topics_cache), get_time_slots(
        time_slots_cache
    )
    (tasks, skipped_tasks), time_slots_data = await asyncio.gather(
        tasks_coro, time_slots_coro
    )

    # Gerar slots e agendar tarefas
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        available_slots = await loop.run_in_executor(
            pool, generate_available_slots, time_slots_data
        )
        scheduled_parts, original_slots, remaining_slots = await loop.run_in_executor(
            pool, schedule_tasks, tasks, available_slots
        )

    # Criar entradas no cronograma em lotes
    insertions = await create_schedules_in_batches(scheduled_parts)

    # Salvar caches
    save_cache(topics_cache, TOPICS_CACHE_FILE, "topics_cache")
    save_cache({"slots": time_slots_data}, TIME_SLOTS_CACHE_FILE, "time_slots_cache")

    # Calcular horas livres restantes
    total_available_hours = sum(
        (slot[1] - slot[0]).total_seconds() / 3600 for slot in original_slots
    )
    total_used_hours = sum(
        (part["end_time"] - part["start_time"]).total_seconds() / 3600
        for part in scheduled_parts
    )
    free_hours = total_available_hours - total_used_hours

    # Calcular tempo de execução
    execution_time = (datetime.datetime.now() - start_time).total_seconds()

    # Estatísticas
    logger.info(
        f"""
        Estatísticas de execução:
        • Tarefas carregadas: {len(tasks)}
        • Tarefas puladas: {skipped_tasks}
        • Inserções no banco de dados: {insertions}
        • Horas livres restantes: {int(free_hours)}h (de {int(total_available_hours)}h totais)
        • Tempo de execução: {execution_time:.2f} segundos
        • Entradas removidas do cronograma: {deleted_entries}"""
    )
    logger.warning("Fim da execução do script")


if __name__ == "__main__":
    asyncio.run(main())
