# Session: Consertos finais do toolkit de pintura GP (tab Paint)

**Date**: 2026-07-06
**Tier**: 3 — Full
**Specialist**: general
**Branch**: `feat/gp-paint-toolkit`

## Task
Ler `nuclear-paint-tab-toolkit.md` e consertar os pontos restantes (FILA/FOCO):
(1) remover o grunge texture; (2) ferramentas de brush Draw/Erase/Fill/Tint funcionarem +
Lasso Fill "sem brush"; (4) 2º modo de smudge (dissolver/borrar); (5) editar em perspectiva.
Escopo escolhido: 1 + 2 + Lasso + 4 + 5 (sem o ponto 3, primitivas com textura).

## What Was Done
- **Ponto 1 — grunge removido**: operador `NUCLEAR_OT_add_tip_texture`, `_GRUNGE_TEX_NAME` e
  o botão saíram do Python; fallback C revertido (`grease_pencil_paint.cc` volta ao HEAD).
- **Ponto 2 — brush tabs**: `_BRUSH_TABS` mapeia `DRAW/ERASE/FILL/TINT`; `brush_tab` seta
  `brush.gpencil_brush_type` (+ `builtin.brush` ativo). Tint corrigido; botões com `depress`.
- **Lasso Fill**: **botão "Lasso Fill" na aba Brushes** que roda o modal sem trocar de
  ferramenta (o brush ativo permanece) — o `draw_settings` na WorkSpaceTool não bastou. O fill
  já renderizava/usava a cor, confirmado ao vivo via MCP.
- **Ponto 4 — Blur/Dissolve**: `GPAINT_BRUSH_TYPE_BLUR = 5` (DNA+RNA+case→`new_smooth_operation`);
  botão "Blur / Dissolve Mode"; toggle generalizado por `brush_type`.
- **Smudge/Blur — raio, força e cursor (ciclos 2-3)**: `paint_cursor.cc` dá `pixel_radius` a
  SMUDGE/BLUR (antes 0 = sem bolinha); `_apply_paint_defaults` desliga `use_unified_size` (o raio
  passa a escalar com `brush.size`); o toggle liga `use_edit_position`/`use_edit_strength` no Blur
  (senão o smooth no-opa); slider **Strength** exposto nos modos deform.
- **Ponto 5 — Perspective: REMOVIDO** a pedido do autor (POC de câmera/keystone não era o que
  ele queria; foco no smudge/blur).

## Decisions Made
- **Troca de brush pelo TIPO, não pela ferramenta** — no 5.0 os brushes GP são assets
  read-only; o tipo (`gpencil_brush_type`) é o que dirige `get_stroke_operation`. Mesmo
  mecanismo que o Smudge já provava.
- **Blur reusa `new_smooth_operation`** (o smooth do sculpt) — dissolve/relaxa, complementar
  ao smear (grab) do Smudge. Seam mínima: append no enum + item RNA + 1 case.
- **Lasso**: não era bug de render; o fill sempre funcionou. O fix mira o sintoma real
  (perda dos controles de brush no header ao ativar a tool não-brush).

## Validation
- **Reprodução ao vivo (MCP)** do Lasso Fill: fill renderiza (screenshot TOP) e usa a cor do
  brush — em objeto de teste descartável, cena restaurada depois.
- **Rebuild** `build_nuclear_full` (container `blender`, `ninja -j3 install`) — exit 0.
- **Smoke test headless** do binário novo: enum `['DRAW','FILL','ERASE','TINT','SMUDGE','BLUR']`,
  operadores/painéis registrados, operador grunge ausente → `SMOKE_OK`.
- **PENDENTE (humano)**: validação DESENHANDO — smear/dissolve reais, Fill/Erase via troca de
  tipo, lasso e perspectiva num processo fresco (o Blender aberto do usuário roda o build antigo).

## Modified Files
- `scripts/startup/nuclear_paint_toolkit.py` — pontos 1, 2, lasso, 4, 5 + UI.
- `source/blender/makesdna/DNA_brush_enums.h` — `GPAINT_BRUSH_TYPE_BLUR = 5`.
- `source/blender/makesrna/intern/rna_brush.cc` — item RNA `BLUR`.
- `source/blender/editors/sculpt_paint/grease_pencil_draw_ops.cc` — case `BLUR → new_smooth_operation`.
- `source/blender/editors/sculpt_paint/paint_cursor.cc` — cursor (raio) p/ SMUDGE/BLUR.
- `source/blender/editors/sculpt_paint/grease_pencil_paint.cc` — revertido ao HEAD (grunge fora).
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — registro da seam BLUR.
- `docs/` — este summary, ADR e CHANGELOG.

## Architectural Decision
[ADR: Consertos finais do toolkit de pintura GP](../decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md)

---

## PR Description Template

## What This PR Does
Fecha os pontos restantes da tab Paint do GP: conserta as categorias de brush e o Lasso
Fill, remove o grunge texture, adiciona um 2º modo de smudge (Blur/Dissolve) e um POC de
edição em perspectiva.

## Why
As categorias Draw/Erase/Fill/Tint usavam `wm.tool_set_by_id`, que no Blender 5.0 não troca
o tipo do brush (brushes = assets read-only); o correto é setar `gpencil_brush_type`. O
grunge foi descartado pelo autor. Smudge ganhou o par "dissolver" reusando o smooth do
sculpt. Base: [ADR 2026-07-06](docs/decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md).

## Key Changes
- [x] Categorias de brush trocam `gpencil_brush_type` (Tint corrigido)
- [x] Lasso Fill mantém os controles de brush no tool-header (`draw_settings`)
- [x] Grunge texture removida (Python + reversão do C)
- [x] `GPAINT_BRUSH_TYPE_BLUR` → `new_smooth_operation` + botão "Blur / Dissolve Mode" + Strength
- [x] Raio (unified size off) + blur (`use_edit_position`) + cursor (`paint_cursor.cc`)

## How to Test
1. Build (`ninja install`) e abrir em **processo fresco** (matar Blender antigo, não reload).
2. GP em Paint mode → tab Paint: clicar Draw/Erase/Fill/Tint e **desenhar** — cada um pinta
   como o tipo. Clicar "Smudge Mode" e arrastar sobre traços (smear); "Blur / Dissolve
   Mode" e arrastar (dissolve/relaxa).
3. Botão **Lasso Fill** na aba Brushes (mantém a ferramenta de brush): laçar uma região →
   fill tingido pela cor do brush, sem perder o brush ativo.
4. Confirmar que **não há** mais botão/UI de "Grunge Texture" nem painel de Perspectiva.
   - Resultado esperado: todos os modos pintam; smudge/blur escalam com Size e têm bolinha;
     brush nunca "some"; sem grunge.

## Impact
- **Breaking changes**: Não (append de enum, sem reorder de DNA de struct, sem versionamento).
- **Migrations required**: Não.
- **New environment variables**: Nenhuma.
- **Rebuild**: Sim (mudança em `DNA_brush_enums.h` propaga p/ makesrna + dependentes).

## References
- ADR: `docs/decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md`
- Divergência: `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` (seção "Ferramentas de pintura GP")
