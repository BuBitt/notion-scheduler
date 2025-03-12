import datetime
from typing import List, Tuple, Dict
from config import Config


def generate_available_slots(
    time_slots_data: List[Tuple[str, datetime.time, datetime.time, datetime.date]],
    logger,
    days_to_schedule: int,
    excluded_dates: List[datetime.date] = None,
) -> Tuple[List[Tuple[datetime.datetime, datetime.datetime]], int, int]:
    """Gera slots disponíveis com base nos dados de time slots, excluindo datas específicas."""
    if excluded_dates is None:
        excluded_dates = []

    available_slots = []
    current_datetime = datetime.datetime.now(Config.LOCAL_TZ)
    current_date = current_datetime.date()
    end_date = current_date + datetime.timedelta(days=days_to_schedule - 1)

    exception_slots_by_day: Dict[
        datetime.date, List[Tuple[datetime.datetime, datetime.datetime]]
    ] = {}
    regular_slots_by_day: Dict[str, List[Tuple[datetime.time, datetime.time]]] = {}

    for slot in time_slots_data:
        day_name, start_time, end_time, exception_date = slot
        day_name_en = Config.DAY_MAP.get(day_name.lower())
        if exception_date:
            if exception_date in excluded_dates:
                continue  # Ignora slots de datas excluídas
            exception_slots_by_day.setdefault(exception_date, []).append(
                (
                    Config.LOCAL_TZ.localize(
                        datetime.datetime.combine(exception_date, start_time)
                    ),
                    Config.LOCAL_TZ.localize(
                        datetime.datetime.combine(exception_date, end_time)
                    ),
                )
            )
        elif day_name_en:
            regular_slots_by_day.setdefault(day_name_en, []).append(
                (start_time, end_time)
            )

    exception_days = set()
    exception_slots_count = 0
    for day in range(days_to_schedule):
        date = current_date + datetime.timedelta(days=day)
        if date in excluded_dates:
            logger.debug(f"Dia {date} excluído do agendamento por exceção sem horários")
            continue  # Pula dias excluídos
        day_name_en = date.strftime("%A")
        if date in exception_slots_by_day:
            exception_days.add(date)
            for start, end in exception_slots_by_day[date]:
                if date == current_date and start <= current_datetime:
                    continue
                available_slots.append((start, end))
                exception_slots_count += 1
        elif day_name_en in regular_slots_by_day:
            for start_time, end_time in regular_slots_by_day[day_name_en]:
                start = Config.LOCAL_TZ.localize(
                    datetime.datetime.combine(date, start_time)
                )
                end = Config.LOCAL_TZ.localize(
                    datetime.datetime.combine(date, end_time)
                )
                if date == current_date and start <= current_datetime:
                    continue
                available_slots.append((start, end))

    available_slots.sort(key=lambda x: x[0])
    logger.info(f"Generated {len(available_slots)} available slots")
    return available_slots, len(exception_days), exception_slots_count


def schedule_part(
    task: Dict,
    available_slots: List[Tuple[datetime.datetime, datetime.datetime]],
    remaining_duration: float,
    due_date_end: datetime.datetime,
    logger,
) -> Tuple[List[Dict], float, bool]:
    """Agenda uma parte de uma tarefa em um slot disponível."""
    MAX_PART_DURATION = Config.MAX_PART_DURATION_HOURS * 3600
    REST_DURATION = Config.REST_DURATION_HOURS * 3600
    task_parts = []
    scheduled = False

    # Verifica se due_date_end tem horário específico (não é apenas meia-noite)
    has_specific_time = (
        due_date_end.hour != 0 or due_date_end.minute != 0 or due_date_end.second != 0
    )

    for i, (slot_start, slot_end) in enumerate(available_slots):
        # Se não há horário específico, exclui completamente o dia da entrega
        if not has_specific_time and slot_start.date() == due_date_end.date():
            continue

        # Se há horário específico, permite agendamento antes dele
        if slot_start >= due_date_end:
            continue
        if slot_end > due_date_end:
            slot_end = due_date_end  # Ajusta o fim do slot para não ultrapassar a hora de entrega

        available_time = (slot_end - slot_start).total_seconds()
        if available_time <= 0:
            continue

        part_duration = min(remaining_duration, MAX_PART_DURATION, available_time)
        part_end = slot_start + datetime.timedelta(seconds=part_duration)

        task_parts.append(
            {
                "task_id": task["id"],
                "start_time": slot_start,
                "end_time": part_end,
                "is_topic": task["is_topic"],
                "activity_id": task.get("activity_id"),
                "name": task["name"],
                "due_date": due_date_end,  # Inclui due_date para referência
            }
        )
        remaining_duration -= part_duration

        if part_end < slot_end:
            remaining_slot_time = (slot_end - part_end).total_seconds()
            if remaining_slot_time >= REST_DURATION and remaining_duration > 0:
                rest_end = part_end + datetime.timedelta(seconds=REST_DURATION)
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

    return task_parts, remaining_duration, scheduled


def schedule_tasks(
    tasks: List[Dict],
    available_slots: List[Tuple[datetime.datetime, datetime.datetime]],
    logger,
) -> Tuple[
    List[Dict],
    List[Tuple[datetime.datetime, datetime.datetime]],
    List[Tuple[datetime.datetime, datetime.datetime]],
    List[Dict],
]:
    """Agenda tarefas em slots disponíveis, retornando partes não agendadas."""
    scheduled_parts = []
    original_slots = available_slots.copy()
    tasks_scheduled = set()
    unscheduled_tasks = []

    sorted_tasks = sorted(tasks, key=lambda x: x["due_date"])
    for task in sorted_tasks:
        task_id = task["id"]
        if task_id in tasks_scheduled:
            continue

        remaining_duration = task["duration"]
        # Usa a due_date diretamente, sem forçar 23:59:59, para respeitar horário específico
        due_date_end = task["due_date"]
        task_parts = []

        while remaining_duration > 0:
            parts, remaining_duration, scheduled = schedule_part(
                task, available_slots, remaining_duration, due_date_end, logger
            )
            task_parts.extend(parts)
            if not scheduled:
                logger.warning(
                    f"Could not schedule task '{task['name']}' before {task['due_date']}"
                )
                unscheduled_tasks.append(task)
                break

        if task_parts:
            scheduled_parts.extend(task_parts)
            tasks_scheduled.add(task_id)

    logger.info(f"Scheduled {len(scheduled_parts)} parts")
    return scheduled_parts, original_slots, available_slots, unscheduled_tasks
