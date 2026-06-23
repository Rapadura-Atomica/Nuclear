# CutterFeature.md — máscara cross-object de Grease Pencil ("Cutter", estilo Toon Boom)

> Documento vivo. Plano + decisões de design do modifier **Cutter** do Nuclear.
> Mantenha atualizado conforme a feature evolui.
>
> Última atualização: 2026-06-18.

---

## 1. O problema

No rig antigo (bones), dava para ter um **olho** e, dentro dele, uma **pupila mascarada**
pela silhueta do olho — manipulando olho e pupila com controladores distintos. Ao migrar
para o sistema de **pegs no nível de objeto** (cada parte do personagem é um objeto GP
separado, ligado por `FOLLOW_PEG`), isso se perdeu: o masking nativo de Grease Pencil é
**estritamente intra-objeto** (a `GreasePencilLayerMask` referencia uma layer **pelo nome
dentro do mesmo objeto** — `find_node_by_name`, cap `GP_MAX_MASKBITS`, e o `draw_mask` puxa
a layer-máscara do cache do **mesmo** `tObject`). Olho e pupila agora são objetos diferentes,
então o masking nativo não os alcança.

Equivalente no Toon Boom: o **Cutter (Mask) node** — um desenho recorta outro pela silhueta
de um matte, e ambos podem ter pegs independentes.

## 2. Decisões de design (confirmadas com o autor, 2026-06-18)

1. **Abordagem = alpha matte por injeção** (não clip geométrico, não cirurgia no draw engine).
2. **O objeto-matte (olho) continua visível e renderiza normal** — o modifier só empresta a
   silhueta dele.
3. **UI = modifier no painel (Fase 1) + integração no Peg Graph (Fase 2).**

**Alternativas rejeitadas:**
- **Clip geométrico** (recortar o contorno da pupila contra o polígono do olho via pyclipper):
  determinístico, mas bordas duras, foco em fill, e perde anti-alias casado. Não bate a
  qualidade do alpha matte nativo.
- **Máscara cross-object no draw engine** (estender `draw_mask` para puxar geometria de outro
  objeto): é o mais fiel, mas exige cirurgia no `gpencil_engine` (área upstream), alta
  divergência em C, e é difícil de testar headless. Contra a regra do projeto de **minimizar e
  isolar divergência**.

## 3. Como funciona ("matte injection")

Um modifier no objeto **mascarado** (pupila), em `modify_geometry_set` (roda na GP avaliada):
1. Lê a GreasePencil **avaliada** do objeto-matte (olho) via depsgraph
   (`DEG_get_evaluated`).
2. Copia as strokes visíveis do matte no frame atual e as transforma para o **espaço-objeto
   da pupila**: `inv(pupil.object_to_world) · matte.object_to_world · matte_layer.layer_to_object_space`.
   Como os transforms de peg vivem nas `object_to_world` (o `FOLLOW_PEG` pós-multiplica), a
   silhueta **segue os dois pegs automaticamente**.
3. **Injeta** essas strokes como uma layer extra **visível, com `opacity = 0`**, nome único
   (`__nuclear_cutter__<nome-do-modifier>`), via
   `GreasePencil::add_layers_with_empty_drawings_for_eval(1)`.
4. Adiciona uma `GreasePencilLayerMask` nativa nas layers-alvo (filtro Influence) apontando
   para a layer injetada, com `invert` opcional.

O pipeline de máscara nativo (mesmo-objeto) então produz o alpha matte sozinho — **sem mudar
o draw engine**.

### Os dois fatos que sustentam isso (verificados no código)
- Adicionar layer na GP avaliada em tempo de eval é caminho oficial e já usado por geometry
  nodes / realize_instances / separate_geometry (`grease_pencil.cc:add_layers_with_empty_drawings_for_eval`).
- A geometria da layer-máscara é submetida ao framebuffer de máscara **independente do
  `opacity` da layer** (`gpencil_engine_c.cc`, `manager->submit(*mask_layer->geom_ps, view)`)
  → `opacity = 0` esconde o desenho do matte mas mantém a silhueta como recorte.

### Gotchas de visibilidade (load-bearing)
- A layer injetada **NÃO pode estar `hide`** (3 gates a barram: `grease_pencil_utils.cc`
  `is_visible()`, `gpencil_cache_utils.cc` na resolução de máscara, e o cache por objeto). Por
  isso **visível + opacity 0**, não oculta.
- O nome da layer injetada precisa ser **único** (a máscara resolve por nome;
  `find_node_by_name` retorna o primeiro match). Usa o nome do modifier (único por objeto).
- A layer-alvo precisa de `use_masks()` ativo → o modifier limpa `GP_LAYER_TREE_NODE_HIDE_MASKS`.

### Gotcha de material (#1)
As strokes do matte carregam `material_index` que referencia os slots do **objeto-matte**,
inexistentes na pupila. O modifier **remapeia tudo para o slot 0** da pupila. Para o matte
virar **área sólida** (e não só contorno), o slot 0 da pupila deve ter **fill**, e o matte
deve ser uma forma fechada (cyclic) — que é o setup natural de um matte no Toon Boom.

### Gotcha de PROFUNDIDADE (#2 — o bug que custou caro, RESOLVIDO)
O frag shader da GP (`gpencil_frag.glsl:118-123`) faz um **teste de profundidade contra o
scene depth**: fragmentos atrás de outra geometria são descartados — **inclusive no mask
pass**. O matte injetado, após o transform, fica na **profundidade do objeto-matte** (ex.: o
olho, atrás da pupila). Como o objeto-matte continua **renderizando** (decisão do usuário), ele
escreve o scene depth, e o matte injetado é **descartado exatamente onde precisa cobrir** →
sobra só o anel do traço → a máscara não recorta (a pupila some inteira ou sobra a fatia do
anel). Sintoma diagnóstico: esconder o objeto-matte do render (`hide_render`) fazia o recorte
funcionar perfeitamente; com ele visível, falhava.
**Fix:** como masking é screen-space, a profundidade do matte é irrelevante para a silhueta.
O modifier **projeta o matte injetado no plano da geometria mascarada** (centroide + normal do
plano de desenho, via `curve_plane_normals()`), deixando-o co-planar com o que mascara → passa
no teste de profundidade exatamente onde importa.
**Sub-gotcha (vista frontal — bug da "linha horizontal", corrigido 2026-06-18):** a 1ª versão
achatava o **eixo Z do mundo**. Isso funciona em vista de cima (profundidade=Z), mas a animação
2D é **vista de frente** (desenho no plano XZ, profundidade=Y): achatar Z **colapsa a silhueta
numa linha horizontal**. Por isso a projeção é ao longo da **normal do plano de desenho**, não de
um eixo fixo do mundo. Validado GPU em vista de cima (XY) E vista de frente (XZ): recorte correto,
sem linha, nos dois casos.

## 4. Arquivos

**Novo (divergência isolada):**
- `source/blender/modifiers/intern/MOD_grease_pencil_mask.cc` — o modifier inteiro.

**Costuras de 1 linha** (registradas em `NUCLEAR_DIVERGENCE.md §2`): DNA enum+struct+defaults,
`MOD_modifiertypes.hh`, `MOD_util.cc`, `CMakeLists.txt`, `rna_modifier.cc`, `rna_object.cc`
(poll `rna_GreasePencil_object_poll`), `rna_internal.hh`, `properties_data_modifier.py`,
`BKE_blender_version.h` (subversion 119→120).

Templates: `MOD_grease_pencil_curve.cc` (esqueleto + ponteiro de objeto + depsgraph) e
`MOD_grease_pencil_array.cc` (`ModifierTypeType::Constructive`, idiom de `material_index`).

## 5. Fase 2 — Peg Graph (FEITA, 2026-06-18)
Em `scripts/startup/nuclear_peg_graph.py`: o `NuclearDrawingNode` ganhou **entrada "Cutter"** +
**saída "Matte"**. Ligar `Matte` de um desenho → `Cutter` de outro cria/atualiza o modifier
`GREASE_PENCIL_MASK` (`mod.object = matte`) via `_apply_graph_to_rig`; desligar remove. `rebuild`
recria os links a partir dos modifiers existentes (helper `_cutter_modifier`); `_graph_signature`
inclui os cutters p/ o sync detectar mudanças. Só manipula a RNA pública da Fase 1. Headless
7/7 PASS (cria/recria/remove). GUI: arrastar o link no editor Peg Graph (a validar visualmente).

## 6. Verificação
Build: `distrobox enter blender -- bash -lc 'cd .../Nuclear/build && ninja && ninja install'`.
Teste via BlenderMCP TCP `127.0.0.1:9876` (nunca `script.reload()` na sessão de produção):
1. **Dados (headless):** olho (círculo fill, cyclic) + pupila (círculo menor, deslocado);
   `mod = pupil.modifiers.new("Cutter",'GREASE_PENCIL_MASK'); mod.object = eye`; avaliar
   depsgraph; conferir na GP avaliada da pupila a layer `__nuclear_cutter__Cutter` (visível,
   opacity 0, com geometria) e `mask_layers` nas layers de desenho apontando pra ela.
2. **Segue o peg:** mover o peg do olho, re-avaliar, conferir o deslocamento da silhueta
   injetada.
3. **GPU/screenshot:** pupila recortada na silhueta; mover peg do olho arrasta o recorte; olho
   renderiza normal; `mod.invert` dá o complemento.

## 7. Status
- **2026-06-18:** Fase 1 **COMPLETA e validada no GPU**. Modifier `GREASE_PENCIL_MASK`
  ("Cutter") funcional: 8/8 asserts de dados headless; recorte alpha-matte correto (non-invert
  = dentro do matte, invert = fora), segue o objeto-matte ao mover (caso do peg), com o matte
  visível. O bug de profundidade (#2) foi diagnosticado e resolvido com o Z-flatten. Fase 2
  (Peg Graph) pendente.

## 7b. Fase 3 — MIGRAÇÃO para máscara NATIVA cross-object + multi-matte + invert (2026-06-23)
A abordagem de **injeção** (Fase 1, modifier `MOD_grease_pencil_mask.cc`) foi **superada** pelo
suporte **nativo a matte cross-object** que entrou no draw engine com a fusão Auto-Patch+Envelope:
- `GreasePencilLayerMask` ganhou os campos `object` + `layer_name` (DNA) → uma máscara pode apontar
  para a layer/grupo de **outro** objeto. `draw_mask` (`gpencil_engine_c.cc`) rasteriza **todos** os
  mattes de uma layer (`tLayer::mattes`) no **mesmo** buffer de máscara → **união automática** de N
  silhuetas. RNA exposta: `layer.mask_layers.new(name="", object=matte, invert=)` / `.remove()`
  (coleção é **`mask_layers`**, prop do nome é **`.name`** com sdna `layer_name`; `.invert`,
  `.use_auto_patch`).
- O **Peg Graph** (`scripts/startup/nuclear_peg_graph.py`) foi reescrito p/ falar **máscara nativa**
  (não mais o modifier): socket **"Cutter" multi-input** (`inputs.new(..., use_multi_input=True)`),
  N links `Matte→Cutter` = N máscaras nativas = união. **Python puro, ZERO C/DNA** (o C já estava no
  source). Helpers: `_set_object_cutters` (reconcilia as máscaras nativas com os links; só mexe em
  máscaras cross-object cujo matte é drawing-node do grafo e **não** Auto-Patch — preserva
  Auto-Patch/Contour/manuais), `_managed_cutter_mattes`, `_object_cutter_invert`,
  `_migrate_legacy_cutter` (converte modifier legado → nativo no `rebuild`, carregando `mod.invert`).
- **Invert** exposto: toggle **"Invert Cutter" por Drawing node** (`cutter_invert` BoolProperty com
  update callback), polaridade **uniforme** a todos os mattes do nó — misturar polaridades numa
  união é frágil no mask pass (flip de buffer dependente de ordem). Fonte da verdade = `mask.invert`;
  `rebuild` restaura o toggle, `_graph_signature` codifica `@0/@1`.
- O modifier de injeção **continua registrado** só p/ carregar e migrar arquivos antigos (limpá-lo é
  tarefa separada). Os gotchas de injeção (profundidade #2, material #1) deixam de se aplicar ao
  caminho nativo.
- **Validação:** headless **22/22** (união, unlink seletivo, invert round-trip, preservação de
  Auto-Patch, migração legada) no binário rebuildado 2026-06-23 17:00. **PENDENTE:** validação visual
  GPU em processo fresco; commit.
- **Limites conhecidos:** a máscara cobre **todas** as leaf layers do objeto com a silhueta do matte
  **inteiro**; granularidade por-layer (via `layer_name`) é evolução futura. "Por baixo/por cima" é
  **ordem de desenho**, não Cutter.

## 8. Evolução futura
- Granularidade por-layer/grupo no matte (usar `layer_name` em vez de objeto inteiro).
- `invert` por-matte (hoje é por-nó/uniforme) — exigiria UI por-link, que o node tree não dá de graça.
- Auto-setup do material de fill no slot remapeado (relevante só p/ o caminho legado de injeção).
- `feather`/suavização da borda do matte (o alpha nativo já dá borda do traço; um falloff
  explícito seria extra).
- Remover/aposentar o modifier de injeção `MOD_grease_pencil_mask.cc` quando todos os arquivos
  estiverem migrados.

Relaciona-se com `NUCLEAR_DIVERGENCE.md`, `CLAUDE.md` (regra de isolar divergência) e o
sistema de pegs (`SquashFeature.md`, PegRig).
