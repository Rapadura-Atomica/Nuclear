# ADR: Persistência do layout do Peg Graph (posições de nós + frames)

**Date**: 2026-06-24
**Status**: Accepted
**Context**: fork Nuclear (Blender 5.0) — subsistema PegRig / Peg Graph (`scripts/startup/nuclear_peg_graph.py`)

## Context

O Peg Graph é um node editor *puramente visual*: ele existe para o rigger arrumar a hierarquia
de pegs de um jeito legível. Mas o arranjo do rigger se perdia em três situações:

1. **Sync / Add Peg / auto-refresh** — `rebuild()` faz `tree.nodes.clear()` e recria os nós do
   zero. Ele tentava preservar posições lendo `tuple(n.location)` antes do clear, mas:
   - `node.location` de um nó **dentro de um frame é relativo ao frame** (RNA: *"Location of the
     node within its parent frame"*). Salvo como se fosse absoluto e reaplicado sem o frame, o nó
     saltava de lugar.
   - **frames não eram preservados de jeito nenhum**: `nodes.clear()` destruía os `NodeFrame` e o
     parenteamento nó→frame, e `rebuild()` não os recriava. Criar um frame com **F**
     (`node.join_named`) e depois dar Sync apagava o frame.
2. **Exportar o rig para outro arquivo** — o layout vivia só no datablock do node tree
   (`NuclearPegTree`), que **não acompanha o `PegRig`** num append/link. No arquivo de destino, o
   Sync criava uma árvore zerada e o visual nascia do auto-place em grade. Pior dos três, porque
   anula justamente o trabalho que o Peg Graph existe para guardar.

## Decision

Tornar o **`PegRig` o dono durável do layout**, com o node tree como cópia de trabalho viva.
Tudo em **Python puro**, sem tocar C/DNA (alinhado à diretriz "prefira camadas superiores" e
"minimize divergência em C" do `tools/nuclear_claude/CLAUDE.md`).

- **Snapshot do layout como ID-property JSON no rig** (`rig["nuclear_peg_graph_layout"]`,
  `_LAYOUT_KEY`). ID-properties são serializadas com o datablock e copiadas no append/link, então
  o layout **viaja com o rig** para outros arquivos. O snapshot guarda: posições dos nós de peg
  (por nome), de drawing (por nome de objeto) e do hub do rig, mais a lista de frames
  (label, cor, `label_size`, `shrink`, posição/tamanho e membros por chave estável; frames
  aninhados referenciados por índice).
- **`location_absolute` em todo lugar** (leitura e escrita), em vez de `location`. É o campo bruto
  do canvas, imune a parenteamento de frame — elimina o salto dos nós emoldurados. (Também
  corrigido o overlay de highlight do nó ativo, `_node_rect_region`, que media o retângulo pelo
  `location` relativo.)
- **`rebuild()` recria os frames** e reata o parenteamento (`_apply_frames`) depois de montar os
  nós; posição setada via `location_absolute` *após* o parent (parentear não move o nó no canvas).
- **Captura nos momentos certos**:
  - no início de `rebuild()`, dobra o arranjo on-screen atual no rig **antes** do clear — mas só
    se a árvore tiver nós (uma árvore vazia, recém-criada num arquivo onde o rig foi *appendado*,
    não pode sobrescrever o layout que veio junto);
  - handler `save_pre` carimba o layout de todo Peg Graph com nós no seu rig **antes de salvar o
    arquivo**, garantindo o caso de export (o append lê de um `.blend` já salvo).

## Alternatives Considered

### Campos nativos em DNA (`PegRigPeg.graph_location[2]`)
- **Pros**: nativo, sem JSON, sem ID-property "solta" aparecendo nas custom properties do rig.
- **Cons**: muda o formato de `.blend` (migração + bump de subversion); não tem casa natural para
  **frames** (que não são pegs) sem ainda mais DNA; viola "minimize divergência em C".
- **Why discarded**: o layout é metadado de UI, não dado de simulação — não justifica migração de
  formato. ID-property entrega o mesmo (viaja com o datablock) a custo zero de C.

### Guardar só no node tree (status quo) + tentar exportar a árvore junto
- **Pros**: posições já vivem nativamente no node tree.
- **Cons**: o usuário exporta o *rig*, não a árvore; arrastar o node tree junto exigiria amarrar
  os dois datablocks e ainda assim quebraria num append só do rig.
- **Why discarded**: não resolve o caso principal (export), que foi o pedido.

### Custom property por nó de peg (no peg) em vez de um snapshot único no rig
- **Cons**: nada para guardar posição do hub do rig nem dos nós de drawing (que são objetos), nem
  dos frames; espalharia o estado em N lugares.
- **Why discarded**: um único snapshot no rig é coeso e cobre todos os tipos de nó.

## Consequences

### Positive
- O arranjo do rigger sobrevive a Sync/Add Peg/auto-refresh, **inclusive nós dentro de frames**.
- Frames (F / *Join in New Frame*) e seu parenteamento são preservados e recriados.
- O layout **viaja com o rig** em append/link para outro arquivo.
- Zero mudança em C/DNA/RNA; sem migração de `.blend`.
- Validado headless no binário compilado: **15/15** asserts (posições mantidas no rebuild, frame
  recriado com label/cor/membros, e restauração num node tree novo simulando export).

### Negative / Trade-offs
- O snapshot aparece como uma custom property (`nuclear_peg_graph_layout`) no painel do rig —
  cosmético e até informativo, mas é estado de UI num datablock de dados.
- A captura roda no `rebuild()` e no `save_pre` (não a cada movimento de nó), então um arranjo
  movido e **não** salvo nem re-sincronizado só entra no rig no próximo save — suficiente para o
  caso de export (que passa por um save).

## Affected Files
- `scripts/startup/nuclear_peg_graph.py` (único arquivo de código; já registrado no
  `NUCLEAR_DIVERGENCE.md`)
- `docs/CHANGELOG.md`, `docs/decisions/2026-06-24-peg-graph-layout-persistence.md` (este)
