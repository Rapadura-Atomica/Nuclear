# Auto-Patch nativo — fidelidade ao Toon Boom Harmony

> **Escopo:** este documento relata **como o auto-patch nativo opera hoje** (lido do código,
> não do que outros docs afirmam) e **onde ele diverge** do Auto Patch do Toon Boom Harmony,
> com uma lista priorizada do que modificar. Complementa
> [`nuclear_auto_patch_nativo.md`](nuclear_auto_patch_nativo.md) (inventário/estado de git) —
> aqui o foco é **mecânica e fidelidade**.
>
> **Onde vive o código:** branch **`feat/gp-masks`** (separada do commit fundido `90ac371` em
> 2026-06-17 — ver o ADR `docs/decisions/2026-06-17-separar-contour-e-masks.md`). Os `file:line`
> abaixo referem-se a essa branch.
>
> **Ressalva:** análise por leitura de código. **Não foi rodado** (build da branch pendente).
> Os detalhes finos do Harmony dependem de validação com quem domina a ferramenta.

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

### 1.4 Render — draw (`gpencil_engine_c.cc:draw_mask`, `:742`)
- Bind do `mask_fb`, clear (cor branca), render no buffer de máscara:
  - mask layers do próprio objeto (own + herdadas), com state-machine de inversão;
  - **mattes cross-object** (`:790`): `object_to_tgp.lookup` acha o tObject do occluder e
    renderiza seus passes (filtrando por objeto todo / 1 layer / descendentes de um grupo).
- A arte do layer é desenhada; o fragment shader descarta onde a máscara é baixa
  (`shaders/gpencil_frag.glsl:130`).
- Chamada em `:865-867` (todo layer com `mask_bits`).

### 1.5 O pulo do gato — "stroke-only" (a costura)
Quando `auto_patch` está ligado, o engine empurra o push-constant `gp_mask_bypass`:
**FILL → 1** (ignora a máscara), **STROKE → 0** (aplica) — `gpencil_engine_c.cc:594` e `:607`;
declarado em `shaders/infos/gpencil_infos.hh:73`; consumido em `gpencil_frag.glsl:127-131`.
Campo `auto_patch` da `tLayer` em `gpencil_engine_private.hh:110-112`; structs de matte
(`tMatteRef`) em `:84`, vetor `mattes` em `:104-105`, mapa `object_to_tgp` em `:228-230`.

**Efeito:** mask invertida + occluder + stroke-only ⇒ **só a LINHA** da parte ativa é cortada
onde o occluder sobrepõe (some a linha dupla na junta); o **fill continua**; o occluder
desenha por cima. Comentário do operador resume: *"the line shows only where the occluder is
NOT, and AUTO_PATCH so only the stroke (not the fill) is cut."*

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

## 3. Divergências (acertou o espírito, diverge na mecânica)

| # | Harmony | Nuclear hoje | Impacto |
|---|---|---|---|
| 1 | Matte = região do **Colour Art (fill)** | Matte = **silhueta inteira** (linha+fill, é o `geom_ps` do layer) | Corte segue a borda do **traço**, não da **cor** → pode sobrar meio-traço; menos "limpo" que o Harmony |
| 2 | **Aditivo** (cor cobre a linha) | **Subtrativo** (apaga a linha de baixo) | Visual parecido, mas a continuidade de cor depende da **ordem de desenho** do occluder estar na frente |
| 3 | **Self-patch** com o próprio colour art (1 desenho) | Exige **dois objetos** GP selecionados | Não cobre junta interna de uma peça só, nem matte de layer arbitrário |
| 4 | Por **conexão de nó**, fonte pode estar oculta | Depende do occluder **visível/avaliado** (sem relação de depsgraph; `object_to_tgp` devolve null → silhueta vazia) | Occluder escondido → patch não acontece. Ver `draw_mask` comentário em `gpencil_engine_c.cc:791` |

**O que está fiel:** o resultado-alvo (sumir linha dupla na junta, manter fill); a relação
"peça de baixo tem a linha escondida pela de cima"; e distinguir linha/fill **por tipo de
drawcall** (mais ergonômico que exigir camadas separadas como no Harmony).

---

## 4. Modificações candidatas (fidelidade × esforço)

> **STATUS (2026-06-17): A, B, C e D IMPLEMENTADAS na `feat/gp-masks`** (worktree
> `../nuclear-gpmasks`, **não commitado**). Build isolado da branch valida a compilação das
> quatro (build dir `../build_gpmasks`, distrobox `blenderdev`). **Validação VISUAL ainda
> pendente** — ver §5. Resumo do que cada uma virou em código:
> - **A — feito.** Pass `fill_ps` paralelo por `tLayer` (`gpencil_engine_private.hh`,
>   `gpencil_cache_utils.cc`, `gpencil_engine_c.cc`): os mattes cross-object passam a submeter
>   só os drawcalls de FILL (corte segue a borda da cor). Sem mudança de DNA.
> - **B — feito (premissas runtime pendentes).** Relação de depsgraph matte→alvo em
>   `deg_builder_relations.cc` (`case ID_GP`, modelada no `bevobj`) + segundo passe `cache_only`
>   no engine (`sync_referenced_mattes` em `gpencil_engine_c.cc`) que cacheia o occluder oculto
>   em `object_to_tgp` sem desenhá-lo. `foreach_id` de `mask->object` já existia. Só o runtime
>   confirma se um objeto oculto referenciado tem a geometria GP do drawing avaliada e se o
>   `ObjectRef`/handle sintético é válido.
> - **C — feito.** Operador `GREASE_PENCIL_OT_auto_patch` ganhou props `matte_source`
>   (OCCLUDER/SELF) e `layer`; self-patch (object==ob + AUTO_PATCH) roteado pelo caminho
>   `mattes` (fill-only) em `gpencil_cache_utils.cc`. Sem mudança de DNA (campos já existiam).
> - **D — feito.** Aviso não-bloqueante no operador quando occluder e peça remendada são
>   coplanares (Δz < 1e-4) e o occluder não está "In Front".
>
> Ver ADR [`docs/decisions/2026-06-17-auto-patch-harmony-fidelity.md`](../../docs/decisions/2026-06-17-auto-patch-harmony-fidelity.md).

- **A. Matte só do FILL do occluder** (não a silhueta com linha). Renderizar só os drawcalls de
  fill no mask buffer → o corte segue a borda da **cor**, igual Harmony. *Maior impacto visual.*
- **B. Relação de depsgraph** matte→alvo, p/ funcionar com o occluder oculto. *(Era "robustez";
  com a lente Harmony vira requisito de fidelidade — divergência #4.)*
- **C. Self-patch / matte de origem arbitrária** — permitir matte = próprio fill da peça, ou um
  layer escolhido, não só "segundo objeto". Cobre junta interna (divergência #3).
- **D. Garantir/expor a ordem de desenho** do occluder na frente, senão o aditivo do Harmony
  não se reproduz (divergência #2).

---

## 5. Pendências de validação

- [x] **Build** da `feat/gp-masks` sozinha (prova empírica de compilação). **FEITO (2026-06-17)**
      — inclusive com A–D aplicadas. Pegadinha: o git worktree não carrega `lib/` (é
      `make update`-managed); symlinkar `lib/linux_x64` da árvore principal resolve.
- [ ] **Rodar num caso real** (junta de rig, ex. JulianoHeroi) e comparar o visual com o
      Harmony — agora **pós-implementação**: medir se A (corte pela cor) e o self-patch (C) batem
      com o Harmony, e ajustar.
- [ ] Confirmar a **polaridade da máscara invertida** no resultado renderizado (clear branco +
      matte; o intent documentado é "linha aparece só onde o occluder NÃO está").
- [ ] **Premissas runtime da Mod B** (só confirmáveis rodando): (1) um occluder OCULTO
      referenciado tem a geometria GP do *drawing* avaliada (não só transform); (2) o `ObjectRef`
      sintético + `manager->unique_handle` no segundo passe não viola asserção do Manager;
      (3) `object_to_tgp` chaveado por `orig_id` casa com o `mask->object` guardado.

### Resultado dos testes ao vivo (2026-06-17, via blender-mcp)

- ✅ **Mod A + auto-patch base: FUNCIONA.** Provado ao vivo (toggle A/B do `use_masks`): o stroke
  do layer remendado é cortado onde o fill do occluder sobrepõe, o fill é mantido. A polaridade da
  máscara invertida está **correta** para occluder visível.
- ⚠️ **GOTCHA importante — força do matte = OPACIDADE do fill do occluder.** O matte vem do canal
  reveal com blend alpha-premult: dentro do occluder o mask vale `1 - alpha_fill`. O corte do stroke
  só dispara quando `mask < 0.001` (`gpencil_frag.glsl:131`), então o occluder precisa de fill
  **opaco** (alpha ~1). Com fill semi-transparente o matte fica fraco (~0.55) e **não corta** — foi o
  que mascarou o teste inicial. Casa com o Harmony (o Colour Art define o matte). **Documentar para o
  usuário: o occluder precisa de fill fechado e opaco.**
- ✅ **Direção correta confirmada (via operador):** ativo=peça remendada (linha cortada),
  outro selecionado=occluder. Demonstrado: a linha da peça ATIVA some onde o occluder sobrepõe; o
  occluder deve estar na FRENTE para o look aditivo (a peça da frente esconde a linha da de trás na
  junta).
- ✅ **Mod D (aviso coplanar): FUNCIONA.** Com occluder e peça no mesmo Z (e sem "In Front"), o
  operador emite o `RPT_WARNING` ("…same depth; draw order is undefined…") e finaliza (não-bloqueante).
- ✅ **Mod C — lado OPERADOR: OK.** Props `matte_source=SELF` + `layer` funcionam; cria a mask com
  `object=self`+`layer_name`, roteada pelo caminho `mattes`. Sem crash.
- ❌ **BUG DE RENDER em B e C** (diagnóstico aprofundado via MCP + instrumentação, 2026-06-17).
  Sintoma: o matte é aplicado mas recorta o **layer inteiro (fill + stroke)** em vez de só o stroke.
  O que foi DESCARTADO como causa (provado ao vivo):
  - **Não é o flag**: instrumentei `object_sync_do` — `tgp_layer->auto_patch=1` e `show_fill=1`
    CHEGAM ao render no layer remendado (tanto self quanto cross-object). O `gp_mask_bypass=1` É
    emitido para o drawcall de fill.
  - **Não é profundidade**: ligar "In Front" no objeto remendado (que troca `depth_tex` por
    `dummy_depth`, pulando o depth-test manual de `gpencil_frag.glsl`) NÃO conserta — o fill segue
    cortado pela máscara.
  - **Cross-object VISÍVEL funciona** (A): com o occluder num objeto separado visível (matte de
    objeto-todo ou layer-filtrado), o fill é MANTIDO e só a linha é cortada. Confirmado ao vivo.
  Logo o bug é **específico dos caminhos self-patch (C, matte = outro layer do MESMO objeto) e
  occluder-oculto (B, sync diferido `cache_only`)** — apesar do `gp_mask_bypass=1` ser emitido, ele
  não surte efeito no fragmento de fill nesses casos (provável: estado de GPU/submissão do pass de
  matte same-object/diferido, ou interação do filtro de nó com a layer do próprio objeto). A causa
  exata não foi isolada; precisa de depuração shader-level (ex.: emitir `gp_mask_bypass` como cor).
  - **Fix alternativo TENTADO p/ C (2026-06-17): rotear self por `mask_bits` em vez de `mattes`**
    (`gpencil_cache_utils.cc`: `is_self` detectado contra eval E orig; self cai no caminho local;
    `set_mask_bit` aceita um layer irmão). **NÃO resolveu** — o fill segue cortado. Isso PROVA que o
    bug não é o caminho do matte, e sim a **mesma-objetividade**.
  - **ROOT CAUSE provável (refinado):** o **teste de profundidade de HARDWARE**, não a máscara.
    Cada `draw_object` limpa o depth buffer no início (`gpencil_engine_c.cc:960`) e os layers GP 2D
    usam `DRW_STATE_DEPTH_GREATER`. Em objetos SEPARADOS (cross-object, A) cada um tem depth limpo
    → o fill passa. No MESMO objeto (self-patch), o layer-matte escreve depth e o hardware descarta
    o fill do layer remendado na região — e o `gp_mask_bypass` só pula o descarte da *máscara* no
    frag, NÃO o depth de hardware (por isso "In Front", que só troca o depth-test *manual*, não
    ajudou). O mesmo raciocínio de depth/visibilidade explica B (occluder oculto/diferido).
  - **Fix de verdade (follow-up):** tratar a profundidade do self-patch — ex.: o layer remendado
    não deve ser depth-ocluído pelo layer-matte do mesmo objeto (render do remendado com depth
    independente, ou ordem/estado de depth específico do auto-patch). É mudança no compositing de
    layers, mais profunda.
  - **A e D estão prontos.** B e C ficam como follow-up com esse diagnóstico.
  - Estado do código: a tentativa de fix (`mask_bits` p/ self) foi **revertida** (a `feat/gp-masks`
    voltou ao roteamento `mattes` da Mod C, com um comentário "KNOWN BUG" no `apply_mask_list`
    apontando o follow-up). **Doc de handoff dedicado para a próxima sessão:**
    `doc/guides/nuclear_auto_patch_bc_followup.md` (na `feat/gp-masks`) — repro, root-cause
    (hardware depth), file:line e direções de fix.

---

## 6. Referências

- [`nuclear_auto_patch_nativo.md`](nuclear_auto_patch_nativo.md) — inventário e estado de git.
- [`nuclear_gp_masks.md`](nuclear_gp_masks.md) / [`nuclear_gp_masks_howto.md`](nuclear_gp_masks_howto.md)
  — docs das masks (na `feat/gp-masks`).
- ADR `docs/decisions/2026-06-17-separar-contour-e-masks.md` — separação do commit `90ac371`.
- Memória do projeto: `nuclear-gp-masks-pegs`, `auto-patch-gp-harmony` (o protótipo Python).
