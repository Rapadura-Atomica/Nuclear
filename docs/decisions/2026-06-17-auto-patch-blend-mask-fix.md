# ADR: Auto-Patch GP — o fill cortado (B/C) é o passe de layer-blend re-aplicando o matte, não o depth

**Date**: 2026-06-17
**Status**: Accepted
**Context**: `source/blender/draw/engines/gpencil` (branch `feat/gp-masks`, worktree `nuclear-gpmasks`)

## Context

O auto-patch nativo do Nuclear (fidelidade ao Toon Boom Harmony) deve cortar **só a linha**
(line-art) do layer remendado onde o matte cobre, **mantendo o fill** (colour-art). Funcionava no
caso cross-object visível (A), mas no **self-patch (C)** e no **occluder oculto (B)** o fill era
cortado junto com a linha — ver `doc/guides/nuclear_auto_patch_bc_followup.md`.

O follow-up hipotetizou que a causa era o **teste de profundidade de hardware** (mesma-objetividade,
`DRW_STATE_DEPTH_GREATER`). Essa hipótese foi **refutada ao vivo** nesta sessão (blender-mcp +
instrumentação de cor no fragment shader): pintando os fragmentos de fill do auto-patch conforme o
resultado do teste de profundidade manual, **nenhum** reprovava (nenhum vermelho), e numa cena de
teste limpa o fill do Art **sobrevivia** no `layer_fb` — só desaparecia na composição final.

### Causa-raiz real

Layers mascarados são compostos em **dois** momentos:

1. **Geometria** (`gpencil_frag.glsl`): cada drawcall desenha no buffer do layer. O `gp_mask_bypass`
   (empurrado pelo auto-patch) faz o **fill** ignorar a máscara e o **stroke** ser descartado onde o
   matte cobre. Até aqui o fill é mantido corretamente no `layer_fb`.
2. **Blend do layer** (`gpencil_layer_blend_frag.glsl`): o layer é composto no buffer do objeto
   multiplicando `color * mask` (`blend_mode_output`). **Este passe re-aplica o matte** ao layer
   inteiro — e como fill e stroke já estão fundidos no `color_buf`, o fill é cortado aqui.

Ou seja: o bypass de máscara só existia no passe de geometria; o passe de blend cortava o fill de
volta. Isso explica todos os sintomas do follow-up: "In Front" não ajudava (não é depth), rotear o
self por `mask_bits` não ajudava (o blend re-aplica a máscara seja qual for o roteamento), e o
push-constant de bypass chegava ao fill (mas no passe errado para resolver).

## Decision

Para layers **auto-patch**, o passe de layer-blend **ignora o matte** (`mask = 1.0`), preservando
apenas `blend_opacity`. O corte por-elemento (fill mantido / stroke cortado) já foi feito
corretamente no passe de geometria via `gp_mask_bypass`, então o stroke já saiu do `color_buf` e o
fill deve ser composto inteiro.

Implementação (mínima, espelhando o padrão `gp_mask_bypass`):
- novo push-constant `blend_auto_patch` na create-info `gpencil_layer_blend`;
- `gpencil_layer_blend_frag.glsl`: `mask = (blend_auto_patch != 0) ? 1.0 : texture(mask_buf)`;
- `gpencil_cache_utils.cc`: empurra `blend_auto_patch = tgp_layer->auto_patch` no `blend_ps`.

## Alternatives Considered

### Mexer no depth-state do `fill_ps` (hipótese original 2B)
- **Pros**: era a direção apontada pelo follow-up.
- **Cons**: a causa não era depth; mexeria em estado que regride o empilhamento de layers.
- **Why discarded**: refutada ao vivo (sem vermelho no debug; fill presente no `layer_fb`).

### Novo `gp_depth_bypass` para o teste manual de `scene_depth` (hipótese original 2A)
- **Pros**: mínimo se a causa fosse o teste manual.
- **Cons**: o teste manual não descartava o fill (nenhum fragmento ficou vermelho no debug).
- **Why discarded**: refutada ao vivo.

### Compor o fill auto-patch direto no buffer do objeto (fora do blend mascarado)
- **Pros**: arquiteturalmente "puro" (fill nunca passa pelo blend mascarado); reutilizaria o `fill_ps`.
- **Cons**: bem mais código (passe extra de composição, ordem/compositing a acertar); maior risco.
- **Why discarded**: a opção escolhida (mask=1 no blend para auto-patch) resolve com 3 linhas, sem
  regredir a máscara normal, e foi validada. "Smallest sufficient change".

## Consequences

### Positive
- **C (self-patch)** e **B (occluder oculto)** passam a manter o fill, como **A**. Validado ao vivo
  (cena limpa `SelfClean`): fill amarelo mantido em toda a largura, linha cortada sob o matte.
- **Sem regressão** na máscara normal (auto-patch OFF corta fill+linha como antes) nem em A (fill
  mantido). Mudança restrita a layers com `auto_patch=true`.
- Custo desprezível: um `int` push-constant e um branch num shader fullscreen; zero passes novos.
- Sem mudança de DNA/RNA nem de interface de usuário.

### Negative / Trade-offs
- A borda do stroke na fronteira do matte é cortada de forma **binária** (descarte no frag de
  geometria em `mask < 0.001`), não suave — leve aliasing de ~1px na costura. Aceitável para um
  seam patch (matte normalmente é hard-edged).
- **B** não foi testado ao vivo nesta sessão (usa o mesmo passe de blend → deve estar coberto);
  recomenda-se uma validação B com occluder de eye-icon desligado.

## Affected Files
- `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh` — push-constant `blend_auto_patch`.
- `source/blender/draw/engines/gpencil/shaders/gpencil_layer_blend_frag.glsl` — ignora matte se auto-patch.
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` — empurra o flag no `blend_ps`.
