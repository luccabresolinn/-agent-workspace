# Changelog

## 2.9.3 — Correções da fase 2 (Windows como plataforma-alvo)
- **BUG CRÍTICO corrigido**: `NameError: _operation_sig` em `core/orchestrator.py`
  quebrava TODA operação local de escrita (nível C/D, caminho HITL) no modo
  supervisionado. Agora usa `tools.permissions.operation_sig` — a mesma função
  que gera a assinatura do journal, garantindo sig aprovado == sig registrado.
- Teste de regressão adicionado (`TestWriteRegression`): fs.write_file ponta a
  ponta com aprovação simulada, verificando arquivo escrito e HITL acionado.
- `validate_root` agora é portável: regras calibradas para Windows continuam
  idênticas (drive raiz/raso/sistema/perfil/repo negados); caminhos POSIX
  (usados por testes/ferramentas) deixaram de ser barrados por contagem de
  componentes pensada só para "C:\". Teste `test_grant_flow_confirm` verde.
- Prompts alinhados ao schema: BASE_PROMPT e AUTO_PROMPT passam a listar os
  mesmos 12 action_types de `core.schemas.ActionType` (scroll/select/reload
  eram descritos no corpo mas omitidos na lista; ask_user/tool harmonizados).
- Documentação: suporte oficial restrito a Windows (decisão do operador).

## 2.9.2 — Reconciliação com a reauditoria (Achados A–C + T3–T9)
- Q-03 real: dias SOMENTE via `dias=N`; numéricos soltos viram finalidade
- Q-04: `create(validate=True)`; repo cross-drive sem ValueError
- Q-05: reset limpa propostas; expiradas podadas; revalidação ao confirmar
- Achado B: mixed simétrico (type/click bloqueados, estaciona, navigate c/ allowlist)
- Achado C: sig da tool com hash local (web imune a tools/ quebrado)
- D: `path_fields=None` vs `()`; G: journal sem duplicata
- Testes: 99 (T3–T9: grants, mixed, import quebrado, sentinela)

## 2.9.1 — Etapa A/B da reauditoria v2.9 (Q-01 trava tudo local sem isso)
- Q-01: assinatura inclui tool+args; tool fora da estagnação (T1 5 distintas OK, T2 3 idênticas abortam)
- Q-09: sem scan em modo local; aborto com mensagem própria de modo
- Q-06: import lazy de tools.permissions (web sobe sem o pacote)
- path_fields declarado por ToolSpec (fim da adivinhação por nome)
- Q-04: cross-drive vira PathDenied; create() valida por padrão
- Q-05: /reset limpa propostas de grant; expiradas podadas
- Q-03: dias só via `dias=N`, resto é finalidade; cartão mostra o parse
- Q-02: mixed = local + navigate com allowlist (simetria documentada)
- tool_ms no audit; testes: 91

## 2.9.0 — R0 da reauditoria v2.8 (sem escrita antes disso)
- P0-1: modo local bloqueia click/type/press_key/navigate + estaciona em about:blank
- P0-2: /grant com validate_root (sem drive raiz/raso/sistema/repo), dias 1–90,
  caminhos com espaço e confirmação em dois passos (`confirmar <token>`)
- P0-4: cross-drive vira PathDenied auditável, nunca ValueError
- P1-6: tool pula o HITL de navegador (aprovação própria); mixed exige allowlist
- P0-3: matriz de canário ampliada (6 variantes PT/EN) + relatório arquivado
- Testes: 89 (R0 completo)

## 2.8.0 — Fundações de operações locais (desligadas por padrão)
- `tools/`: contrato (base), safepath, secretscan, permissions (grants A–F),
  `filesystem/read` (6 ferramentas de leitura A/B)
- `AgentAction` com `tool`/`args`; despacho no orquestrador atrás de
  `LOCAL_TOOLS_ENABLED=false` (com flag off, comportamento é idêntico à v2.7)
- Modo de tarefa: primeira ferramenta muda para `local` e bloqueia `navigate`
- Journal `ops.jsonl`; `/grant`, `/revoke`, `/grants`; prompts marcam dado não confiável
- Canário F-01: matriz 3/3 contida, relatório em `tests/manual/canary_REPORT.md`
- Testes: 79 (safepath, permissions, leitura, despacho)

## 2.7.0 — Comandos /stop e /reset
- `/stop`: cancela a execução, nega confirmações, resolve perguntas, limpa a fila
- `/reset`: reset total em memória (fila, pendências, travas, registry) com resumo;
  histórico e logs preservados; processo segue rodando (restart via `.bat`)
- Testes: 54 (stop/reset com mocks)

## 2.6.0 — Respostas e firewall de credenciais
- Resposta a pergunta do agente resolve a pergunta (não vira tarefa nova);
  comandos furam a espera (`/cancel` continua valendo)
- Firewall: pedido de senha/token é recusado com orientação de login manual;
  resposta com cara de segredo aborta sem ir a log, memória ou LLM
- Backstop `_redact` no audit: `senha <valor>` nunca persiste
- `on_ask` no Telegram/Discord/CLI (legado booleano mantido como fallback)
- Testes: 51 (firewall, Q&A, roteamento)

## 2.5.0 — Fase A da reauditoria v2.4
- G-08/NF-01: tecla de `press_key` visível na aprovação; só `type` é mascarado
- G-05/NF-02: confirmação com peek-then-pop — terceiro não destrói pendência
- G-04: rótulos todos-numé hex disfarçados bloqueados (`127.0.0.0x1`)
- G-06: assinatura com destino/onclick/bbox; falha de re-scan BLOQUEIA
- NF-03: `build_detail` extraído e testado de verdade
- G-01: sonda de canário versionada em `tests/manual/` (verde em 2026-10-12)
- G-03: `tests/manual/guard_redirect.py` + estado do guard no `/diag`
- G-21: `scan_ms`/`llm_ms`/`action_ms` no audit + p50 no `/diag`
- F-14/F-15 com regressão; `history.json` atômico; rotação de log
- Testes: 43 (orquestrador com stubs, callback, edited_message)

## 2.4.0 — Fase 0 da reauditoria v2.3
- F-02: `text_content` mascarado na aprovação HITL (comprimento, nunca o segredo)
- F-07: formas numéricas não-padrão de IP bloqueadas (decimal, curta, hex, octal)
- F-05: alvo revalidado após aprovação; divergência pede confirmação de novo
- F-13/F-14/F-15: detalhe sem "None"; `m.reply_text` nos ramos de erro;
  chave de confirmação `(chat_id, message_id)`
- F-17: `history.json` atômico; rotação de `agent.log` (5MB)
- F-18: fonte única de `ALLOWED_DOMAINS` (policy lê o env); removida config fantasma
- F-12: `.bat` com perfil existente preservado, countdown antes de fechar o Chrome
- F-03: estado do route guard no `/diag`; MEDIDO: redirect 302 não é
  interceptado pré-requisição (contido pós-ação) — documentado, sem alegação falsa
- F-01: sonda de canário executada — sem exfiltração (evidência parcial, ver relatório)
- Testes: 35 (regressões F-02/F-07/F-13/F-15, IPs alternativos, anti-eco)

## 2.3.0 — Política central, diagnóstico e memória persistente
- `core/policy.py`: classificação de risco central (read/write/critical);
  orquestrador delega (sem regex duplicado)
- Removida config fantasma `HITL_KEYWORDS` (não tinha efeito; classifier é regex interno)
- Auditoria em `ask_user`/`ask_decision` e registro de verificação no `finish` (url+título)
- `/diag`: CDP, chromium, CLI, modelo e falhas recentes (read-only)
- Histórico de tarefas persistido em `logs/history.json`; registry podado
- Testes: 29 (política central, parsing de saída do LLM)
- Processo roda sem elevação (usuário padrão) — isolamento maior exige conta dedicada (documentado, não executado)

## 2.2.0 — Reauditoria: HITL, URL e privacidade
- HITL: `Enter`/`Return` e `type=submit` sempre pedem aprovação; verbos
  (aceitar, permitir, autorizar, sacar, withdraw, post, tweet, criar conta) e
  paths (`/delete`, `/remove`, `/admin`, `/account`) adicionados
- `policy.py`: rejeita `\`/controles, `localhost` por nome, DNS assíncrono;
  falha de DNS bloqueia com allowlist ativa
- Navegação verificada pós-ação (redirecionamento p/ host interno volta p/ about:blank)
  + guarda de rota no contexto (best effort)
- `type` não ecoa o texto (resultado/memória/log); parser expõe `type=` em buttons
- Auditoria com `actor` e URLs sem query; filho `opencode` morto também no cancel
- Sessão do navegador se recupera se o contexto morrer
- Telegram: `edited_message` sem crash, `/status` sem Markdown
- Discord: fila limitada, timeout, worker único, `autorizar` não vira tarefa
- Testes: 20 (policy com DNS mockado, matriz A-05, anti-eco)
- README alinhado ao comportamento real (A-21)
- Corrige falso positivo que eu mesmo introduzi: `pag*` casava "página" (v2.1)

## 2.1.0 — Central de comandos e gerenciamento de tarefas
- Comandos: `/help`, `/status`, `/cancel <id>`, `/version` (+ `/start`)
- Registry de tarefas com IDs curtos (`[#a1b2c3]`), histórico e timeout global (`TASK_TIMEOUT_SEC`)
- Cancelamento de pendentes e em execução (`should_stop` no loop ReAct)
- Fila limitada (`QUEUE_MAX`), rate-limit (`RATE_LIMIT_SEC`) e anti-duplicata (`DUP_WINDOW_SEC`)
- Validação de config no boot (`settings.validate`) com mensagens claras
- Correlation ID (`tid`) nos eventos de `logs/agent.log`
- Testes: `python -m unittest discover -s tests` (13 testes)
- `.gitignore` (`.env`, perfil do navegador, logs fora do versionamento)
- Corrige falso positivo do HITL: `pag\w*` casava "página" — padrão apertado

## 2.0.0 — Endurecimento pós-auditoria (P0/P1)
- `llm/client.py`: sem `cmd /c` (binário direto), prompt por arquivo, env allowlist,
  cwd isolado com limpeza, erros do `opencode run` surfados
- `browser/policy.py`: gate de URL (esquemas, rede interna, `ALLOWED_DOMAINS`)
- HITL determinístico sobre ação concreta; crítica sem canal bloqueia
- Discord fail-closed + confirmação vinculada; callback Telegram autenticado
- Senhas fora do prompt; `drop_pending_updates`; `.bat` sem `taskkill` cego
- `screenshot()` com timeout + fallback (tarefa concluída nunca vira "erro interno")
- Worker não morre em silêncio; confirmação funciona sem foto

## 1.0.0 — Esqueleto inicial
- Loop ReAct, Indexed AXTree, fila assíncrona, CDP, guardrails básicos
