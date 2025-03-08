## Distribuidor Automático de Tarefas em Horários Livres

Este script tem como objetivo distribuir automaticamente atividades dentro dos horários disponíveis de um cronograma. Ele utiliza a API do Notion para interagir com bases de dados que armazenam informações sobre tarefas, tópicos de estudo, horários livres e a programação já existente.

### Requisitos

#### 1. Acesso à API do Notion
Para que o script funcione corretamente, é necessário ter:
- Uma conta no Notion.
- Um banco de dados configurado no Notion para armazenar as informações.
- Uma chave de integração (API Key) gerada no [Notion Integrations](https://www.notion.so/my-integrations).
- Os IDs das bases de dados que serão manipuladas pelo script.

#### 2. Dependências
O script requer algumas bibliotecas para funcionar corretamente. Certifique-se de instalar as dependências:
```sh
pip install -r requirements.txt
```

#### 3. Bases de Dados Necessárias
O funcionamento do script depende de quatro bases de dados no Notion:

##### **ATIVIDADES**
Esta base contém todas as tarefas que precisam ser distribuídas ao longo do cronograma. Cada atividade deve ter:
- **Nome**: Nome da atividade.
- **Duração Estimada**: Tempo necessário para realizar a atividade.
- **Prioridade**: Grau de importância da atividade.
- **Status**: Indica se a atividade já foi realizada ou ainda precisa ser alocada.

##### **TÓPICOS**
Esta base contém os assuntos das atividades. Cada tópico deve ter:
- **Nome do Tópico**: Nome do tema a ser estudado.
- **Relação com Atividades**: Indicação de quais atividades pertencem a este tópico.

##### **CRONOGRAMA**
Esta base contém a programação das atividades já distribuídas. Cada entrada deve ter:
- **Data e Hora**: Quando a atividade será realizada.
- **Nome da Atividade**: Nome da atividade planejada.

##### **HORÁRIOS**
Esta base contém os horários livres disponíveis. Cada entrada deve ter:
- **Data e Hora**: Momento disponível no cronograma.
- **Duração**: Tempo disponível para alocação.

### Funcionamento do Script
1. O script acessa a base **ATIVIDADES** para identificar quais tarefas precisam ser alocadas.
2. Ele verifica os **HORÁRIOS** disponíveis no cronograma.
3. Com base nas prioridades e durações das atividades, o script distribui as tarefas nos horários disponíveis.
4. As informações são salvas na base **CRONOGRAMA**, garantindo que todas as atividades sejam organizadas de maneira eficiente.

### Configuração
Para utilizar o script, crie um arquivo `.env` na mesma pasta do código e adicione:
```env
NOTION_API_KEY="sua_api_key"
DATABASE_ATIVIDADES_ID="id_da_base_atividades"
DATABASE_TOPICOS_ID="id_da_base_topicos"
DATABASE_CRONOGRAMA_ID="id_da_base_cronograma"
DATABASE_HORARIOS_ID="id_da_base_horarios"
```
Substitua os valores pelos respectivos IDs das bases de dados.

### Execução
Após configurar o ambiente, execute o script com o comando:
```sh
python script.py
```
Isso garantirá que as atividades sejam automaticamente distribuídas nos horários livres do cronograma.

---
Esse sistema ajuda a otimizar o planejamento de tarefas, garantindo que todas as atividades sejam organizadas de maneira eficiente dentro do tempo disponível.

