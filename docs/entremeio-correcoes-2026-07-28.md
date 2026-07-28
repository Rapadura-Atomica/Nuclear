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

**Antes:** `measure_fidelity` sempre reportava `WARNING` quando encontrava drift. O Depsgraph do Nuclear 1.7.3-b16 tem um bug pré-existente (`evaluated_get` retorna valores trocados entre frames vizinhos em slotted actions), causando drift de ~4.5 mesmo sem o Entremeio fazer nada. O warning aparecia em TODO `generate`, parecendo erro.

**Depois:** O drift é medido ANTES da geração (`drift_before`) e depois (`max_drift`). Só dispara `WARNING` se `max_drift > drift_before + 1e-4` (ou seja, se o Entremeio PIOROU). Drift pré-existente aparece como `INFO` com a nota "não causado pelo Entremeio".

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

A cena tem 10 pegs animadas em 3 frames (1, 2, 3) — gera 1 in-between. O drift de ~4.5 no
Depsgraph é pré-existente e reportado como INFO.
