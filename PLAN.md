# Plano de Execução: Design Snapshot Bot (MVP)

> **Para a IA executora (Claude Code):** Este documento é um plano de implementação. Leia tudo antes de começar. Execute os passos em ordem. Em cada passo há critérios de validação — só avance quando o passo atual estiver validado. Se algo divergir do plano, **pare e pergunte** antes de improvisar.

---

## 1. Contexto do problema

Um time de desenvolvimento Android sofre com designers alterando o Figma **depois** que a task entrou em "Doing", sem avisar o dev. Branching nativo do Figma e e-mails de alerta já foram tentados e não funcionaram (devs não viam).

A solução de longo prazo será um bot que:
1. Detecta quando uma task entra em "Doing" no Jira.
2. Tira um snapshot (PNG + metadados) do design no Figma naquele momento.
3. Monitora periodicamente se o Figma daquela task mudou e alerta o time.

**Este documento cobre apenas o MVP** — os passos 1 a 3 do plano original. O objetivo é validar manualmente que o snapshot funciona antes de automatizar com Jira e cron.

## 2. Escopo do MVP

O que entra:
- Repositório novo, isolado de qualquer código de app.
- Um GitHub Actions workflow disparado **manualmente** (`workflow_dispatch`) que recebe uma URL do Figma e um identificador de task como inputs.
- Um script Python que baixa as imagens dos frames daquele link via Figma API, salva como PNG em `/snapshots/{TASK_ID}/{TIMESTAMP}/`, gera um `metadata.json` com as informações da versão, e commita de volta no repo.

O que **não** entra (ficará para fases seguintes):
- Integração com Jira (webhook ou polling).
- Cron de detecção de mudança.
- Notificações automáticas.
- Qualquer interface web ou dashboard.

## 3. Decisões já tomadas (não reabrir)

- **Linguagem:** Python 3.11+.
- **CI:** GitHub Actions.
- **Trigger:** `workflow_dispatch` manual (sem webhook nesta fase).
- **Armazenamento dos snapshots:** no próprio repositório, em `/snapshots/`. O git vira o histórico/auditoria.
- **Formato de imagem:** PNG, escala 2x.
- **Nome do repositório de exemplo:** `design-snapshot-poc` (ajustar conforme o squad).

## 4. Pré-requisitos que o usuário humano precisa providenciar

Antes da IA executora começar, o usuário humano precisa ter:

1. Um **Figma Personal Access Token** com escopo `file_content:read` e `file_metadata:read`. Gerar em: Figma → Settings → Security → Personal access tokens.
2. O repositório criado no GitHub (vazio ou só com README) — a IA executora não cria repositório, só popula.
3. O token do Figma adicionado como **secret** do repositório com o nome `FIGMA_TOKEN` (Settings → Secrets and variables → Actions → New repository secret).

> **IA executora:** se algum desses pré-requisitos não estiver satisfeito quando você for testar, pare e avise o usuário em vez de tentar contornar.

---

## 5. Estrutura final esperada do repositório

```
.
├── .github/
│   └── workflows/
│       └── manual-snapshot.yml
├── scripts/
│   └── snapshot.py
├── snapshots/
│   └── .gitkeep
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 6. Passos de execução

### Passo 1 — Inicializar a estrutura

Criar os arquivos abaixo com conteúdo mínimo. Não preencher lógica ainda.

- `requirements.txt` com as dependências: `requests` e `python-dotenv` (este último só pra facilitar testes locais).
- `.gitignore` cobrindo: `.env`, `__pycache__/`, `*.pyc`, `.venv/`.
- `snapshots/.gitkeep` vazio (pra o diretório existir no git).
- `README.md` com 1 parágrafo explicando o que é o repo (uma versão curta da seção 1 deste plano) e como rodar manualmente o workflow no GitHub Actions.

**Validação:** o usuário humano consegue clonar e rodar `pip install -r requirements.txt` sem erro.

---

### Passo 2 — Implementar `scripts/snapshot.py`

Esse é o coração do MVP. O script tem que:

**Inputs (lidos de variáveis de ambiente):**
- `FIGMA_TOKEN` — obrigatório.
- `FIGMA_URL` — URL completa de um frame ou file do Figma. Exemplos válidos:
  - `https://www.figma.com/design/{FILE_KEY}/{TITLE}?node-id=123-456`
  - `https://www.figma.com/file/{FILE_KEY}/{TITLE}?node-id=123-456`
- `TASK_ID` — identificador livre da task (ex: `JIRA-123`). Vai virar o nome da pasta.

**Lógica:**

1. **Parsear a URL do Figma** para extrair `FILE_KEY` e `NODE_ID`.
   - O `FILE_KEY` é o segmento depois de `/design/` ou `/file/`.
   - O `NODE_ID` vem do query param `node-id`. Atenção: o Figma usa `-` na URL mas a API quer `:`. Exemplo: URL `node-id=123-456` vira nodeId `123:456` na chamada da API.
   - Se `node-id` não estiver presente, o script deve falhar com mensagem clara — não tentar adivinhar.

2. **Chamar `GET https://api.figma.com/v1/files/{FILE_KEY}/nodes?ids={NODE_ID}`** com header `X-Figma-Token: {FIGMA_TOKEN}`. Isso retorna metadados do(s) node(s).

3. **Chamar `GET https://api.figma.com/v1/images/{FILE_KEY}?ids={NODE_ID}&scale=2&format=png`**. Retorna um JSON com URLs temporárias de S3 para cada nodeId. Baixar o PNG dessas URLs.

4. **Chamar `GET https://api.figma.com/v1/files/{FILE_KEY}/versions`** e pegar a versão mais recente (primeiro item da lista). Guardar `id`, `created_at` e `label` (se houver).

5. **Salvar tudo em** `snapshots/{TASK_ID}/{TIMESTAMP}/`, onde `TIMESTAMP` é UTC no formato `YYYYMMDD-HHMMSS`. Dentro dessa pasta:
   - `frame.png` — a imagem baixada. Se houver múltiplos nodes, salvar como `frame_{nodeId}.png`.
   - `metadata.json` — com a estrutura abaixo.

**Formato do `metadata.json`:**

```json
{
  "task_id": "JIRA-123",
  "captured_at_utc": "2026-05-06T18:30:00Z",
  "figma": {
    "url": "<URL original passada como input>",
    "file_key": "<FILE_KEY>",
    "node_ids": ["123:456"],
    "current_version_id": "<id da versão>",
    "current_version_created_at": "<timestamp da versão>",
    "current_version_label": "<label ou null>"
  },
  "frames": [
    {
      "node_id": "123:456",
      "name": "<nome do frame extraído da resposta de /nodes>",
      "image_file": "frame.png"
    }
  ]
}
```

**Tratamento de erros:**
- Token inválido (401): mensagem explícita pedindo para verificar o secret `FIGMA_TOKEN`.
- File não encontrado (404): mensagem dizendo que o `FILE_KEY` extraído da URL não foi encontrado, e mostrar o `FILE_KEY` extraído pra o usuário conferir.
- Node não encontrado: idem, mostrando o `NODE_ID` traduzido (com `:`).
- Erro de download da imagem: tentar novamente uma vez antes de falhar.

**Estilo do código:**
- Funções pequenas e nomeadas: `parse_figma_url`, `fetch_node_metadata`, `fetch_image_urls`, `download_image`, `fetch_latest_version`, `save_snapshot`, `main`.
- Sem classes desnecessárias — é um script.
- Usar `requests` direto, sem wrappers.
- Logs simples com `print`, prefixados com `[snapshot]`.

**Validação:** rodar localmente com:
```bash
export FIGMA_TOKEN=...
export FIGMA_URL='https://www.figma.com/design/abc123/Test?node-id=1-2'
export TASK_ID=TEST-001
python scripts/snapshot.py
```
Resultado esperado: pasta `snapshots/TEST-001/<timestamp>/` criada com `frame.png` e `metadata.json` válidos.

---

### Passo 3 — Implementar `.github/workflows/manual-snapshot.yml`

Workflow do GitHub Actions com `workflow_dispatch` e dois inputs: `figma_url` (string, required) e `task_id` (string, required).

**O workflow precisa:**

1. Rodar em `ubuntu-latest`.
2. `actions/checkout@v4` com `token: ${{ secrets.GITHUB_TOKEN }}` e `persist-credentials: true` (precisa pra dar push depois).
3. `actions/setup-python@v5` com Python 3.11.
4. Instalar deps: `pip install -r requirements.txt`.
5. Rodar o script passando as variáveis de ambiente:
   ```yaml
   env:
     FIGMA_TOKEN: ${{ secrets.FIGMA_TOKEN }}
     FIGMA_URL: ${{ inputs.figma_url }}
     TASK_ID: ${{ inputs.task_id }}
   ```
6. **Commitar e pushar** os arquivos novos em `snapshots/`. Configurar o git user como `github-actions[bot]`. Mensagem do commit: `snapshot: {task_id} @ {timestamp}`.
   - Se não houver mudanças (sem novos arquivos), o step de commit deve passar sem falhar — usar `git diff --staged --quiet || git commit ...`.

**Permissões necessárias no workflow:**
```yaml
permissions:
  contents: write
```

**Validação:** ir em Actions → Manual Snapshot → Run workflow, preencher um link real do Figma e um task_id qualquer, e ver:
- O workflow termina verde.
- Aparece um commit novo no repo com a pasta `snapshots/<task_id>/<timestamp>/`.
- O `frame.png` abre e mostra o design correto.

---

## 7. Critério de aceitação geral do MVP

O MVP está pronto quando um humano consegue:

1. Ir no GitHub, aba Actions.
2. Disparar o workflow manualmente passando uma URL real do Figma e um task_id.
3. Ver o resultado commitado no repositório em até 1 minuto.
4. Abrir a imagem e confirmar que é o design correto.
5. Abrir o `metadata.json` e ver a versão atual do arquivo Figma registrada.

Se isso funciona pra 3 tasks reais diferentes, o MVP está validado e o próximo passo (não coberto aqui) é adicionar polling do Jira e cron de detecção de mudança.

---

## 8. O que NÃO fazer

- Não tentar integrar com Jira agora, mesmo que pareça fácil.
- Não criar diff visual entre snapshots agora.
- Não adicionar testes automatizados — é um POC manual.
- Não usar bibliotecas pesadas tipo `pydantic`, `click`, `httpx`. Manter `requests` puro.
- Não criar interface web ou Streamlit.
- Não armazenar imagens em S3/cloud externo — o git resolve nesta fase.

---

## 9. Quando terminar

Ao finalizar, deixar um comentário/resumo para o usuário humano contendo:
- Lista dos arquivos criados.
- Comando exato para testar localmente (com placeholders pros valores).
- Print/cópia da resposta esperada de uma execução bem-sucedida (estrutura de pastas gerada).
- Qualquer ponto onde você precisou tomar uma decisão que não estava 100% no plano.
