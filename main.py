import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
import os
from typing import List, Tuple, Dict
from collections import defaultdict
from pathlib import Path
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


async def calculate_days_to_schedule(
    tasks: List[Dict], current_date: datetime.date
) -> int:
    """Calcula o número de dias necessários para agendamento com base nas tarefas.

    Args:
        tasks: Lista de dicionários contendo informações das tarefas.
        current_date: Data atual no fuso horário local.

    Returns:
        Número de dias a serem agendados, com mínimo de 1 ou DAYS_TO_SCHEDULE se não houver tarefas.
    """
    if not tasks:
        return Config.DAYS_TO_SCHEDULE
    max_due_date = max(task["due_date"].date() for task in tasks)
    return max((max_due_date - current_date).days + 1, 1)


async def gather_initial_data(
    topics_cache: Dict, time_slots_cache: Dict
) -> Tuple[List[Dict], int, List, List[datetime.date]]:
    """Carrega tarefas e slots de tempo do Notion em paralelo.

    Args:
        topics_cache: Cache de tópicos previamente carregados.
        time_slots_cache: Cache de slots de tempo previamente carregados.

    Returns:
        Tupla contendo tarefas, tarefas puladas, dados de slots de tempo e datas excluídas.
    """
    tasks_result, slots_result = await asyncio.gather(
        get_tasks(topics_cache, logger), get_time_slots(time_slots_cache, logger)
    )
    tasks, skipped_tasks = tasks_result
    time_slots_data, excluded_dates = slots_result
    return tasks, skipped_tasks, time_slots_data, excluded_dates


async def process_scheduling(
    tasks: List[Dict], time_slots_data: List, excluded_dates: List[datetime.date]
) -> Tuple[List[Dict], List, List[Dict]]:
    """Gera slots disponíveis e agenda tarefas.

    Args:
        tasks: Lista de tarefas a serem agendadas.
        time_slots_data: Dados dos slots de tempo do Notion.
        excluded_dates: Lista de datas a serem excluídas do agendamento.

    Returns:
        Tupla com partes agendadas, slots originais e tarefas não agendadas.
    """
    current_date = datetime.datetime.now(Config.LOCAL_TZ).date()
    days_to_schedule = await calculate_days_to_schedule(tasks, current_date)

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor() as pool:
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
        scheduled_parts, original_slots, _, unscheduled_tasks = (
            await loop.run_in_executor(
                pool, schedule_tasks, tasks, available_slots, logger
            )
        )
    logger.info(
        f"Dias com exceções: {exception_days_count}, Slots de exceção: {exception_slots_count}"
    )
    return scheduled_parts, original_slots, unscheduled_tasks


def calculate_time_stats(
    scheduled_parts: List[Dict], original_slots: List
) -> Dict[str, float]:
    """Calcula estatísticas de tempo (horas disponíveis, comprometidas e livres).

    Args:
        scheduled_parts: Lista de partes agendadas.
        original_slots: Lista de slots disponíveis originalmente.

    Returns:
        Dicionário com total de horas disponíveis, horas comprometidas e horas livres.
    """
    total_available_hours = sum(
        (slot[1] - slot[0]).total_seconds() / 3600 for slot in original_slots
    )
    committed_hours = sum(
        (part["end_time"] - part["start_time"]).total_seconds() / 3600
        for part in scheduled_parts
    )
    return {
        "total_available_hours": total_available_hours,
        "committed_hours": committed_hours,
        "free_hours": total_available_hours - committed_hours,
    }


def calculate_weekly_free_hours(
    scheduled_parts: List[Dict], original_slots: List
) -> Dict[int, float]:
    """Calcula horas livres por semana.

    Args:
        scheduled_parts: Lista de partes agendadas.
        original_slots: Lista de slots disponíveis originalmente.

    Returns:
        Dicionário com horas livres por número da semana.
    """
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

    return {
        week: round(week_hours[week] - week_committed.get(week, 0), 1)
        for week in week_hours
    }


async def main() -> None:
    """Função principal para execução do agendador."""
    start_time = datetime.datetime.now()
    logger.info("Script execution started")

    caches_dir = Path(__file__).parent / "caches"
    caches_dir.mkdir(exist_ok=True)
    topics_cache_file = caches_dir / "topics_cache.json"
    time_slots_cache_file = caches_dir / "time_slots_cache.json"

    topics_cache, topics_hash = load_cache(topics_cache_file, "topics_cache", logger)
    time_slots_cache, slots_hash = load_cache(
        time_slots_cache_file, "time_slots_cache", logger
    )

    tasks, skipped_tasks, time_slots_data, excluded_dates = await gather_initial_data(
        topics_cache, time_slots_cache
    )
    scheduled_parts, original_slots, unscheduled_tasks = await process_scheduling(
        tasks, time_slots_data, excluded_dates
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

    time_stats = calculate_time_stats(scheduled_parts, original_slots)
    execution_time = (datetime.datetime.now() - start_time).total_seconds()
    scheduled_days = len({part["start_time"].date() for part in scheduled_parts})
    free_hours_per_week = calculate_weekly_free_hours(scheduled_parts, original_slots)

    stats_lines = [
        "Estatísticas de Execução:",
        f"• Tarefas carregadas: {len(tasks)}",
        f"• Tarefas puladas: {skipped_tasks}",
        f"• Tarefas não agendadas: {len(unscheduled_tasks)}",
        f"• Inserções no banco de dados: {insertions}",
        f"• Horas comprometidas: {int(time_stats['committed_hours'])}h",
        f"• Horas livres restantes: {int(time_stats['free_hours'])}h (de {int(time_stats['total_available_hours'])}h no total)",
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
