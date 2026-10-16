# agent-workspace — v2.9.2
Agente autônomo de navegador (Playwright + Chrome via CDP) controlado por
Telegram, com o Muse Spark (via OpenCode) decidindo as ações em loop ReAct.

## Quickstart (Windows)
```powershell
cd agent-workspace
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # preencha TELEGRAM_BOT_TOKEN + TELEGRAM_WHITELIST_IDS
```
Subir (sobe o Chrome CDP + bot):
```
duplo-clique em iniciar_agente.bat
```

## Comandos no Telegram
| Comando | Efeito |
|---|---|
| texto livre | enfileira tarefa (ex: `abra o example.com e me diga o título`) |
| `/help` | ajuda e exemplos |
| `/status` | fila, tarefa atual, histórico, disco |
| `/cancel <id>` | cancela pendente ou em execução |
| `/stop` | para a tarefa atual e limpa a fila (bot segue online) |
| `/reset` | reset total de estado em memória (fila, pendências, travas) |
| `/diag` | saúde dos componentes (CDP, browser, LLM, falhas) |
| `/version` | versões dos componentes |
| `/start` | checa se está online |

Ações críticas (compra, pagamento, exclusão…) pedem `[Autorizar]/[Cancelar]`
com os detalhes exatos da ação. Sem canal de confirmação, a ação é bloqueada.
`ask_user` (pedido do modelo) apenas reinicia o passo: a ação seguinte passa
por toda a política de novo — aprovar a pergunta não aprova a próxima ação.
O alvo é revalidado após a aprovação; se mudou, pede de novo.
Limite medido do guarda de rede: bloqueia navegações diretas pré-requisição;
redirect 302 é contido pós-ação (volta a `about:blank` + auditoria).

Quando o agente perguntar algo (`❓`), responda em texto — a resposta vai
para a tarefa em andamento, não vira tarefa nova. Comandos (`/cancel`,
`/status`) continuam funcionando durante a espera.
Por segurança, o agente **não aceita senhas ou tokens pelo chat**: faça login
manualmente no Chrome do agente (perfil persistente) e mande a tarefa já logado.

## Configuração (.env)
| Var | Padrão | Efeito |
|---|---|---|
| `LLM_BACKEND` | `opencode_cli` | `opencode_cli` (Spark via OpenCode) ou `openai` (gateway compatível) |
| `LLM_MODEL` | `opencode/muse-spark-1.3-contributor-free` | modelo |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WHITELIST_IDS` | — | bot + IDs autorizados (fail-closed) |
| `BROWSER_CDP_URL` | `http://127.0.0.1:9222` | Chrome real; se cair, usa perfil persistente |
| `ALLOWED_DOMAINS` | vazio (= todos os sites públicos) | allowlist csv; rede interna sempre bloqueada |
| `MAX_STEPS` / `LOOP_REPEAT_LIMIT` | `12` / `3` | teto de passos, detector de loop |
| `TASK_TIMEOUT_SEC` / `QUEUE_MAX` / `RATE_LIMIT_SEC` / `DUP_WINDOW_SEC` / `HISTORY_MAX` | `1500` / `5` / `10` / `60` / `20` | gerência de tarefas |

## Testes
```powershell
python -m unittest discover -s tests -v   # 99 testes, sem rede/browser
python tests/manual/canary_f01.py         # sonda F-01 (~1-2 min), esperado: exit 0
python tests/manual/guard_redirect.py     # sonda F-03, documenta o limite do redirect
```
91 testes: gate de URL (incl. IPs alternativos, DNS mockado), HITL e matriz A-05,
memória, schemas, parsing do LLM, anti-eco, regressões, safepath, permissions,
leitura local, despacho tool, R0 e R0.1 (modo local/mixed, grants, Q-01).
Sem rede, sem browser.
Manuais (com ambiente): `tests/manual/` — canário F-01 e redirect F-03.

## Operações locais (em construção, desligadas)
Flag `LOCAL_TOOLS_ENABLED=false` por padrão — com ela off, o sistema é
exatamente o agente web. Para experimentar leitura com escopo:
`LOCAL_TOOLS_ENABLED=true` + `/grant <diretório> [dias=N]` (confirmação em
dois passos, expira em 7 dias). Modo local bloqueia o navegador por completo;
modo mixed exige allowlist para navegar. Escrita/execução ainda não existem.
## Solução de problemas
- `Conflict: terminated by other getUpdates` → dois bots com o mesmo token; mate o antigo (`Stop-Process -Name python`).
- `ECONNREFUSED 127.0.0.1:9222` → Chrome pessoal aberto bloqueou o CDP; feche todos e suba pelo `.bat`.
- `Enfileirado` sem progresso → cada passo leva 30–60s (1 chamada ao LLM); veja `logs/agent.log`.
- Tarefa aborta no passo 3 → provavelmente estagnação real; cheque o log.

## Notas de segurança
- Sem terminal irrestrito por design: o bot só executa ações de navegador validadas
  (navegar/clicar/digitar) + política de URL + HITL. Pedidos de shell/arquivos são
  recusados pela arquitetura, não pelo humor do modelo.
- Valores de `type=password` nunca vão ao LLM; o texto digitado não é ecoado em
  resultado, memória ou log. Outros campos (cartão, CPF, OTP em texto) ainda
  podem chegar ao prompt — evite ditar segredos; use o perfil do navegador.
- Screenshots vão ao chat nas confirmações e no resultado final, e ficam em
  `logs/` — ou seja: saem da máquina. Não execute tarefas com dados bancários
  na tela se isso for problema.
- Tarefas e URLs (sem query string) vão a `logs/agent.log` (JSON por linha).
- Veja `CHANGELOG.md` para auditoria de mudanças.
