import asyncio
import os
import sys
from config.settings import settings

def _single_instance(mode: str) -> str:
    """Trava de instância única: segundo processo falha rápido com mensagem
    clara em vez de duas instâncias se matando com Conflict no Telegram."""
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    lock = os.path.join(settings.LOG_DIR, f"bot-{mode}.lock")
    me = os.getpid()
    try:
        with open(lock, encoding="utf-8") as f:
            old = int((f.read() or "0").strip())
    except (OSError, ValueError):
        old = 0
    if old and old != me:
        try:
            os.kill(old, 0)  # existe?
            print(f"Outra instância do modo {mode} já está rodando (PID {old}). "
                  f"Feche-a antes de iniciar outra.")
            sys.exit(2)
        except OSError:
            pass  # PID morto: trava obsoleta, assume
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(me))
    except OSError as e:
        print(f"Aviso: não consegui gravar a trava ({e}).")
    return lock

async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "telegram"
    if mode not in ("telegram", "discord", "cli"):
        print(f"modo desconhecido: {mode} (use telegram|discord|cli)")
        return
    try:
        settings.validate(mode)
    except RuntimeError as e:
        print(f"Config inválida: {e}")
        sys.exit(1)
    if mode in ("telegram", "discord"):
        _single_instance(mode)
    if mode == "telegram":
        from interface.telegram_bot import build_telegram_app, worker
        app = build_telegram_app()
        async with app:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)  # F-07: sem backlog no restart
            print("Telegram polling + worker online.", flush=True)
            await worker(app)  # loop infinito
    elif mode == "discord":
        from interface.discord_bot import build_discord_bot
        bot = build_discord_bot()
        await bot.start(settings.DISCORD_BOT_TOKEN)
    elif mode == "cli":
        # Modo CLI sem Telegram — útil para teste local
        from core.orchestrator import Orchestrator
        orch = Orchestrator()
        task = " ".join(sys.argv[2:]) or input("Tarefa: ")
        async def prog(t: str): print(">>", t)
        async def conf(t: str, shot: str) -> bool:
            import os as _os
            if _os.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
                print(f"HITL AUTO-OK: {t[:150]}")
                return True
            print(f"HITL: {t} [{shot}]")
            return input("Autorizar? (s/n): ").lower().startswith("s")
        async def ask(q: str, shot: str):
            import os as _os2
            if _os2.getenv("AUTONOMOUS_MODE", "false").lower() == "true":
                return "Autorizado automaticamente (modo autônomo) — prossiga."
            print(f"PERGUNTA: {q} [{shot}]")
            try:
                return input("Resposta (vazio cancela): ") or None
            except EOFError:
                return None
        res = await orch.run_task(task, on_progress=prog, on_confirm=conf, on_ask=ask)
        print(("OK: " if res.ok else "FALHA: ") + res.message)
    else:
        print(f"modo desconhecido: {mode} (use telegram|discord|cli)")

if __name__ == "__main__":
    asyncio.run(main())
