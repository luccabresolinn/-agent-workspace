@echo off
chcp 65001 > nul
title Agente Autônomo - OpenCode ^& Telegram

:: 1. Localizar o executável do Google Chrome no Windows
set "CHROME_BIN="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_BIN=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_BIN%"=="" (
    echo [ERRO] Google Chrome não foi localizado nos diretórios padrão.
    pause
    exit /b 1
)

:: 2. Perfil dedicado. Reaproveita C:\chrome-agent se já existir (não perde
:: logins); instalação nova usa %LOCALAPPDATA% (funciona como usuário padrão).
set "AGENT_PROFILE=%LOCALAPPDATA%\chrome-agent"
if exist "C:\chrome-agent" set "AGENT_PROFILE=C:\chrome-agent"
if not exist "%AGENT_PROFILE%" mkdir "%AGENT_PROFILE%"

:: 2b. CDP só precisa subir se a porta 9222 não estiver escutando.
echo [0/3] Verificando CDP na porta 9222...
netstat -ano | findstr "127.0.0.1:9222" | findstr "LISTENING" > nul
if %errorlevel%==0 (
    echo CDP já ativo, reaproveitando. Confira que é o Chrome do agente.
    goto venv
)
echo CDP inativo. Para ativá-lo é preciso fechar o Chrome (ele bloqueia a porta).
echo ATENÇÃO: isso fecha o Chrome pessoal e pode perder abas não salvas.
echo Pressione Ctrl+C para desistir, ou aguarde 10 segundos para continuar...
timeout /t 10 /nobreak
taskkill /F /IM chrome.exe > nul 2>&1
timeout /t 3 /nobreak > nul

:: 3. Iniciar o Chrome com a porta de depuração remota 9222
echo [1/3] Iniciando Chrome com CDP (porta 9222)...
start "" "%CHROME_BIN%" --remote-debugging-port=9222 --user-data-dir="%AGENT_PROFILE%"

:: Aguarda 2 segundos para o endpoint CDP subir
timeout /t 2 /nobreak > nul

:venv
:: 4. Ativar ambiente virtual Python
echo [2/3] Ativando ambiente virtual...
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [AVISO] Pasta .venv não encontrada. Usando Python padrão do sistema.
)

:: 5. Iniciar o orquestrador do Telegram
echo [3/3] Iniciando agente do Telegram...
python main.py telegram

pause
