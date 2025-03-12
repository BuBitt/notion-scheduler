# Guia da Tabela "Horários" no Notion Scheduler

Este documento explica como usar a tabela "Horários" (associada ao `TIME_SLOTS_DB_ID` no Notion) no programa `notion-scheduler`. A tabela "Horários" define os slots de tempo disponíveis para o agendamento de tarefas e tópicos, e é essencial para o funcionamento do sistema. Abaixo, você encontrará uma visão geral de seu propósito, como configurá-la e as funções relacionadas no código.

## Propósito da Tabela "Horários"
A tabela "Horários" no Notion é usada para:
- **Definir Slots Regulares**: Especificar períodos de tempo recorrentes em dias da semana (ex.: toda segunda-feira das 9h às 12h).
- **Definir Exceções**: Sobrescrever ou excluir slots em datas específicas (ex.: feriados ou dias com horários especiais).
- **Controlar Disponibilidade**: Informar ao programa quando tarefas podem ser agendadas, respeitando o fuso horário local (`Config.LOCAL_TZ`).

Os dados desta tabela são processados pela função `get_time_slots` em `notion_api.py` e usados em `generate_available_slots` em `scheduler.py` para criar a lista de slots disponíveis para agendamento.

## Estrutura da Tabela no Notion
A tabela "Horários" deve conter as seguintes colunas (propriedades):

| Nome da Coluna       | Tipo no Notion | Descrição                                                                 |
|----------------------|----------------|---------------------------------------------------------------------------|
| `Dia da Semana`      | Select         | Dia da semana para slots regulares (ex.: "Segunda", "Terça"). Opcional se houver "Exceções". |
| `Hora de Início`     | Rich Text      | Hora de início do slot no formato `HH:MM:SS` (ex.: "09:00:00"). Obrigatório. |
| `Hora de Fim`        | Rich Text      | Hora de fim do slot no formato `HH:MM:SS` (ex.: "12:00:00"). Obrigatório.   |
| `Exceções`           | Date           | Data específica para exceções (ex.: "2025-03-15"). Opcional.              |

### Requisitos
- **"Dia da Semana"**: Deve corresponder aos valores em `Config.DAY_MAP` (ex.: "segunda", "terça", etc., em minúsculas). Use nomes em português consistentes com o mapeamento.
- **"Hora de Início" e "Hora de Fim"**: Devem estar no formato `HH:MM:SS` (24 horas). Exemplo: "08:30:00" para 8:30 da manhã.
- **"Exceções"**: Se preenchido, define uma data específica para o slot. Se vazio, o slot é considerado recorrente para o dia da semana indicado.

## Como Configurar a Tabela
1. **Clone a Base de Dados no Notion**:

2. **Adicione Slots Regulares**:
   - Para cada dia da semana com disponibilidade recorrente:
     - Preencha "Dia da Semana" (ex.: "Segunda").
     - Insira "Hora de Início" (ex.: "09:00:00") e "Hora de Fim" (ex.: "12:00:00").
     - Deixe "Exceções" vazio.
   - Exemplo:
     ```
     Dia da Semana: Segunda
     Hora de Início: 09:00:00
     Hora de Fim: 12:00:00
     Exceções: [vazio]
     ```

3. **Adicione Exceções**:
   - Para datas específicas (ex.: feriados ou ajustes pontuais):
     - Deixe "Dia da Semana" vazio ou preenchido (o programa atualizará automaticamente para o dia correspondente à data).
     - Preencha "Hora de Início" e "Hora de Fim".
     - Insira a data em "Exceções" (ex.: "2025-03-15").
   - Exemplo:
     ```
     Dia da Semana: [vazio]
     Hora de Início: 14:00:00
     Hora de Fim: 16:00:00
     Exceções: 2025-03-15
     ```
   - Para excluir um dia inteiro, deixe "Hora de Início" e "Hora de Fim" vazios e preencha apenas "Exceções":
     ```
     Dia da Semana: [vazio]
     Hora de Início: [vazio]
     Hora de Fim: [vazio]
     Exceções: 2025-03-20
     ```

4. **Valide os Dados**:
   - Certifique-se de que "Hora de Início" seja anterior a "Hora de Fim".
   - Verifique que os dias em "Dia da Semana" estejam em português e correspondam ao `DAY_MAP` em `config.py`.

## Exemplo Completo no Notion
| Dia da Semana | Hora de Início | Hora de Fim | Exceções   |
|---------------|----------------|-------------|------------|
| Segunda       | 09:00:00       | 12:00:00    | [vazio]    |
| Terça         | 14:00:00       | 17:00:00    | [vazio]    |
| [vazio]       | 10:00:00       | 12:00:00    | 2025-03-15 |
| [vazio]       | [vazio]        | [vazio]     | 2025-03-20 |

- **Resultado**:
  - Slots regulares toda segunda (9h-12h) e terça (14h-17h).
  - Exceção em 15/03/2025 (10h-12h).
  - 20/03/2025 excluído do agendamento.
