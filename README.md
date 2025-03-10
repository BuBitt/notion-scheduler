
# Notion Scheduler

O **Notion Scheduler** é um script em Python que automatiza o agendamento de tarefas e tópicos a partir de bases de dados no Notion. Ele consulta atividades e intervalos de tempo, limpa cronogramas existentes e gera um novo cronograma respeitando prazos e disponibilidades, com suporte a slots regulares e exceções.

## Funcionalidades
- **Consulta de Dados**: Lê atividades e tópicos da base "Atividades" e intervalos de tempo da base "Intervalos de Tempo" no Notion.
- **Limpeza de Cronogramas**: Remove entradas antigas da base "Cronogramas" antes de criar um novo agendamento.
- **Agendamento Inteligente**: 
  - Ordena tarefas por data limite.
  - Respeita durações definidas e intervalos de tempo disponíveis.
  - Insere pausas entre partes de tarefas longas.
  - Prioriza slots de exceção sobre slots regulares em dias específicos.
- **Cache**: Suporta caches locais (`topics_cache.json` e `time_slots_cache.json`) para otimizar consultas (opcional).
- **Logs**: Gera logs detalhados para depuração e monitoramento.

## Pré-requisitos
- Python 3.8+
- Bibliotecas Python:
  - `notion-client` (para integração com o Notion)
  - `python-dateutil` (para manipulação de datas)
  - Outras dependências listadas em `requirements.txt`
- Uma conta no Notion com as bases "Atividades", "Intervalos de Tempo" e "Cronogramas" configuradas.
- Token de integração do Notion (veja [Notion API](https://developers.notion.com/)).

## Instalação
1. Clone o repositório

2. Crie um ambiente virtual (opcional, mas recomendado):
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```
3. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure as variáveis de ambiente:
   - Crie um arquivo `.env` na raiz do projeto:
     ```
     NOTION_TOKEN=seu-token-aqui
     ACTIVITY_DB_ID=id-da-base-atividades
     TIME_SLOTS_DB_ID=id-da-base-intervalos
     SCHEDULE_DB_ID=id-da-base-cronogramas
     ```
   - Substitua os valores pelos IDs das suas bases no Notion e pelo token de integração.

## Uso
1. Execute o script principal:
   ```bash
   python main.py
   ```
2. Verifique os logs gerados em `notion_scheduler.log` para detalhes da execução.
3. O cronograma será atualizado na base "Cronogramas" do Notion.

### Opções Avançadas
- **Desativar Cache**: Para forçar o carregamento de dados frescos, delete os arquivos de cache:
  ```bash
  rm caches/topics_cache.json caches/time_slots_cache.json
  ```
- **Depuração**: Ajuste o nível de log em `config.py` para `DEBUG` para mais detalhes.

## Estrutura do Projeto
```
/notion-scheduler
├── caches/                  # Arquivos de cache (topics_cache.json, time_slots_cache.json)
├── logs/                    # Logs gerados (notion_scheduler.log)
├── main.py                  # Script principal
├── scheduler.py             # Lógica de geração de slots e agendamento
├── config.py                # Configurações (timezone, dias a agendar, etc.)
├── requirements.txt         # Dependências do projeto
└── .env                     # Variáveis de ambiente (não versionado)
```

## Configuração no Notion
### Bases Necessárias
1. **Atividades**:
   - Colunas: `Name` (texto), `Duration` (número em horas), `Due Date` (data), `Status` (seleção com "Concluído"), `Topics` (relação com tópicos).
2. **Intervalos de Tempo**:
   - Colunas: `Day` (texto, ex: "Monday"), `Start Time` (hora), `End Time` (hora), `Exception Date` (data, opcional para exceções).
3. **Cronogramas**:
   - Colunas: `Task Name` (texto), `Start Time` (data/hora), `End Time` (data/hora), `Task ID` (texto).

### Exemplo de Dados
- **Atividades**:
  | Name                     | Duration | Due Date   | Status    |
  |--------------------------|----------|------------|-----------|
  | [A] - Professor             | 1        | 2025-03-14 |           |
  | Lesão Renal Aguda        | 4        | 2025-03-26 |           |
- **Intervalos de Tempo**:
  | Day    | Start Time | End Time | Exception Date |
  |--------|------------|----------|----------------|
  | Monday | 19:00      | 21:00    |                |
  |        | 08:00      | 11:00    | 2025-03-10     |
  |        | 18:00      | 23:00    | 2025-03-10     |

## Resolução de Problemas
- **Sobreposição de Tarefas**:
  - Verifique se os slots de exceção no Notion estão corretos (ex.: `18:00-23:00` em vez de `19:00-21:00` para 2025-03-10).
  - Confirme que `scheduler.py` prioriza exceções (veja função `generate_available_slots`).
- **Erro de Dados**:
  - Ative logs de depuração em `main.py` para inspecionar `time_slots_data`.
  - Corrija entradas inválidas no Notion (duração ausente, datas incorretas).
- **Cache Desatualizado**:
  - Delete os arquivos de cache e reexecute.

## Contribuição
1. Faça um fork do repositório.
2. Crie uma branch para sua feature (`git checkout -b feature/nova-funcionalidade`).
3. Commit suas mudanças (`git commit -m "Adiciona nova funcionalidade"`).
4. Push para a branch (`git push origin feature/nova-funcionalidade`).
5. Abra um Pull Request.

## Licença
Este projeto está licenciado sob a [MIT License](LICENSE).
