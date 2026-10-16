import discord
from discord.ext import commands
import asyncio
import secrets
from config.settings import settings
from core.orchestrator import Orchestrator

orch = Orchestrator()

def build_discord_bot() -> commands.Bot:
    # A-03: falhar fechado — sem whitelist, o bot nem inicia
    if not settings.DISCORD_WHITELIST_IDS:
        raise RuntimeError("DISCORD_WHITELIST_IDS vazio: recusando iniciar (fail-closed).")
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    queue: asyncio.Queue = asyncio.Queue(maxsize=settings.QUEUE_MAX)

    @bot.event
    async def on_ready():
        print(f"Discord online como {bot.user}")
        # N-02: on_ready pode disparar em reconexões — um worker só
        if getattr(bot, "_worker_started", False):
            return
        bot._worker_started = True
        bot.loop.create_task(worker())

    async def worker():
        while True:
            task, channel, status_msg, requester_id = await queue.get()
            async def progress(text: str):
                try:
                    await status_msg.edit(content=text[:2000])
                except Exception:
                    pass
            async def confirm(text: str, shot: str) -> bool:
                if bool(getattr(settings, "AUTONOMOUS_MODE", False)):
                    return True
                # A-07: aprovação vinculada ao solicitante + token único
                token = secrets.token_hex(3)
                try:
                    if shot:
                        f = discord.File(shot)
                        await channel.send(
                            f"{text[:1200]}\nResponda `autorizar {token}` em 60s (só o solicitante).", file=f)
                    else:
                        await channel.send(
                            f"{text[:1500]}\nResponda `autorizar {token}` em 60s (só o solicitante).")
                    def check(m):
                        return (m.author.id == requester_id and m.channel == channel
                                and m.content.strip().lower() == f"autorizar {token}")
                    await bot.wait_for("message", check=check, timeout=60)
                    return True
                except Exception:
                    return False
            async def ask(question: str, shot: str):
                if bool(getattr(settings, "AUTONOMOUS_MODE", False)):
                    return "Autorizado automaticamente (modo autônomo) — prossiga."
                try:
                    if shot:
                        await channel.send(f"❓ {question[:1200]}\nResponda em texto (60s, só o solicitante).",
                                           file=discord.File(shot))
                    else:
                        await channel.send(f"❓ {question[:1500]}\nResponda em texto (60s, só o solicitante).")
                    def check2(m):
                        return (m.author.id == requester_id and m.channel == channel
                                and not m.content.strip().lower().startswith("autorizar "))
                    m = await bot.wait_for("message", check=check2, timeout=60)
                    return m.content.strip() or None
                except Exception:
                    return None
            try:
                res = await asyncio.wait_for(
                    orch.run_task(task, on_progress=progress, on_confirm=confirm,
                                  on_ask=ask),
                    timeout=settings.TASK_TIMEOUT_SEC)
                out = ("✅ " if res.ok else "⛔ ") + res.message
                if res.screenshot_path:
                    await channel.send(out[:2000], file=discord.File(res.screenshot_path))
                else:
                    await channel.send(out[:2000])
            except asyncio.TimeoutError:
                await channel.send(f"⛔ timeout de {settings.TASK_TIMEOUT_SEC}s.")
            except Exception as e:
                try:
                    await channel.send(f"Erro interno: {e}")
                except Exception:
                    print(f"[WORKER] falha ao reportar erro: {e}", flush=True)

    @bot.event
    async def on_message(msg: discord.Message):
        if msg.author.bot:
            return
        if msg.author.id not in settings.DISCORD_WHITELIST_IDS:
            return
        # F-16: mensagem de confirmação não é tarefa
        if msg.content.strip().lower().startswith("autorizar "):
            return
        if msg.content.startswith("!"):
            await bot.process_commands(msg)
            return
        status = await msg.channel.send(f"Enfileirado: {msg.content[:80]}")
        await queue.put((msg.content, msg.channel, status, msg.author.id))

    return bot
