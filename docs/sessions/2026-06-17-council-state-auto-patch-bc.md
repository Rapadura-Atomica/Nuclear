---
tier: 3
specialist: general
task: "Resolver o bug de render do auto-patch GP (self-patch C e occluder oculto B): o fill é cortado junto com a linha onde o matte cobre, em vez de só a linha. Branch feat/gp-masks (worktree nuclear-gpmasks)."
date: "2026-06-17"
---

## Investigation

## 🔍 Investigation Report

### Project Context
O auto-patch nativo do Nuclear (fidelidade ao Toon Boom Harmony) tem 4 mods na branch
`feat/gp-masks`. **A (matte fill-only)** e **D (aviso coplanar)** funcionam ao vivo. **B
(occluder oculto)** e **C (self-patch)** têm um bug de RENDER: onde o matte cobre, o auto-patch
deveria cortar **só a linha** do layer remendado e **manter o fill** — mas corta o layer inteiro
(fill + linha). A instrumentação já provou (ver `nuclear_auto_patch_bc_followup.md` §"descartado")
que o `gp_mask_bypass=1` É emitido no drawcall de fill, o flag `auto_patch` chega ao render, e que
rotear self por `mask_bits` em vez de `mattes` NÃO resolve. Logo o bug **não está no roteamento da
máscara nem no caminho do bypass de máscara** — está em algum **teste de profundidade** que descarta
o fragmento de fill antes/depois do teste de máscara.

### Mapa do pipeline de render (fatos de código confirmados)
O fragment shader `gpencil_frag.glsl` aplica, em ordem, **três** descartes ao fragmento de fill:
1. **`frag_color.a < 0.001` → discard** (`:109-112`) — opacidade/holdout.
2. **Teste de profundidade MANUAL** (`:118-123`): `if (gl_FragCoord.z > scene_depth) discard`,
   onde `scene_depth = texture(gp_scene_depth_tx, uvs)`. É o teste de compositing GP-vs-cena.
   Desabilitado quando "In Front" troca `depth_tex` por `dummy_depth` (`cache_utils :529`).
3. **Teste de MÁSCARA** (`:129-135`): `if (mask < 0.001) discard` — **pulado** quando
   `gp_mask_bypass != 0`. É exatamente este que o auto-patch fura para o fill (`object_sync_do`
   `:621-624` empurra `gp_mask_bypass=1` no fill; `:638-641` empurra `0` no stroke). **Comprovado
   funcionando** (caso A).
4. Por fim escreve `gl_FragDepth = gp_interp_flat.depth` (constante por layer) (`:141-146`).

Estado do `geom_ps` (`cache_utils :532-536`): `WRITE_COLOR | WRITE_DEPTH | BLEND_ALPHA_PREMUL`
+ **`DRW_STATE_DEPTH_GREATER`** (modo 2D). O depth buffer do objeto é **limpo uma vez por objeto**
em `draw_object` (`engine_c :950`, clear para 0.0 em 2D). Os layers são desenhados em ordem, cada um
com `gl_FragDepth` crescente → camadas de cima passam no `DEPTH_GREATER` sobre as de baixo.

### A máscara em si está CORRETA (não é a causa)
O matte é renderizado num framebuffer **separado** (`mask_fb`/`mask_tx`) por `draw_mask`
(`engine_c :839-937`): caminho same-object `mask_bits` (`:860-875`) e caminho cross-object/self
`mattes` (`:880-928`, submete o **`fill_ps`** do occluder — o matte fill-only do Mod A). O stroke do
layer remendado É cortado corretamente nos casos B/C → **a textura de máscara está correta**. Como o
fill some mesmo com o teste de máscara comprovadamente pulado, **o fill não está sendo descartado
pela máscara** — só sobram o teste #2 (manual, contra `scene_depth`) e o teste de profundidade de
**hardware** (`DEPTH_GREATER` no buffer do objeto) como suspeitos.

### Relevant Files
- `…/gpencil/shaders/gpencil_frag.glsl` — os 3 descartes (`:109,:118-123,:129-135`) + write de
  `gl_FragDepth` (`:141-146`). É aqui que se faz o **debug de cor** para confirmar a causa.
- `…/gpencil/gpencil_cache_utils.cc` — `grease_pencil_layer_cache_add`: estado do geom_ps
  (`:529-536`, `DEPTH_GREATER` + `WRITE_DEPTH` + bind do `gp_scene_depth_tx`), roteamento self/cross
  (`:406-435`), construção do `fill_ps` (`:566-583`). É onde mora qualquer ajuste de **DRWState**.
- `…/gpencil/gpencil_engine_c.cc` — `draw_object` (`:939-991`, clear de depth :950, loop de layers,
  `draw_mask` :958, merge p/ `scene_fb` :985-988); `object_sync_do` (push do `gp_mask_bypass`
  :617-645); `draw_mask` (:839-937); `sync_referenced_mattes` (Mod B, :677-728).
- `…/gpencil/gpencil_engine_private.hh` — `tLayer.fill_ps`, `tLayer.auto_patch`, `tMatteRef`,
  `Instance.referenced_mattes`.

### Diferencial CRÍTICO entre o caso que funciona (A) e os que quebram (B/C)
Em **A (cross-object visível)**, o occluder é um **objeto separado**: tem seu próprio `draw_object`
(depth limpo só pra ele) e sua profundidade é mesclada em `scene_fb` via `merge_depth_ps` (`:985-988`)
**depois** que o objeto remendado já desenhou — então o occluder **não** está no `scene_depth` na hora
em que o fill remendado faz o teste manual #2. → fill sobrevive. ✅
Em **C (self)**, matte e remendado partilham o **mesmo `draw_object`/mesmo depth buffer**; o
layer-matte (opacidade 0 por ser usado como máscara, `cache_utils :356`) é desenhado **antes**.
Em **B (occluder oculto)**, o occluder é cacheado `cache_only` (`sync_referenced_mattes`) e **nunca**
desenhado no buffer do objeto → não entra no `scene_depth`, igual… mas mesmo assim quebra.

### Causas-raiz candidatas (ranqueadas, com evidência de código)
1. **(hipótese do doc) Depth de HARDWARE same-object.** No self, o layer-matte escreveria depth no
   buffer do objeto e o `DEPTH_GREATER` descartaria o fill do remendado. **Ponto fraco que encontrei:**
   o layer-matte renderiza com **opacidade 0** e é descartado em `:109` *antes* de escrever
   `gl_FragDepth` — então talvez **não** escreva depth, enfraquecendo esta hipótese. Precisa de
   confirmação (alguns drivers escrevem depth mesmo com discard tardio; e a ordem layer/`DEPTH_GREATER`
   pode falhar fill-vs-stroke do mesmo layer, que têm `gl_FragDepth` igual).
2. **(meu lead, igualmente forte) Teste MANUAL contra `gp_scene_depth_tx` (`:118-123`).** Explica o
   diferencial A-funciona/B-C-quebram melhor que "hardware": A escreve scene-depth tarde demais pra se
   auto-ocluir; B/C têm a geometria do matte no mesmo buffer/sem merge. "In Front" *deveria* matar este
   teste — mas o doc diz que In Front não consertou; **porém** In Front só troca o bind do **geom_ps**,
   e é preciso confirmar que troca também no **fill_ps** e que o `dummy_depth` realmente anula o teste.
3. **Comportamento de write-de-depth do matte opacidade-0.** Sub-caso de (1): confirmar empiricamente
   se um layer usado-como-máscara escreve no depth do objeto.

> O `nuclear_auto_patch_bc_followup.md` já lista a direção de fix mais provável e, com razão, **exige
> um experimento de confirmação antes de mexer no depth-state** (debug de cor no frag). A investigação
> confirma que isso é o certo: há **duas** hipóteses fortes e mutuamente excludentes (#1 hardware vs #2
> manual), e a escolha do fix depende de qual o experimento eliminar.

### Reusable Code
- **`fill_ps`** (matte fill-only, Mod A) — já existe e é o veículo correto para qualquer estado de
  depth especial do auto-patch; um fix de DRWState entra aqui sem tocar o `geom_ps` normal.
- **`gp_mask_bypass`** (push-constant + uniform no frag) — o padrão "fura um teste só para o fill" já
  está estabelecido; um eventual `gp_depth_bypass` seguiria exatamente o mesmo molde.
- Instrumentação `getenv("NUCLEAR_DEBUG_AUTOPATCH")` + `fprintf(stderr,…)` (já usada e removida) —
  reaproveitável para o passo de diagnóstico.

### Impacted Dependencies
Mexer no DRWState/depth do fill do auto-patch afeta **só** os drawcalls com `auto_patch=1` se for
feito no `fill_ps`/condicionado ao flag. Risco de regressão recai sobre o **empilhamento normal de
layers 2D** (`DEPTH_GREATER`) e o **compositing GP-vs-cena 3D** (`merge_depth_ps`/`gp_scene_depth_tx`)
se o estado for trocado no geom_ps global.

### Identified Risks
- **Regredir o stacking de layers 2D:** mitigar aplicando qualquer mudança de depth-state APENAS ao
  caminho auto-patch (flag `auto_patch`/`fill_ps`), nunca ao geom_ps de layers normais.
- **Quebrar compositing GP↔3D:** se a causa for o teste manual #2, NÃO desligá-lo globalmente; furá-lo
  só para o fill auto-patch (novo uniform), espelhando o padrão `gp_mask_bypass`.
- **Driver-dependência (depth com discard tardio):** o experimento de cor deve rodar no mesmo
  hardware-alvo (RX 580 / Mesa) para não confirmar uma causa que só existe noutro driver.

### Gaps / What Needs to Be Created
1. Um **patch de diagnóstico** temporário no frag (saída de cor = resultado de cada teste de depth) —
   não existe; precisa ser escrito e depois removido.
2. Conforme o resultado: ou um **`gp_depth_bypass`** (uniform + push) análogo ao mask bypass, ou um
   ajuste de **DRWState do `fill_ps`** (ex.: `DEPTH_ALWAYS`/sem `WRITE_DEPTH` no fill auto-patch).
3. Re-habilitar/validar **B** depois que **C** estiver correto (B compartilha o caminho de render).

## Plan

## 📐 Implementation Plan

### Chosen Approach
**Confirmar-depois-corrigir, em duas fases.** Primeiro um experimento de diagnóstico mínimo (debug de
cor no `gpencil_frag.glsl` + contadores) que decide, sem ambiguidade, qual dos dois testes de
profundidade descarta o fill no caso same-object. Só então aplicar o fix **mínimo** correspondente,
sempre restrito ao caminho `auto_patch`/`fill_ps`, validando ao vivo via blender-mcp na cena
`nuclear_autopatch_debug.blend` (objeto `SelfTest`).

### Why This Approach
A investigação isolou o bug em **um de dois testes de profundidade** (#1 hardware `DEPTH_GREATER`
no buffer do objeto, ou #2 manual contra `gp_scene_depth_tx`) e mostrou que as duas hipóteses
explicam parcialmente o diferencial A-funciona/B-C-quebram, mas levam a **fixes diferentes e
incompatíveis**. Mexer no depth-state às cegas arrisca regredir o stacking de layers ou o compositing
GP↔3D (ambos dependem desses mesmos estados). O próprio follow-up exige o experimento primeiro — a
investigação confirma que é o caminho de menor risco. Reaproveitamos o `fill_ps` e o molde
`gp_mask_bypass` para manter o fix cirúrgico (smallest sufficient change).

### Execution Order
1. **FASE 0 — Diagnóstico (não-destrutivo).**
   1a. No `gpencil_frag.glsl`, sob `#ifdef`/uniform de debug, pintar o fill auto-patch de cor
       distinta conforme **qual** teste o descartaria: ex. emitir VERMELHO se reprovaria no teste
       manual (#2), VERDE se passaria os dois — sem chamar `gpu_discard_fragment()` no fill auto-patch.
       Complementar com `fprintf(stderr,…)` guardado por `NUCLEAR_DEBUG_AUTOPATCH` contando descartes.
   1b. Build (distrobox `blenderdev`, ver setup) e rodar a cena `SelfTest` via blender-mcp
       (`get_viewport_screenshot`). **Decisão:**
       - Fill fica VERMELHO na região do matte → **causa = teste manual #2** (`scene_depth`). → Passo 2A.
       - Fill some mesmo sem o discard manual → **causa = hardware `DEPTH_GREATER`**. → Passo 2B.
       - Confirmar de passagem se o layer-matte opacidade-0 escreve depth (candidata #3).
2. **FASE 1 — Fix mínimo (um dos dois ramos).**
   - **2A (causa = teste manual #2):** introduzir um **`gp_depth_bypass`** (uniform no frag + push no
     `object_sync_do`), idêntico em molde ao `gp_mask_bypass`, que pule **apenas** o bloco `:118-123`
     **apenas** no fill auto-patch. NÃO desligar o teste para layers normais nem para o stroke.
   - **2B (causa = hardware depth):** dar ao **`fill_ps`** do auto-patch um DRWState que não seja
     ocluído pelo matte do mesmo objeto — ex. remover `WRITE_DEPTH` do fill auto-patch e/ou usar
     `DEPTH_ALWAYS` só nesse drawcall — preservando `DEPTH_GREATER` no geom_ps normal. Avaliar se o
     fill precisa parar de escrever depth para não auto-ocluir o stroke do mesmo layer.
3. **FASE 2 — Validar C** ao vivo (toggle `use_masks` no `SelfTest`): fill amarelo inteiro + linha
   cortada. Conferir que A e D **não regrediram** (cena cross-object visível + aviso coplanar).
4. **FASE 3 — Re-habilitar e validar B** (occluder oculto): como B compartilha o caminho de render
   (matte→`fill_ps`→mask), o fix de C deve cobri-lo; validar `sync_referenced_mattes` (occluder
   eye-off) e as premissas runtime do guia de fidelidade §5 (ObjectRef sintético, key por `orig_id`).
5. **FASE 4 — Limpeza:** remover todo o código de debug da Fase 0; `make format`; rodar
   `check_spelling_c`/`check_clang_array` nos arquivos tocados.

### Files to Create
- (temporário) bloco de debug dentro de `gpencil_frag.glsl` — **removido na Fase 4**, não é arquivo novo.
- (se ramo 2A) declaração do uniform `gp_depth_bypass` no create-info de `gpencil_geometry`
  (`infos/gpencil_infos.hh`) — análogo a `gp_mask_bypass`.

### Files to Modify
- `…/gpencil/shaders/gpencil_frag.glsl` — Fase 0 (debug) e, se 2A, o gate do teste manual.
- `…/gpencil/gpencil_engine_c.cc` `object_sync_do` — se 2A, push do `gp_depth_bypass` no fill.
- `…/gpencil/gpencil_cache_utils.cc` `grease_pencil_layer_cache_add` — se 2B, DRWState do `fill_ps`.
- `…/gpencil/infos/gpencil_infos.hh` — se 2A, uniform novo.

### Files NOT to Touch
- O **`geom_ps`** de layers normais (estado `DEPTH_GREATER`/`WRITE_DEPTH` em `cache_utils :532-536`):
  qualquer mudança ali regride o empilhamento de TODOS os layers GP. O fix vive no `fill_ps`/flag.
- `merge_depth_ps` / pipeline `scene_fb` (`engine_c :985-988`): mexer ali afeta compositing GP↔3D.
- `draw_mask` e o roteamento `mattes`/`mask_bits`: já provado correto; não é a causa.

### Resulting Interface / Contract
Nenhuma mudança de DNA/RNA, nenhuma propriedade nova de usuário (props `matte_source`/`layer` do
operador já existem). Internamente: ou um novo uniform `gp_depth_bypass` (ramo 2A), ou um DRWState
distinto no `fill_ps` (ramo 2B). O contrato de usuário do auto-patch (Art masca Matte com
auto_patch+invert) permanece idêntico — só o resultado de render é corrigido.

### Required Tests
- **C (self):** `SelfTest` com `use_masks` ON → fill amarelo inteiro + linha cortada sob o matte; OFF
  → ambos inteiros. (Validação visual blender-mcp; não há gtest de render GP prático aqui.)
- **A (não-regressão):** dois objetos, occluder fill opaco com Z distinto → fill mantido, linha cortada.
- **D (não-regressão):** matte coplanar → aviso ainda dispara.
- **B (occluder oculto):** occluder com eye-icon off → recorta como o visível.
- Estática: `make format`, `check_spelling_c`, `check_clang_array` nos arquivos tocados.

### Plan Risks
- **Experimento confirma causa só no driver-alvo:** rodar a Fase 0 na RX 580/Mesa (o mesmo HW de uso).
- **Fill que para de escrever depth (2B) pode mudar a interação fill↔stroke do mesmo layer:**
  validar explicitamente que a linha continua por cima do fill no `SelfTest`.
- **B não coberto pelo fix de C:** se a Fase 3 mostrar que B ainda quebra, ele tem componente própria
  (cache_only/scene-depth ausente) e vira um sub-ciclo — sinalizar ao usuário, não forçar.

### ❌ Discarded Alternative: Desligar o teste manual de profundidade globalmente
- **O que seria:** remover/curto-circuitar `:118-123` no frag para todos os layers GP.
- **Por que descartado:** quebra o compositing de GP atrás/à frente de geometria 3D — regressão ampla
  e exatamente o tipo de mudança difícil de reverter que o Tier 3 manda evitar.

### ❌ Discarded Alternative: Forçar "In Front" no objeto remendado como "fix"
- **O que seria:** ligar `is_in_front` para trocar `scene_depth_tx`→`dummy_depth`.
- **Por que descartado:** o doc já testou ao vivo e **não conserta**; e mudaria semântica de
  compositing do objeto inteiro. (Mas o *porquê* de não consertar é um dado do experimento da Fase 0.)

### ❌ Discarded Alternative: Rotear o self-patch por `mask_bits` (same-object bitmap)
- **O que seria:** tratar o matte same-object pelo caminho de bitmap em vez de `mattes`.
- **Por que descartado:** **já tentado e revertido** (doc §"descartado" #2) — provou que o bug é a
  same-objetividade no depth, não o roteamento da máscara.

## 📄 ADR Draft: Corrigir o corte indevido do fill no auto-patch same-object (self-patch e occluder oculto)

**Context**: O auto-patch GP do Nuclear deve cortar só a linha do layer remendado sob o matte,
mantendo o fill (estilo Harmony). Funciona quando o matte é um objeto separado e visível (A), mas
corta o fill inteiro quando o matte é outro layer do mesmo objeto (C, self-patch) ou um occluder
oculto cacheado em diferido (B). Já está provado que o bypass de **máscara** (`gp_mask_bypass`) chega
ao fill e funciona; o fill é descartado por um **teste de profundidade** — resta decidir entre o
teste manual contra `gp_scene_depth_tx` (frag `:118-123`) e o teste de hardware `DEPTH_GREATER` no
buffer do objeto. As duas hipóteses levam a fixes diferentes e incompatíveis.

**Decision**: Adotar um fluxo **confirmar-depois-corrigir**: um experimento de debug-de-cor no
fragment shader decide a causa; o fix subsequente é mínimo e restrito ao caminho `auto_patch`/`fill_ps`
— ou um novo `gp_depth_bypass` (se a causa for o teste manual), ou um DRWState de depth distinto no
`fill_ps` (se for o teste de hardware) — sem tocar o `geom_ps` de layers normais nem o compositing
GP↔3D.

**Consequences**: B e C passam a manter o fill como A. Custo: um experimento descartável e mais um
uniform OU um estado de pass adicional, ambos seguindo padrões já existentes (baixo risco, reversível).
Fica mais fácil estender o auto-patch no futuro (padrão "furar um teste só para o fill" consolidado).
Fica como ponto de atenção a dependência de driver no comportamento de depth (validar na RX 580/Mesa)
e a possibilidade de B precisar de um ajuste próprio se o fix de C não o cobrir.

**Alternatives considered**: desligar o teste manual globalmente (rejeitado: quebra compositing);
forçar In Front (rejeitado: já provado que não conserta); rotear self por `mask_bits` (rejeitado: já
tentado e revertido).

[Note: the Documenter will finalize and move this to docs/decisions/]
