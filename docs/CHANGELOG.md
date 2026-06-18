# Changelog

Mudanças fork-specific do Nuclear (não-upstream). Formato: Keep a Changelog.

## [Unreleased]

### Fixed
- Auto-Patch GP: o fill (colour-art) deixava de ser cortado junto com a linha no self-patch e no
  occluder oculto. A causa era o passe de layer-blend re-aplicando o matte ao layer já remendado;
  agora layers auto-patch ignoram o matte no blend (o corte por-elemento já é feito no passe de
  geometria via `gp_mask_bypass`). (ver [ADR](decisions/2026-06-17-auto-patch-blend-mask-fix.md))
  - Affected files: `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh`,
    `source/blender/draw/engines/gpencil/shaders/gpencil_layer_blend_frag.glsl`,
    `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc`
