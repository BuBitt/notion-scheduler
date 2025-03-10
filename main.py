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
    logger.info("Início da execução do script")

    caches_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "caches")
    os.makedirs(caches_dir, exist_ok=True)

    topics_cache_file = os.path.join(caches_dir, "topics_cache.json")
    time_slots_cache_file = os.path.join(caches_dir, "time_slots_cache.json")

    topics_cache = load_cache(topics_cache_file, "topics_cache", logger)
    time_slots_cache = load_cache(time_slots_cache_file, "time_slots_cache", logger)

    # Carregar tarefas e slots de tempo
    tasks_coro, time_slots_coro = get_tasks(topics_cache, logger), get_time_slots(
        time_slots_cache, logger
    )
    (tasks, skipped_tasks), time_slots_data = await asyncio.gather(
        tasks_coro, time_slots_coro
    )

    # Encontrar a data mais distante entre as tarefas
    current_datetime = datetime.datetime.now(Config.LOCAL_TZ)
    current_date = current_datetime.date()

    if not tasks:
        logger.warning("Nenhuma tarefa encontrada. Usando DAYS_TO_SCHEDULE padrão.")
        days_to_schedule = Config.DAYS_TO_SCHEDULE
    else:
        max_due_date = max(task["due_date"] for task in tasks).date()
        days_to_schedule = (
            max_due_date - current_date
        ).days + 1  # +1 para incluir o dia final
        logger.info(
            f"Data mais distante encontrada: {max_due_date}. Dias a agendar: {days_to_schedule}"
        )

    # Garantir que days_to_schedule seja pelo menos 1
    days_to_schedule = max(days_to_schedule, 1)

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
        # Passar days_to_schedule dinâmico para generate_available_slots
        result = await loop.run_in_executor(
            pool, generate_available_slots, time_slots_data, logger, days_to_schedule
        )
        available_slots, exception_days_count, exception_slots_count = result
        scheduled_parts, original_slots, remaining_slots = await loop.run_in_executor(
            pool, schedule_tasks, tasks, available_slots, logger
        )

    # Limpar o cronograma antes de inserir os novos dados
    deleted_entries = await clear_schedules_db(logger)

    # Inserir os novos dados no Notion
    insertions = await create_schedules_in_batches(scheduled_parts, logger)

    save_cache(topics_cache, topics_cache_file, "topics_cache", logger)
    save_cache(
        {"slots": time_slots_data}, time_slots_cache_file, "time_slots_cache", logger
    )

    # Cálculo das estatísticas existentes
    total_available_hours = sum(
        (slot[1] - slot[0]).total_seconds() / 3600 for slot in original_slots
    )
    committed_hours = sum(
        (part["end_time"] - part["start_time"]).total_seconds() / 3600
        for part in scheduled_parts
    )
    free_hours = total_available_hours - committed_hours
    execution_time = (datetime.datetime.now() - start_time).total_seconds()

    # Novos campos: Dias agendados
    scheduled_days = set()
    for part in scheduled_parts:
        start_date = part["start_time"].date()
        scheduled_days.add(start_date)
    days_scheduled = len(scheduled_days)

    # Novos campos: Horas livres por semana
    week_hours = defaultdict(float)
    week_committed = defaultdict(float)
    for slot in original_slots:
        start_time = slot[0]
        end_time = slot[1]
        duration = (end_time - start_time).total_seconds() / 3600
        week_number = start_time.isocalendar()[1]
        week_hours[week_number] += duration

    for part in scheduled_parts:
        start_time = part["start_time"]
        end_time = part["end_time"]
        duration = (end_time - start_time).total_seconds() / 3600
        week_number = start_time.isocalendar()[1]
        week_committed[week_number] += duration

    free_hours_per_week = {
        week: round(week_hours[week] - week_committed.get(week, 0), 1)
        for week in week_hours
    }

    # Exibir estatísticas ajustadas
    stats = f"""
        Estatísticas de execução:
        • Tarefas carregadas: {len(tasks)}
        • Tarefas puladas: {skipped_tasks}
        • Inserções no banco de dados: {insertions}
        • Horas comprometidas: {int(committed_hours)}h
        • Horas livres restantes: {int(free_hours)}h (de {int(total_available_hours)}h totais)
        • Dias com exceções: {exception_days_count}
        • Slots distribuídos por exceções: {exception_slots_count}
        • Tempo de execução: {execution_time:.2f} segundos
        • Entradas removidas do cronograma: {deleted_entries}
        • Dias agendados: {days_scheduled}
        • Horas livres por semana:"""
    for week, hours in free_hours_per_week.items():
        stats += f"\n\t  - Semana {week}: {hours}h"

    logger.info(stats)
    logger.warning("Fim da execução do script")


if __name__ == "__main__":
    asyncio.run(main())
