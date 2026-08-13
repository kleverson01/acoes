# O app não inicia — como resolver

## O que está acontecendo

Quando o `start_app.bat` **abre no Edge** em vez de executar, o
problema não é o código: é a **associação de arquivos do Windows**. O
sistema deixou de tratar `.bat` como programa e passou a tratar como
documento. Costuma acontecer depois que algum programa altera as
associações padrão.

O código em si está bem — validei que o app sobe normalmente.

---

## Solução 1 — rodar direto (mais rápido)

Abra o **PowerShell** e cole:

```powershell
cd C:\Users\kleve\Documents\acoes
python -m streamlit run streamlit_app.py
```

Se subir, confirma o diagnóstico: o problema era só a associação.

Se o comando `python` não for reconhecido, use o caminho completo:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m streamlit run streamlit_app.py
```

---

## Solução 2 — o novo lançador `INICIAR.ps1`

Incluí um lançador em PowerShell, que **não depende da associação de
`.bat`**:

1. Clique com o **botão direito** em `INICIAR.ps1`
2. Escolha **"Executar com o PowerShell"**

Ele faz o mesmo que o `.bat`: acha o Python, instala dependências na
primeira vez, testa o MetaTrader e sobe o app.

Se o Windows bloquear scripts, libere uma vez (PowerShell como
administrador):

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Solução 3 — consertar a associação de `.bat`

Para o `.bat` voltar a funcionar (útil também para outros programas):

1. Abra o **Prompt de Comando como Administrador** (não PowerShell)
2. Rode:

```
assoc .bat=batfile
ftype batfile="%1" %*
```

Depois disso, o duplo clique no `start_app.bat` volta a executar.

---

## Também corrigi: o prompt de e-mail

Havia um segundo problema que podia parecer travamento. Na primeira
execução, o Streamlit exibe:

```
Welcome to Streamlit!
...
Email:
```

E **fica esperando você digitar algo no terminal**. Se a janela não
estivesse em foco, parecia que o app tinha travado.

Adicionei `.streamlit/config.toml` desligando a coleta de estatísticas,
o que elimina esse prompt. O mesmo arquivo já fixa a porta 8501 e
aplica o tema escuro desde o primeiro frame (antes havia um lampejo
branco ao carregar).

---

## Se ainda não subir

Rode pelo PowerShell (Solução 1) e me mande **a mensagem de erro
completa**. Com o comando direto, o erro aparece na tela em vez de
sumir junto com a janela.

Erros mais comuns:

| Mensagem | Causa |
|---|---|
| `No module named streamlit` | Dependências não instaladas: `python -m pip install -r requirements.txt` |
| `Port 8501 is already in use` | Já há um app rodando; feche-o ou use `--server.port 8502` |
| `ModuleNotFoundError: MetaTrader5` | Falta: `python -m pip install -r requirements-local.txt` |
| `python não é reconhecido` | Python fora do PATH — use o caminho completo (Solução 1) |
