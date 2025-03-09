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
current_dir = os.path.dirname(os.path.abspath(__file__))
logs_dir = os.path.join(current_dir, "logs")
caches_dir = os.path.join(current_dir, "caches")

os.makedirs(logs_dir, exist_ok=True)
os.makedirs(caches_dir, exist_ok=True)

log_file = os.path.join(
    logs_dir, f"scheduler_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)

log_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
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
TOPICS_CACHE_FILE = os.path.join(caches_dir, "topics_cache.json")
TIME_SLOTS_CACHE_FILE = os.path.join(caches_dir, "time_slots_cache.json")


# Funções de cache
def load_cache(file_path, cache_name, max_age_days=1):
    if os.path.exists(file_path):
        mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
        if (datetime.datetime.now() - mod_time).days <= max_age_days:
            try:
                with open(file_path, "r") as f:
                    cache = json.load(f)
                if cache_name == "time_slots_cache":
                    cache["slots"] = [
                        (
                            slot[0],  # day_of_week (pode ser None)
                            datetime.time.fromisoformat(slot[1]),  # start_time
                            datetime.time.fromisoformat(slot[2]),  # end_time
                            (
                                datetime.date.fromisoformat(slot[3])
                                if slot[3]
                                else None
                            ),  # exception_date
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
            serializable_cache = {
                "slots": [
                    (
                        slot[0],  # day_of_week (pode ser None)
                        slot[1].isoformat(),  # start_time
                        slot[2].isoformat(),  # end_time
                        slot[3].isoformat() if slot[3] else None,  # exception_date
                    )
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
    task_ids_seen = set()  # Para atividades
    topic_ids_seen = set()  # Para tópicos
    logger.debug("Consultando base de Atividades")
    response = await notion.databases.query(tasks_db_id)

    for activity in response["results"]:
        activity_id = activity["id"]
        if activity_id in task_ids_seen:
            logger.warning(f"Atividade duplicada detectada: {activity_id}, pulando")
            continue
        task_ids_seen.add(activity_id)

        name_key = "Professor"
        properties = activity.get("properties", {})
        title_prop = properties.get(name_key)
        if not title_prop or "title" not in title_prop or not title_prop["title"]:
            logger.error(
                f"Propriedade '{name_key}' não encontrada ou vazia para atividade {activity_id}"
            )
            continue
        name = title_prop["title"][0]["plain_text"]

        due_date_prop = properties.get("Data de Entrega", {}).get("date")
        if due_date_prop is None:
            logger.warning(
                f"Data de Entrega não definida para atividade {name} ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        due_date_str = due_date_prop["start"]
        due_date_naive = datetime.datetime.fromisoformat(due_date_str.replace("Z", ""))
        due_date = (
            LOCAL_TZ.localize(due_date_naive)
            if due_date_naive.tzinfo is None
            else due_date_naive
        )

        duration_value = properties.get("Duração", {}).get("number")
        if duration_value is None:
            logger.warning(
                f"Duração não definida para atividade {name} ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        duration = duration_value * 3600  # Convertendo horas para segundos

        topics = await get_topics_for_activity(activity_id, topics_cache)
        if not topics:
            tasks.append(
                {
                    "id": activity_id,
                    "name": name,
                    "duration": duration,
                    "due_date": due_date,
                    "is_topic": False,
                }
            )
            logger.debug(f"Atividade sem tópicos adicionada: {name} ({activity_id})")
        else:
            for topic in topics:
                topic_id = topic["id"]
                if topic_id in topic_ids_seen:
                    logger.debug(f"Tópico duplicado ignorado: {topic_id}")
                    continue
                topic_ids_seen.add(topic_id)

                topic_name_key = "Name"
                topic_properties = topic.get("properties", {})
                topic_title_prop = topic_properties.get(topic_name_key)
                if (
                    not topic_title_prop
                    or "title" not in topic_title_prop
                    or not topic_title_prop["title"]
                ):
                    logger.error(
                        f"Propriedade '{topic_name_key}' não encontrada ou vazia para tópico {topic_id}"
                    )
                    continue
                topic_name = topic_title_prop["title"][0]["plain_text"]

                topic_duration_value = topic_properties.get("Duração", {}).get("number")
                if topic_duration_value is None:
                    logger.warning(
                        f"Duração não definida para tópico {topic_name} ({topic_id}), pulando"
                    )
                    skipped_tasks += 1
                    continue
                topic_duration = (
                    topic_duration_value * 3600
                )  # Convertendo horas para segundos

                tasks.append(
                    {
                        "id": topic_id,
                        "name": topic_name,
                        "duration": topic_duration,
                        "due_date": due_date,
                        "is_topic": True,
                        "activity_id": activity_id,
                    }
                )
                logger.debug(f"Tópico adicionado: {topic_name} ({topic_id})")

    logger.info(f"Tarefas carregadas: {len(tasks)}")
    return tasks, skipped_tasks


async def get_topics_for_activity(activity_id, topics_cache):
    if activity_id in topics_cache:
        logger.debug(f"Cache hit para tópicos da atividade {activity_id}")
        cached_topics = topics_cache[activity_id]
        unique_topics = {topic["id"]: topic for topic in cached_topics}.values()
        logger.debug(
            f"Tópicos únicos no cache para {activity_id}: {len(unique_topics)}"
        )
        return list(unique_topics)

    filter = {
        "property": "ATIVIDADES",
        "relation": {"contains": activity_id},
    }
    logger.debug(f"Consultando tópicos para atividade {activity_id}")
    response = await notion.databases.query(database_id=topics_db_id, filter=filter)
    topics = response["results"]
    unique_topics = {topic["id"]: topic for topic in topics}.values()
    topics_cache[activity_id] = list(unique_topics)
    logger.debug(f"Tópicos únicos carregados para {activity_id}: {len(unique_topics)}")
    return list(unique_topics)


async def update_time_slot_day(notion, slot_id, day_of_week):
    """Atualiza a coluna 'Dia da Semana' de um slot no Notion."""
    try:
        await notion.pages.update(
            page_id=slot_id,
            properties={"Dia da Semana": {"select": {"name": day_of_week}}},
        )
        logger.info(
            f"Atualizado 'Dia da Semana' para '{day_of_week}' no slot {slot_id}"
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar 'Dia da Semana' para o slot {slot_id}: {e}")


async def get_time_slots(time_slots_cache):
    if time_slots_cache.get("slots"):
        logger.debug("Usando cache para intervalos de tempo")
        return time_slots_cache["slots"]

    logger.debug("Consultando base de Intervalos de Tempo")
    response = await notion.databases.query(time_slots_db_id)
    time_slots_data = []

    for slot in response["results"]:
        slot_id = slot["id"]
        day_key = "Dia da Semana"
        properties = slot.get("properties", {})
        day_of_week = None
        exception_date = None

        # Buscar a coluna "Exceções"
        exception_date_prop = properties.get("Exceções", {}).get("date")
        if exception_date_prop and exception_date_prop["start"]:
            exception_date_naive = datetime.datetime.fromisoformat(
                exception_date_prop["start"].replace("Z", "")
            ).date()
            exception_date = exception_date_naive
            # Inferir o dia da semana a partir da data de exceção
            day_of_week = exception_date.strftime("%A")
            day_of_week_portuguese = {
                "Monday": "Segunda",
                "Tuesday": "Terça",
                "Wednesday": "Quarta",
                "Thursday": "Quinta",
                "Friday": "Sexta",
                "Saturday": "Sábado",
                "Sunday": "Domingo",
            }.get(day_of_week, None)

        # Verificar "Dia da Semana" apenas se não houver exceção
        if not exception_date:
            day_prop = properties.get(day_key)
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                logger.error(
                    f"Propriedade '{day_key}' não encontrada ou vazia para slot {slot_id} sem exceção"
                )
                continue
            day_of_week = day_prop["select"]["name"]
        else:
            # Se houver exceção e "Dia da Semana" estiver vazio, atualizar a base
            day_prop = properties.get(day_key)
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                if day_of_week_portuguese:
                    await update_time_slot_day(notion, slot_id, day_of_week_portuguese)
                    day_of_week = day_of_week_portuguese
            else:
                day_of_week = day_prop["select"]["name"]

        start_time_rich = properties.get("Hora de Início", {}).get("rich_text")
        end_time_rich = properties.get("Hora de Fim", {}).get("rich_text")

        if not start_time_rich or not end_time_rich:
            logger.error(f"Hora de Início ou Fim vazia para slot {slot_id}")
            continue

        start_time_str = start_time_rich[0]["plain_text"]
        end_time_str = end_time_rich[0]["plain_text"]

        start_time = datetime.time.fromisoformat(start_time_str)
        end_time = datetime.time.fromisoformat(end_time_str)

        time_slots_data.append((day_of_week, start_time, end_time, exception_date))

    time_slots_cache["slots"] = time_slots_data
    logger.info(f"Intervalos de tempo carregados: {len(time_slots_data)}")
    return time_slots_data


def generate_available_slots(time_slots_data, num_days=30):
    available_slots = []
    current_datetime = datetime.datetime.now(LOCAL_TZ)
    current_date = current_datetime.date()

    # Contadores para estatísticas
    exception_days = set()  # Conjunto para dias únicos com exceções
    exception_slots_count = 0  # Contador de slots gerados a partir de exceções

    logger.debug(
        f"Gerando slots para {num_days} dias até {current_date + datetime.timedelta(days=num_days-1)}"
    )

    for day in range(num_days):
        date = current_date + datetime.timedelta(days=day)
        day_name = date.strftime("%A")

        # Filtrar slots com exceções para essa data
        exception_slots = [
            (slot[1], slot[2])  # (start_time, end_time)
            for slot in time_slots_data
            if slot[3] and slot[3] == date
        ]

        if exception_slots:
            # Se houver exceções, usar apenas esses slots
            logger.debug(
                f"Exceção encontrada para {date}: {len(exception_slots)} slots"
            )
            exception_days.add(date)
            for start_time, end_time in exception_slots:
                start_datetime_naive = datetime.datetime.combine(date, start_time)
                end_datetime_naive = datetime.datetime.combine(date, end_time)
                start_datetime = LOCAL_TZ.localize(start_datetime_naive)
                end_datetime = LOCAL_TZ.localize(end_datetime_naive)

                if date == current_date and start_datetime <= current_datetime:
                    logger.debug(
                        f"Slot ignorado: {start_datetime} - {end_datetime} (passou ou em andamento)"
                    )
                    continue

                available_slots.append((start_datetime, end_datetime))
                exception_slots_count += 1
        else:
            # Usar slots regulares apenas se não houver exceções
            for slot in time_slots_data:
                slot_day_lower = slot[0].lower() if slot[0] else None
                if (
                    slot_day_lower
                    and slot_day_lower in DAY_MAP
                    and DAY_MAP[slot_day_lower] == day_name
                ):
                    start_datetime_naive = datetime.datetime.combine(date, slot[1])
                    end_datetime_naive = datetime.datetime.combine(date, slot[2])
                    start_datetime = LOCAL_TZ.localize(start_datetime_naive)
                    end_datetime = LOCAL_TZ.localize(end_datetime_naive)

                    if date == current_date and start_datetime <= current_datetime:
                        logger.debug(
                            f"Slot ignorado: {start_datetime} - {end_datetime} (passou ou em andamento)"
                        )
                        continue

                    available_slots.append((start_datetime, end_datetime))

    available_slots.sort(key=lambda x: x[0])
    logger.debug(
        f"Slots disponíveis: {[f'{slot[0]} - {slot[1]}' for slot in available_slots]}"
    )
    logger.info(f"Slots disponíveis gerados: {len(available_slots)}")
    return available_slots, len(exception_days), exception_slots_count


def schedule_tasks(tasks, available_slots):
    scheduled_parts = []
    original_slots = available_slots.copy()
    tasks_scheduled = set()
    MAX_PART_DURATION = 7200  # 2 horas em segundos
    REST_DURATION = 3600  # 1 hora de descanso em segundos

    # Ordenar tarefas por data limite
    sorted_tasks = sorted(tasks, key=lambda x: x["due_date"])
    logger.debug(
        f"Tarefas ordenadas por data limite: {[task['name'] + ' (' + str(task['due_date']) + ')' for task in sorted_tasks]}"
    )

    for task in sorted_tasks:
        task_id = task["id"]
        if task_id in tasks_scheduled:
            logger.debug(f"Tarefa {task['name']} ({task_id}) já agendada, pulando")
            continue

        remaining_duration = task["duration"]
        due_date_end = task["due_date"].replace(hour=23, minute=59, second=59)
        task_parts = []

        logger.debug(
            f"Agendando tarefa {task['name']} ({task_id}) com duração {remaining_duration/3600}h, limite {due_date_end}"
        )

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

                part_duration = min(
                    remaining_duration, MAX_PART_DURATION, available_time
                )
                if remaining_duration < MAX_PART_DURATION and remaining_duration > 3600:
                    part_duration = min(remaining_duration, available_time)
                elif remaining_duration <= 3600:
                    part_duration = min(remaining_duration, available_time)

                part_end = slot_start + datetime.timedelta(seconds=part_duration)

                task_parts.append(
                    {
                        "task_id": task_id,
                        "start_time": slot_start,
                        "end_time": part_end,
                        "is_topic": task["is_topic"],
                        "activity_id": task.get("activity_id"),
                        "name": task["name"],
                    }
                )
                logger.debug(
                    f"Parte agendada: {task['name']} ({task_id}) de {slot_start} a {part_end} ({part_duration/3600}h)"
                )
                remaining_duration -= part_duration

                if part_end < slot_end:
                    remaining_slot_time = (slot_end - part_end).total_seconds()
                    if remaining_slot_time >= REST_DURATION and remaining_duration > 0:
                        rest_end = part_end + datetime.timedelta(seconds=REST_DURATION)
                        logger.debug(
                            f"Descanso inserido de {part_end} a {rest_end} (1h)"
                        )
                        if rest_end < slot_end:
                            available_slots[i] = (rest_end, slot_end)
                        else:
                            del available_slots[i]
                    else:
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

        scheduled_parts.extend(task_parts)
        tasks_scheduled.add(task_id)

    logger.info(f"Partes agendadas: {len(scheduled_parts)}")
    return scheduled_parts, original_slots, available_slots


async def create_schedule_entry(
    task_id,
    start_time,
    end_time,
    is_topic,
    activity_id,
    task_name,
    part_number=None,
    total_parts=None,
):
    start_time_local = (
        LOCAL_TZ.localize(start_time) if start_time.tzinfo is None else start_time
    )
    end_time_local = (
        LOCAL_TZ.localize(end_time) if end_time.tzinfo is None else end_time
    )

    # Remover o offset do fuso horário, mantendo apenas a data/hora local
    start_time_no_offset = start_time_local.replace(tzinfo=None).isoformat()
    end_time_no_offset = end_time_local.replace(tzinfo=None).isoformat()

    # Extrair o tipo da tarefa (ex.: [S], [A], [P]) se estiver presente no início
    task_type = ""
    if task_name.startswith("[") and "]" in task_name:
        task_type = task_name[: task_name.index("]") + 1]
        task_name = task_name[task_name.index("]") + 1 :].strip()

    # Garantir que o nome seja descritivo; fallback para "Tarefa sem nome" se vazio
    short_name = task_name if task_name else "Tarefa sem nome"
    # Abreviar o nome para no máximo 12 caracteres (deixando espaço para "...N")
    if len(short_name) > 12:
        short_name = short_name[:12]

    # Adicionar o número da parte se fornecido
    if part_number is not None:
        name_with_suffix = f"{task_type}{short_name}...{part_number}"
    else:
        name_with_suffix = f"{task_type}{short_name}"

    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": name_with_suffix}}]},
        "Agendamento": {
            "date": {
                "start": start_time_no_offset,  # Sem offset
                "end": end_time_no_offset,  # Sem offset
                "time_zone": LOCAL_TZ.zone,  # Fuso horário explícito
            }
        },
    }

    if is_topic:
        properties["TÓPICOS"] = {"relation": [{"id": task_id}]}
        if activity_id:
            properties["ATIVIDADES"] = {"relation": [{"id": activity_id}]}
    else:
        properties["ATIVIDADES"] = {"relation": [{"id": task_id}]}

    logger.debug(f"Criando entrada no cronograma: {name_with_suffix}")
    await notion.pages.create(
        parent={"database_id": schedules_db_id},
        properties=properties,
    )


async def create_schedules_in_batches(scheduled_parts, batch_size=10):
    task_parts_count = {}
    for part in scheduled_parts:
        task_id = part["task_id"]
        task_parts_count[task_id] = task_parts_count.get(task_id, 0) + 1

    parts_with_numbers = []
    task_part_counters = {}
    for part in scheduled_parts:
        task_id = part["task_id"]
        task_part_counters[task_id] = task_part_counters.get(task_id, 0) + 1
        part_number = task_part_counters[task_id]
        parts_with_numbers.append((part, part_number))

    for i in range(0, len(parts_with_numbers), batch_size):
        batch = parts_with_numbers[i : i + batch_size]
        tasks = [
            create_schedule_entry(
                part["task_id"],
                part["start_time"],
                part["end_time"],
                part["is_topic"],
                part["activity_id"],
                part["name"],
                part_number=part_number,
            )
            for part, part_number in batch
        ]
        await asyncio.gather(*tasks)
        logger.info(f"Lote de {len(batch)} entradas criado")
    return len(scheduled_parts)


async def main():
    start_time = datetime.datetime.now()
    logger.info("Início da execução do script")

    topics_cache = {}
    time_slots_cache = {"slots": []}

    deleted_entries = await clear_schedules_db()
    tasks_coro, time_slots_coro = get_tasks(topics_cache), get_time_slots(
        time_slots_cache
    )
    (tasks, skipped_tasks), time_slots_data = await asyncio.gather(
        tasks_coro, time_slots_coro
    )

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool, generate_available_slots, time_slots_data
        )
        available_slots, exception_days_count, exception_slots_count = result
        scheduled_parts, original_slots, remaining_slots = await loop.run_in_executor(
            pool, schedule_tasks, tasks, available_slots
        )

    insertions = await create_schedules_in_batches(scheduled_parts)

    save_cache(topics_cache, TOPICS_CACHE_FILE, "topics_cache")
    save_cache({"slots": time_slots_data}, TIME_SLOTS_CACHE_FILE, "time_slots_cache")

    total_available_hours = sum(
        (slot[1] - slot[0]).total_seconds() / 3600 for slot in original_slots
    )
    committed_hours = sum(
        (part["end_time"] - part["start_time"]).total_seconds() / 3600
        for part in scheduled_parts
    )
    free_hours = total_available_hours - committed_hours
    execution_time = (datetime.datetime.now() - start_time).total_seconds()

    logger.info(
        f"""
        Estatísticas de execução:
        • Tarefas carregadas: {len(tasks)}
        • Tarefas puladas: {skipped_tasks}
        • Inserções no banco de dados: {insertions}
        • Horas comprometidas: {int(committed_hours)}h
        • Horas livres restantes: {int(free_hours)}h (de {int(total_available_hours)}h totais)
        • Dias com exceções: {exception_days_count}
        • Slots distribuídos por exceções: {exception_slots_count}
        • Tempo de execução: {execution_time:.2f} segundos
        • Entradas removidas do cronograma: {deleted_entries}"""
    )
    logger.warning("Fim da execução do script")


if __name__ == "__main__":
    asyncio.run(main())
