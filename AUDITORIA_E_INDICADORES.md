# Auditoria dos cálculos e guia dos indicadores

## Parte 1 — Os erros que você apontou (corrigidos)

### IFR estava errado — erro de até 20 pontos

Você validou e estava certo. A causa era a **semente** do cálculo.

Wilder inicia o IFR com a **média simples** dos 14 primeiros ganhos e
perdas, e só a partir daí aplica o suavizamento. Meu código usava
`ewm(adjust=False)` direto sobre a série inteira, o que na prática
semeia com o primeiro ganho isolado. Isso gera um erro grande que decai
lentamente ao longo da série.

Validação contra os dados de referência do próprio Wilder:

| Índice | Antes | Correto | Erro |
|---|---|---|---|
| 14 | 50,66 | 70,46 | **−19,81** |
| 18 | 50,07 | 66,29 | −16,22 |
| 25 | 42,47 | 50,39 | −7,92 |
| 32 | 33,74 | 37,79 | −4,05 |

Depois da correção, a divergência contra o cálculo recursivo exato de
Wilder é de **1,4 × 10⁻¹⁴** — ou seja, idêntico, a menos de ponto
flutuante. Agora bate com MT5, TradingView e Profit.

**Bug secundário corrigido**: mercado parado (sem variação) retornava
IFR = 100. Agora retorna 50, que é o correto.

### ATR também divergia — 2 a 5%

Auditando o resto, encontrei o mesmo tipo de problema no ATR: estava
usando média **simples** do True Range, enquanto MT5 e TradingView usam
suavizamento de Wilder (que eles chamam de SMMA/RMA).

Divergência média de 2,2%, máxima de 5,4%. Parece pouco, mas **o ATR
define a distância mínima do seu stop** — então ia direto para o
tamanho do risco de cada operação. Corrigido e validado da mesma forma.

### O que estava certo

- **EMAs** (9/21/50/200) — divergência zero contra a referência
- **VWAP** — preço típico (H+L+C)/3 ponderado por volume, reiniciado a
  cada sessão. Convenção padrão, sem problemas.

---

## Parte 2 — Quais indicadores valem a pena

Rodei uma medição empírica: 60 séries, contando com que frequência cada
leitura gera sinal operável e quanto elas concordam entre si.

### Frequência de sinal

| Leitura | Opera em | Avaliação |
|---|---|---|
| Médias Móveis | **90%** | ⚠️ Dispara quase sempre |
| SMC | 78% | ✅ Boa base |
| VWAP | 43% | ✅ Seletivo, útil |
| Price Action | 1,7% | ⚠️ Quase nunca dispara |
| IFR (10/90) | **0%** | ⚠️ Praticamente nunca dispara |

### O problema do IFR em 10/90

Esse é o achado mais importante e preciso ser direto: **com limiares
10/90, o IFR quase nunca vai disparar.** Em 60 séries testadas, zero
sinais.

Dados sintéticos são mais suaves que o mercado real (que tem tendências
e choques mais fortes), então na prática você verá algum sinal — mas
raro, talvez alguns por semana no conjunto todo dos 24 ativos.

Isso pode ser exatamente o que você quer (máxima seletividade). Mas se
você esperava usar o IFR como gatilho recorrente de entrada, 10/90 não
vai entregar isso. Sugestão: comece com **20/80** e observe a frequência
por algumas semanas, ajustando conforme o histórico mostrar. O slider
está em "Ajustes avançados".

### O problema oposto: Médias Móveis

Uma leitura que dispara em 90% dos casos carrega pouca informação — se
quase sempre aponta alguma direção, ela não está distinguindo muita
coisa. É a leitura em que eu confiaria menos isoladamente.

### Redundância entre leituras

| Par | Concordam |
|---|---|
| SMC × Médias Móveis | 71,7% |
| Price Action × VWAP | 58,3% |
| Médias Móveis × VWAP | 50,0% |
| SMC × Price Action | 23,3% |

SMC e Médias Móveis concordam em 72% dos casos — as duas são
seguidoras de tendência, então em boa parte do tempo estão dizendo a
mesma coisa com nomes diferentes. Na Confluência, isso significa que o
"voto" de tendência pesa mais do que a contagem de categorias sugere.

(A concordância de 98% entre Price Action e IFR é artificial: as duas
ficam quase sempre neutras, então "concordam" em não dizer nada.)

---

## Parte 3 — Recomendação prática

**Para uso diário, sugiro focar em:**

1. **Confluência** — é a leitura que combina tudo com pesos. Use como
   base de decisão.
2. **SMC** — estrutura de mercado é o que dá contexto de onde o preço
   está no ciclo.
3. **VWAP** — boa seletividade e informação genuinamente diferente das
   outras (referência de preço médio da sessão).

**Pode ignorar no dia a dia:**

- **Médias Móveis isolada** — muito redundante com SMC. Continua útil
  *dentro* da Confluência, mas olhar o painel dela separadamente
  raramente acrescenta.
- **Price Action isolada** — dispara pouco demais para servir de
  triagem. Vale olhar quando já escolheu um ativo, não para filtrar.
- **IFR isolado em 10/90** — dispara raro demais para ser gatilho
  primário. Use como **confirmação**: quando aparecer, é forte.

**O filtro mais útil que você tem agora** é a coluna **Exaustão IFR** no
Scanner. Exaustão simultânea em 2+ timeframes é raro e significativo —
vale mais que qualquer leitura isolada.

---

## Parte 4 — Simplificação da interface

A barra lateral estava com oito seções abertas. Reorganizei:

**Sempre visível** (o que você mexe todo dia):
- Modo · Fonte de dados · Estilo · Modalidade · Ativo para análise

**Recolhido** (configura uma vez):
- Gerenciar watchlist
- Ajustes avançados (candles, risco, piso do stop, score mínimo,
  limiares do IFR)

O Scanner também ficou mais limpo: 13 colunas em vez de 18, com resumo
no topo, dois filtros rápidos e score em barra visual.

---

## Uma sugestão sobre método

Toda a avaliação acima é de dados sintéticos e teoria. O que realmente
vale é **o seu histórico**. O Histórico de Sinais já registra cada
recomendação com horário, entrada, stop e alvo, e confere o resultado.

Depois de algumas semanas operando, esse histórico responde com dado
próprio: quais setups acertam mais, se o alinhamento de IFR em vários
timeframes performa melhor, se o score alto realmente prevê acerto.
Aí você calibra com evidência, não com opinião — nem a minha, nem a de
ninguém.
