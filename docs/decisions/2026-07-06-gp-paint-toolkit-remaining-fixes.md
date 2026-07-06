# ADR: Consertos finais do toolkit de pintura GP (brush por tipo, remoção do grunge, 2º modo de smudge, perspectiva)

**Date**: 2026-07-06
**Status**: Accepted
**Context**: Grease Pencil — tab "Paint" (`nuclear_paint_toolkit.py` + seams C em sculpt_paint/makesdna/makesrna)

## Context

A tab Paint tinha quatro frentes pendentes (seção FILA/FOCO da memória
`nuclear-paint-tab-toolkit`), além de um bug relatado depois:

1. **Grunge texture** — o usuário quis removê-la. Era um fallback C
   (`grease_pencil_paint.cc`) que samplava um datablock "Nuclear Grunge Tex" quando
   `brush->mtex.tex` era null, ligado/desligado por um operador Python. Nunca commitado.
2. **Ferramentas de brush** (Draw/Erase/Fill/Tint) "não trocavam/aplicavam". A raiz: o
   operador usava `wm.tool_set_by_id`, mas no Blender 5.0 os brushes GP são **assets
   linkados read-only** e a operação de pintura é escolhida pelo **tipo do brush**
   (`grease_pencil_draw_ops.cc::get_stroke_operation`), não pela ferramenta ativa. Além
   disso `_BRUSH_TABS` mapeava **Draw e Tint para o mesmo `builtin.brush`** (Tint nunca
   virava tint).
3. **Lasso Fill** — "não adiciona brush nenhum". Reprodução ao vivo mostrou que o fill
   **renderiza e já usa a cor do brush**; o sintoma real é que a `NuclearLassoFillTool`
   (WorkSpaceTool, não-brush) some com os controles de brush no tool-header → o artista
   percebe "o brush sumiu".
4. **Smudge** — faltava um 2º modo "dissolver/borrar" (o 1º, smear, já reusa o grab do
   sculpt via `GPAINT_BRUSH_TYPE_SMUDGE`).
5. **Editar em perspectiva** — desejo de julgar/editar o desenho selecionado com
   profundidade (alternativa ao Quick Edit).

## Decision

- **Padronizar troca de "modo de pincel" via `brush.gpencil_brush_type`** — o mecanismo
  que o toggle de Smudge já provava funcionar no 5.0 (onde `tool_set_by_id`/asset_activate
  falham). `_BRUSH_TABS` passa a mapear `DRAW/ERASE/FILL/TINT`; `brush_tab` garante a
  ferramenta `builtin.brush` ativa e seta o tipo no brush ativo.
- **Remover o grunge** por completo: tira a UI/operador Python e reverte o fallback C não
  commitado (o `grease_pencil_paint.cc` volta ao estado commitado, que mantém a amostragem
  de `brush->mtex.tex` — inerte, pois GP não expõe mtex por Python).
- **Lasso Fill**: o `draw_settings` na WorkSpaceTool não bastou; a solução definitiva é um
  **botão "Lasso Fill" na aba Brushes** que roda o modal **sem trocar de ferramenta** — o
  brush ativo (e seus controles) permanece. A WorkSpaceTool da toolbar continua existindo.
- **2º modo de smudge**: novo `GPAINT_BRUSH_TYPE_BLUR = 5` (append em `eBrushGPaintType`)
  roteado a `new_smooth_operation` (reusa o smooth do sculpt para dissolver/relaxar
  traços). Botão "Blur / Dissolve Mode" na tab; toggle generalizado.
- **Raio + força do smudge/blur** (achado no teste ao vivo): as ops de sculpt reusadas leem
  size/força via `BKE_brush_size_get`/`BKE_brush_alpha_get` (unified-aware) e o smooth só
  age sob `sculpt_mode_flag & APPLY_*` — coisas que um brush de paint não configura. Fixes
  (Python): desligar `use_unified_size` no GP paint (brush.size passa a valer p/ a op e casa
  com o painel/cursor); ligar `use_edit_position`/`use_edit_strength` ao entrar em Blur; e
  expor um slider **Strength**. Em C, `paint_cursor.cc` passa a dar `pixel_radius` a
  SMUDGE/BLUR (antes ficava 0 = sem bolinha).
- **Perspectiva**: descartada. Um POC (toggle de câmera, depois um keystone deform) foi
  tentado, mas não correspondeu ao que o autor queria; a pedido dele foi **removida** para
  focar no smudge/blur.

## Alternatives Considered

### Manter `wm.tool_set_by_id` e "consertar" os tool IDs
- **Prós**: menor mudança conceitual.
- **Contras**: no 5.0 a ferramenta genérica é `builtin.brush` e o tipo vem do asset ativo;
  trocar ferramenta não troca tipo de brush de forma confiável.
- **Por que descartado**: reintroduz exatamente o bug; o fork já contornou via
  `gpencil_brush_type`.

### Deixar o fallback C do grunge inerte (sem reverter)
- **Prós**: zero mexida em C.
- **Contras**: código morto numa seam de motor upstream-mantida.
- **Por que descartado**: contraria "minimize e isole divergência C"; reverter o não
  commitado é mais limpo e reversível.

### Perspectiva (POC de câmera / keystone deform)
- **Prós**: daria ao artista uma noção de profundidade sobre o desenho 2D.
- **Contras**: o toggle de câmera não deformava nada; o keystone deform funcionava mas não
  era o fluxo que o autor imaginou.
- **Por que descartado**: a pedido do autor — remover e focar no smudge/blur, que é o que
  importa nesta rodada.

## Consequences

### Positive
- Comportamento de brush consistente e testável (mesmo mecanismo em toda a tab).
- Menos divergência C viva (grunge fora); a nova seam BLUR é mínima (append + 1 case).
- Lasso Fill não perde mais o brush; Smudge ganha o par smear/dissolve.

### Negative / Trade-offs
- **Fill/Erase via troca de tipo** (não ferramenta): roteamento correto, mas o Fill nativo
  tem settings próprios — pode exigir tratamento híbrido tipo-vs-ferramenta depois.
- O código C commitado de tip-texture (`brush->mtex.tex`) fica sem UI Nuclear (inerte).
- **Desligar `use_unified_size`** no GP paint afeta todo o paint mode (não só smudge/blur),
  mas é coerente com a filosofia do toolkit (o painel Size edita `brush.size` direto).
- Exigiu 2 rebuilds do `build_nuclear_full` (o 1º pela mudança em `DNA_brush_enums.h` que
  propaga p/ makesrna + dependentes ~515 alvos; o 2º só `paint_cursor.cc`).

## Affected Files
- `scripts/startup/nuclear_paint_toolkit.py`
- `source/blender/makesdna/DNA_brush_enums.h`
- `source/blender/makesrna/intern/rna_brush.cc`
- `source/blender/editors/sculpt_paint/grease_pencil_draw_ops.cc`
- `source/blender/editors/sculpt_paint/paint_cursor.cc` (cursor SMUDGE/BLUR)
- `source/blender/editors/sculpt_paint/grease_pencil_paint.cc` (revertido ao HEAD)
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` (seams BLUR + cursor)
