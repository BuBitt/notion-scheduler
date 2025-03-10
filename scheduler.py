import datetime
from config import Config


import datetime
from config import Config


def generate_available_slots(time_slots_data, logger, days_to_schedule):
    available_slots = []
    current_datetime = datetime.datetime.now(Config.LOCAL_TZ)
    current_date = current_datetime.date()
    end_date = current_date + datetime.timedelta(days=days_to_schedule - 1)

    # Dicionários para separar slots por dia
    exception_slots_by_day = {}
    regular_slots_by_day = {}

    logger.debug(f"Gerando slots para {days_to_schedule} dias até {end_date}")

    # Classificar os slots em regulares e exceções
    for slot in time_slots_data:
        day_name, start_time, end_time, exception_date = slot

        if exception_date:
            # Slot de exceção (tem uma data específica)
            if exception_date not in exception_slots_by_day:
                exception_slots_by_day[exception_date] = []
            start_datetime_naive = datetime.datetime.combine(exception_date, start_time)
            end_datetime_naive = datetime.datetime.combine(exception_date, end_time)
            start_datetime = Config.LOCAL_TZ.localize(start_datetime_naive)
            end_datetime = Config.LOCAL_TZ.localize(end_datetime_naive)
            exception_slots_by_day[exception_date].append(
                (start_datetime, end_datetime)
            )
        else:
            # Slot regular (baseado no dia da semana)
            day_name_en = Config.DAY_MAP.get(day_name.lower())
            if not day_name_en:
                logger.warning(f"Dia inválido no slot regular: {day_name}, ignorando")
                continue
            regular_slots_by_day[day_name_en] = regular_slots_by_day.get(
                day_name_en, []
            ) + [(start_time, end_time)]

    # Gerar slots disponíveis dia a dia
    exception_days = set()
    exception_slots_count = 0

    for day in range(days_to_schedule):
        date = current_date + datetime.timedelta(days=day)
        day_name_en = date.strftime("%A")

        if date in exception_slots_by_day:
            # Usar apenas slots de exceção para este dia
            exception_days.add(date)
            for start_datetime, end_datetime in exception_slots_by_day[date]:
                if date == current_date and start_datetime <= current_datetime:
                    logger.debug(
                        f"Slot ignorado: {start_datetime} - {end_datetime} (passou ou em andamento)"
                    )
                    continue
                available_slots.append((start_datetime, end_datetime))
                exception_slots_count += 1
            logger.debug(
                f"Exceção encontrada para {date}: {len(exception_slots_by_day[date])} slots"
            )
        elif day_name_en in regular_slots_by_day:
            # Usar slots regulares se não houver exceções
            for start_time, end_time in regular_slots_by_day[day_name_en]:
                start_datetime_naive = datetime.datetime.combine(date, start_time)
                end_datetime_naive = datetime.datetime.combine(date, end_time)
                start_datetime = Config.LOCAL_TZ.localize(start_datetime_naive)
                end_datetime = Config.LOCAL_TZ.localize(end_datetime_naive)

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


def schedule_tasks(tasks, available_slots, logger):
    scheduled_parts = []
    original_slots = available_slots.copy()
    tasks_scheduled = set()
    MAX_PART_DURATION = Config.MAX_PART_DURATION_HOURS * 3600
    REST_DURATION = Config.REST_DURATION_HOURS * 3600

    # Ordenar tarefas por due_date crescente (mais próximo primeiro)
    sorted_tasks = sorted(tasks, key=lambda x: x["due_date"])
    logger.info(
        "Tarefas ordenadas por prioridade: do due_date mais próximo ao mais distante"
    )
    logger.debug(
        f"Tarefas ordenadas: {[task['name'] + ' (' + str(task['due_date']) + ')' for task in sorted_tasks]}"
    )

    for task in sorted_tasks:
        task_id = task["id"]
        if task_id in tasks_scheduled:
            logger.debug(f"Tarefa {task['name']} ({task_id}) já agendada, pulando")
            continue

        remaining_duration = task["duration"]
        due_date_end = task["due_date"].replace(hour=23, minute=59, second=59)
        due_date_date = task["due_date"].date()  # Data limite sem horário
        task_parts = []

        logger.info(
            f"Agendando tarefa {task['name']} ({task_id}) com alta prioridade - Due Date: {due_date_end}, Duração: {remaining_duration/3600}h"
        )

        while remaining_duration > 0:
            scheduled = False
            for i, (slot_start, slot_end) in enumerate(available_slots):
                # Excluir qualquer slot que toque o dia da data limite
                slot_start_date = slot_start.date()
                slot_end_date = slot_end.date()
                if slot_start_date == due_date_date or slot_end_date == due_date_date:
                    continue

                # Garantir que o slot esteja antes da data limite
                if slot_start >= due_date_end:
                    continue
                if slot_end > due_date_end:
                    slot_end = due_date_end  # Cortar o slot antes da data limite

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
