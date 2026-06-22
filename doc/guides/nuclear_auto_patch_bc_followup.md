# Follow-up: auto-patch GP — fill cortado no self-patch (C) e occluder oculto (B)

> **✅ RESOLVIDO em 2026-06-17** (ciclo /council Tier 3). A causa NÃO era profundidade — era o
> **passe de layer-blend re-aplicando o matte**. Fix: para layers auto-patch o blend ignora a
> máscara (`mask=1`), pois o corte por-elemento já é feito no passe de geometria via
> `gp_mask_bypass`. Ver ADR `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`. O texto abaixo
> (hipótese de depth) ficou **registrado como histórico/refutado** — ver "ATUALIZAÇÃO" ao final.
>
> Estado original em 2026-06-17. Branch **`feat/gp-masks`** (worktree `../nuclear-gpmasks`).
> Complementa [`nuclear_auto_patch_harmony_fidelity.md`](nuclear_auto_patch_harmony_fidelity.md) e o
> ADR `docs/decisions/2026-06-17-auto-patch-harmony-fidelity.md`.

## TL;DR do que precisa de fix

O auto-patch nativo tem 4 melhorias (A: matte fill-only; B: occluder oculto; C: self-patch;
D: aviso de ordem). **A e D funcionam** (validados ao vivo). **B e C têm um bug de RENDER
não resolvido**: em vez de cortar só a LINHA do layer remendado onde o matte cobre, eles
cortam o **layer inteiro (fill + linha)** — o fill-bypass do auto-patch não surte efeito.

## O que JÁ foi descartado (provado ao vivo, via blender-mcp + instrumentação)

1. **Não é o flag `auto_patch`.** Instrumentei `Instance::object_sync_do` e confirmei que
   `tgp_layer->auto_patch == 1` e `show_fill == 1` chegam ao render para o layer remendado,
   e que o push-constant `gp_mask_bypass = 1` É emitido no drawcall de fill (igual ao caso A
   que funciona). O fragment shader (`shaders/gpencil_frag.glsl:127-135`) pula o descarte da
   máscara quando `gp_mask_bypass != 0`.
2. **Não é o caminho do matte (`mattes` vs `mask_bits`).** Tentei rotear o self-patch pelo
   caminho `mask_bits` (same-object) em vez de `mattes` — **não resolveu** (revertido). Logo
   o bug não está no roteamento.
3. **Não é o depth-test MANUAL do frag.** Ligar "In Front" no objeto remendado (que troca
   `depth_tex` por `dummy_depth`, anulando o teste `if (gl_FragCoord.z > scene_depth)` em
   `gpencil_frag.glsl:119-123`) **não conserta** o fill cortado.
4. **Cross-object VISÍVEL funciona** (caso A): occluder num objeto SEPARADO e visível (matte
   de objeto-todo ou layer-filtrado) → fill mantido, só a linha cortada.

## Hipótese de ROOT CAUSE (a investigar primeiro)

**Teste de profundidade de HARDWARE, ligado à mesma-objetividade.**

- `Instance::draw_object` limpa o depth buffer no início de CADA objeto
  (`gpencil_engine_c.cc:960`, `GPU_framebuffer_clear_depth_stencil`).
- Os layers GP em 2D usam `DRW_STATE_DEPTH_GREATER | DRW_STATE_WRITE_DEPTH`
  (`gpencil_cache_utils.cc:512-516`).
- **Cross-object (A):** occluder e peça remendada são objetos separados → cada `draw_object`
  limpa seu próprio depth → o fill do remendado passa no teste de hardware. ✅
- **Self-patch (C):** layer-matte e layer-remendado no MESMO objeto → MESMO depth buffer
  (limpo uma vez). O layer-matte (desenhado antes) escreve depth; o teste de profundidade de
  **hardware** descarta o fill do layer remendado na região do matte. O `gp_mask_bypass` só
  pula o descarte da *máscara* no frag — **não** o teste de profundidade de hardware. Por isso
  o fill some mesmo com o bypass ativo, e por isso "In Front" (que só mexe no depth-test
  *manual*) não ajuda.
- **Occluder oculto (B):** mesmo raciocínio de visibilidade/depth + o caminho diferido
  `cache_only` (`sync_referenced_mattes`); provavelmente compartilha a raiz.

> ⚠️ A hipótese de hardware-depth é a mais forte mas **não foi 100% confirmada**. Próximo
> passo de diagnóstico sugerido: emitir `gp_mask_bypass` (ou o resultado do depth-test) como
> COR no `gpencil_frag.glsl` para ver, pixel a pixel, o que o fragmento de fill realmente
> recebe/descarta no caso same-object. Alternativamente, logar/contar descartes.

## Como reproduzir (rápido)

1. **Build** (ver setup abaixo) e abra o Nuclear.
2. Gere a cena de teste:
   `bin/blender --background --factory-startup --python ../make_autopatch_test.py`
   (script em `~/Documentos/GitHub/make_autopatch_test.py`) — cria `nuclear_autopatch_test.blend`
   com dois GP retangulares. Ou use `~/Documentos/GitHub/nuclear_autopatch_debug.blend`, que já
   tem um objeto `SelfTest` (layers `Matte` = fill + `Art` = linha) montado para self-patch.
3. **Self-patch (C):** no `SelfTest`, layer `Art` com mask `object=self`, `layer_name="Matte"`,
   `use_auto_patch=True`, `invert=True`; ponha `Art` no topo (`gpd.layers.move_top`). Toggle
   `Art.use_masks`:
   - **Esperado:** fill amarelo INTEIRO + linha cortada onde o fill `Matte` cobre.
   - **Bug atual:** o fill amarelo SOME na região do `Matte` (aparece o azul por baixo).
4. **Contraste (A, funciona):** dois objetos SEPARADOS (PartLower remendado + PartUpper
   occluder), occluder com **fill opaco** e Z diferente → fill mantido, linha cortada.

Validação visual ao vivo: addon **blender-mcp** (painel "Blender MCP" → "Connect to MCP
server"; porta 9876). Use `get_viewport_screenshot` + `execute_blender_code`.

## Arquivos relevantes (na `feat/gp-masks`)

- `source/blender/draw/engines/gpencil/gpencil_engine_c.cc`
  - `Instance::object_sync_do` (~:460-648) — loop de drawcalls; push de `gp_mask_bypass`
    (fill→1 em ~:611-623, stroke→0 em ~:628-637).
  - `Instance::draw_object` (~:949) — limpa depth (:960); loop de layers; chama `draw_mask`
    (:967-968); submete `geom_ps` (:979).
  - `Instance::draw_mask` (~:839) — renderiza o matte (mask_bits same-object :871-884; mattes
    cross-object :880-928, submete `fill_ps`).
  - `Instance::sync_referenced_mattes` (~:677) — Mod B, sync diferido `cache_only`.
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc`
  - `grease_pencil_layer_cache_add` — `auto_patch` init (:368), state com `DEPTH_GREATER`
    (:512-516), `apply_mask_list` (~:395-440: roteamento self/cross-object, `set_mask_bit`
    rejeita o próprio layer em :382), criação do `fill_ps` (~:541-562).
  - `gpencil_object_cache_add` — param `cache_only` (Mod B, :44-137).
- `source/blender/draw/engines/gpencil/shaders/gpencil_frag.glsl`
  - depth-test manual (:119-123), bypass da máscara (:127-135).
- `source/blender/draw/engines/gpencil/gpencil_engine_private.hh` — `tLayer.fill_ps`,
  `tLayer.auto_patch`, `Instance.referenced_mattes`, `tMatteRef`.

## Direções de fix candidatas

- **(mais provável)** Fazer o layer remendado NÃO ser ocluído por depth pelo layer-matte do
  mesmo objeto: ex. renderizar o remendado com depth independente do matte, ou dar ao drawcall
  de fill do auto-patch um estado de depth que não seja descartado pelo matte (sem quebrar o
  compositing normal entre layers). Cuidado para não regredir o empilhamento normal de layers.
- Confirmar primeiro a hipótese de hardware-depth (debug de cor no frag) antes de mexer.
- Para B, validar também as premissas runtime listadas no guia de fidelidade §5 (geometria de
  objeto oculto avaliada; `ObjectRef` sintético; keying por `orig_id`).

## Setup de build (cross-machine)

- Worktree: `~/Documentos/GitHub/nuclear-gpmasks` (branch `feat/gp-masks`).
- **Pegadinha:** o git worktree NÃO carrega `lib/` (é `make update`-managed). Symlinkar:
  `ln -s ~/Documentos/GitHub/Nuclear/lib/linux_x64 ~/Documentos/GitHub/nuclear-gpmasks/lib/linux_x64`
- Build: `distrobox enter blenderdev -- bash -lc 'cd ~/Documentos/GitHub/build_gpmasks && ninja -j8 && ninja install'`
  (dir `~/Documentos/GitHub/build_gpmasks`; `-j8` e log na HOME, não `/tmp` — `/tmp` não é
  compartilhado de forma estável com o container).
- Binário: `~/Documentos/GitHub/build_gpmasks/bin/blender`.
- Instrumentação de debug usada (já removida): prints guardados por `getenv("NUCLEAR_DEBUG_AUTOPATCH")`
  em `object_sync_do`, via `fprintf(stderr, ...)` (stdout para arquivo é bufferizado).

## ATUALIZAÇÃO (2026-06-17) — RESOLVIDO. A causa NÃO era profundidade.

A hipótese de hardware-depth acima foi **refutada ao vivo**. Como foi descoberto e corrigido:

**Experimento decisivo (debug de cor no frag).** Inseri, temporariamente, no `gpencil_frag.glsl`, um
bloco que — só para fragmentos de fill do auto-patch (`gp_mask_bypass != 0`) — pulava os descartes
manual/máscara e pintava o fragmento de **VERMELHO** se reprovaria no teste de profundidade manual
(`gl_FragCoord.z > scene_depth`) ou **VERDE** se passaria, deixando o depth de hardware ainda atuar.
Numa cena de teste limpa (retângulos preenchidos opacos, vista TOP, fundo magenta):
- **Nenhum vermelho** apareceu → o teste manual contra `scene_depth` (#2) NÃO descartava o fill.
- O fill do Art aparecia **verde** (presente no `layer_fb`), mas **sumia na composição final**.

Isso eliminou ambas as hipóteses de depth e apontou para a etapa de **composição** do layer.

**Causa-raiz.** Layer mascarado é composto pelo passe `blend_ps` (shader
`gpencil_layer_blend_frag.glsl`), que faz `color * mask` (`blend_mode_output`). Esse passe
**re-aplica o matte** ao layer inteiro. O `gp_mask_bypass` só furava a máscara no passe de
**geometria** (mantendo o fill no `layer_fb`); o passe de **blend** cortava o fill de volta. Por isso
"In Front" (depth) e o reroute `mask_bits` não resolviam, e o bypass "chegava ao fill" mas no passe
errado.

**Fix (3 linhas).** Para layers auto-patch, o blend ignora o matte (`mask = 1.0`), mantendo só
`blend_opacity`. O corte do stroke já foi feito no frag de geometria (o stroke já saiu do
`color_buf`), então o fill é composto inteiro e o stroke fica cortado.
- `shaders/infos/gpencil_infos.hh`: push-constant `blend_auto_patch` na create-info `gpencil_layer_blend`.
- `shaders/gpencil_layer_blend_frag.glsl`: `mask = (blend_auto_patch != 0) ? 1.0 : texture(mask_buf)`.
- `gpencil_cache_utils.cc` (~:507): empurra `blend_auto_patch = tgp_layer->auto_patch` no `blend_ps`.

**Validado ao vivo (blender-mcp):** C (self-patch) = fill mantido + linha cortada ✓; A (cross-object)
= fill mantido ✓; máscara normal (auto-patch OFF) = fill+linha cortados, sem regressão ✓.
**B (occluder eye-icon off) — VALIDADO 2026-06-18** (blender-mcp + amostragem de pixel em render
OpenGL/GP). Com `PartUpper` oculto (`hide_set`+`hide_render`) o matte ainda é aplicado a `PartLower`
(confirma o Mod B / `deg_builder_relations.cc` forçando avaliação do occluder oculto), e com
auto-patch ON o fill na região do matte volta a ser idêntico ao fill sem máscara (`.77,.55,.55`)
enquanto a linha fica cortada (`.22` vs preto) — corta só a linha, mantém o fill. Sem regressão na
região livre. Fix completo commitado na `feat/gp-masks` (commit `da8a00cc64f`).
Limitação menor: borda do stroke na costura é corte binário (leve aliasing de ~1px). ADR:
`docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`.
