import asyncio
import datetime
from notion_client import AsyncClient
from config import Config

notion = AsyncClient(auth=Config.NOTION_API_KEY)


async def clear_schedules_db(logger):
    if not Config.SCHEDULE_CLEAR_DB:
        logger.info("Limpeza da base de Cronogramas desativada")
        return 0
    logger.info("Iniciando limpeza da base de Cronogramas")
    response = await notion.databases.query(Config.SCHEDULES_DB_ID)
    pages = response["results"]
    tasks = [notion.pages.update(page_id=page["id"], archived=True) for page in pages]
    if tasks:
        await asyncio.gather(*tasks)
    logger.info(f"Base de Cronogramas limpa: {len(pages)} entradas removidas")
    return len(pages)


async def get_tasks(topics_cache, logger):
    tasks = []
    skipped_tasks = 0
    task_ids_seen = set()
    topic_ids_seen = set()
    logger.debug("Consultando base de Atividades")
    response = await notion.databases.query(Config.TASKS_DB_ID)

    for activity in response["results"]:
        activity_id = activity["id"]
        if activity_id in task_ids_seen:
            logger.warning(f"Atividade duplicada detectada: {activity_id}, pulando")
            continue
        task_ids_seen.add(activity_id)

        properties = activity.get("properties", {})

        # Verificar o campo Status
        status_prop = properties.get("Status", {}).get("status")
        if status_prop and status_prop["name"] == "Concluído":
            name_key = "Professor"
            title_prop = properties.get(name_key)
            name = (
                title_prop["title"][0]["plain_text"]
                if title_prop and "title" in title_prop and title_prop["title"]
                else "Sem Nome"
            )
            logger.info(
                f"Atividade '{name}' ({activity_id}) marcada como 'Concluído', ignorada no agendamento"
            )
            continue

        # Continuar processando apenas atividades não concluídas
        name_key = "Professor"
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
            Config.LOCAL_TZ.localize(due_date_naive)
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


async def get_topics_for_activity(activity_id, topics_cache, logger):
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
    response = await notion.databases.query(
        database_id=Config.TOPICS_DB_ID, filter=filter
    )
    topics = response["results"]
    unique_topics = {topic["id"]: topic for topic in topics}.values()
    topics_cache[activity_id] = list(unique_topics)
    logger.debug(f"Tópicos únicos carregados para {activity_id}: {len(unique_topics)}")
    return list(unique_topics)


async def update_time_slot_day(slot_id, day_of_week, logger):
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


async def get_time_slots(time_slots_cache, logger):
    if time_slots_cache.get("slots"):
        logger.debug("Usando cache para intervalos de tempo")
        return time_slots_cache["slots"]

    logger.debug("Consultando base de Intervalos de Tempo")
    response = await notion.databases.query(Config.TIME_SLOTS_DB_ID)
    time_slots_data = []

    for slot in response["results"]:
        slot_id = slot["id"]
        day_key = "Dia da Semana"
        properties = slot.get("properties", {})
        day_of_week = None
        exception_date = None

        exception_date_prop = properties.get("Exceções", {}).get("date")
        if exception_date_prop and exception_date_prop["start"]:
            exception_date_naive = datetime.datetime.fromisoformat(
                exception_date_prop["start"].replace("Z", "")
            ).date()
            exception_date = exception_date_naive
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

        if not exception_date:
            day_prop = properties.get(day_key)
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                logger.error(
                    f"Propriedade '{day_key}' não encontrada ou vazia para slot {slot_id} sem exceção"
                )
                continue
            day_of_week = day_prop["select"]["name"]
        else:
            day_prop = properties.get(day_key)
            if not day_prop or "select" not in day_prop or not day_prop["select"]:
                if day_of_week_portuguese:
                    await update_time_slot_day(slot_id, day_of_week_portuguese, logger)
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


async def create_schedule_entry(
    task_id,
    start_time,
    end_time,
    is_topic,
    activity_id,
    task_name,
    logger,
    part_number=None,
):
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

    if part_number is not None:
        name_with_suffix = f"{task_type}{short_name}...{part_number}"
    else:
        name_with_suffix = f"{task_type}{short_name}"

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
        parent={"database_id": Config.SCHEDULES_DB_ID},
        properties=properties,
    )


async def create_schedules_in_batches(scheduled_parts, logger):
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
