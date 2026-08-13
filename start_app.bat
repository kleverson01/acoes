@echo off
REM ======================================================================
REM  start_app.bat - Inicia o Day Trade SMC localmente, com MT5 direto.
REM
REM  Basta dar DUPLO CLIQUE neste arquivo. Ele cuida de tudo:
REM    1. Acha o Python (sem depender do PATH do Windows, que ja deu
REM       problema antes por causa do atalho da Microsoft Store)
REM    2. Instala/atualiza as dependencias na primeira execucao
REM    3. Sobe o app e abre no navegador
REM
REM  Requisitos: MetaTrader 5 aberto e logado nesta maquina.
REM ======================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ====================================================
echo   Day Trade SMC - iniciando...
echo  ====================================================
echo.

REM --- Procura o Python em locais conhecidos, na ordem ---
set "PYEXE="

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :found
)
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :found
)
if exist "C:\Python312\python.exe" (
    set "PYEXE=C:\Python312\python.exe"
    goto :found
)

REM Ultimo recurso: usa o "py launcher", que ignora o atalho da Store
where py >nul 2>&1
if %errorlevel%==0 (
    set "PYEXE=py"
    goto :found
)

echo  [ERRO] Python nao encontrado nesta maquina.
echo.
echo  Instale o Python 3.12 em https://www.python.org/downloads/release/python-31210/
echo  e marque a opcao "Add python.exe to PATH" durante a instalacao.
echo.
pause
exit /b 1

:found
echo  Python encontrado: %PYEXE%
echo.

REM --- Instala dependencias apenas na primeira execucao ---
if not exist ".deps_ok" (
    echo  Primeira execucao detectada. Instalando dependencias...
    echo  Isso leva alguns minutos, mas so acontece uma vez.
    echo.
    "%PYEXE%" -m pip install --upgrade pip
    "%PYEXE%" -m pip install -r requirements.txt
    "%PYEXE%" -m pip install -r requirements-local.txt
    if !errorlevel! neq 0 (
        echo.
        echo  [ERRO] Falha ao instalar dependencias. Veja as mensagens acima.
        pause
        exit /b 1
    )
    echo instalado > .deps_ok
    echo.
    echo  Dependencias instaladas com sucesso.
    echo.
)

REM --- Confere se o MT5 responde antes de subir o app ---
echo  Verificando conexao com o MetaTrader 5...
"%PYEXE%" -c "import MetaTrader5 as mt5; import sys; sys.exit(0 if mt5.initialize() else 1)" 2>nul
if %errorlevel%==0 (
    echo  [OK] MetaTrader 5 conectado - dados em tempo real.
) else (
    echo  [AVISO] MT5 nao respondeu. Abra e faca login no MetaTrader 5.
    echo          O app vai subir mesmo assim, usando Yahoo Finance como alternativa.
)
echo.

echo  Abrindo o app no navegador...
echo  Para ENCERRAR: feche esta janela ou aperte Ctrl+C.
echo.

"%PYEXE%" -m streamlit run streamlit_app.py

pause
