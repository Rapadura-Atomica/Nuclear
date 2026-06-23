# Session: Junção Auto-Patch + Envelope na mainline Nuclear

**Date**: 2026-06-23
**Tier**: 3 — Full
**Specialist**: general

## Task
"Temos duas atualizações atualmente, autopatch e envelope; procure pelas versões mais
recentes e implemente uma junção de ambas as features; após checar conflitos, procure pela
versão mais atual do Nuclear e implemente essas mudanças nela. Além disso, na gp-masks,
retirar o nome 'Toon Boom' do botão do auto-patch." Alvo final confirmado: branch `Nuclear`.

## What Was Done
- Renomeado o operador/botão do Auto-Patch: `"Auto-Patch (Toon Boom)"` → `"Auto-Patch"`
  (label + tooltip) na `feat/gp-masks` (commit `a1d321ea3c9`).
- Criada `integration/autopatch-envelope` a partir da mainline `Nuclear` (`7ad3a045fa1`).
- Merge de `integration/gp-contour-1.1` (envelope) — 4 conflitos resolvidos, com o Contour
  realocado de eType **88 → 89** para não colidir com o Cutter (`GreasePencilMask=88`).
- Merge de `feat/gp-masks` (auto-patch) — **18 hunks** de conflito em 5 arquivos de engine
  resolvidos como união 3-way, preservando os 3 fixes conhecidos (matpool clamp, blend fix
  `897dcc4f519`, depth-fix `gp_in_mask_pass` `e3a4f264bf2`) e o `referenced_mattes`.
- Build limpo no distrobox `blenderdev` (ninja, RC 0; ninja install RC 0) + smoke test
  headless: `GREASE_PENCIL_MASK`, `GREASE_PENCIL_CONTOUR` instanciam; `grease_pencil.auto_patch`
  registra com label "Auto-Patch" (sem Toon Boom) e props `matte_source`/`layer`/`mutual`.
- Resultado trazido para a branch `Nuclear`.

## Decisions Made
- **Alvo = mainline `Nuclear`, merge sequencial B→A** (não merge isolado A+B depois rebase):
  resolve cada arquivo de engine uma só vez no contexto final com o Cutter presente.
- **Contour 88→89** (append-only): o Cutter já estava publicado/na mainline em 88; nenhum
  dos dois está em build publicado, mas mover o Contour minimiza risco de compat.
- **peg_graph.py**: mantida a versão da mainline (mattes via Cutter modifier) — implementação
  mais nova do mesmo masking cross-object; a versão engine-based das branches era herança da
  base antiga e não acrescentava função.
- **Sem bump de `NUCLEAR_BUILD`**: a publicação/empacotamento fica para o agente `nuclear-release`.

## Modified Files
- `source/blender/makesdna/DNA_modifier_types.h` — Contour eType 88→89.
- `source/blender/draw/engines/gpencil/{gpencil_engine_c.cc,gpencil_cache_utils.cc,gpencil_engine_private.hh,shaders/infos/gpencil_infos.hh}` — união 3-way.
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` — merge + rename do botão.
- `scripts/startup/nuclear_peg_graph.py`, `source/blender/blenkernel/BKE_blender_version.h` — resolução.
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md`, `docs/CHANGELOG.md`, `doc/guides/nuclear_auto_patch_harmony_fidelity.md`.

## Architectural Decision
Ver [ADR 2026-06-23](../decisions/2026-06-23-merge-autopatch-envelope-nuclear.md).

## PR Description (pronto para usar)

### What This PR Does
Junta numa só linha as duas features GP refinadas — Auto-Patch (engine seam-patch) e
Envelope/Contour (modifier deformer) — e as integra na mainline `Nuclear`, que já tinha o
Cutter Modifier. Renomeia o botão do Auto-Patch removendo "Toon Boom".

### Why
As features viviam em branches separadas (`feat/gp-masks`, `integration/gp-contour-1.1`) e
precisavam coexistir na `Nuclear` para o próximo release 2D. Ver ADR para a estratégia de merge
e a realocação do eType do Contour (88→89).

### Key Changes
- [x] Contour modifier realocado para eType 89 (Cutter mantém 88).
- [x] União 3-way dos 5 arquivos de draw engine GP, preservando os fixes do auto-patch.
- [x] Botão do Auto-Patch renomeado para "Auto-Patch".
- [x] Build + smoke test headless dos 3 sistemas.

### How to Test
1. Build: `distrobox enter blenderdev -- bash -lc 'cd ~/Documentos/GitHub/build_nuclear_full && ninja && ninja install'`.
2. Abrir o Nuclear, criar 2 objetos GP, adicionar modifiers Cutter e Contour/Envelope; usar
   o operador Auto-Patch (matte_source Occluder/Same Object, opção Mutual).
3. Resultado esperado: corte de linha mantendo o fill; envelope deforma pela curva Bézier;
   botão exibe "Auto-Patch". **Validar em processo fresco e da vista TOP, com overlap.**

### Impact
- **Breaking changes**: Não (eType do Contour ainda não publicado).
- **Migrations required**: Não.
- **New environment variables**: Nenhuma.

### References
- ADR: docs/decisions/2026-06-23-merge-autopatch-envelope-nuclear.md
