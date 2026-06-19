# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Auto-patch nativo (GP) — fidelidade ao Toon Boom Harmony: matte só do fill (A), paridade com
  occluder oculto via relação de depsgraph + segundo passe no engine (B), self-patch / matte de
  layer arbitrário (C) e aviso de ordem de desenho coplanar (D). Implementado e compilando na
  `feat/gp-masks` (worktree, não commitado); validação visual pendente
  (ver [ADR](decisions/2026-06-17-auto-patch-harmony-fidelity.md)).
  - Arquivos afetados (na `feat/gp-masks`): `gpencil_engine_private.hh`, `gpencil_cache_utils.cc`,
    `gpencil_engine_c.cc`, `grease_pencil_layers.cc`, `deg_builder_relations.cc`;
    doc `doc/guides/nuclear_auto_patch_harmony_fidelity.md`.
- Self-serve de release: subcomandos `bump`/`verify-zip`/`check-manifest` no
  `nuclear_release.py` e o script orquestrador `tools/nuclear_release.sh`, que encadeia
  bump → build opcional (`--build`) → empacotar → verificar regras de ouro #3/#4 →
  manifesto → publicar (com confirmação) → lembrete de CLAUDE.md → commit, para
  programadores rodarem um release sem precisar do agente Claude.
  - Arquivos afetados: `tools/nuclear_release.py`, `tools/nuclear_release.sh` (novo),
    `.claude/agents/nuclear-release.md`, `tools/nuclear_claude/CLAUDE.md`.

### Changed
- Separadas, em branches independentes, as duas features que o commit `90ac371` havia fundido:
  o modifier GP Contour (envelope) e as masks nativas (auto-patch). Cada metade agora é
  cherry-pickável isoladamente — `feat/gp-contour` e `feat/gp-masks`, ambas a partir do pai
  real `8d7e310` (ver [ADR](decisions/2026-06-17-separar-contour-e-masks.md)).
  - Arquivos afetados nesta linha: `doc/guides/nuclear_auto_patch_nativo.md`.

### Fixed
- `doc/guides/nuclear_auto_patch_nativo.md` §3: caminho de `grease_pencil_layers.cc` corrigido
  para `source/blender/editors/grease_pencil/intern/` (faltava `editors/`).
