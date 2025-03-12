import asyncio
import csv
import datetime
from typing import List, Dict, Tuple
from pathlib import Path
from config import Config
from logger import setup_logger
from notion_api import get_tasks, get_time_slots, create_schedules_in_batches
from scheduler import generate_available_slots, schedule_tasks

logger = setup_logger()


class ScheduleExporter:
    """Classe para exportar cronogramas em diferentes formatos."""

    def __init__(self, output_dir: str = "export"):
        """Inicializa o exportador de cronogramas.

        Args:
            output_dir: Diretório onde os arquivos serão salvos (padrão: 'export').
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.local_tz = Config.LOCAL_TZ
        self.today = datetime.datetime.now(self.local_tz).date()

    def get_periods(self) -> Dict[str, Tuple[datetime.date, datetime.date]]:
        """Define os períodos de tempo para exportação.

        Returns:
            Dicionário com nomes dos períodos e tuplas de datas de início e fim.
        """
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

    @staticmethod
    def format_datetime(dt: datetime.datetime) -> str:
        """Formata data e hora para exibição.

        Args:
            dt: Objeto datetime a ser formatado.

        Returns:
            String no formato 'YYYY-MM-DD HH:MM'.
        """
        return dt.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def calculate_duration(start: datetime.datetime, end: datetime.datetime) -> float:
        """Calcula a duração em horas entre dois datetimes.

        Args:
            start: Data e hora de início.
            end: Data e hora de fim.

        Returns:
            Duração em horas.
        """
        return (end - start).total_seconds() / 3600

    def _filter_by_period(
        self,
        items: List[Dict],
        start_date: datetime.date,
        end_date: datetime.date,
        date_key: str,
    ) -> List[Dict]:
        """Filtra itens por período de datas.

        Args:
            items: Lista de dicionários a serem filtrados.
            start_date: Data inicial do período.
            end_date: Data final do período.
            date_key: Chave do dicionário que contém a data a ser filtrada.

        Returns:
            Lista de itens filtrados.
        """
        return [
            item for item in items if start_date <= item[date_key].date() <= end_date
        ]

    def generate_txt(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo TXT com o cronograma legível.

        Args:
            scheduled_parts: Lista de partes agendadas.
            unscheduled_tasks: Lista de tarefas não agendadas.
            period_name: Nome do período (ex.: 'today').
            start_date: Data inicial do período.
            end_date: Data final do período.
        """
        file_path = self.output_dir / f"schedule_{period_name}.txt"
        tasks_by_activity = {}
        unscheduled_ids = {task["id"] for task in unscheduled_tasks}

        for part in self._filter_by_period(
            scheduled_parts, start_date, end_date, "start_time"
        ):
            activity_id = part.get("activity_id", part["task_id"])
            tasks_by_activity.setdefault(activity_id, []).append(part)

        with file_path.open("w", encoding="utf-8") as f:
            f.write(
                f"Cronograma - {period_name.replace('_', ' ').title()} ({start_date} a {end_date})\n\n"
            )
            f.write("=== Tarefas Agendadas ===\n\n")
            for activity_id, parts in tasks_by_activity.items():
                part = parts[0]
                activity_name = (
                    f"[{part['name']}] (Tópico)" if part["is_topic"] else part["name"]
                )
                status = (
                    "Agendada"
                    if activity_id not in unscheduled_ids
                    else "Parcialmente Agendada"
                )
                due_date = (
                    self.format_datetime(part["due_date"])
                    if isinstance(part["due_date"], datetime.datetime)
                    else "N/A"
                )
                f.write(
                    f"Atividade: {activity_name}\n  ID Atividade: {activity_id}\n  ID Tópico: {part['task_id'] if part['is_topic'] else 'N/A'}\n  Status: {status}\n  Vencimento: {due_date}\n"
                )
                for p in sorted(parts, key=lambda x: x["start_time"]):
                    start, end = self.format_datetime(
                        p["start_time"]
                    ), self.format_datetime(p["end_time"])
                    duration = self.calculate_duration(p["start_time"], p["end_time"])
                    f.write(f"  - {start} até {end} (Duração: {duration:.2f} horas)\n")
                f.write("\n")

            if unscheduled_tasks:
                f.write("=== Tarefas Não Agendadas ===\n\n")
                for task in self._filter_by_period(
                    unscheduled_tasks, start_date, end_date, "due_date"
                ):
                    duration = (
                        f"{task['duration'] / 3600:.2f} horas"
                        if isinstance(task["duration"], (int, float))
                        else "N/A"
                    )
                    f.write(
                        f"Tarefa: {task['name']}\n  ID Atividade: {task.get('activity_id', 'N/A')}\n  ID Tópico: {task['id'] if task.get('is_topic', False) else 'N/A'}\n  Status: Não Agendada\n  Vencimento: {self.format_datetime(task['due_date'])}\n  Duração Estimada: {duration}\n\n"
                    )

            f.write(
                f"Total de partes agendadas: {len(scheduled_parts)}\nTotal de tarefas não agendadas: {len(unscheduled_tasks)}\n"
            )
        logger.info(f"Arquivo TXT gerado: {file_path}")

    def generate_markdown(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo Markdown com tabela de cronograma.

        Args:
            scheduled_parts: Lista de partes agendadas.
            unscheduled_tasks: Lista de tarefas não agendadas.
            period_name: Nome do período (ex.: 'today').
            start_date: Data inicial do período.
            end_date: Data final do período.
        """
        file_path = self.output_dir / f"schedule_{period_name}.md"
        unscheduled_ids = {task["id"] for task in unscheduled_tasks}

        with file_path.open("w", encoding="utf-8") as f:
            f.write(
                f"# Cronograma - {period_name.replace('_', ' ').title()} ({start_date} a {end_date})\n\n## Tarefas Agendadas\n\n"
            )
            f.write(
                "| Atividade | Início | Fim | Duração (h) | Tópico | ID Atividade | ID Tópico | Status | Vencimento |\n|-----------|--------|-----|-------------|--------|--------------|-----------|--------|------------|\n"
            )
            for part in sorted(
                self._filter_by_period(
                    scheduled_parts, start_date, end_date, "start_time"
                ),
                key=lambda x: x["start_time"],
            ):
                due_date = (
                    self.format_datetime(part["due_date"])
                    if isinstance(part["due_date"], datetime.datetime)
                    else "N/A"
                )
                f.write(
                    f"| {part['name']} | {self.format_datetime(part['start_time'])} | {self.format_datetime(part['end_time'])} | {self.calculate_duration(part['start_time'], part['end_time']):.2f} | {'Sim' if part['is_topic'] else 'Não'} | {part.get('activity_id', 'N/A')} | {part['task_id'] if part['is_topic'] else 'N/A'} | {'Agendada' if part['task_id'] not in unscheduled_ids else 'Parcialmente Agendada'} | {due_date} |\n"
                )

            if unscheduled_tasks:
                f.write(
                    "\n## Tarefas Não Agendadas\n\n| Tarefa | Vencimento | Duração Estimada | ID Atividade | ID Tópico | Status |\n|--------|------------|------------------|--------------|-----------|--------|\n"
                )
                for task in self._filter_by_period(
                    unscheduled_tasks, start_date, end_date, "due_date"
                ):
                    duration = (
                        f"{task['duration'] / 3600:.2f} h"
                        if isinstance(task["duration"], (int, float))
                        else "N/A"
                    )
                    f.write(
                        f"| {task['name']} | {self.format_datetime(task['due_date'])} | {duration} | {task.get('activity_id', 'N/A')} | {task['id'] if task.get('is_topic', False) else 'N/A'} | Não Agendada |\n"
                    )

            f.write(
                f"\n**Total de partes agendadas:** {len(scheduled_parts)}\n**Total de tarefas não agendadas:** {len(unscheduled_tasks)}\n"
            )
        logger.info(f"Arquivo Markdown gerado: {file_path}")

    def generate_csv(
        self,
        scheduled_parts: List[Dict],
        unscheduled_tasks: List[Dict],
        period_name: str,
        start_date: datetime.date,
        end_date: datetime.date,
    ):
        """Gera um arquivo CSV com o cronograma.

        Args:
            scheduled_parts: Lista de partes agendadas.
            unscheduled_tasks: Lista de tarefas não agendadas.
            period_name: Nome do período (ex.: 'today').
            start_date: Data inicial do período.
            end_date: Data final do período.
        """
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
            for part in sorted(
                self._filter_by_period(
                    scheduled_parts, start_date, end_date, "start_time"
                ),
                key=lambda x: x["start_time"],
            ):
                due_date = (
                    self.format_datetime(part["due_date"])
                    if isinstance(part["due_date"], datetime.datetime)
                    else "N/A"
                )
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
            for task in self._filter_by_period(
                unscheduled_tasks, start_date, end_date, "due_date"
            ):
                duration = (
                    f"{task['duration'] / 3600:.2f}"
                    if isinstance(task["duration"], (int, float))
                    else "N/A"
                )
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
        """Exporta o cronograma para os três formatos em todos os períodos.

        Args:
            scheduled_parts: Lista de partes agendadas.
            unscheduled_tasks: Lista de tarefas não agendadas.
        """
        for period_name, (start_date, end_date) in self.get_periods().items():
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
    """Função principal para exportação de cronogramas."""
    exporter = ScheduleExporter()
    time_slots_cache = {"slots": []}
    tasks, _ = await get_tasks({}, logger)
    time_slots_data, _ = await get_time_slots(time_slots_cache, logger)

    days_to_schedule = 37
    available_slots, _, _ = generate_available_slots(
        time_slots_data, logger, days_to_schedule
    )
    scheduled_parts, _, _, unscheduled_tasks = schedule_tasks(
        tasks, available_slots, logger
    )

    await exporter.export_schedules(scheduled_parts, unscheduled_tasks)


if __name__ == "__main__":
    asyncio.run(main())
