import asyncio
from functools import wraps
import datetime
from typing import List, Dict, Tuple, Optional
from notion_client import AsyncClient
from config import Config

notion = AsyncClient(auth=Config.NOTION_API_KEY)


def retry(max_attempts: int = 3, delay: int = 1):
    """Decorator para retentativas em caso de falha em chamadas à API.

    Args:
        max_attempts: Número máximo de tentativas.
        delay: Tempo inicial de espera entre tentativas (em segundos).

    Returns:
        Função decorada com lógica de retentativa.
    """

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
                    logger.warning(f"Tentativa {attempt + 1} falhou: {e}")
                    await asyncio.sleep(delay * (2**attempt))

        return wrapper

    return decorator


def parse_date(date_str: str, logger) -> datetime.datetime:
    """Converte string de data para datetime com timezone, preservando horário se presente.

    Args:
        date_str: String de data no formato ISO (ex.: '2025-03-15T14:00:00').
        logger: Objeto de log para registrar mensagens.

    Returns:
        Objeto datetime com timezone local.
    """
    naive_date = datetime.datetime.fromisoformat(date_str.replace("Z", ""))
    if naive_date.hour == naive_date.minute == naive_date.second == 0:
        logger.debug(f"Data {date_str} sem horário, assumindo 00:00")
    return (
        Config.LOCAL_TZ.localize(naive_date)
        if naive_date.tzinfo is None
        else naive_date
    )


@retry()
async def clear_schedules_db(logger) -> int:
    """Limpa a base de cronogramas arquivando todas as entradas.

    Args:
        logger: Objeto de log para registrar mensagens.

    Returns:
        Número de entradas removidas.
    """
    if not Config.SCHEDULE_CLEAR_DB:
        logger.info("Limpeza da base de cronogramas desativada")
        return 0
    logger.info("Iniciando limpeza da base de cronogramas")
    response = await notion.databases.query(Config.SCHEDULES_DB_ID)
    pages = response["results"]
    if pages:
        await asyncio.gather(
            *[notion.pages.update(page_id=page["id"], archived=True) for page in pages]
        )
    logger.info(f"Base de cronogramas limpa: {len(pages)} entradas removidas")
    return len(pages)


async def fetch_notion_data(
    database_id: str, filter_conditions: Optional[Dict] = None, logger=None
) -> List[Dict]:
    """Consulta uma base de dados do Notion com filtro opcional.

    Args:
        database_id: ID da base de dados no Notion.
        filter_conditions: Condições de filtro para a consulta (opcional).
        logger: Objeto de log para registrar mensagens (opcional).

    Returns:
        Lista de resultados da consulta.
    """
    logger.debug(f"Consultando base de dados {database_id}")
    if filter_conditions is None:
        response = await notion.databases.query(database_id)  # Sem filtro
    else:
        response = await notion.databases.query(
            database_id, filter=filter_conditions
        )  # Com filtro
    return response["results"]


@retry()
async def get_tasks(
    topics_cache: Dict[str, List[Dict]], logger
) -> Tuple[List[Dict], int]:
    """Carrega tarefas não concluídas do Notion.

    Args:
        topics_cache: Cache de tópicos previamente carregados.
        logger: Objeto de log para registrar mensagens.

    Returns:
        Tupla com lista de tarefas e número de tarefas puladas.
    """
    tasks = []
    skipped_tasks = 0
    task_ids_seen = set()
    topic_ids_seen = set()

    filter_conditions = {
        "property": "Status",
        "formula": {"string": {"does_not_equal": "✅ Concluído"}},
    }
    activities = await fetch_notion_data(Config.TASKS_DB_ID, filter_conditions, logger)

    for activity in activities:
        activity_id = activity["id"]
        if activity_id in task_ids_seen:
            logger.warning(f"Tarefa duplicada detectada: {activity_id}, pulando")
            continue
        task_ids_seen.add(activity_id)

        properties = activity.get("properties", {})
        name = properties.get("Professor", {}).get("title", [{}])[0].get("plain_text")
        if not name:
            logger.error(
                f"Propriedade 'Professor' ausente ou vazia para tarefa {activity_id}"
            )
            continue

        due_date_prop = properties.get("Data de Entrega", {}).get("date")
        if not due_date_prop:
            logger.warning(
                f"Data de entrega não definida para tarefa '{name}' ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        due_date = parse_date(due_date_prop["start"], logger)

        duration = properties.get("Duração", {}).get("number")
        if duration is None:
            logger.warning(
                f"Duração não definida para tarefa '{name}' ({activity_id}), pulando"
            )
            skipped_tasks += 1
            continue
        duration *= 3600

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

                topic_name = (
                    topic["properties"]
                    .get("Name", {})
                    .get("title", [{}])[0]
                    .get("plain_text")
                )
                if not topic_name:
                    logger.error(
                        f"Propriedade 'Name' ausente ou vazia para tópico {topic_id}"
                    )
                    continue

                topic_duration = topic["properties"].get("Duração", {}).get("number")
                if topic_duration is None:
                    logger.warning(
                        f"Duração não definida para tópico '{topic_name}' ({topic_id}), pulando"
                    )
                    skipped_tasks += 1
                    continue
                topic_duration *= 3600

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
    """Obtém tópicos relacionados a uma atividade, excluindo concluídos.

    Args:
        activity_id: ID da atividade no Notion.
        topics_cache: Cache de tópicos previamente carregados.
        logger: Objeto de log para registrar mensagens.

    Returns:
        Lista de tópicos únicos associados à atividade.
    """
    if activity_id in topics_cache:
        logger.debug(f"Cache encontrado para tópicos da atividade {activity_id}")
        cached_topics = topics_cache[activity_id]
        return list({topic["id"]: topic for topic in cached_topics}.values())

    filter_conditions = {
        "and": [
            {"property": "ATIVIDADES", "relation": {"contains": activity_id}},
            {
                "property": "Status",
                "formula": {"string": {"does_not_equal": "✅ Concluído"}},
            },
        ]
    }
    topics = await fetch_notion_data(Config.TOPICS_DB_ID, filter_conditions, logger)
    unique_topics = list({topic["id"]: topic for topic in topics}.values())
    topics_cache[activity_id] = unique_topics
    logger.debug(f"Tópicos únicos carregados para {activity_id}: {len(unique_topics)}")
    return unique_topics


@retry()
async def update_time_slot_day(slot_id: str, day_of_week: str, logger) -> None:
    """Atualiza o dia da semana de um slot de tempo no Notion.

    Args:
        slot_id: ID do slot de tempo.
        day_of_week: Nome do dia da semana a ser atualizado.
        logger: Objeto de log para registrar mensagens.
    """
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
async def get_time_slots(time_slots_cache: Dict[str, List], logger) -> Tuple[
    List[Tuple[str, datetime.time, datetime.time, Optional[datetime.date]]],
    List[datetime.date],
]:
    """Carrega slots de tempo do Notion e identifica dias excluídos por exceções sem horários.

    Args:
        time_slots_cache: Cache de slots de tempo previamente carregados.
        logger: Objeto de log para registrar mensagens.

    Returns:
        Tupla com lista de slots de tempo e lista de datas excluídas.
    """
    if time_slots_cache.get("slots"):
        logger.debug("Usando cache para intervalos de tempo")
        return time_slots_cache["slots"], []

    time_slots_data = []
    excluded_dates = []
    slots = await fetch_notion_data(
        Config.TIME_SLOTS_DB_ID, None, logger
    )  # Passa None como filtro

    for slot in slots:
        slot_id = slot["id"]
        properties = slot.get("properties", {})
        exception_date_prop = properties.get("Exceções", {}).get("date")
        start_time_rich = properties.get("Hora de Início", {}).get("rich_text")
        end_time_rich = properties.get("Hora de Fim", {}).get("rich_text")

        if exception_date_prop and exception_date_prop["start"]:
            exception_date = datetime.datetime.fromisoformat(
                exception_date_prop["start"].replace("Z", "")
            ).date()
            if not start_time_rich or not end_time_rich:
                logger.info(
                    f"Exceção em {exception_date} sem horários definida, dia excluído do agendamento"
                )
                excluded_dates.append(exception_date)
                continue
            day_of_week = exception_date.strftime("%A")
            day_of_week_portuguese = {
                v: k.capitalize() for k, v in Config.DAY_MAP.items()
            }.get(day_of_week)
        else:
            day_prop = properties.get("Dia da Semana", {}).get("select", {})
            if not day_prop.get("name"):
                logger.error(
                    f"Propriedade 'Dia da Semana' ausente ou vazia para slot {slot_id}"
                )
                continue
            day_of_week = day_prop["name"]
            exception_date = None

        if not start_time_rich or not end_time_rich:
            logger.error(f"Hora de início ou fim ausente para slot {slot_id}")
            continue

        start_time = datetime.time.fromisoformat(start_time_rich[0]["plain_text"])
        end_time = datetime.time.fromisoformat(end_time_rich[0]["plain_text"])
        time_slots_data.append((day_of_week, start_time, end_time, exception_date))

        if exception_date and day_of_week_portuguese:
            day_prop = properties.get("Dia da Semana", {}).get("select", {})
            if not day_prop.get("name"):
                await update_time_slot_day(slot_id, day_of_week_portuguese, logger)

    time_slots_cache["slots"] = time_slots_data
    logger.info(f"Intervalos de tempo carregados: {len(time_slots_data)}")
    logger.info(f"Dias excluídos por exceções sem horários: {len(excluded_dates)}")
    return time_slots_data, excluded_dates


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
    """Cria uma entrada no cronograma do Notion.

    Args:
        task_id: ID da tarefa ou tópico.
        start_time: Data e hora de início do agendamento.
        end_time: Data e hora de fim do agendamento.
        is_topic: Indica se é um tópico ou tarefa.
        activity_id: ID da atividade relacionada (se for tópico).
        task_name: Nome da tarefa ou tópico.
        logger: Objeto de log para registrar mensagens.
        part_number: Número da parte, se dividida.
    """
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

    task_type = (
        task_name[: task_name.index("]") + 1]
        if task_name.startswith("[") and "]" in task_name
        else ""
    )
    short_name = (
        task_name[len(task_type) :].strip() if task_type else task_name
    ) or "Tarefa sem nome"
    if len(short_name) > 12:
        short_name = short_name[:12]
    name_with_suffix = (
        f"{task_type}{short_name}{f'...{part_number}' if part_number else ''}"
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
    """Cria entradas no cronograma em lotes.

    Args:
        scheduled_parts: Lista de partes agendadas.
        logger: Objeto de log para registrar mensagens.

    Returns:
        Número total de entradas criadas.
    """
    task_part_counters = {}
    parts_with_numbers = [
        (part, task_part_counters.setdefault(part["task_id"], 0) + 1)
        for part in scheduled_parts
    ]
    for part in scheduled_parts:
        task_part_counters[part["task_id"]] = (
            task_part_counters.get(part["task_id"], 0) + 1
        )

    for i in range(0, len(parts_with_numbers), Config.SCHEDULE_BATCH_SIZE):
        batch = parts_with_numbers[i : i + Config.SCHEDULE_BATCH_SIZE]
        await asyncio.gather(
            *[
                create_schedule_entry(
                    part["task_id"],
                    part["start_time"],
                    part["end_time"],
                    part["is_topic"],
                    part["activity_id"],
                    part["name"],
                    logger,
                    part_number,
                )
                for part, part_number in batch
            ]
        )
        logger.info(f"Lote de {len(batch)} entradas criado")
    return len(scheduled_parts)
