# Terminal SMC — o que mudou nesta versão

## 1. MetaTrader não conecta: como descobrir o motivo

Criei um diagnóstico que testa cada etapa isoladamente. Com o MT5
aberto, rode na pasta do projeto:

```
python diagnostico_mt5.py
```

Ele responde nove perguntas em sequência e, em cada falha, diz o que
fazer. Isso importa porque "não conecta" pode significar seis coisas
bem diferentes, cada uma com solução própria:

| Etapa que falha | O que significa |
|---|---|
| 1. Pacote | `MetaTrader5` não instalado |
| 2. `initialize()` | Terminal fechado, ou DLL imports bloqueado |
| 3. `connected: False` | Terminal aberto mas **sem link com a corretora** |
| 4. `account_info` vazio | Conta deslogada ou desativada |
| 6. Ações sem candles | Símbolo fora do Market Watch, ou histórico não baixado |
| 7. Sem WINFUT | Contrato não disponível nessa conta |

### O que eu já sei do seu caso

No print que você mandou, o log do terminal dizia
`no connection to ClearInvestimentos-CLEAR`, e mesmo assim havia preços
no Market Watch. Isso é o cenário da **etapa 3**: o terminal está
aberto, mostrando cache local, mas sem link ativo com a corretora. Foi
por isso que `copy_rates_from_pos` devolveu `None` — a API não serve o
cache visual do terminal.

Duas causas prováveis, nessa ordem:

1. **Era sábado.** A Clear derruba o servidor MT5 fora do pregão. Teste
   num dia útil entre 10h e 18h antes de qualquer outra coisa.
2. **Conta MT5 desativada por inatividade** (você mencionou ser a
   segunda vez). Na Clear: Minha Conta → Senhas → Senha MetaTrader 5 →
   Receber Nova Senha. Se a opção não aparecer, a contratação caiu e
   precisa do suporte.

O diagnóstico distingue as duas: se a etapa 3 disser
`Conectado ao servidor: True` num dia útil, o problema era só o fim de
semana.

---

## 2. WINFUT em aba própria

Novo modo na barra lateral, com prazos próprios:

- **Confirmação:** 5 e 15 minutos
- **Contexto:** 60 minutos e Diário
- **Limiares de IFR:** 10 / 90, iguais aos do Day Trade

O 5 minutos sobe para a confirmação (nas ações é só contexto) porque o
mini índice gira rápido demais para depender só do fechamento do 15.

### Resolução automática do contrato

O mini índice não tem código único: cada corretora nomeia o contínuo de
um jeito, e o contrato cheio muda de código a cada vencimento. O app
testa `WIN$N`, `WIN$`, `WIN$D`, `WINFUT`, `WIN` e, se nenhum servir,
varre todos os símbolos com "WIN" no nome — usando o primeiro que
realmente entregue candles. Contínuos têm prioridade, para o histórico
não quebrar na virada de vencimento.

O código escolhido aparece no topo da tela. Se nada for encontrado, o
diagnóstico lista o que a sua corretora oferece.

**Importante:** o WINFUT só funciona via MetaTrader 5. O Yahoo Finance
não distribui futuros da B3, e o app avisa isso ao invés de falhar.

---

## 3. Redesenho

**Direção:** terminal de mesa de operações. Fundo tinta-profunda com
viés azul (preto puro achata a hierarquia quando há muitos painéis),
hierarquia por elevação de superfície e fios de 1px.

**Três famílias com papéis distintos:**

- *Space Grotesk* nos títulos — grotesca técnica, numerais com desenho
  próprio
- *Inter* no texto e controles
- *JetBrains Mono* em todo número — não é enfeite: numerais tabulares
  mantêm as casas alinhadas na vertical, e é isso que permite varrer
  uma coluna de preços com o olho sem ler valor por valor

**Cor com significado fixo:** verde-azulado = compra, rosa = venda,
âmbar = exaustão. O âmbar é exclusivo da exaustão de IFR — é o evento
raro que a estratégia persegue, então é a única coisa na tela com
permissão de brilhar.

**O elemento-assinatura** é o trilho de IFR: as zonas de exaustão são
pintadas fisicamente no trilho, então "onde o marcador está" vira
leitura de posição, não de número. Quando entra na zona, o marcador
acende em âmbar. No painel multi-prazo, cada timeframe ganha sua linha
— comparar prazos vira leitura espacial em vez de aritmética.

**Cabeçalho de estado** com indicador de pregão aberto/fechado, horário
e fonte de dados ativa.

---

## Como usar

1. Abra o MetaTrader 5 e faça login
2. Duplo clique em `start_app.bat`
3. Se o MT5 não conectar, rode `python diagnostico_mt5.py`

Para o mini índice: barra lateral → Modo → **WINFUT**.
