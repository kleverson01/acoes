@echo off
REM ======================================================================
REM  start_remoto.bat - Sobe o terminal E publica na internet.
REM
REM  Use este arquivo na maquina de CASA (a que tem o MetaTrader 5).
REM  Ele deixa o app rodando e cria um endereco publico que voce abre
REM  do trabalho, do celular, de qualquer lugar - sem instalar nada no
REM  outro computador, so o navegador.
REM
REM  Requisitos:
REM    - MetaTrader 5 aberto e logado nesta maquina
REM    - cloudflared.exe em C:\cloudflared\
REM    - senha configurada em .streamlit\secrets.toml
REM ======================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ============================================================
echo   TERMINAL SMC - modo acesso remoto
echo  ============================================================
echo.

REM --- Localiza o Python (sem depender do PATH do Windows) ---
set "PYEXE="
for %%D in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python311" "%LOCALAPPDATA%\Programs\Python\Python313" "C:\Python312") do (
    if exist "%%~D\python.exe" (
        set "PYEXE=%%~D\python.exe"
        goto :py_ok
    )
)
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE (
    echo  [ERRO] Python nao encontrado.
    echo         Instale de https://www.python.org/downloads/release/python-31210/
    echo         marcando "Add python.exe to PATH".
    pause & exit /b 1
)
:py_ok
echo  Python: %PYEXE%

REM --- Confere o cloudflared ---
set "CFD=C:\cloudflared\cloudflared.exe"
if not exist "%CFD%" (
    echo.
    echo  [ERRO] cloudflared.exe nao encontrado em C:\cloudflared\
    echo.
    echo  Para instalar, cole no PowerShell:
    echo    mkdir C:\cloudflared -Force
    echo    cd C:\cloudflared
    echo    Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "cloudflared.exe"
    echo.
    pause & exit /b 1
)

REM --- Avisa se nao houver senha configurada ---
if not exist ".streamlit\secrets.toml" (
    echo.
    echo  [ATENCAO] Nenhuma senha configurada.
    echo            O endereco publico ficaria aberto a qualquer pessoa
    echo            que tivesse o link.
    echo.
    echo            Crie o arquivo .streamlit\secrets.toml com:
    echo                app_password = "sua-senha-aqui"
    echo.
    set /p SEGUIR="  Continuar mesmo assim? (S/N): "
    if /i not "!SEGUIR!"=="S" exit /b 0
)

REM --- Dependencias, so na primeira vez ---
if not exist ".deps_ok" (
    echo.
    echo  Instalando dependencias (so acontece uma vez)...
    "%PYEXE%" -m pip install --upgrade pip
    "%PYEXE%" -m pip install -r requirements.txt
    "%PYEXE%" -m pip install -r requirements-local.txt
    if !errorlevel! neq 0 ( echo  [ERRO] Falha ao instalar. & pause & exit /b 1 )
    echo instalado > .deps_ok
)

REM --- Testa o MT5 ---
echo.
echo  Verificando o MetaTrader 5...
"%PYEXE%" -c "import MetaTrader5 as mt5,sys; sys.exit(0 if mt5.initialize() else 1)" 2>nul
if %errorlevel%==0 (
    echo  [OK] MetaTrader 5 conectado - dados em tempo real.
) else (
    echo  [AVISO] MT5 nao respondeu. Abra e faca login no MetaTrader 5.
    echo          Rode diagnostico_mt5.py se o problema persistir.
)

REM --- Sobe o app em segundo plano ---
echo.
echo  Iniciando o terminal...
start "Terminal SMC (app)" /min "%PYEXE%" -m streamlit run streamlit_app.py --server.port 8501 --server.headless true

echo  Aguardando o app subir...
timeout /t 12 /nobreak >nul

REM --- Abre o tunel e captura a URL ---
echo.
echo  Publicando na internet...
echo.
if exist tunel.log del tunel.log
start "Terminal SMC (tunel)" /min cmd /c ""%CFD%" tunnel --url http://localhost:8501 --logfile tunel.log 2^>^&1"

echo  Aguardando o endereco publico...
set "URL="
for /l %%i in (1,1,30) do (
    timeout /t 2 /nobreak >nul
    if exist tunel.log (
        for /f "tokens=*" %%L in ('findstr /c:"trycloudflare.com" tunel.log 2^>nul') do (
            for %%W in (%%L) do (
                echo %%W | findstr /c:"https://" >nul && set "URL=%%W"
            )
        )
    )
    if defined URL goto :pronto
)

:pronto
echo.
echo  ============================================================
if defined URL (
    echo   ENDERECO DE ACESSO:
    echo.
    echo     !URL!
    echo.
    echo   Abra esse endereco do trabalho, do celular, de onde for.
    echo   Nao precisa instalar nada no outro computador.
) else (
    echo   Nao consegui capturar o endereco automaticamente.
    echo   Abra o arquivo tunel.log desta pasta e procure a linha
    echo   terminada em .trycloudflare.com
)
echo  ============================================================
echo.
echo   ATENCAO: o endereco MUDA toda vez que voce reinicia.
echo   Para ter um endereco fixo, veja ACESSO_REMOTO.md
echo.
echo   Para ENCERRAR: feche esta janela e as duas janelas
echo   minimizadas (app e tunel).
echo.
pause
