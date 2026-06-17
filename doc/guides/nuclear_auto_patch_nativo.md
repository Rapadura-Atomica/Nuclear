# Auto-Patch Nativo (estilo Toon Boom Harmony) — Grease Pencil v3 / Nuclear

> Status deste documento: **inventário do que foi feito + o que ainda falta**, escrito a
> partir dos transcripts das sessões de desenvolvimento e do estado atual do repositório
> (`~/Documentos/GitHub/Nuclear`). Foco **exclusivo no auto-patch nativo**. O *envelope/contour
> deformer* (`GreasePencilContour`, MVC) é **outro projeto** e só aparece aqui quando se
> misturou com este — ver a seção [Emaranhado com o envelope](#emaranhado-com-o-envelope).

---

## 1. O que é o "auto-patch nativo"

É a implementação **nativa em C++** do *Auto-Patch* do Toon Boom Harmony para Grease Pencil v3:
esconder/recortar a **costura** que aparece na articulação onde uma parte do rig cutout
sobrepõe a vizinha. O mecanismo nativo é o sistema de **masks de GP + cutter cross-object**:
o *matte* (silhueta) de uma parte recorta as camadas da parte vizinha exatamente na junta,
sem depender de acidente de ordem de camada.

- **Não confundir** com o *auto-patch em Python* (`nuclear_auto_patch_v3.py`, addon estilo
  Harmony com `cover_patch`/`merge_joint`) — aquilo é protótipo de addon. Este documento é
  sobre a feature **nativa do fork**.
- **Não confundir** com o *envelope/contour deformer* (`GreasePencilContour`) — aquele
  *deforma* a arte com uma cage; este *mascara/recorta*. São projetos distintos que
  infelizmente acabaram no mesmo commit (ver §6).

**Fonte:** `~/Documentos/GitHub/Nuclear` · **Build de dev:** `build_nuclear_lite` (também
buildado em `build_nuclear_full`) dentro do distrobox `blenderdev`.

---

## 2. Arquitetura (modelo de dado único)

A feature usa **um só modelo de dado** que serve tanto *mask de grupo/peg* (dentro do mesmo
objeto) quanto *cutter cross-object* (um objeto recorta outro):

### Dois sistemas de "peg" (não confundir)
1. **PegRig** — `DNA_pegrig_types.h`, `BKE_pegrig`, `bFollowPegConstraint`. Data-block
   separado; objetos GP inteiros seguem um peg. É o que a **Peg View**
   (`scripts/startup/nuclear_peg_graph.py`, um NodeTree custom) visualiza.
2. **Peg embutido no layer-tree** — um `GreasePencilLayerTreeGroup` com a flag
   `GP_LAYER_TREE_NODE_IS_PEG` vira controlador de transform dentro de **um** objeto GP.

### Masks nativas
- Base: `GreasePencilLayerMask` (ListBase `masks` na folha `GreasePencilLayer`), resolvidas
  por **nome dentro do mesmo objeto**; render por bitmap de 256 bits por objeto
  (`GP_MAX_MASKBITS`) em `gpencil_cache_utils.cc` + `draw_mask` em `gpencil_engine_c.cc`.
- A feature **estende** isso para grupos/pegs e para **cross-object**.

---

## 3. Mudanças feitas — por arquivo

Mudanças concretas que compõem o auto-patch nativo (subconjunto "masks" do commit `90ac371`;
ver §5). Os arquivos do *envelope* estão deliberadamente **fora** desta lista.

### DNA (modelo de dado)
- `source/blender/makesdna/DNA_grease_pencil_types.h` — `GreasePencilLayerMask.object`
  (`Object*` matte externo; `null` = mesmo objeto) + `masks` / `active_mask_index` no
  `GreasePencilLayerTreeGroup`.

### Kernel / ciclo de vida
- `source/blender/blenkernel/intern/grease_pencil.cc` — ctor/copy/dtor do `LayerGroup`;
  **`foreach_id`** (remap/delete do matte — o template foi `layer->parent`); blend
  read/write dos masks de grupo; rename-fixup para layers **e** grupos.
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` — lógica de máscara
  em camadas/grupos (núcleo do cutter cross-object).

### RNA / API de autoria
- `source/blender/makesrna/intern/rna_grease_pencil.cc` — `mask.object` (poll só
  `GREASEPENCIL`) + coleção `mask_layers` no grupo.
- `source/blender/makesrna/intern/rna_grease_pencil_api.cc` — **API
  `mask_layers.new(name, object, invert)` / `.remove()`** (não existia; `.new()` é
  necessária para autoria via script e via Peg View).

### Render / draw engine
- `source/blender/draw/engines/gpencil/gpencil_engine_c.cc` — render dentro-do-objeto
  (folha **herda** masks dos grupos/pegs ancestrais; mask que aponta para grupo **expande**
  para as folhas descendentes; `is_used_as_layer_mask_in_viewlayer` generalizado) **e**
  cross-object: `draw_mask` renderiza as layers do objeto-matte no `mask_fb` (filtra por nó
  nomeado, ou objeto inteiro se `name==""`).
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` — `tLayer.mattes`
  (`Vector<tMatteRef>`), mapa `Instance.object_to_tgp` (chaveado por objeto **avaliado e
  original**, para sobreviver ao remap de COW).
- `source/blender/draw/engines/gpencil/gpencil_engine_private.hh` — structs de suporte
  (`tMatteRef`, etc.).
- `source/blender/draw/engines/gpencil/shaders/gpencil_frag.glsl` e
  `shaders/infos/gpencil_infos.hh` — caminho de mask no fragment shader.

### UI / Python
- `scripts/startup/bl_ui/properties_data_grease_pencil.py` — campo `object` na lista de masks.
- `scripts/startup/nuclear_peg_graph.py` — socket `NuclearMatteSocket` (ciano) + "Matte
  In/Out" nos Drawing nodes; link A→B grava cutter whole-object (`object` set, `name=""`) em
  cada folha de B; round-trip no rebuild.

### Documentação (no próprio source-tree)
- `doc/guides/nuclear_gp_masks.md`, `doc/guides/nuclear_gp_masks_howto.md`.

---

## 4. O que foi validado

- **Teste headless por contagem de pixels** (sessão `c77f0498`): objeto B **cortado de
  28→1** pixel onde o matte cobre; com `invert` mantém o complemento. Comportamento de
  cutter cross-object confirmado.
- Render headless: `render.render()` com **`BLENDER_EEVEE`** (cria contexto GPU offscreen).
  `render.opengl` **não** roda em background.

> ⚠️ Essa validação foi feita **antes** de o código ser empacotado no commit `90ac371` e
> parqueado. Não há re-validação documentada após o empacotamento, nem teste numa junta de
> rig real (ex.: JulianoHeroi). Ver §7.

---

## 5. Estado no git / versão

| Item | Valor |
|---|---|
| Commit fundido (origem) | `90ac371d58a` — *"feat(gp): modifier Contour (envelope MVC) + masks nativas de GP"* |
| Branch de origem | `feat/native-auto-patch` (preservada, intocada) |
| Cherry-pick preservado em | `integration/gp-contour-1.1` (base `origin/auto/integration`) |
| **Split FEITO (2026-06-17)** | `feat/gp-masks` (`d949910`, 14 arq/992 ins) **+** `feat/gp-contour` (`570ff05`, 9 arq/458 ins), ambas a partir do pai real `8d7e310` |
| Linha de release 1.1 | `integration/1.1-ui-squash` — **masks/auto-patch EXCLUÍDOS de propósito** |
| Bump de versão | `1.2.0` / `NUCLEAR_BUILD 3` — **pertence à linha UI/squash, não ao auto-patch** |

O código do auto-patch **existe e compila** (à época da v1), mas está **parqueado**: foi
cherry-picked para `integration/gp-contour-1.1` e deliberadamente **deixado de fora** da build
1.1 empacotada.

**Separação concluída (2026-06-17, sessão /council Tier 3 — ver ADR
`docs/decisions/2026-06-17-separar-contour-e-masks.md`).** O commit `90ac371` fundia os dois
projetos; agora cada metade vive numa branch independente, cherry-pickável isoladamente:
- **`feat/gp-masks`** — só as masks/auto-patch.
- **`feat/gp-contour`** — só o modifier Contour/envelope.
O único arquivo que precisava de split em nível de hunk era `grease_pencil.cc` (1 hunk de
contour — o `case eModifierType_GreasePencilContour` em `influence_data_from_modifier` — vs.
8 hunks de mask). Verificado por reconstrução: `8d7e310 + contour + masks == 90ac371`
byte-a-byte, e nenhum lado referencia símbolos do outro. **Build de validação de cada branch
ainda pendente** (ver §7).

---

## 6. Emaranhado com o envelope

A suspeita de mistura entre os projetos **se confirma**:

1. A branch chama-se `feat/native-auto-patch` (nome de auto-patch), mas o que foi commitado
   nela inclui o **envelope/contour MVC**.
2. O commit **`90ac371` funde os dois projetos num ponto só**: o modifier `GreasePencilContour`
   (envelope) **e** as masks nativas (auto-patch) entraram juntos, ficando **inseparáveis**
   nesse commit.
3. O termo "costura"/"seam" no chat de empacotamento (`39c4e4e0`) refere-se à **costura de
   UI** (o `__init__.py` do app-template que remapeia labels) — fácil de confundir com a
   costura de junta do auto-patch, mas é coisa diferente.

**Consequência prática:** quem quiser publicar o auto-patch **sem** o envelope precisa
primeiro **separar** os dois dentro de `90ac371`.

---

## 7. O que ainda falta

### Integração / release
- [x] **Separar** masks (auto-patch) do contour (envelope) — ~~hoje fundidos no commit `90ac371`~~
      **FEITO em 2026-06-17**: branches `feat/gp-masks` e `feat/gp-contour` (ver §5 e o ADR).
- [ ] **Build de validação** de cada branch separada no distrobox `blenderdev` (cada metade
      compila sozinha sobre `8d7e310`) — a independência foi provada por análise/reconstrução,
      falta a prova empírica de compilação.
- [ ] **Integrar** o auto-patch na linha de release canônica (`origin/auto/integration` / 1.1)
      — atualmente excluído da build empacotada. Agora basta cherry-pick de `feat/gp-masks`.
- [ ] Documentar os *seams* (pontos de divergência do upstream) no `NUCLEAR_DIVERGENCE.md`.
- [ ] Empacotar build / regerar `version.json` **se** o auto-patch entrar numa release (hoje
      o bump `1.2.0`/`build 3` é da linha UI, não cobre o auto-patch).

### Validação
- [ ] Re-validar as masks **depois** do empacotamento (render headless, pixel-count) numa
      **junta de rig real** (ex.: JulianoHeroi), não só no objeto sintético B.

### Limitações conhecidas da v1 (a endereçar)
- [ ] **Cross-object exige matte visível**: o objeto-matte precisa estar avaliado/visível no
      view layer para ser cacheado; matte escondido → silhueta vazia. **Não há relação de
      depsgraph** adicionada (o draw re-sincroniza todo objeto a cada redraw, então o
      *transform* do matte atualiza, mas a *visibilidade* não pode ser desligada).

### Pegadinhas que mordem (registrar/automatizar)
- **Masks são opt-in**: novos layers nascem com `GP_LAYER_TREE_NODE_HIDE_MASKS` ("Hide masks
  by default") → `use_masks()` retorna `False`. Sem ligar **Use Masks** no layer, **nenhuma**
  mask aplica. (Quebra os primeiros testes de render.)
- **Build após troca de branch**: trocar de branch no GitHub Desktop **esvazia**
  `lib/linux_x64`. Rodar antes de qualquer build da branch de masks/contour:
  `git submodule update --init --checkout --force lib/linux_x64`.
- **Enum do engine** nesta árvore é `BLENDER_EEVEE`, **não** `BLENDER_EEVEE_NEXT`.
- **Teste de fill**: Suzanne GP (`grease_pencil_add type='MONKEY'`) é line-art **sem fill** —
  medir por **contagem de pixels opacos**, não por cor de fill.

---

## 8. Como buildar

Dentro do distrobox `blenderdev` (o host não tem o toolchain):

```bash
distrobox enter blenderdev -- bash -lc '
  cd /var/home/rapaduraatomica/Documentos/GitHub/build_nuclear_lite &&
  cmake . &&            # regenera o cache (evita fixar /usr/bin/cmake) \
  ninja -j4 install     # -j4 por causa de OOM em ~15Gi com -j maior
'
# binário em build_nuclear_lite/bin/blender
```

> **Não** bumpar `NUCLEAR_BUILD` manualmente — release é responsabilidade do agente
> *nuclear-release*.

---

## 9. Referências (memórias do projeto)

- `nuclear-gp-masks-pegs` — arquitetura completa das masks/pegs + cutter cross-object (fonte
  primária deste doc; sessão `c77f0498`).
- `nuclear-contour-envelope-deformer` — o **envelope** (projeto separado, NÃO é auto-patch).
- `auto-patch-gp-harmony` — o addon **Python** de auto-patch (protótipo, NÃO é a feature nativa).
- `nuclear-build-setup` — build do fork no distrobox `blenderdev`.
