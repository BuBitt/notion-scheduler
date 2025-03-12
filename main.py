import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import os
from typing import List, Tuple, Dict
from config import Config
from logger import setup_logger
from notion_api import (
    clear_schedules_db,
    get_tasks,
    get_time_slots,
    create_schedules_in_batches,
)
from scheduler import generate_available_slots, schedule_tasks
from utils import load_cache, save_cache
from collections import defaultdict

logger = setup_logger()


async def calculate_days_to_schedule(
    tasks: List[dict], current_date: datetime.date
) -> int:
    return (
        max((max(task["due_date"] for task in tasks).date() - current_date).days + 1, 1)
        if tasks
        else Config.DAYS_TO_SCHEDULE
    )


async def main() -> None:
    start_time = datetime.datetime.now()
    logger.info("Script execution started")

    caches_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caches")
    os.makedirs(caches_dir, exist_ok=True)

    topics_cache_file = os.path.join(caches_dir, "topics_cache.json")
    time_slots_cache_file = os.path.join(caches_dir, "time_slots_cache.json")

    topics_cache, topics_hash = load_cache(topics_cache_file, "topics_cache", logger)
    time_slots_cache, slots_hash = load_cache(
        time_slots_cache_file, "time_slots_cache", logger
    )

    # Recebe os slots e as datas excluídas
    (tasks, skipped_tasks), (time_slots_data, excluded_dates) = await asyncio.gather(
        get_tasks(topics_cache, logger), get_time_slots(time_slots_cache, logger)
    )

    current_datetime = datetime.datetime.now(Config.LOCAL_TZ)
    current_date = current_datetime.date()
    days_to_schedule = await calculate_days_to_schedule(tasks, current_date)

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        # Passa as datas excluídas para generate_available_slots
        available_slots, exception_days_count, exception_slots_count = (
            await loop.run_in_executor(
                pool,
                generate_available_slots,
                time_slots_data,
                logger,
                days_to_schedule,
                excluded_dates,
            )
        )
        scheduled_parts, original_slots, remaining_slots, unscheduled_tasks = (
            await loop.run_in_executor(
                pool, schedule_tasks, tasks, available_slots, logger
            )
        )

    deleted_entries = await clear_schedules_db(logger)
    insertions = await create_schedules_in_batches(scheduled_parts, logger)

    save_cache(topics_cache, topics_cache_file, "topics_cache", logger, topics_hash)
    save_cache(
        {"slots": time_slots_data},
        time_slots_cache_file,
        "time_slots_cache",
        logger,
        slots_hash,
    )

    total_available_hours = sum(
        (slot[1] - slot[0]).total_seconds() / 3600 for slot in original_slots
    )
    committed_hours = sum(
        (part["end_time"] - part["start_time"]).total_seconds() / 3600
        for part in scheduled_parts
    )
    free_hours = total_available_hours - committed_hours
    execution_time = (datetime.datetime.now() - start_time).total_seconds()

    scheduled_days = len({part["start_time"].date() for part in scheduled_parts})
    free_hours_per_week: Dict[int, float] = {}
    week_hours = defaultdict(float)
    week_committed = defaultdict(float)

    for slot in original_slots:
        week_number = slot[0].isocalendar().week
        week_hours[week_number] += (slot[1] - slot[0]).total_seconds() / 3600
    for part in scheduled_parts:
        week_number = part["start_time"].isocalendar().week
        week_committed[week_number] += (
            part["end_time"] - part["start_time"]
        ).total_seconds() / 3600
    free_hours_per_week = {
        week: round(week_hours[week] - week_committed.get(week, 0), 1)
        for week in week_hours
    }

    stats_lines = [
        "Estatísticas de Execução:",
        f"• Tarefas carregadas: {len(tasks)}",
        f"• Tarefas puladas: {skipped_tasks}",
        f"• Tarefas não agendadas: {len(unscheduled_tasks)}",
        f"• Inserções no banco de dados: {insertions}",
        f"• Horas comprometidas: {int(committed_hours)}h",
        f"• Horas livres restantes: {int(free_hours)}h (de {int(total_available_hours)}h no total)",
        f"• Dias com exceções: {exception_days_count}",
        f"• Slots de exceção: {exception_slots_count}",
        f"• Dias excluídos por exceções sem horários: {len(excluded_dates)}",
        f"• Tempo de execução: {execution_time:.2f} segundos",
        f"• Entradas de cronograma removidas: {deleted_entries}",
        f"• Dias agendados: {scheduled_days}",
        "• Horas livres por semana:",
    ]
    stats_lines.extend(
        f"\t- Semana {week}: {hours}h" for week, hours in free_hours_per_week.items()
    )
    logger.info("\n".join(stats_lines))

    if unscheduled_tasks:
        logger.warning("Tarefas não agendadas:")
        for task in unscheduled_tasks:
            logger.warning(f" - {task['name']} (Vencimento: {task['due_date']})")

    logger.info("Execução do script concluída")


if __name__ == "__main__":
    asyncio.run(main())
