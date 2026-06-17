# ADR: Separar Contour (envelope) e Masks (auto-patch) em commits independentes

**Date**: 2026-06-17
**Status**: Accepted
**Context**: fork Nuclear / Grease Pencil v3 (engine, DNA/RNA, modifiers)

## Context

O commit `90ac371d58a` ("feat(gp): modifier Contour (envelope MVC) + masks nativas de GP")
fundiu **dois projetos não relacionados** num único ponto da história:

1. O **modifier `GreasePencilContour`** (eType 88) — deformer de envelope estilo Toon Boom
   via Mean Value Coordinates contra um cage.
2. As **masks nativas de GP** (auto-patch / cutter cross-object) — mascaramento em
   pegs/grupos onde o matte de uma parte recorta as camadas da vizinha na junta.

Enquanto estivessem fundidos, era impossível shippar um sem o outro numa linha de release.
A linha 1.1 (`integration/1.1-ui-squash`) excluiu ambos de propósito justamente por não dar
para separar. O objetivo desta decisão é tornar cada feature cherry-pickável isoladamente.

## Decision

Reconstruir o conteúdo de `90ac371` como **duas branches independentes a partir do pai real
`8d7e310`**, preservando as branches originais como snapshot histórico:

- **`feat/gp-contour`** (`570ff05`) — 9 arquivos / 458 inserções (só o modifier Contour).
- **`feat/gp-masks`** (`d949910`) — 14 arquivos / 992 inserções (só as masks/auto-patch).

A separação é limpa no nível de arquivo para 21 dos 22 arquivos. O único arquivo misturado é
`source/blender/blenkernel/intern/grease_pencil.cc`, dividido em nível de hunk: **1 hunk de
contour** (o `case eModifierType_GreasePencilContour` em `influence_data_from_modifier`, 4
linhas aditivas) vs. **8 hunks de mask** (foreach_id, ctor/copy/dtor de `LayerMask`/`LayerGroup`,
`rename_node`, blend read/write de grupo).

O split foi resolvido sem editar headers de diff à mão: para cada branch, os arquivos
dedicados vieram via `git checkout 90ac371 -- <arquivos>`, e o arquivo misturado foi obtido
adicionando/removendo deterministicamente o bloco de 4 linhas do contour.

### Detalhe crítico: o pai real é `8d7e310`, não `29d9836`

A primeira tentativa ramificou de `29d9836` (avô). Entre ele e `90ac371` existe o commit
`8d7e310` ("Pegs: destaque de drawings"), que toca **só** `nuclear_peg_graph.py` (157 linhas).
Ramificar do avô arrastava esse trabalho intermediário pra dentro do commit de masks (o diff
de `nuclear_peg_graph.py` inflava de 206 → 363). Corrigido ramificando do pai real `8d7e310`.

## Alternatives Considered

### `git rebase -i` parando em 90ac371 para editar/dividir o commit
- **Pros**: fluxo "canônico" de split de commit; mantém a branch original.
- **Cons**: reescreve a `feat/native-auto-patch` publicada; o ambiente não suporta flags
  interativas (`rebase -i`, `add -i`, `add -p`).
- **Why discarded**: bloqueado pelo ambiente e destrutivo para a branch preservada.

### `git reset --soft HEAD~1` + `git add -p` re-stageando por hunk na própria branch
- **Pros**: simples conceitualmente.
- **Cons**: `git add -p` é interativo (bloqueado); mexe na branch existente em vez de produzir
  artefatos limpos e preservar o snapshot.
- **Why discarded**: interatividade bloqueada e perda do snapshot histórico.

## Consequences

### Positive
- Cada feature é cherry-pickável isoladamente para qualquer linha de release.
- Integrar o auto-patch na 1.1 agora é um simples cherry-pick de `feat/gp-masks`.
- Reconstrução verificada: `8d7e310 + feat/gp-contour + feat/gp-masks == 90ac371` byte-a-byte;
  nenhum lado referencia símbolos do outro (compila independente por análise).
- Branches de preservação intactas (`feat/native-auto-patch`@`90ac371`,
  `integration/gp-contour-1.1`).

### Negative / Trade-offs
- Passam a existir 3 representações do mesmo trabalho (a fusão original + as duas metades); se
  ambas evoluírem isoladamente, manter em sincronia dá trabalho (mitigado: as originais são
  snapshots, não recebem mais commits).
- **Validação de compilação ainda pendente** — a independência foi provada por análise e
  reconstrução de árvore, não por build de cada branch.

## Affected Files

Branches novas (não na 1.1):
- `feat/gp-contour`: `MOD_grease_pencil_contour.cc`, `DNA_modifier_types.h`,
  `DNA_modifier_defaults.h`, `dna_defaults.c`, `rna_modifier.cc`, `MOD_modifiertypes.hh`,
  `MOD_util.cc`, `modifiers/CMakeLists.txt`, `grease_pencil.cc` (1 hunk).
- `feat/gp-masks`: `grease_pencil.cc` (8 hunks), `grease_pencil_layers.cc`,
  `DNA_grease_pencil_types.h`, `rna_grease_pencil.cc`, `rna_grease_pencil_api.cc`,
  `gpencil_cache_utils.cc`, `gpencil_engine_c.cc`, `gpencil_engine_private.hh`,
  `gpencil_frag.glsl`, `gpencil_infos.hh`, `properties_data_grease_pencil.py`,
  `nuclear_peg_graph.py`, `doc/guides/nuclear_gp_masks*.md`.

Nesta branch (`integration/1.1-ui-squash`):
- `doc/guides/nuclear_auto_patch_nativo.md` — §3 (correção de caminho), §5/§7 (split feito).
