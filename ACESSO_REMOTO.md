# Acesso remoto — casa → trabalho

## Como funciona

```
CASA (sempre ligada)                    TRABALHO
┌──────────────────────┐               ┌──────────────┐
│  MetaTrader 5        │               │              │
│        ↓             │               │  Navegador   │
│  Terminal SMC        │               │              │
│  localhost:8501      │               └──────┬───────┘
│        ↓             │                      │
│  cloudflared ────────┼──── internet ────────┘
└──────────────────────┘
```

O app roda **em casa**, na mesma máquina do MetaTrader — é por isso que
tem dado em tempo real. O `cloudflared` cria um endereço público que
aponta para ele. No trabalho, você só abre esse endereço no navegador.

**Nada é instalado no computador do trabalho.** Só o navegador que já
está lá.

### Por que não o Streamlit Cloud

O Streamlit Cloud roda em servidor Linux, e o MetaTrader 5 é um
programa Windows que precisa estar aberto e logado. Não existe MT5
naquele servidor, e não há como haver. Aquele deploy só consegue usar o
Yahoo Finance, com 15-20 minutos de atraso — que é justamente o que
você quer evitar.

### Por que não a ponte via GitHub

Foi o caminho que tentamos antes: sete elos entre você e o dado, cada
um um ponto de falha. O túnel tem um elo.

---

## Configuração

### Passo 1 — Senha (faça antes de expor)

Sem isso, quem tiver o endereço entra. Na pasta do projeto, crie a
pasta `.streamlit` e dentro dela o arquivo `secrets.toml`:

```toml
app_password = "escolha-uma-senha-boa-aqui"
```

Pelo PowerShell, se preferir:

```powershell
cd C:\Users\kleve\Documents\acoes
mkdir .streamlit -Force
notepad .streamlit\secrets.toml
```

Com isso, o terminal passa a pedir senha antes de mostrar qualquer
coisa. Sem o arquivo, o app abre direto — o que é o certo para uso
local, mas perigoso quando publicado.

### Passo 2 — cloudflared

Se ainda não baixou:

```powershell
mkdir C:\cloudflared -Force
cd C:\cloudflared
Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "cloudflared.exe"
```

### Passo 3 — Ligar

Na máquina de casa, com o MetaTrader aberto:

**Duplo clique em `start_remoto.bat`**

Ele sobe o app, abre o túnel e mostra o endereço na tela:

```
============================================================
 ENDERECO DE ACESSO:

   https://alguma-coisa-aleatoria.trycloudflare.com

 Abra esse endereco do trabalho, do celular, de onde for.
============================================================
```

Copie esse endereço (mande para o seu celular ou e-mail) e abra no
trabalho.

---

## A limitação desta versão

**O endereço muda toda vez que você reinicia.** Se o PC reiniciar ou o
túnel cair, você precisa olhar o endereço novo na máquina de casa —
o que é ruim justamente quando você está longe dela.

Para uso diário, vale resolver isso.

---

## Versão definitiva: endereço fixo

Com um domínio próprio (~R$ 40/ano no Registro.br), você ganha:

- **Endereço fixo**, tipo `terminal.seudominio.com.br`
- **Sobe sozinho** com o Windows, como serviço — não precisa clicar em nada
- **Login por e-mail** (Cloudflare Access, gratuito até 50 usuários),
  bem mais seguro que uma senha compartilhada
- **HTTPS automático**, sem configurar certificado
- Nenhuma porta aberta no roteador

### Resumo dos passos

1. Registre um domínio (Registro.br ou similar)
2. Crie conta gratuita na Cloudflare e adicione o domínio (troca dos
   servidores DNS — a Cloudflare instrui)
3. Autentique o cloudflared:
   ```powershell
   cd C:\cloudflared
   .\cloudflared.exe tunnel login
   ```
4. Crie o túnel nomeado:
   ```powershell
   .\cloudflared.exe tunnel create terminal-smc
   .\cloudflared.exe tunnel route dns terminal-smc terminal.seudominio.com.br
   ```
5. Crie `C:\Users\kleve\.cloudflared\config.yml`:
   ```yaml
   tunnel: terminal-smc
   credentials-file: C:\Users\kleve\.cloudflared\<id-gerado>.json
   ingress:
     - hostname: terminal.seudominio.com.br
       service: http://localhost:8501
     - service: http_status:404
   ```
6. Instale como serviço do Windows:
   ```powershell
   .\cloudflared.exe service install
   ```
7. No painel da Cloudflare: **Zero Trust → Access → Applications** →
   adicione o hostname e exija login por e-mail

Depois disso, basta manter o MetaTrader e o app rodando em casa. O
túnel cuida de si mesmo.

---

## Rotina do dia a dia

**Em casa, de manhã:**
1. MetaTrader 5 aberto e logado
2. Duplo clique em `start_remoto.bat`
3. Anote o endereço (ou, na versão com domínio, ele é sempre o mesmo)

**No trabalho:**
1. Abra o endereço no navegador
2. Digite a senha
3. Use normalmente — os dados vêm do MT5 de casa, em tempo real

---

## Quando algo não funcionar

**A página não abre**
O PC de casa desligou, ou a janela do túnel foi fechada. Ambos precisam
ficar de pé.

**Abre, mas os dados não atualizam**
O MetaTrader fechou ou deslogou. Rode `python diagnostico_mt5.py` na
máquina de casa.

**"Nenhum terminal MetaTrader 5 acessível"**
O app subiu antes do MT5. Feche tudo e comece pelo MetaTrader.

**Ficou lento**
São 3 GB de RAM naquela máquina, rodando MT5 + Python + túnel. Evite
manter navegador aberto nela, e prefira analisar um ativo por vez a
rodar o scanner dos 24 repetidamente.
