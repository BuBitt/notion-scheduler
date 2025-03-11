import asyncio
from functools import wraps
import datetime
import unicodedata
from typing import List, Dict, Any, Tuple, Optional
from notion_client import AsyncClient
from config import Config

notion = AsyncClient(auth=Config.NOTION_API_KEY)


def retry(max_attempts: int = 3, delay: int = 1):
    """Decorator para retentativas em caso de falha em chamadas à API."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger = kwargs.get("logger", args[-1] if args else None)
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    logger.warning(f"Tentativa {attempt+1} falhou: {e}")
                    await asyncio.sleep(delay * (2**attempt))

        return wrapper

    return decorator


def parse_date(date_str: str) -> datetime.datetime:
    """Converte string de data para datetime com timezone."""
    naive_date = datetime.datetime.fromisoformat(date_str.replace("Z", ""))
    return (
        Config.LOCAL_TZ.localize(naive_date)
        if naive_date.tzinfo is None
        else naive_date
    )


@retry()
async def clear_schedules_db(logger) -> int:
    """Limpa a base de cronogramas arquivando todas as entradas."""
    if not Config.SCHEDULE_CLEAR_DB:
        logger.info("Limpeza da base de cronogramas desativada")
        return 0
    logger.info("Iniciando limpeza da base de cronogramas")
    response = await notion.databases.query(Config.SCHEDULES_DB_ID)
    pages = response["results"]
    tasks = [notion.pages.update(page_id=page["id"], archived=True) for page in pages]
    if tasks:
        await asyncio.gather(*tasks)
    logger.info(f"Base de cronogramas limpa: {len(pages)} entradas removidas")
    return len(pages)


@retry()
async def get_tasks(
    topics_cache: Dict[str, List[Dict]], logger
) -> Tuple[List[Dict], int]:
    """Carrega tarefas não concluídas do Notion."""
    tasks = []
    skipped_tasks = 0
    task_ids_seen = set()
    topic_ids_seen = set()
    logger.debug("Consultando base de tarefas")

    filter = {
        "property": "Status",
        "formula": {"string": {"does_not_equal": "✅ Concluído"}},
    }
    response = await notion.databases.query(Config.TASKS_DB_ID, filter=filter)

    for activity in response["results"]:
        activity_id = activity["id"]
        if activity_id in task_ids_seen:
            logger.warning(f"Tarefa duplicada detectada: {activity_id}, pulando")
            continue
        task_ids_seen.add(activity_id)

        properties = activity.get("properties", {})
        name_key = "Professor"
        title_prop = properties.get(name_key)
        if not title_prop or "title" not in title_prop or not title_prop["title"]:
            logger.error(
                f"Propriedade '{name_key}' ausente ou vazia para tarefa {activity_id}"
            )
            continue
        name = title_prop["title"][0]["plain_text"]

        due_date_prop = properties.get("Data de Entrega", {}).get("date")
        if due_date_prop is None:
            logger.warning(
                f"Data de entrega não definida para tarefa '{name}' ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        due_date = parse_date(due_date_prop["start"])

        duration_value = properties.get("Duração", {}).get("number")
        if duration_value is None:
            logger.warning(
                f"Duração não definida para tarefa '{name}' ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        duration = duration_value * 3600

        topics = await get_topics_for_activity(activity_id, topics_cache, logger)
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
            logger.debug(f"Tarefa sem tópicos adicionada: {name} ({activity_id})")
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
                        f"Propriedade '{topic_name_key}' ausente ou vazia para tópico {topic_id}"
                    )
                    continue
                topic_name = topic_title_prop["title"][0]["plain_text"]

                topic_duration_value = topic_properties.get("Duração", {}).get("number")
                if topic_duration_value is None:
                    logger.warning(
                        f"Duração não definida para tópico '{topic_name}' ({topic_id}), pulando"
                    )
                    skipped_tasks += 1
                    continue
                topic_duration = topic_duration_value * 3600

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


@retry()
async def get_topics_for_activity(
    activity_id: str, topics_cache: Dict[str, List[Dict]], logger
) -> List[Dict]:
    """Obtém tópicos relacionados a uma atividade, excluindo concluídos."""
    if activity_id in topics_cache:
        logger.debug(f"Cache encontrado para tópicos da atividade {activity_id}")
        cached_topics = topics_cache[activity_id]
        unique_topics = {topic["id"]: topic for topic in cached_topics}.values()
        return list(unique_topics)

    filter = {
        "and": [
            {"property": "ATIVIDADES", "relation": {"contains": activity_id}},
            {
                "property": "Status",
                "formula": {"string": {"does_not_equal": "✅ Concluído"}},
            },
        ]
    }
    logger.debug(f"Consultando tópicos para atividade {activity_id}")
    response = await notion.databases.query(
        database_id=Config.TOPICS_DB_ID, filter=filter
    )
    topics = response["results"]
    unique_topics = {topic["id"]: topic for topic in topics}.values()
    topics_cache[activity_id] = list(unique_topics)
    logger.debug(f"Tópicos únicos carregados para {activity_id}: {len(unique_topics)}")
    return list(unique_topics)


@retry()
async def update_time_slot_day(slot_id: str, day_of_week: str, logger) -> None:
    """Atualiza o dia da semana de um slot de tempo."""
    try:
        await notion.pages.update(
            page_id=slot_id,
            properties={"Dia da Semana": {"select": {"name": day_of_week}}},
        )
        logger.info(
            f"'Dia da Semana' atualizado para '{day_of_week}' no slot {slot_id}"
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar 'Dia da Semana' para o slot {slot_id}: {e}")


@retry()
async def get_time_slots(
    time_slots_cache: Dict[str, List], logger
) -> List[Tuple[str, datetime.time, datetime.time, Optional[datetime.date]]]:
    """Carrega slots de tempo do Notion."""
    if time_slots_cache.get("slots"):
        logger.debug("Usando cache para intervalos de tempo")
        return time_slots_cache["slots"]

    logger.debug("Consultando base de intervalos de tempo")
    response = await notion.databases.query(Config.TIME_SLOTS_DB_ID)
    time_slots_data = []

    for slot in response["results"]:
        slot_id = slot["id"]
        properties = slot.get("properties", {})
        day_of_week = None
        exception_date = None

        exception_date_prop = properties.get("Exceções", {}).get("date")
        if exception_date_prop and exception_date_prop["start"]:
            exception_date = datetime.datetime.fromisoformat(
                exception_date_prop["start"].replace("Z", "")
            ).date()
            day_of_week = exception_date.strftime("%A")
            day_of_week_portuguese = {
                v: k.capitalize() for k, v in Config.DAY_MAP.items()
            }.get(day_of_week)

        if not exception_date:
            day_prop = properties.get("Dia da Semana")
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                logger.error(
                    f"Propriedade 'Dia da Semana' ausente ou vazia para slot {slot_id}"
                )
                continue
            day_of_week = day_prop["select"]["name"]
        else:
            day_prop = properties.get("Dia da Semana")
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                if day_of_week_portuguese:
                    await update_time_slot_day(slot_id, day_of_week_portuguese, logger)
                    day_of_week = day_of_week_portuguese
            else:
                day_of_week = day_prop["select"]["name"]

        start_time_rich = properties.get("Hora de Início", {}).get("rich_text")
        end_time_rich = properties.get("Hora de Fim", {}).get("rich_text")
        if not start_time_rich or not end_time_rich:
            logger.error(f"Hora de início ou fim ausente para slot {slot_id}")
            continue

        start_time = datetime.time.fromisoformat(start_time_rich[0]["plain_text"])
        end_time = datetime.time.fromisoformat(end_time_rich[0]["plain_text"])

        time_slots_data.append((day_of_week, start_time, end_time, exception_date))

    time_slots_cache["slots"] = time_slots_data
    logger.info(f"Intervalos de tempo carregados: {len(time_slots_data)}")
    return time_slots_data


@retry()
async def create_schedule_entry(
    task_id: str,
    start_time: datetime.datetime,
    end_time: datetime.datetime,
    is_topic: bool,
    activity_id: Optional[str],
    task_name: str,
    logger,
    part_number: Optional[int] = None,
) -> None:
    """Cria uma entrada no cronograma do Notion."""
    start_time_local = (
        Config.LOCAL_TZ.localize(start_time)
        if start_time.tzinfo is None
        else start_time
    )
    end_time_local = (
        Config.LOCAL_TZ.localize(end_time) if end_time.tzinfo is None else end_time
    )
    start_time_no_offset = start_time_local.replace(tzinfo=None).isoformat()
    end_time_no_offset = end_time_local.replace(tzinfo=None).isoformat()

    task_type = ""
    if task_name.startswith("[") and "]" in task_name:
        task_type = task_name[: task_name.index("]") + 1]
        task_name = task_name[task_name.index("]") + 1 :].strip()

    short_name = task_name if task_name else "Tarefa sem nome"
    if len(short_name) > 12:
        short_name = short_name[:12]

    name_with_suffix = (
        f"{task_type}{short_name}...{part_number}"
        if part_number
        else f"{task_type}{short_name}"
    )

    properties = {
        "Name": {"title": [{"type": "text", "text": {"content": name_with_suffix}}]},
        "Agendamento": {
            "date": {
                "start": start_time_no_offset,
                "end": end_time_no_offset,
                "time_zone": Config.LOCAL_TZ.zone,
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
        parent={"database_id": Config.SCHEDULES_DB_ID}, properties=properties
    )


@retry()
async def create_schedules_in_batches(scheduled_parts: List[Dict], logger) -> int:
    """Cria entradas no cronograma em lotes."""
    task_parts_count = {}
    for part in scheduled_parts:
        task_id = part["task_id"]
        task_parts_count[task_id] = task_parts_count.get(task_id, 0) + 1

    parts_with_numbers = []
    task_part_counters = {}
    for part in scheduled_parts:
        task_id = part["task_id"]
        task_part_counters[task_id] = task_part_counters.get(task_id, 0) + 1
        parts_with_numbers.append((part, task_part_counters[task_id]))

    for i in range(0, len(parts_with_numbers), Config.SCHEDULE_BATCH_SIZE):
        batch = parts_with_numbers[i : i + Config.SCHEDULE_BATCH_SIZE]
        tasks = [
            create_schedule_entry(
                part["task_id"],
                part["start_time"],
                part["end_time"],
                part["is_topic"],
                part["activity_id"],
                part["name"],
                logger,
                part_number=part_number,
            )
            for part, part_number in batch
        ]
        await asyncio.gather(*tasks)
        logger.info(f"Lote de {len(batch)} entradas criado")
    return len(scheduled_parts)
