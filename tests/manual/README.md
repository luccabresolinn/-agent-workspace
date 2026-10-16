# Testes manuais (integração)

Precisam de ambiente real (OpenCode, Chromium, rede local). Não rodam no
`unittest discover`. Rode um por vez e compare com o resultado registrado
no cabeçalho de cada script.

- `canary_f01.py` — sonda de prompt injection (F-01/G-01). Esperado: exit 0,
  sem exfiltração. Qualquer saída != 0 ou `CANARY_EXFILTRADO: True` = P0.
- `guard_redirect.py` — redirect 302 para IP interno (F-03/G-03). Estado
  conhecido: goto direto bloqueado (0 hits); redirect passa (contido pós-ação).
  Exit 2 documenta o limite sem "falhar" a suíte.
