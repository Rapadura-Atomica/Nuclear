# Pegs (rig cutout estilo Toon Boom) no Nuclear

Este documento explica o sistema de **pegs** do fork Nuclear: o que é, como os dados
são guardados, como o node editor e a viewport se conectam ao rig, e a representação
visual da posição na hierarquia ao subir com `Ctrl+B`.

## O que é um peg

Um **peg** é um nó de transformação puro (sem desenho), no estilo do Toon Boom Harmony.
Personagens 2D em Grease Pencil são montados como um *cutout*: cada parte (braço,
antebraço, mão…) é um objeto GP, e os pegs formam a hierarquia que move/gira/escala
essas partes em torno de pivôs (ombro, cotovelo, pulso). Posar = girar pegs.

## Onde os dados vivem

O sistema tem duas camadas:

### 1. Data-block nativo `PegRig` (C/C++)

Um rig de pegs é um data-block próprio (`bpy.data.pegrigs`), análogo a uma Armature.

- `source/blender/makesdna/DNA_pegrig_types.h` — as structs:
  - **`PegRigPeg`**: `name[64]`, `parent_index` (-1 = root), `translation`, `rotation`
    (euler XYZ), `scale`, `pivot` (centro de rotação/escala em espaço local) e
    `world_mat` (cache em runtime).
  - **`PegRig`**: `id`, `adt` (animação), `pegs[]` + `pegs_num`, e
    **`active_peg_index`** — o peg "ativo" para a navegação de hierarquia.
- `source/blender/blenkernel/BKE_pegrig.hh` / `intern/pegrig.cc` — a API de kernel:
  `BKE_pegrig_peg_add/remove/reparent`, `BKE_pegrig_peg_is_ancestor`,
  `BKE_pegrig_solve_world_matrices`, etc. A matriz local de um peg é
  **`T(t+p) · R · S · T(-p)`** (o centro de rotação é `pivot + translation`).
- `source/blender/makesrna/intern/rna_pegrig.cc` — expõe tudo ao Python
  (`rig.pegs.new(name, parent_index)`, `rig.pegs.remove(peg)`, propriedades por peg).
- `source/blender/editors/object/object_pegrig.cc` — operadores de object-mode:
  - `OBJECT_OT_pegrig_pick` — clica um desenho na viewport e torna seu peg o ativo.
  - **`OBJECT_OT_pegrig_select_parent`** — o **climb**: sobe a hierarquia gravando o
    pai do peg atual em `active_peg_index` (atalho `Ctrl+B` no tool "Peg Pose").
- `source/blender/editors/transform/transform_convert_pegrig.cc` — integra os pegs às
  ferramentas de mover/girar/escalar.

### 2. Constraint `Follow Peg`

Cada objeto Grease Pencil é amarrado a um peg por uma constraint do tipo `FOLLOW_PEG`:
`con.rig` (qual `PegRig`) e `con.peg_name` (qual peg dentro dele). `con.peg_name`
vazio = membro do rig que não segue peg nenhum (pendura direto no hub).

## O front-end Python: `scripts/startup/nuclear_peg_graph.py`

É **só visualização/edição** — o `PegRig` é a fonte da verdade. Duas faces:

### Peg Graph (node editor)

Uma `NodeTree` (`NuclearPegTree`) que **espelha** o rig:

- `NuclearRigNode` — o hub composto (um por rig, sem transform). Pegs-raiz e desenhos
  soltos penduram nele (modelo Toon Boom de um composite central).
- `NuclearPegNode` — um peg (entrada "Parent", saída "Children").
- `NuclearDrawingNode` — um objeto GP (entrada "Peg").

Uma ligação `A.saída → B.entrada` significa "**B é controlado por A**". O grafo é
**gerado** do rig por `rebuild()`; editar links no grafo é **escrito de volta** no rig
por `NuclearPegTree.update` → `_apply_graph_to_rig()`. Um guard `_SYNCING` impede que
as duas direções se reentrem. Um handler `depsgraph_update_post` refaz o grafo quando a
estrutura do rig muda (compara uma assinatura barata).

**Add Peg vira PAI do nó ativo** (`NODE_OT_nuclear_peg_add`): criar uma peg com um nó
clicado/ativo já a liga na hierarquia como pai, em vez de nascer solta na raiz:
- nó de **peg** ativo → a nova peg é **inserida acima** dele: ela herda o pai antigo do peg
  clicado, e o peg clicado passa a pendurar nela (a nova peg é o pai);
- nó de **desenho** ativo → a nova peg vira o **controlador/pai** desse desenho, mas só se o
  objeto ainda não tem peg pai (não rouba um binding existente).
A nova peg também já fica selecionada (`active_peg_index`).

### Overlay da viewport

Um draw handler GPU desenha os **pivôs** dos pegs (onde cada um realmente gira), além de
operadores de pivô: `pivot_to_drawing` (snap no centro do desenho), `pivot_grab` (P) e
`pivot_reset`.

## Navegação de hierarquia: o climb `Ctrl+B`

No tool "Peg Pose", `Ctrl+B` chama `OBJECT_OT_pegrig_select_parent`, que **sobe** um nível
(grava o ancestral em `rig.active_peg_index`), e `Ctrl+Shift+B`
(`OBJECT_OT_pegrig_select_child`) **desce** um nível rumo ao desenho (o filho do peg atual
que está no caminho até o peg próprio do objeto). O helper Python `active_peg(context)`
resolve o peg "controlado no momento": é o `active_peg_index` quando ele é o peg próprio
do objeto **ou um ancestral dele** (mid-climb); senão, o peg próprio do objeto. Assim você
seleciona a mão e navega: `Ctrl+B` sobe pulso → antebraço → braço → corpo, `Ctrl+Shift+B`
volta descendo — girando o nível que quiser. (Usa `Ctrl` porque `B` puro é box-select na viewport.)

`Ctrl+B` no padrão do Blender é "Set Render Region" (`view3d.render_border`), que sombreava a
navegação de pegs. O addon **desativa** esse bind global de `Ctrl+B` ao registrar
(`_set_render_border_ctrl_b(False)`) e o **restaura** no `unregister` — assim `Ctrl+B` fica
livre pros pegs sem perder o "Set Render Region" se o sistema de pegs for desativado.
(`Ctrl+Alt+B` / "Clear Render Region" continua intacto.)

## Representação visual da peg selecionada

A peg **selecionada** (a última clicada/pegada, em `rig.active_peg_index`) fica destacada — e
**somente ela** — nas duas views, com a mesma cor âmbar, pra você sempre saber qual peg vai mexer.

O helper `_selected_peg_index(context)` resolve qual peg destacar: o `active_peg_index` do rig
(o rig vem da constraint Follow Peg do objeto ativo), com fallback pro peg próprio do objeto.
Diferente de `active_peg()` (usado pra posar, que é limitado ao climb), o realce **não** é
limitado à cadeia — clicar em qualquer peg destaca exatamente ela.

### Na viewport (`_draw_pivot_overlay`)

- **Anel âmbar** no pivô da peg selecionada — e só nela.
- Os outros pegs aparecem como **pontinhos faint**, só pra você saber onde estão pra clicar.

### No Peg Graph (`_draw_node_highlight`)

Um draw handler `POST_PIXEL` no `SpaceNodeEditor` acende um **halo âmbar** em volta do nó da
peg selecionada — só esse nó. As coords de nó (`node.location`/`width`/`dimensions`) viram
pixels via `region.view2d.view_to_region`, com altura em unidades de árvore = `dimensions.y/ui_scale`.

### Seleção sincronizada nas duas direções

- **Viewport → tudo:** clicar um desenho (`OBJECT_OT_pegrig_pick`) ou `Ctrl+B` grava `active_peg_index`.
- **Peg Graph → tudo:** clicar um nó de peg não dispara callback nenhum, então um timer leve
  (`_sync_node_selection`, 0.15 s) espelha o nó ativo do grafo em `active_peg_index`. Ele só age
  quando o nó ativo **muda** (rastreado por árvore), pra nunca brigar com o `Ctrl+B`.
- **Redraw imediato:** `active_peg_index` muda **sem** update de depsgraph, então uma assinatura
  `bpy.msgbus.subscribe_rna` em `(PegRig, "active_peg_index")` marca `tag_redraw()` nas áreas
  `VIEW_3D` e `NODE_EDITOR`. Re-armada no `load_post` (msgbus é limpo ao abrir arquivo).

## Cores

| Elemento                         | Cor                         | Significado                         |
|----------------------------------|-----------------------------|-------------------------------------|
| Peg selecionada (anel/halo)      | âmbar (`1,0.75,0.10`)       | a peg que você vai mexer            |
| Outros pegs (viewport)           | âmbar faint (alpha 0.35)    | contexto, pra localizar/clicar      |

(No Harmony, vermelho seria o modo *rigging*; aqui o overlay é sempre de pose, então fica
no verde. Os hex são aproximações editáveis no código, não valores oficiais da Toon Boom.)
