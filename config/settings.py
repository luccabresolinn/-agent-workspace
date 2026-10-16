import os
from dotenv import load_dotenv

load_dotenv()

def _int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

def _int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Config inválida: {name}={raw!r} não é inteiro.")

class Settings:
    LLM_BACKEND: str = os.getenv("LLM_BACKEND", "opencode_cli")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:4096/v1")
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "sk-local-placeholder")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "opencode/muse-spark-1.3-contributor-free")

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WHITELIST_IDS: list[int] = _int_list(os.getenv("TELEGRAM_WHITELIST_IDS", ""))

    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
    DISCORD_WHITELIST_IDS: list[int] = _int_list(os.getenv("DISCORD_WHITELIST_IDS", ""))

    BROWSER_USER_DATA_DIR: str = os.getenv("BROWSER_USER_DATA_DIR", "./.browser-profile")
    BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
    BROWSER_CDP_URL: str = os.getenv("BROWSER_CDP_URL", "")
    # Fonte única de ALLOWED_DOMAINS: browser/policy.py lê o env a cada chamada.

    MAX_STEPS: int = _int("MAX_STEPS", 12)
    LOOP_REPEAT_LIMIT: int = _int("LOOP_REPEAT_LIMIT", 3)
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")

    # Gerenciamento de tarefas (Ciclo P1)
    TASK_TIMEOUT_SEC: int = _int("TASK_TIMEOUT_SEC", 1500)
    RATE_LIMIT_SEC: int = _int("RATE_LIMIT_SEC", 10)
    QUEUE_MAX: int = _int("QUEUE_MAX", 5)
    HISTORY_MAX: int = _int("HISTORY_MAX", 20)
    DUP_WINDOW_SEC: int = _int("DUP_WINDOW_SEC", 60)

    # Operações locais (Fase 1: tudo desligado por padrão)
    LOCAL_TOOLS_ENABLED: bool = os.getenv("LOCAL_TOOLS_ENABLED", "false").lower() == "true"
    GRANTS_PATH: str = os.getenv("GRANTS_PATH", "./data/grants.json")
    BACKUP_DIR: str = os.getenv("BACKUP_DIR", "./logs/backups")
    FS_MAX_FILE_MB: int = _int("FS_MAX_FILE_MB", 2)
    FS_MAX_RESULT_CHARS: int = _int("FS_MAX_RESULT_CHARS", 200000)
    CMD_TIMEOUT_SEC: int = _int("CMD_TIMEOUT_SEC", 300)
    CMD_MAX_OUTPUT_KB: int = _int("CMD_MAX_OUTPUT_KB", 200)
    TASK_MODE_DEFAULT: str = os.getenv("TASK_MODE_DEFAULT", "browser")

    # Modo autônomo: o operador assume risco total; o bot não pede
    # nenhuma autorização (HITL, ask_user, grants, credenciais, URL guard).
    AUTONOMOUS_MODE: bool = os.getenv("AUTONOMOUS_MODE", "false").lower() == "true"
    ALLOW_CREDENTIALS: bool = os.getenv("ALLOW_CREDENTIALS", "false").lower() == "true"
    DISABLE_URL_GUARD: bool = os.getenv("DISABLE_URL_GUARD", "false").lower() == "true"
    AUTO_GRANT_ROOT: str = os.getenv("AUTO_GRANT_ROOT", "")

    def validate(self, mode: str):
        """Falha rápido com mensagem clara em vez de quebrar no meio da tarefa."""
        if self.MAX_STEPS < 1:
            raise RuntimeError("MAX_STEPS deve ser >= 1.")
        if self.LOOP_REPEAT_LIMIT < 2:
            raise RuntimeError("LOOP_REPEAT_LIMIT deve ser >= 2.")
        if self.TASK_TIMEOUT_SEC < 60:
            raise RuntimeError("TASK_TIMEOUT_SEC deve ser >= 60.")
        if self.QUEUE_MAX < 1:
            raise RuntimeError("QUEUE_MAX deve ser >= 1.")
        if mode == "telegram":
            if not self.TELEGRAM_BOT_TOKEN:
                raise RuntimeError("Defina TELEGRAM_BOT_TOKEN no .env")
            if not self.TELEGRAM_WHITELIST_IDS:
                raise RuntimeError("TELEGRAM_WHITELIST_IDS vazio: ninguém seria atendido.")
        if mode == "discord":
            if not self.DISCORD_BOT_TOKEN:
                raise RuntimeError("Defina DISCORD_BOT_TOKEN no .env")
            if not self.DISCORD_WHITELIST_IDS:
                raise RuntimeError("DISCORD_WHITELIST_IDS vazio: bot nem inicia (fail-closed).")
        if self.TASK_MODE_DEFAULT not in ("browser", "local", "mixed"):
            raise RuntimeError("TASK_MODE_DEFAULT deve ser browser|local|mixed.")
        if self.FS_MAX_FILE_MB < 1 or self.CMD_TIMEOUT_SEC < 10:
            raise RuntimeError("FS_MAX_FILE_MB >= 1 e CMD_TIMEOUT_SEC >= 10.")

settings = Settings()
