# Session: Auto-Patch GP — corrigir fill cortado no self-patch (C) e occluder oculto (B)

**Date**: 2026-06-17
**Tier**: 3 — Full
**Specialist**: general (graphics / C++ / GLSL — render pipeline)

## Task
Ler `doc/guides/nuclear_auto_patch_bc_followup.md` e achar maneiras de resolver o bug em que o
auto-patch GP cortava o fill junto com a linha no self-patch (C) e no occluder oculto (B).

## What Was Done
- Investiguei o pipeline de render GP (geometria + máscara + blend) no código real, não só no doc.
- Fase 0 (diagnóstico): instrumentei o `gpencil_frag.glsl` com debug de cor e rodei ao vivo
  (blender-mcp) numa cena de teste limpa. **Refutei** a hipótese de depth do doc (nenhum fragmento
  reprovava no teste manual; o fill sobrevivia no `layer_fb`).
- Achei a **causa-raiz real**: o passe `blend_ps` (`gpencil_layer_blend_frag.glsl`) re-aplica o matte
  ao layer inteiro; o `gp_mask_bypass` só furava a máscara no passe de geometria.
- Implementei o fix mínimo (3 linhas): layers auto-patch ignoram o matte no blend (`mask=1`).
- Validei ao vivo: C corrigido, A sem regressão, máscara normal sem regressão.

## Decisions Made
- **Confirmar antes de corrigir**: o experimento de cor mudou o diagnóstico (de depth para o blend),
  evitando um fix errado no depth-state que regrediria o empilhamento de layers.
- **mask=1 no blend (em vez de compor o fill fora do blend)**: 3 linhas, sem regressão na máscara
  normal, validado. Espelha o padrão `gp_mask_bypass`. Alternativa "pura" (passe de composição
  separado) descartada por custo/risco.
- Cena de teste limpa criada via script porque a `nuclear_autopatch_debug.blend` tinha confounds
  (fills com alpha-0 de vértice, matte opaco ocluindo, geometria vista edge-on).

## Modified Files
- `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh` — push-constant `blend_auto_patch`.
- `source/blender/draw/engines/gpencil/shaders/gpencil_layer_blend_frag.glsl` — ignora matte se auto-patch.
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` — empurra `blend_auto_patch` no `blend_ps`.
- `doc/guides/nuclear_auto_patch_bc_followup.md` — marcado RESOLVIDO + seção de atualização (causa real).

## Architectural Decision
Ver ADR: `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`.

---

## PR Description Template

## What This PR Does
Corrige o auto-patch GP do Nuclear para manter o fill (colour-art) e cortar só a linha (line-art)
nos casos self-patch e occluder oculto, igual ao caso cross-object que já funcionava.

## Why
O corte por-elemento (fill mantido / stroke cortado) era feito no passe de geometria via
`gp_mask_bypass`, mas o passe de composição do layer (`gpencil_layer_blend_frag.glsl`) re-aplicava o
matte ao layer inteiro, cortando o fill de volta. A hipótese anterior (teste de profundidade) foi
refutada ao vivo. Ver ADR `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`.

## Key Changes
- [x] Push-constant `blend_auto_patch` na create-info `gpencil_layer_blend`.
- [x] `gpencil_layer_blend_frag.glsl`: layers auto-patch ignoram o matte (`mask=1`), mantendo `blend_opacity`.
- [x] `gpencil_cache_utils.cc`: empurra `blend_auto_patch = tgp_layer->auto_patch` no `blend_ps`.

## How to Test
1. Crie um GP com 2 layers no mesmo objeto: `Matte` (retângulo preenchido) e `Art` (retângulo
   preenchido + linha) sobrepondo parcialmente o Matte.
2. No `Art`: mask layer `Matte`, `object`=self, `use_auto_patch=True`, `invert=True`, `use_masks=True`.
3. Vista TOP, shading SOLID.
4. Expected: o fill do `Art` permanece em toda a largura; a linha do `Art` é cortada onde o `Matte`
   cobre. Com `use_auto_patch=False` (máscara normal), fill+linha são cortados (sem regressão).

## Impact
- **Breaking changes**: No.
- **Migrations required**: No (sem mudança de DNA/RNA/.blend).
- **New environment variables**: None.

## References
- ADR: `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`
- Follow-up (refutado/atualizado): `doc/guides/nuclear_auto_patch_bc_followup.md`
