# Changelog

Mudanças fork-specific do Nuclear (não-upstream). Formato: Keep a Changelog.

## [Unreleased]

### Added
- Auto-Patch GP: modo **Mutual** no operador `grease_pencil.auto_patch` (prop booleana `mutual`,
  cross-object). Ao patch A→B cria **também** a máscara recíproca no occluder (B→A, `auto_patch+invert`,
  matte = o objeto ativo inteiro), pra **corte de junta bidirecional** (as duas linhas de costura somem
  na sobreposição, e se mantém no movimento) numa chamada só. Alvo da recíproca = a camada do occluder
  com o **mesmo nome** da layer patcheada (ex.: ambas "Lines"), com fallback pra layer ativa; guarda
  anti-duplicata. Validado ao vivo 2026-06-19 (binário rebuilded, cena de debug, vista TOP): primário
  corta 4849px, recíproco 2147px; ambos-visíveis=0 é oclusão §5 (correto).
  - Affected files: `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc`

### Fixed
- Auto-Patch GP (cross-object): o corte da linha **só aparecia quando o objeto-occluder estava
  OCULTO** — com a peça-matte VISÍVEL (o caso real de dois braços/membros sobrepostos) a costura não
  era cortada. Root cause: a matte (silhueta de fill) sofria o **teste manual de profundidade da cena**
  (`gpencil_frag.glsl`); a geometria do occluder visível, presente no depth buffer, descartava a própria
  matte na zona de sobreposição → mask buffer vazio ali → stroke não cortado. (Era a suspeita do
  comentário "KNOWN BUG" no `gpencil_cache_utils.cc`.) Fix: novo push-constant `gp_in_mask_pass` (=1 no
  `fill_ps`, usado só como matte), e o frag pula o scene-depth-test quando setado. Cirúrgico: o depth
  test segue ativo no desenho normal. Validado (fresh-process, vista TOP): caso ambos-visíveis 0→573,
  e visual confirma a costura sumindo com as duas peças visíveis.
  - Affected files: `source/blender/draw/engines/gpencil/shaders/gpencil_frag.glsl`,
    `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh`,
    `source/blender/draw/engines/gpencil/gpencil_engine_c.cc`
- Auto-Patch GP: o fill (colour-art) deixava de ser cortado junto com a linha no self-patch e no
  occluder oculto. A causa era o passe de layer-blend re-aplicando o matte ao layer já remendado;
  agora layers auto-patch ignoram o matte no blend (o corte por-elemento já é feito no passe de
  geometria via `gp_mask_bypass`). (ver [ADR](decisions/2026-06-17-auto-patch-blend-mask-fix.md))
  - Affected files: `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh`,
    `source/blender/draw/engines/gpencil/shaders/gpencil_layer_blend_frag.glsl`,
    `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc`

### Notes
- **Auto-Patch GP — re-validação 2026-06-19: confirmado FUNCIONAL** (cross-object, mantém fill, corta
  stroke; Mod B occluder oculto ok). Uma revisão deste dia chegou a uma conclusão errada ("inerte em
  stroke") por **erro de método de render** (cena de debug medida de FRONT sendo a geometria no plano
  X-Y → exige TOP; e personagem sem sobreposição na pose de descanso). Lição e protocolo de medição em
  [`doc/guides/nuclear_auto_patch_validation_b_2026-06-18.md`](../doc/guides/nuclear_auto_patch_validation_b_2026-06-18.md)
  §10. Pendência real (workflow, não bug): operador `grease_pencil.auto_patch` ganhar modo **mútuo**
  (cria a máscara recíproca no occluder) para corte de junta bidirecional num clique.
