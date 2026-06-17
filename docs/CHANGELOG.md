# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- Separadas, em branches independentes, as duas features que o commit `90ac371` havia fundido:
  o modifier GP Contour (envelope) e as masks nativas (auto-patch). Cada metade agora é
  cherry-pickável isoladamente — `feat/gp-contour` e `feat/gp-masks`, ambas a partir do pai
  real `8d7e310` (ver [ADR](decisions/2026-06-17-separar-contour-e-masks.md)).
  - Arquivos afetados nesta linha: `doc/guides/nuclear_auto_patch_nativo.md`.

### Fixed
- `doc/guides/nuclear_auto_patch_nativo.md` §3: caminho de `grease_pencil_layers.cc` corrigido
  para `source/blender/editors/grease_pencil/intern/` (faltava `editors/`).
