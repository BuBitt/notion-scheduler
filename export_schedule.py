import asyncio
import csv
import datetime
import os
from typing import List, Dict
from pathlib import Path
from config import Config
from logger import setup_logger
from notion_api import get_tasks, get_time_slots, create_schedules_in_batches
from scheduler import generate_available_slots, schedule_tasks

logger = setup_logger()


class ScheduleExporter:
    def __init__(self, output_dir: str = "export"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.local_tz = Config.LOCAL_TZ
        self.today = datetime.datetime.now(self.local_tz).date()

    def get_periods(self) -> Dict[str, tuple]:
        """Define os períodos de tempo para exportação."""
        return {
            "today": (self.today, self.today),
            "next_7_days": (
                self.today + datetime.timedelta(days=1),
                self.today + datetime.timedelta(days=7),
            ),
            "next_30_days": (
                self.today + datetime.timedelta(days=8),
                self.today + datetime.timedelta(days=37),
            ),
        }

    def format_datetime(self, dt: datetime.datetime) -> str:
        """Formata data e hora para exibição."""
        return dt.strftime("%Y-%m-%d %H:%M")

    def calculate_duration(
        self, start: datetime.datetime, end: datetime.datetime
    ) -> float:
        """Calcula a duração em horas entre dois datetimes."""
        return (end - start).total_seconds() / 3600

    def generate_txt(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo TXT com o cronograma legível e informações adicionais."""
        file_path = self.output_dir / f"schedule_{period_name}.txt"
        tasks_by_activity: Dict[str, List[Dict]] = {}
        unscheduled_ids = {task["id"] for task in unscheduled_tasks}

        for part in scheduled_parts:
            start_date_part = part["start_time"].date()
            if start_date_part < start_date or start_date_part > end_date:
                continue
            activity_id = part.get("activity_id", part["task_id"])
            tasks_by_activity.setdefault(activity_id, []).append(part)

        with file_path.open("w", encoding="utf-8") as f:
            f.write(
                f"Cronograma - {period_name.replace('_', ' ').title()} ({start_date} a {end_date})\n\n"
            )
            f.write("=== Tarefas Agendadas ===\n\n")
            for activity_id, parts in tasks_by_activity.items():
                activity_name = (
                    parts[0]["name"]
                    if not parts[0]["is_topic"]
                    else f"[{parts[0]['name']}] (Tópico)"
                )
                status = (
                    "Agendada"
                    if activity_id not in unscheduled_ids
                    else "Parcialmente Agendada"
                )
                due_date = parts[0].get("due_date", "N/A")
                if isinstance(due_date, datetime.datetime):
                    due_date = self.format_datetime(due_date)
                f.write(f"Atividade: {activity_name}\n")
                f.write(f"  ID Atividade: {activity_id}\n")
                f.write(
                    f"  ID Tópico: {parts[0]['task_id'] if parts[0]['is_topic'] else 'N/A'}\n"
                )
                f.write(f"  Status: {status}\n")
                f.write(f"  Vencimento: {due_date}\n")
                for part in sorted(parts, key=lambda x: x["start_time"]):
                    start = self.format_datetime(part["start_time"])
                    end = self.format_datetime(part["end_time"])
                    duration = self.calculate_duration(
                        part["start_time"], part["end_time"]
                    )
                    f.write(f"  - {start} até {end} (Duração: {duration:.2f} horas)\n")
                f.write("\n")

            if unscheduled_tasks:
                f.write("=== Tarefas Não Agendadas ===\n\n")
                for task in unscheduled_tasks:
                    task_start_date = task["due_date"].date()
                    if task_start_date < start_date or task_start_date > end_date:
                        continue
                    duration = task.get("duration", "N/A")
                    if isinstance(duration, (int, float)):
                        duration = f"{duration / 3600:.2f} horas"
                    f.write(f"Tarefa: {task['name']}\n")
                    f.write(f"  ID Atividade: {task.get('activity_id', 'N/A')}\n")
                    f.write(
                        f"  ID Tópico: {task['id'] if task.get('is_topic', False) else 'N/A'}\n"
                    )
                    f.write(f"  Status: Não Agendada\n")
                    f.write(f"  Vencimento: {self.format_datetime(task['due_date'])}\n")
                    f.write(f"  Duração Estimada: {duration}\n\n")

            f.write(f"Total de partes agendadas: {len(scheduled_parts)}\n")
            f.write(f"Total de tarefas não agendadas: {len(unscheduled_tasks)}\n")
        logger.info(f"Arquivo TXT gerado: {file_path}")

    def generate_markdown(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo Markdown com tabela de cronograma e informações adicionais."""
        file_path = self.output_dir / f"schedule_{period_name}.md"
        unscheduled_ids = {task["id"] for task in unscheduled_tasks}

        with file_path.open("w", encoding="utf-8") as f:
            f.write(
                f"# Cronograma - {period_name.replace('_', ' ').title()} ({start_date} a {end_date})\n\n"
            )
            f.write("## Tarefas Agendadas\n\n")
            f.write(
                "| Atividade | Início | Fim | Duração (h) | Tópico | ID Atividade | ID Tópico | Status | Vencimento |\n"
            )
            f.write(
                "|-----------|--------|-----|-------------|--------|--------------|-----------|--------|------------|\n"
            )
            for part in sorted(scheduled_parts, key=lambda x: x["start_time"]):
                start_date_part = part["start_time"].date()
                if start_date_part < start_date or start_date_part > end_date:
                    continue
                name = part["name"]
                start = self.format_datetime(part["start_time"])
                end = self.format_datetime(part["end_time"])
                duration = self.calculate_duration(part["start_time"], part["end_time"])
                is_topic = "Sim" if part["is_topic"] else "Não"
                activity_id = part.get("activity_id", "N/A")
                topic_id = part["task_id"] if part["is_topic"] else "N/A"
                status = (
                    "Agendada"
                    if part["task_id"] not in unscheduled_ids
                    else "Parcialmente Agendada"
                )
                due_date = part.get("due_date", "N/A")
                if isinstance(due_date, datetime.datetime):
                    due_date = self.format_datetime(due_date)
                f.write(
                    f"| {name} | {start} | {end} | {duration:.2f} | {is_topic} | {activity_id} | {topic_id} | {status} | {due_date} |\n"
                )

            if unscheduled_tasks:
                f.write("\n## Tarefas Não Agendadas\n\n")
                f.write(
                    "| Tarefa | Vencimento | Duração Estimada | ID Atividade | ID Tópico | Status |\n"
                )
                f.write(
                    "|--------|------------|------------------|--------------|-----------|--------|\n"
                )
                for task in unscheduled_tasks:
                    task_start_date = task["due_date"].date()
                    if task_start_date < start_date or task_start_date > end_date:
                        continue
                    duration = task.get("duration", "N/A")
                    if isinstance(duration, (int, float)):
                        duration = f"{duration / 3600:.2f} h"
                    f.write(
                        f"| {task['name']} | {self.format_datetime(task['due_date'])} | {duration} | {task.get('activity_id', 'N/A')} | {task['id'] if task.get('is_topic', False) else 'N/A'} | Não Agendada |\n"
                    )

            f.write(f"\n**Total de partes agendadas:** {len(scheduled_parts)}\n")
            f.write(f"**Total de tarefas não agendadas:** {len(unscheduled_tasks)}\n")
        logger.info(f"Arquivo Markdown gerado: {file_path}")

    def generate_csv(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo CSV com o cronograma e informações adicionais."""
        file_path = self.output_dir / f"schedule_{period_name}.csv"
        headers = [
            "Atividade",
            "Início",
            "Fim",
            "Duração (h)",
            "É Tópico",
            "ID Atividade",
            "ID Tópico",
            "Status",
            "Vencimento",
        ]
        unscheduled_ids = {task["id"] for task in unscheduled_tasks}

        with file_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for part in sorted(scheduled_parts, key=lambda x: x["start_time"]):
                start_date_part = part["start_time"].date()
                if start_date_part < start_date or start_date_part > end_date:
                    continue
                due_date = part.get("due_date", "N/A")
                if isinstance(due_date, datetime.datetime):
                    due_date = self.format_datetime(due_date)
                writer.writerow(
                    {
                        "Atividade": part["name"],
                        "Início": self.format_datetime(part["start_time"]),
                        "Fim": self.format_datetime(part["end_time"]),
                        "Duração (h)": f"{self.calculate_duration(part['start_time'], part['end_time']):.2f}",
                        "É Tópico": part["is_topic"],
                        "ID Atividade": part.get("activity_id", "N/A"),
                        "ID Tópico": part["task_id"] if part["is_topic"] else "N/A",
                        "Status": (
                            "Agendada"
                            if part["task_id"] not in unscheduled_ids
                            else "Parcialmente Agendada"
                        ),
                        "Vencimento": due_date,
                    }
                )

            for task in unscheduled_tasks:
                task_start_date = task["due_date"].date()
                if task_start_date < start_date or task_start_date > end_date:
                    continue
                duration = task.get("duration", "N/A")
                if isinstance(duration, (int, float)):
                    duration = f"{duration / 3600:.2f}"
                writer.writerow(
                    {
                        "Atividade": task["name"],
                        "Início": "",
                        "Fim": "",
                        "Duração (h)": duration,
                        "É Tópico": task.get("is_topic", False),
                        "ID Atividade": task.get("activity_id", "N/A"),
                        "ID Tópico": (
                            task["id"] if task.get("is_topic", False) else "N/A"
                        ),
                        "Status": "Não Agendada",
                        "Vencimento": self.format_datetime(task["due_date"]),
                    }
                )
        logger.info(f"Arquivo CSV gerado: {file_path}")

    async def export_schedules(
        self, scheduled_parts: List[Dict], unscheduled_tasks: List[Dict]
    ):
        """Exporta o cronograma para os três formatos em todos os períodos."""
        periods = self.get_periods()
        for period_name, (start_date, end_date) in periods.items():
            self.generate_txt(
                scheduled_parts, unscheduled_tasks, period_name, start_date, end_date
            )
            self.generate_markdown(
                scheduled_parts, unscheduled_tasks, period_name, start_date, end_date
            )
            self.generate_csv(
                scheduled_parts, unscheduled_tasks, period_name, start_date, end_date
            )


async def main():
    exporter = ScheduleExporter(output_dir="export")

    # Carregar dados existentes do Notion
    time_slots_cache = {"slots": []}  # Cache vazio para simplificação
    tasks, _ = await get_tasks({}, logger)  # Sem cache de tópicos para este exemplo
    time_slots_data = await get_time_slots(time_slots_cache, logger)

    # Gerar slots e agendar tarefas
    days_to_schedule = 37  # Cobrir hoje + 7 dias + 30 dias
    available_slots, _, _ = generate_available_slots(
        time_slots_data, logger, days_to_schedule
    )
    scheduled_parts, _, _, unscheduled_tasks = schedule_tasks(
        tasks, available_slots, logger
    )

    # Exportar os cronogramas com informações adicionais
    await exporter.export_schedules(scheduled_parts, unscheduled_tasks)

    # Opcional: atualizar o Notion com os agendamentos
    # await create_schedules_in_batches(scheduled_parts, logger)


if __name__ == "__main__":
    asyncio.run(main())
