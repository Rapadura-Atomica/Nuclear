# Session: Separar masks (auto-patch) do contour (envelope) no commit 90ac371

**Date**: 2026-06-17
**Tier**: 3 — Full
**Specialist**: general (engine C++ do fork)

## Task

Ler `doc/guides/nuclear_auto_patch_nativo.md` e continuar a implementação. Frente escolhida do
§7: **separar** as masks nativas (auto-patch) do modifier Contour (envelope MVC), que estavam
fundidos no commit `90ac371`, em mudanças independentes.

## What Was Done

- Mapeado o commit `90ac371` (22 arquivos / 1450 ins): 8 arquivos dedicados de contour, 13 de
  mask, e **1 arquivo misturado** (`grease_pencil.cc`).
- Criadas duas branches independentes a partir do pai real `8d7e310`:
  - `feat/gp-contour` (`570ff05`) — 9 arq / 458 ins.
  - `feat/gp-masks` (`d949910`) — 14 arq / 992 ins.
- `grease_pencil.cc` dividido em nível de hunk (1 hunk de contour vs. 8 de mask) sem editar
  diffs à mão.
- Verificado por reconstrução: `8d7e310 + contour + masks == 90ac371` byte-a-byte; cada lado
  livre de símbolos do outro.
- Atualizados o guia (§3 path fix, §5/§7 status) e a memória do projeto.

## Decisions Made

- **Branches novas do pai real, não rebase -i**: preserva as branches originais como snapshot
  e contorna o bloqueio de flags git interativas no ambiente.
- **Pai real `8d7e310`, não `29d9836`**: o commit intermediário `8d7e310` só toca
  `nuclear_peg_graph.py`; ramificar do avô contaminava o commit de masks (206 → 363 linhas
  nesse arquivo). Pego no sanity-check de stat e corrigido.
- **Split do arquivo misturado por checkout + edição determinística do bloco de 4 linhas** em
  vez de `git apply` com patch montado à mão — mais verificável.
- **Caso de borda achado**: `git add -A` seguido de `git reset --hard` apagou o
  `council-state.md` (untracked → staged → resetado). Conteúdo recriado como este resumo.

## Modified Files

- `feat/gp-contour` / `feat/gp-masks` — branches novas (ver ADR para a lista de arquivos).
- `doc/guides/nuclear_auto_patch_nativo.md` — §3 caminho de `grease_pencil_layers.cc`
  (faltava `editors/`), §5 tabela de git, §7 checkbox do split.
- `docs/decisions/2026-06-17-separar-contour-e-masks.md`, `docs/CHANGELOG.md` — novos.

## Architectural Decision

Ver `docs/decisions/2026-06-17-separar-contour-e-masks.md`.

## Pendente

- Build de validação de cada branch no distrobox `blenderdev`.
- (Outras frentes do §7) integrar na release, depsgraph relation, re-validar em rig real.
