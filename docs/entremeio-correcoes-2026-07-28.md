# Correções — Entremeio (2026-07-28)

## Arquivos alterados

> ⚠️ **As correções vivem no repo-fonte `~/Documentos/GitHub/entremeio/addon/`.**
> A cópia em `Nuclear/scripts/addons_core/entremeio/` é **gerada** por
> `tools/sync_to_nuclear.sh` — editar lá é perder o trabalho no próximo release.

| Arquivo (no repo `entremeio`) | Mudança |
|---|---|
| `addon/engine/spline.py` | Anti-overshoot com `_clamp()` |
| `addon/__init__.py` | Drift baseline antes da geração |
| `addon/ir.py` | `anchors_span()` ignora biblioteca de poses e Cell Library |
| `tests/test_engines.py`, `tests/test_range.py` | 3 testes novos (49 passando) |

---

## 1. Preview range respeita `anim_start`/`anim_end`

**Antes:** `_span()` varria keyframes reais e definia o range de playback pelo span das âncoras. Com âncoras só nos frames 1 e 3, o preview tocava 1–3 ignorando o que o usuário digitou.

**Depois:** O `invoke()` do preview usa `_frame_range(props)` direto. Se o usuário definiu Início=1, Fim=20, o playback vai de 1 a 20. Fallback para range da cena se os campos estiverem em 0.

---

## 2. Anti-overshoot no spline Hermite/Catmull-Rom

**Antes:** Tangentes Catmull-Rom podiam causar overshoot — valores interpolados extrapolando o intervalo `[pose_A, pose_B]`. Ex: âncoras em `(1, 0)`, `(3, 0)`, `(5, 100)` produziam valores > 0 no segmento 1–3, jogando peças para posições inesperadas ("saindo do canto").

**Depois:** Função `_clamp(val, a, b)` limita cada componente ao intervalo `[min(a,b), max(a,b)]`. Aplicada por componente em todo frame gerado.

```python
def _clamp(val, a, b):
    lo, hi = (a, b) if a <= b else (b, a)
    if val < lo: return lo
    if val > hi: return hi
    return val
```

---

## 3. Warning de drift não é mais falso alarme

**Antes:** `measure_fidelity` sempre reportava `WARNING` quando encontrava drift, e o warning aparecia em TODO `generate`, parecendo erro.

**Depois:** O drift é medido ANTES da geração (`drift_before`) e depois (`max_drift`). Só dispara `WARNING` se `max_drift > drift_before + 1e-4` (ou seja, se o Entremeio PIOROU).

> ⚠️ **A explicação original desta seção estava ERRADA e foi corrigida em 2026-07-28 (2ª rodada).**
> Dizia que o drift de ~4.5 vinha de um bug do Depsgraph com slotted actions. Não vem: era o
> **rig órfão** (seção 7). Num rig que o depsgraph avalia, o drift é **0**. O rebaixamento para
> INFO continua certo, mas o sinal real de "drift alto na linha de base" agora tem dono e é
> reportado como tal.

---

## 4. `reinforce_anchors` removido

Função criada e removida durante a investigação. Ela regravava âncoras via `rig.keyframe_insert()`, mas o Depsgraph do Nuclear fazia swap dos valores entre frames vizinhos, **piorando** o problema. O `write_keys` original (via `keyframe_insert`) não corrompe âncoras — drift de FCurve = 0 nos testes.

---

## 5. As duas cópias do add-on estavam divergentes (fechado)

As correções 1–3 tinham sido feitas na cópia **gerada** dentro do Nuclear, que era uma
versão *mais antiga* do add-on (sem o descarte por diff do preview, sem `clipped()`/escopo)
com as correções por cima. O repo-fonte, mais novo, não as tinha. Fechado assim:

- `_clamp()` e o drift baseline **portados para o repo-fonte** (a correção 1, preview
  range, já existia lá noutro desenho: `props.frame_start/frame_end` mandam no loop).
- `sync_to_nuclear.sh` rodado → a árvore do Nuclear voltou a ser cópia fiel da fonte.
- `ENTREMEIO_OT_preview._span()` (código morto) removido junto no sync.

## 6. Trecho detectado nascia em frame negativo

Regressão exposta pelo teste no take real logo após o sync: `PlanIR.anchors_span()` contava
**todas** as âncoras, então o trecho da Carolina era detectado como **-3–3** — os frames
negativos são biblioteca de poses, não animação. Agora `anchors_span()` só considera
`0 <= frame < CELL_LIBRARY_BASE` (100000), e o trecho sai **1–3**, que é a animação real.

## 7. O rig órfão — a causa real do "não gera keyframe"

Achado no teste ao vivo (MCP, take `DPE_EP06_C12T67` aberto na GUI). O take tem **dois PegRigs**:

| PegRig | users | objetos com FOLLOW_PEG | é avaliado? |
|---|---|---|---|
| `carolina_heroi` | 1 | **0** | não — congelado |
| `carolina_heroi.001` | 51 | **51** | sim |

O add-on escolhia `bpy.data.pegrigs[0]`, ou seja, **a cópia órfã**. Os keyframes entravam de
verdade nas FCurves, mas nada na cena se movia — para o animador, "não gerou nada". E como o
depsgraph nunca avalia esse rig, `measure_fidelity` comparava o plano com um valor congelado:
daí o "drift ~4" que a seção 3 atribuía ao Depsgraph.

**Conserto:**
- `rig_bridge.followers_of(rig)` — objetos presos ao rig por constraint `FOLLOW_PEG`.
- `rig_bridge.pick_default_rig()` — escolhe o rig com mais seguidores (empate/nenhum: primeiro
  da lista, como antes). Usado em todos os pontos que faziam `pegrigs[0]`.
- `generate` avisa quando o rig alvo não tem seguidor nenhum:
  *"N keys geradas, mas NENHUM objeto segue 'X' — nada vai se mover na tela. Use 'X.001'."*

Provado ao vivo: no rig certo, `antebraco.d` sai de (-2.46, 0.22) no frame 1 para (-2.48, -2.08)
no 24, com **drift = 0** (não mais "pré-existente=4").

## 8. "Nada a gerar" culpava as poses quando a culpa era do Passo

Com **Passo = 2** e o único vão do take valendo 2 frames, `range(f0+2, f1, 2)` fica vazio e a
mensagem dizia *"nenhuma peg tem âncoras com vão entre elas"* — falso, e manda o animador
procurar problema nas poses. Agora, quando o passo não cabe no maior vão:
*"Nada a gerar: o Passo (2) não cabe no maior vão entre poses (2 frames) — reduza o Passo."*

---

## Testes

**Suíte (`python3 -m pytest tests -q` no repo `entremeio`): 49 passando**, incluindo 3 novos —
anti-overshoot no segmento parado, `anchors_span` ignorando biblioteca/Cell Library, e o caso
em que só existem frames de biblioteca. Com `_clamp` desligado, o teste de overshoot pega o
bug (o segmento "parado" mergulha a −0,45).

**Take real `DPE_EP06_C12T67.blend` (Carolina), headless:**

```
read_rig    → FINISHED   (80 pegs, 10 com âncoras, animação detectada em 1–3)
detect_range→ FINISHED   (trecho 1–3, não mais -3–3)
generate    → FINISHED   (3 keys, INFO: drift pré-existente=4, sem WARNING)
âncoras perdidas: 0 · drift nas FCurves: 0 · violações de overshoot: 0
```

**Preview, na GUI** (o modal não roda em `-b`): `RUNNING_MODAL`, com `frame_start/end` = 1/20
digitados no painel → `use_preview_range=True`, range **1–20**, frame atual 1.

**Ao vivo, pelo MCP, no take aberto na GUI:** trecho detectado 1–3; geração com âncoras intactas
e drift 0 nas FCurves; anti-overshoot provado num caso montado (parada em 1–11, salto em 21 →
segmento parado fica exatamente 0.0) com a peg de teste apagada depois; escolha automática do rig
caindo em `carolina_heroi.001`; aviso de rig órfão e mensagem do Passo conferidos.

**Achado de produção:** varredura dos **115 takes do Ep06** — nenhum tem PegRig com vãos entre
poses, exceto o T67 (um vão de 2 frames). Não existe material animado para o Entremeio mastigar
enquanto a produção não animar poses espaçadas em PegRig.

A cena tem 10 pegs animadas em 3 frames (1, 2, 3) — gera 1 in-between. O drift de ~4.5 no
Depsgraph é pré-existente e reportado como INFO.
