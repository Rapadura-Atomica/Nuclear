# Auto-Patch nativo — fidelidade ao Toon Boom Harmony

> **Escopo:** este documento relata **como o auto-patch nativo opera hoje** (lido do código,
> não do que outros docs afirmam) e **onde ele diverge** do Auto Patch do Toon Boom Harmony,
> com uma lista priorizada do que modificar. Complementa `nuclear_auto_patch_nativo.md`
> (inventário/estado de git — vive na branch `integration/1.1-ui-squash`) — aqui o foco é
> **mecânica e fidelidade**.
>
> **Onde vive o código:** branch **`feat/gp-masks`** (separada do commit fundido `90ac371` em
> 2026-06-17 — ver o ADR `docs/decisions/2026-06-17-separar-contour-e-masks.md`, na branch
> `integration/1.1-ui-squash`). Os `file:line`
> abaixo referem-se a essa branch.

---

> ## ✅ ATUALIZAÇÃO 2026-06-19 — leia isto primeiro
>
> A análise original (§1–§5) foi escrita em **17/06 de manhã, por leitura de código, antes do
> build**. Desde então as quatro modificações foram **implementadas, compiladas, validadas ao
> vivo e commitadas**, mais duas melhorias novas. **O status "B e C têm bug de render" da §4/§5
> está OBSOLETO — foi RESOLVIDO.** Quadro atual, fonte = código + validação por amostragem de
> pixel (ver [`nuclear_auto_patch_validation_b_2026-06-18.md`](nuclear_auto_patch_validation_b_2026-06-18.md)
> e [`nuclear_auto_patch_bc_followup.md`](nuclear_auto_patch_bc_followup.md)):
>
> | Mod | O que é | Status | Commit |
> |---|---|---|---|
> | **A** | Matte só do FILL do occluder (corte pela cor) | ✅ pronto e validado | `897dcc4f519` |
> | **B** | Occluder **oculto** ainda remenda (depsgraph + sync diferido) | ✅ pronto e validado (pixel) | `897dcc4f519` |
> | **C** | Self-patch (matte = outro layer do mesmo objeto) | ✅ pronto e validado | `897dcc4f519` |
> | **D** | Aviso de ordem de desenho (peças coplanares) | ✅ pronto e validado | `897dcc4f519` |
> | **mutual** | Operador cria a máscara **recíproca** no occluder (corte mútuo da junta) | ✅ pronto | `4056b50cf4e` |
> | **depth-fix** | Matte cross-object com os **dois objetos visíveis** agora corta | ✅ pronto | `e3a4f264bf2` |
>
> **A causa do bug de B/C NÃO era profundidade** (a hipótese da §5 foi refutada ao vivo). Era o
> **passe de layer-blend (`blend_ps`) re-aplicando o matte** ao layer inteiro depois do passe de
> geometria — o `gp_mask_bypass` furava a máscara no passe certo, mas o blend cortava o fill de
> volta. Fix de 3 linhas (`blend_auto_patch`). Detalhe completo na §5-bis abaixo e no ADR
> `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`.
>
> **Limitações que restam** (ver §5-bis): (1) o depth-skip do depth-fix só foi aplicado ao
> caminho cross-object (`fill_ps`), **não** ao same-object — *self-patch com matte visível pode
> precisar do mesmo tratamento (não testado)*; (2) aliasing de ~1px na borda da costura (corte
> binário); (3) **gotcha de produção: o occluder precisa de fill opaco** (a força do matte = a
> opacidade do fill dele); (4) **release**: foi rebuild de dev — para empacotar no updater, build
> limpo + bump de `NUCLEAR_BUILD`.

---

## 1. Como opera hoje (ponta a ponta)

### 1.1 Autoria — operador de um clique
`GREASE_PENCIL_OT_auto_patch` (C), em
`source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc:1318` (exec), `:1372`
(registro do tipo), `:1410` (append). UI em
`scripts/startup/bl_ui/properties_data_grease_pencil.py:82`.

Fluxo: seleciona **dois objetos GP** — ativo = parte a remendar, outro = **occluder**. O
operador cria um `LayerMask` no layer ativo:
- `mask->object = occluder`; `layer_name = ""` (= silhueta do **objeto inteiro**);
- flags `GP_LAYER_MASK_INVERT | GP_LAYER_MASK_AUTO_PATCH`;
- limpa `GP_LAYER_TREE_NODE_HIDE_MASKS` no layer (liga as masks — o opt-in some neste caminho);
- guarda anti-duplicata por occluder.

> **Props novas (Mods C e mutual):** o operador ganhou `matte_source` (OCCLUDER/SELF) + `layer`
> para o self-patch, e o booleano `mutual` (cross-object) que cria também a máscara recíproca
> no occluder (B→A) para limpar a junta nos dois sentidos. Ver §5-bis.

### 1.2 Modelo de dado
`GreasePencilLayerMask` com `object` (Object* matte; null = mesmo objeto), `layer_name` (filtro:
vazio = objeto todo / nome de layer / nome de grupo) e flags. Vive em folhas **e** grupos/pegs.
Flags relevantes em `source/blender/makesdna/DNA_grease_pencil_types.h`:
`GP_LAYER_MASK_AUTO_PATCH` (`:198`), `GP_LAYER_TREE_NODE_HIDE_MASKS` (`:257`).
RNA: `use_auto_patch` em `source/blender/makesrna/intern/rna_grease_pencil.cc:933`.

### 1.3 Render — cache/sync (`gpencil_cache_utils.cc`)
- `apply_mask_list` (`:394`) percorre as masks do layer **+ as dos grupos/pegs ancestrais**
  (herança); gate por `use_masks()` em `:331`.
- Mask **mesmo-objeto** → seta bits em `mask_bits` (bitmap de 256 por objeto).
- Mask **cross-object** (`mask->object != self`) → `tgp_layer->mattes.append({object, node_name,
  invert})` (`:~409`).
- Flag `AUTO_PATCH` → `tgp_layer->auto_patch = true` (`:402`).
- Mapa `Instance.object_to_tgp` indexa todo objeto avaliado (`:123`) p/ o matte achar os passes
  do occluder no draw.
- **Mod A:** os mattes cross-object passam a submeter só os drawcalls de **FILL** (passe `fill_ps`
  paralelo por `tLayer`), então o corte segue a borda da **cor**, não da silhueta inteira.

### 1.4 Render — draw (`gpencil_engine_c.cc:draw_mask`)
- Bind do `mask_fb`, clear (cor branca), render no buffer de máscara:
  - mask layers do próprio objeto (own + herdadas), com state-machine de inversão;
  - **mattes cross-object**: `object_to_tgp.lookup` acha o tObject do occluder e
    renderiza seus passes de fill (filtrando por objeto todo / 1 layer / descendentes de um grupo).
- A arte do layer é desenhada; o fragment shader descarta onde a máscara é baixa
  (`shaders/gpencil_frag.glsl`).
- **Mod B:** `sync_referenced_mattes` faz um segundo passe `cache_only` que cacheia o occluder
  **oculto** em `object_to_tgp` sem desenhá-lo; relação de depsgraph em `deg_builder_relations.cc`
  força a avaliação da geometria do occluder oculto.

### 1.5 O pulo do gato — "stroke-only" (a costura)
Quando `auto_patch` está ligado, o engine empurra o push-constant `gp_mask_bypass`:
**FILL → 1** (ignora a máscara), **STROKE → 0** (aplica) — `gpencil_engine_c.cc`;
declarado em `shaders/infos/gpencil_infos.hh`; consumido em `gpencil_frag.glsl`.

**Efeito:** mask invertida + occluder + stroke-only ⇒ **só a LINHA** da parte ativa é cortada
onde o occluder sobrepõe (some a linha dupla na junta); o **fill continua**; o occluder
desenha por cima. Comentário do operador resume: *"the line shows only where the occluder is
NOT, and AUTO_PATCH so only the stroke (not the fill) is cut."*

> ⚠️ **Mas isso sozinho não bastava** — o passe de **blend do layer** re-aplicava o matte e
> cortava o fill de volta. Esse era o bug de B/C. Ver §5-bis (resolvido).

---

## 2. Como o Harmony faz (referência)

- Pilar: separação **Line Art / Colour Art** (+ Overlay/Underlay) que todo desenho do Harmony
  tem.
- O Auto Patch usa o **Colour Art (fill)** pra gerar um *matte* que **cobre a linha** da peça
  adjacente na junta. Patch **aditivo**: a cor da peça de cima tampa o contorno da de baixo.
- É um **nó** ligado na hierarquia → funciona pela **conexão**, independente da visibilidade da
  fonte.
- Permite patchear a linha de um desenho com o **próprio colour art** (self-patch de junta
  interna), não só de uma peça vizinha.

---

## 3. Divergências (no estado de análise 17/06; coluna "agora" = pós Mods A–D)

| # | Harmony | Nuclear (análise 17/06) | Status agora |
|---|---|---|---|
| 1 | Matte = região do **Colour Art (fill)** | Matte = **silhueta inteira** (linha+fill) | ✅ **fechada pela Mod A** — matte só do fill, corte segue a cor |
| 2 | **Aditivo** (cor cobre a linha) | **Subtrativo** (apaga a linha de baixo) | ➖ ainda subtrativo, mas a costura fica limpa; **Mod D** avisa quando a ordem de desenho é ambígua |
| 3 | **Self-patch** com o próprio colour art (1 desenho) | Exige **dois objetos** GP | ✅ **fechada pela Mod C** — `matte_source=SELF` + `layer` |
| 4 | Por **conexão de nó**, fonte pode estar oculta | Depende do occluder **visível/avaliado** | ✅ **fechada pela Mod B** — depsgraph força avaliação do occluder oculto |

**O que já estava fiel:** o resultado-alvo (sumir linha dupla na junta, manter fill); a relação
"peça de baixo tem a linha escondida pela de cima"; e distinguir linha/fill **por tipo de
drawcall** (mais ergonômico que exigir camadas separadas como no Harmony).

---

## 4. Modificações candidatas — TODAS IMPLEMENTADAS

> **STATUS (2026-06-19): A, B, C, D + mutual + depth-fix IMPLEMENTADAS, VALIDADAS e COMMITADAS na
> `feat/gp-masks`.** O bloco abaixo era o plano; ver §5-bis para o resultado de cada uma.

- **A. Matte só do FILL do occluder** — ✅ feito (`fill_ps` paralelo por `tLayer`). Corte segue a
  borda da cor, igual Harmony. *Maior impacto visual.*
- **B. Relação de depsgraph** matte→alvo, p/ funcionar com o occluder oculto — ✅ feito
  (`deg_builder_relations.cc` + `sync_referenced_mattes`). Validado por amostragem de pixel.
- **C. Self-patch / matte de origem arbitrária** — ✅ feito (props `matte_source`/`layer`).
- **D. Garantir/expor a ordem de desenho** do occluder na frente — ✅ feito (aviso não-bloqueante
  quando coplanar e sem "In Front").

---

## 5. (HISTÓRICO) Diagnóstico do bug B/C — hipótese de depth REFUTADA

> Esta seção é mantida como **registro histórico**. A hipótese de "hardware depth test" abaixo
> foi **refutada ao vivo** (debug de cor no frag); a causa real está na §5-bis. Preservada porque
> a sequência diagnóstica é instrutiva — mas **não é mais o estado do código.**

Sintoma original (17/06): o matte recortava o **layer inteiro (fill + stroke)** em vez de só o
stroke. O que foi descartado como causa (provado ao vivo): não era o flag (`auto_patch=1` e
`gp_mask_bypass=1` chegavam ao render); não era o roteamento (`mattes` vs `mask_bits`); não era o
depth-test *manual* do frag ("In Front" não consertava). A hipótese então levantada — **teste de
profundidade de HARDWARE** ligado à mesma-objetividade — parecia forte mas **estava errada**.
Handoff detalhado: [`nuclear_auto_patch_bc_followup.md`](nuclear_auto_patch_bc_followup.md).

---

## 5-bis. RESOLUÇÃO (2026-06-17 → 06-19) — o que de fato consertou

### Causa-raiz real (B/C): o passe de layer-blend
Layer mascarado é composto em **dois** momentos: (1) **geometria** (`gpencil_frag.glsl`) — o
`gp_mask_bypass` faz o fill ignorar a máscara e o stroke ser descartado; até aqui o fill é mantido.
(2) **blend do layer** (`gpencil_layer_blend_frag.glsl`) — compõe fazendo `color * mask` e
**re-aplica o matte** ao layer inteiro, cortando o fill de volta. Por isso o bypass "chegava ao
fill" mas no **passe errado**, e depth/In-Front nunca ajudavam.

**Fix (3 linhas):** para layers auto-patch o blend ignora o matte (`mask = 1.0`):
- `shaders/infos/gpencil_infos.hh`: push-constant `blend_auto_patch` na create-info `gpencil_layer_blend`.
- `shaders/gpencil_layer_blend_frag.glsl`: `mask = (blend_auto_patch != 0) ? 1.0 : texture(mask_buf)`.
- `gpencil_cache_utils.cc`: empurra `blend_auto_patch = tgp_layer->auto_patch` no `blend_ps`.

**Validado (amostragem de pixel, vista TOP, occluder oculto):** com auto-patch ON o fill na região
do matte volta a ser idêntico ao fill sem máscara (`.77,.55,.55`) e só a linha fica cortada (`.22`
vs preto). Sem regressão. Commit `897dcc4f519`. ADR `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`.

### Modo `mutual` (06-19, `4056b50cf4e`)
O operador ganhou a prop `mutual` (cross-object): além da máscara A→B, cria a **recíproca** B→A no
occluder (`auto_patch+invert`, matte = objeto ativo inteiro; alvo = layer de mesmo nome, fallback
ativa; anti-duplicata). Resultado: as **duas** linhas da junta somem na zona comum. (Rodar o
operador manualmente nos dois sentidos produz o mesmo.)

### Fix do depth test cross-object visível (06-19, `e3a4f264bf2`)
**Sintoma:** a matte cross-object só cortava com o occluder **OCULTO**; com a peça-matte
**VISÍVEL** (dois braços sobrepostos, o caso real) a costura não era cortada. **Causa:** o
`gpencil_frag.glsl` faz um teste manual `if (gl_FragCoord.z > scene_depth) discard`; a matte
(silhueta de fill do occluder) passa por esse shader no mask buffer e, com o occluder visível, sua
geometria está em `gp_scene_depth_tx` → o depth descarta a **própria matte** na zona de overlap →
mask vazio → stroke não cortado. **Fix:** push-constant `gp_in_mask_pass` (=1 no `fill_ps`
submetido como matte, =0 no passe normal); o frag pula o scene-depth-test quando =1. Cirúrgico — o
desenho normal mantém o depth test. Validado (processo fresco, TOP): ambos-visíveis **0→573 px**;
casos oculto inalterados; confirmado numa junta real de antebraço/braço.

> **Limitação conhecida:** o depth-skip só foi aplicado ao caminho cross-object (`fill_ps`), **não**
> ao same-object (`mask_bits`/`geom_ps`) — *self-patch com matte VISÍVEL pode precisar de tratamento
> análogo (não testado)*.

---

## 6. Pendências de validação / limitações restantes

- [x] **Build** da `feat/gp-masks` — feito (com A–D + mutual + depth-fix). Pegadinha: o git
      worktree não carrega `lib/`; symlinkar `lib/linux_x64` da árvore principal.
- [x] **Rodar num caso real e validar A/B/C/D ao vivo** — feito (amostragem de pixel + junta de
      personagem). Ver os docs de validação.
- [ ] **Self-patch com matte VISÍVEL** — o depth-skip do cross-object pode precisar de análogo no
      caminho same-object (não testado). Self-patch com a configuração validada funciona.
- [ ] **Aliasing da costura (~1px)** — corte binário na borda do stroke; melhoria opcional (AA).
- [ ] **Conteúdo real variado** — fill com gradiente/textura, múltiplos layers, stroke de espessura
      variável (sentir aliasing e polaridade do `invert` no fluxo real).
- [ ] **Release** — foi rebuild de dev; para empacotar no updater do Nuclear, **build limpo + bump
      de `NUCLEAR_BUILD`** (ver CLAUDE.md do fork).

> **Gotcha de produção (importante para quem usa):** a força do matte = **opacidade do fill do
> occluder**. Dentro do occluder o mask vale `1 - alpha_fill`; o corte do stroke só dispara com
> `mask < 0.001`. Occluder precisa de **fill opaco e fechado** — fill semi-transparente → matte
> fraco → **não corta**. Casa com o Harmony (o Colour Art define o matte).

---

## 7. Referências

- [`nuclear_auto_patch_bc_followup.md`](nuclear_auto_patch_bc_followup.md) — diagnóstico + resolução do bug B/C (RESOLVIDO).
- [`nuclear_auto_patch_validation_b_2026-06-18.md`](nuclear_auto_patch_validation_b_2026-06-18.md) — validação por amostragem de pixel (A/B/C) + errata 06-19 (mutual/depth-fix).
- `nuclear_auto_patch_nativo.md` — inventário e estado de git (na branch `integration/1.1-ui-squash`).
- [`nuclear_gp_masks.md`](nuclear_gp_masks.md) / [`nuclear_gp_masks_howto.md`](nuclear_gp_masks_howto.md) — docs das masks.
- ADR `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md` — o fix do blend (causa-raiz real).
- ADR `docs/decisions/2026-06-17-separar-contour-e-masks.md` — separação do commit `90ac371` (branch `integration/1.1-ui-squash`).
- Memória do projeto: `nuclear-gp-masks-pegs`, `nuclear-auto-patch-harmony-fidelity`, `auto-patch-gp-harmony`.
