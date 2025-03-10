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

logger = setup_logger()


async def main():
    start_time = datetime.datetime.now()
    logger.info("Início da execução do script")

    caches_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caches")
    os.makedirs(caches_dir, exist_ok=True)

    topics_cache_file = os.path.join(caches_dir, "topics_cache.json")
    time_slots_cache_file = os.path.join(caches_dir, "time_slots_cache.json")

    topics_cache = load_cache(topics_cache_file, "topics_cache", logger)
    time_slots_cache = load_cache(time_slots_cache_file, "time_slots_cache", logger)

    deleted_entries = await clear_schedules_db(logger)
    tasks_coro, time_slots_coro = get_tasks(topics_cache, logger), get_time_slots(
        time_slots_cache, logger
    )
    (tasks, skipped_tasks), time_slots_data = await asyncio.gather(
        tasks_coro, time_slots_coro
    )

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(
            pool, generate_available_slots, time_slots_data, logger
        )
        available_slots, exception_days_count, exception_slots_count = result
        scheduled_parts, original_slots, remaining_slots = await loop.run_in_executor(
            pool, schedule_tasks, tasks, available_slots, logger
        )

    insertions = await create_schedules_in_batches(scheduled_parts, logger)

    save_cache(topics_cache, topics_cache_file, "topics_cache", logger)
    save_cache(
        {"slots": time_slots_data}, time_slots_cache_file, "time_slots_cache", logger
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
