"""
diagnostico_mt5.py

Testa a conexão com o MetaTrader 5 etapa por etapa e diz exatamente
onde ela falha. Rode assim, na pasta do projeto, com o MT5 aberto:

    python diagnostico_mt5.py

Cada etapa é isolada de propósito: "não conecta" pode significar seis
coisas muito diferentes (terminal fechado, conta desconectada da
corretora, símbolo não habilitado no Market Watch, mercado fechado,
histórico não baixado, nome de símbolo diferente na corretora) e cada
uma tem uma solução diferente.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta


VERDE = "\033[92m"; VERM = "\033[91m"; AMAR = "\033[93m"; FIM = "\033[0m"


def ok(msg):    print(f"  {VERDE}[OK]{FIM} {msg}")
def erro(msg):  print(f"  {VERM}[FALHA]{FIM} {msg}")
def aviso(msg): print(f"  {AMAR}[AVISO]{FIM} {msg}")
def titulo(n, t): print(f"\n{'='*62}\n {n}. {t}\n{'='*62}")


def main() -> int:
    print("\n" + "="*62)
    print(" DIAGNÓSTICO DA CONEXÃO COM O METATRADER 5")
    print("="*62)

    # ---------------------------------------------------------------
    titulo(1, "O pacote MetaTrader5 está instalado?")
    try:
        import MetaTrader5 as mt5
        ok(f"Pacote encontrado (versão {mt5.__version__})")
    except ImportError:
        erro("Pacote MetaTrader5 não instalado.")
        print("\n  COMO RESOLVER:")
        print("    python -m pip install MetaTrader5")
        return 1

    # ---------------------------------------------------------------
    titulo(2, "O Python consegue abrir o terminal?")
    if not mt5.initialize():
        erro(f"initialize() falhou: {mt5.last_error()}")
        print("\n  COMO RESOLVER, em ordem:")
        print("    1. Abra o MetaTrader 5 e faça login")
        print("    2. No MT5: Ferramentas > Opções > Expert Advisors")
        print("       marque 'Permitir DLL imports'")
        print("    3. Rode este script SEM privilégios de administrador")
        print("       (se o MT5 roda como usuário normal, o Python também precisa)")
        print("    4. Feche outras instâncias do MT5 abertas ao mesmo tempo")
        return 1
    ok("Terminal aberto e respondendo")

    # ---------------------------------------------------------------
    titulo(3, "Informações do terminal")
    info = mt5.terminal_info()
    if info is None:
        erro("terminal_info() não retornou nada")
    else:
        ok(f"Nome: {info.name}  ·  build {info.build}")
        ok(f"Empresa: {info.company}")
        print(f"       Conectado ao servidor: {info.connected}")
        print(f"       Trade permitido: {info.trade_allowed}")
        if not info.connected:
            aviso("O terminal NÃO está conectado ao servidor da corretora.")
            print("       -> O histórico em cache ainda pode funcionar,")
            print("          mas cotações novas não chegam.")
            print("       -> Verifique login/senha e o status da conta.")

    # ---------------------------------------------------------------
    titulo(4, "A conta está logada?")
    conta = mt5.account_info()
    if conta is None:
        erro(f"account_info() vazio: {mt5.last_error()}")
        aviso("Normalmente significa conta deslogada ou desativada.")
        print("       Na Clear: Minha Conta > Senhas > Senha MetaTrader 5")
        print("       > Receber Nova Senha. Se a opção não aparecer, a")
        print("       contratação da plataforma caiu — acione o suporte.")
    else:
        ok(f"Conta {conta.login} · {conta.server}")
        ok(f"Titular: {conta.name}")
        print(f"       Moeda: {conta.currency}  ·  Saldo: {conta.balance}")

    # ---------------------------------------------------------------
    titulo(5, "Quantos símbolos o terminal enxerga?")
    total = mt5.symbols_total()
    if not total:
        erro("Nenhum símbolo disponível — conta sem dados de mercado.")
    else:
        ok(f"{total} símbolos disponíveis no total")

    # ---------------------------------------------------------------
    titulo(6, "Teste com ações da B3")
    acoes = ["PETR4", "VALE3", "ITUB4", "BBDC4", "ABEV3"]
    sucesso_acoes = []
    for s in acoes:
        i = mt5.symbol_info(s)
        if i is None:
            erro(f"{s}: símbolo não existe nesta corretora")
            continue
        if not i.visible:
            if mt5.symbol_select(s, True):
                print(f"       {s}: adicionado ao Market Watch agora")
            else:
                erro(f"{s}: não foi possível habilitar no Market Watch")
                continue
        candles = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M15, 0, 10)
        if candles is None or len(candles) == 0:
            erro(f"{s}: sem candles M15 ({mt5.last_error()})")
        else:
            ultimo = datetime.fromtimestamp(candles[-1]["time"])
            ok(f"{s}: {len(candles)} candles · último {ultimo:%d/%m %H:%M} · fech. {candles[-1]['close']:.2f}")
            sucesso_acoes.append(s)

    # ---------------------------------------------------------------
    titulo(7, "Procurando o WINFUT (mini índice)")
    # A corretora pode nomear o contínuo de várias formas; e o contrato
    # cheio muda de código a cada vencimento (letra do mês + ano).
    candidatos = ["WIN$N", "WIN$", "WIN$D", "WINFUT", "WIN"]
    encontrados = []
    for c in candidatos:
        if mt5.symbol_info(c) is not None:
            encontrados.append(c)
            ok(f"Encontrado: {c}")

    todos = mt5.symbols_get("*WIN*")
    if todos:
        nomes = [s.name for s in todos][:25]
        print(f"\n       Símbolos com 'WIN' no nome ({len(todos)} no total):")
        print(f"       {', '.join(nomes)}")
        for s in todos:
            if s.name not in encontrados:
                encontrados.append(s.name)
    if not encontrados:
        erro("Nenhum símbolo de mini índice encontrado nesta conta.")

    # Testa qual deles realmente entrega candles
    print()
    funcionando = []
    for nome in encontrados[:12]:
        if mt5.symbol_info(nome) and not mt5.symbol_info(nome).visible:
            mt5.symbol_select(nome, True)
        r = mt5.copy_rates_from_pos(nome, mt5.TIMEFRAME_M5, 0, 5)
        if r is not None and len(r) > 0:
            ok(f"{nome}: entrega candles M5 · último fech. {r[-1]['close']:.1f}")
            funcionando.append(nome)

    # ---------------------------------------------------------------
    titulo(8, "Teste dos timeframes usados pelo app")
    alvo = sucesso_acoes[0] if sucesso_acoes else (funcionando[0] if funcionando else None)
    if alvo is None:
        erro("Nenhum símbolo funcional para testar timeframes.")
    else:
        print(f"       Usando {alvo} como referência\n")
        tfs = {"M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
               "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1}
        for nome, tf in tfs.items():
            r = mt5.copy_rates_from_pos(alvo, tf, 0, 250)
            if r is None or len(r) == 0:
                erro(f"{nome}: sem dados ({mt5.last_error()})")
            elif len(r) < 200:
                aviso(f"{nome}: só {len(r)} candles (o app pede 250 — histórico curto)")
            else:
                ok(f"{nome}: {len(r)} candles")

    # ---------------------------------------------------------------
    titulo(9, "Resumo")
    if sucesso_acoes:
        ok(f"Ações funcionando: {', '.join(sucesso_acoes)}")
    else:
        erro("NENHUMA ação retornou candles.")
        print("       Causa mais provável: conta desconectada da corretora")
        print("       (veja a etapa 3/4 acima) ou fora do horário de pregão")
        print("       com histórico não baixado.")
    if funcionando:
        ok(f"WINFUT funcionando: {', '.join(funcionando)}")
        print(f"\n       >> Use este código no app: {VERDE}{funcionando[0]}{FIM}")
    else:
        aviso("WINFUT não retornou candles nesta conta.")

    agora = datetime.now()
    if agora.weekday() >= 5:
        print(f"\n  {AMAR}Nota:{FIM} hoje é fim de semana — a B3 está fechada.")
        print("       Sem pregão, várias corretoras derrubam a conexão do")
        print("       servidor MT5. Só o histórico já baixado funciona.")
    elif not (10 <= agora.hour < 18):
        print(f"\n  {AMAR}Nota:{FIM} fora do horário de pregão (10h-18h).")

    mt5.shutdown()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
