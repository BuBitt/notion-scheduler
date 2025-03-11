import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import os
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


async def main():
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

    (tasks, skipped_tasks), time_slots_data = await asyncio.gather(
        get_tasks(topics_cache, logger), get_time_slots(time_slots_cache, logger)
    )

    current_datetime = datetime.datetime.now(Config.LOCAL_TZ)
    current_date = current_datetime.date()
    days_to_schedule = (
        max((max(task["due_date"] for task in tasks).date() - current_date).days + 1, 1)
        if tasks
        else Config.DAYS_TO_SCHEDULE
    )

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        available_slots, exception_days_count, exception_slots_count = (
            await loop.run_in_executor(
                pool,
                generate_available_slots,
                time_slots_data,
                logger,
                days_to_schedule,
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

    scheduled_days = len(set(part["start_time"].date() for part in scheduled_parts))
    free_hours_per_week = {}
    week_hours = defaultdict(float)
    week_committed = defaultdict(float)
    for slot in original_slots:
        week_number = slot[0].isocalendar()[1]
        week_hours[week_number] += (slot[1] - slot[0]).total_seconds() / 3600
    for part in scheduled_parts:
        week_number = part["start_time"].isocalendar()[1]
        week_committed[week_number] += (
            part["end_time"] - part["start_time"]
        ).total_seconds() / 3600
    free_hours_per_week = {
        week: round(week_hours[week] - week_committed.get(week, 0), 1)
        for week in week_hours
    }

    stats = f"""
        Estatísticas de Execução:
        • Tarefas carregadas: {len(tasks)}
        • Tarefas puladas: {skipped_tasks}
        • Tarefas não agendadas: {len(unscheduled_tasks)}
        • Inserções no banco de dados: {insertions}
        • Horas comprometidas: {int(committed_hours)}h
        • Horas livres restantes: {int(free_hours)}h (de {int(total_available_hours)}h no total)
        • Dias com exceções: {exception_days_count}
        • Slots de exceção: {exception_slots_count}
        • Tempo de execução: {execution_time:.2f} segundos
        • Entradas de cronograma removidas: {deleted_entries}
        • Dias agendados: {scheduled_days}
        • Horas livres por semana:"""

    for week, hours in free_hours_per_week.items():
        stats += f"\n\t  - Semana {week}: {hours}h"
    logger.info(stats)

    if unscheduled_tasks:
        logger.warning("Tarefas não agendadas:")
        for task in unscheduled_tasks:
            logger.warning(f" - {task['name']} (Vencimento: {task['due_date']})")

    logger.info("Execução do script concluída")


if __name__ == "__main__":
    asyncio.run(main())
