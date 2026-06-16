# Nuclear — Masks em pegs/grupos e cutter cross-object

Documento para devs. Explica a feature de máscaras de Grease Pencil estendida no fork
Nuclear: mascarar uma **peg/grupo inteira** e usar **outro objeto como matte (cutter)**, com
autoria pela **Peg View**.

## Contexto rápido

O Blender já tem máscaras de GP: cada **layer** (`GreasePencilLayer`) tem uma lista `masks`
de `GreasePencilLayerMask`, cada uma apontando por **nome** para outra layer **do mesmo
objeto**. O render monta um bitmap de até 256 bits (um por layer do objeto) e desenha as
layers-matte num framebuffer de máscara (`mask_fb`/`mask_tx`).

Nuclear estende isso em duas direções, com **um único modelo de dado**:

1. **Mask de grupo/peg (within-object):** um `GreasePencilLayerTreeGroup` também pode ter
   `masks`. Uma folha herda as máscaras de todos os grupos ancestrais → mascarar uma peg
   inteira. Uma máscara que aponta para um grupo expande para todas as folhas dele.
2. **Cutter cross-object:** uma `GreasePencilLayerMask` ganhou um ponteiro `object`. Quando
   setado, o matte são as layers de **outro objeto GP** (nome vazio = objeto inteiro).

## Modelo de dado (DNA / RNA)

`DNA_grease_pencil_types.h`:

```c
typedef struct GreasePencilLayerMask {
  ...
  char *layer_name;     /* nó (layer ou grupo) que serve de matte */
  struct Object *object; /* NUCLEAR: matte externo; null = mesmo objeto */
  uint16_t flag;         /* GP_LAYER_MASK_HIDE / GP_LAYER_MASK_INVERT */
} GreasePencilLayerMask;

typedef struct GreasePencilLayerTreeGroup {
  ...
  ListBase masks;          /* NUCLEAR: máscaras do grupo/peg */
  int active_mask_index;
} GreasePencilLayerTreeGroup;
```

Pontos de ciclo de vida (todos em `blenkernel/intern/grease_pencil.cc`):

- `LayerMask` ctor/copy zeram/copiam `object`.
- `LayerGroup` ctor/copy/dtor gerem a ListBase `masks` (espelham o leaf).
- **`grease_pencil_foreach_id`** percorre `mask->object` (layers e grupos) com
  `IDWALK_CB_USER` — necessário para relink/remap/delete. Template foi `layer->parent`.
- blend read/write dos masks de grupo (`read_layer_tree_group` / `write_layer_tree_group`);
  o ponteiro `object` é religado pelo `foreach_id`, não precisa de código de IO próprio.
- rename de nó corrige nomes em **todas** as listas de máscara (layers e grupos), só nas
  same-object (`object == null`).

RNA (`makesrna/intern/rna_grease_pencil*.cc`):

- `GreasePencilLayerMask.object` (poll só aceita objeto GP).
- Coleção `mask_layers` no grupo + índice ativo.
- **API nova `mask_layers.new(name, object=None, invert=False)` / `.remove(mask)`** nas duas
  coleções (não existia; é o que permite autoria por script e pela Peg View).

> Sem mudança de versioning: os campos novos são zerados ao ler arquivos antigos.

## Render

`draw/engines/gpencil/`:

- **`gpencil_cache_utils.cc`** (`grease_pencil_layer_cache_add`): ao montar a máscara de cada
  layer, junta as máscaras próprias + as de cada grupo/peg ancestral. Para cada entrada:
  - matte same-object → seta o bit (layer) ou expande para as folhas (grupo);
  - matte cross-object (`mask->object` setado) → empilha um `tMatteRef` em `tLayer.mattes`.
- **`gpencil_engine_c.cc`** (`draw_mask`): além do bitmap same-object, percorre
  `layer->mattes`, resolve o `tObject` do matte via `Instance.object_to_tgp` e submete as
  layers dele no `mask_fb`. `object_to_tgp` é preenchido em `gpencil_object_cache_add`,
  chaveado pelo objeto avaliado **e** pelo original (sobrevive ao remap copy-on-write).
- `is_used_as_layer_mask_in_viewlayer` generalizado para reconhecer matte via grupo e via
  grupos ancestrais.

## Peg View (`scripts/startup/nuclear_peg_graph.py`)

A Peg View é um Node Editor que visualiza o `PegRig`. Ganhou autoria de máscara:

- Socket `NuclearMatteSocket` (ciano) + sockets **"Matte In"/"Matte Out"** nos Drawing nodes.
- Link `A.Matte Out → B.Matte In` = "A mascara B". O write-back grava um **cutter de objeto
  inteiro** (`object=A`, `layer_name=""`) em cada folha de B e liga `use_masks`. O `rebuild`
  recria os links a partir das máscaras existentes (bidirecional, com guard `_SYNCING`).

## Pegadinhas

- **Máscaras são opt-in por layer:** layers nascem com `GP_LAYER_TREE_NODE_HIDE_MASKS`
  (`use_masks()` False). Sem ligar **Use Masks**, nenhuma máscara aplica. A Peg View liga
  sozinha ao criar o cutter.
- **Limitação v1 do cross-object:** o objeto-matte precisa estar avaliado/visível no view
  layer para ser cacheado; matte escondido → silhueta vazia. (Fase 2: forçar sync do matte +
  relação de depsgraph.)
- `GP_MAX_MASKBITS` = 256: o bitmap same-object continua limitado a 256 layers por objeto.
- Render headless: `render.opengl` não roda em background; use `render.render()` com
  `BLENDER_EEVEE` (o enum é `BLENDER_EEVEE`, não `_NEXT`).

## Mapa de arquivos

| Arquivo | O quê |
|---|---|
| `makesdna/DNA_grease_pencil_types.h` | campos `object`, `masks` no grupo |
| `blenkernel/intern/grease_pencil.cc` | ciclo de vida, foreach_id, IO, rename |
| `makesrna/intern/rna_grease_pencil.cc` | RNA + defs da API new/remove |
| `makesrna/intern/rna_grease_pencil_api.cc` | impl da API new/remove |
| `draw/engines/gpencil/gpencil_cache_utils.cc` | coleta de máscaras/mattes |
| `draw/engines/gpencil/gpencil_engine_c.cc` | `draw_mask`, mapa object→tObject |
| `draw/engines/gpencil/gpencil_engine_private.hh` | `tMatteRef`, `tLayer.mattes`, `object_to_tgp` |
| `scripts/startup/nuclear_peg_graph.py` | sockets/links de Matte na Peg View |
| `scripts/startup/bl_ui/properties_data_grease_pencil.py` | campo `object` na lista de máscaras |
</content>
