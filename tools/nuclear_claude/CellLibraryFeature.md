# CellLibraryFeature.md — Drawing Substitution + biblioteca de cells (estilo Toon Boom)

> Documento vivo. Plano + decisões de design da **substituição de desenhos (Drawing
> Substitution)** e da **biblioteca de cells** do Nuclear.
> Mantenha atualizado conforme a feature evolui.
>
> Última atualização: 2026-06-22.

---

## 1. O problema

No Toon Boom Harmony, um *element/coluna* guarda um conjunto de **drawings (cells)** —
ex.: as bocas de um lip-sync (A/E/I/O/U), poses de mão, blinks. Na timeline, a
**exposição** define qual cell aparece em cada frame, e o painel de *Drawing
Substitution* (slider + thumbnails) **troca rapidamente qual cell daquele element está
exposta no frame atual**, sem arrastar nada. É um dos workflows mais usados do cut-out.

O Blender tem o **Asset Browser**, mas ele é a ferramenta errada para isso:
- granularidade é **por ID** (objeto, node group…), e um *drawing* de Grease Pencil
  **não é um ID** — embrulhar cada cell num objeto/asset é desajeitado;
- o fluxo é "arrastar da biblioteca pra cena", não "scrubar a cell exposta no frame
  atual" — não bate o *feel* do slider do Harmony.

**Objetivo:** uma substituição de cell rápida (slider/atalhos) + uma biblioteca de cells
reutilizável **entre arquivos**, **sem** usar o Asset Browser.

> Duas coisas que o Harmony junta e que vale separar:
> 1. **Drawing Substitution** — troca, *dentro de um element*, qual cell está exposta no
>    frame atual. É o foco desta feature e é **quase 100% nativo** no GP v3.
> 2. **Library / Templates** — acervo reutilizável **entre cenas/arquivos**. No Blender
>    isso é **link/append de datablock** (nativo) — **não** é o Asset Browser.

## 2. Decisões de design (confirmadas com o autor, 2026-06-22)

| Eixo | Decisão | Consequência |
|---|---|---|
| **Escopo** | Biblioteca **cross-file** | Via **append de datablock GreasePencil** — sem Asset Browser, **sem ID novo** |
| **Storage** | **Coluna de cells** (modelo Harmony) | Cells = keyframes na layer do element; variantes não-expostas ficam em keyframes **fora do range de playback** da própria layer |
| **Importação** | **Cópia baked** (append) | `add_duplicate_drawings` — arquivo autossuficiente, **sem** link vivo; editar a biblioteca não propaga |
| **UI** | **Slider + atalhos primeiro** | Thumbnails são Fase 3 (não há infra de preview pra drawings hoje) |

**Achado decisivo (o que torna isto barato):** o modelo de dados do GP v3 já entrega a
substituição e o cross-file nativamente. **Não é preciso criar DNA/ID novo** (a opção
"datablock custom" foi descartada). Cross-file ≠ Asset Browser: GreasePencil é um **ID**,
logo é linkável/appendável entre arquivos de fábrica.

**Alternativas rejeitadas:**
- **Asset Browser por baixo com UI Harmony por cima:** drawings não são IDs; exigiria
  embrulhar cada cell num objeto/node-group. Desajeitado e contra o pedido do autor.
- **Datablock/ID "Drawing Library" custom (DNA novo):** modelo limpo e nomeável, mas C++
  pesado (DNA, RNA, versioning, I/O, depsgraph) e máxima divergência do upstream — viola a
  regra de **minimizar divergência em C**. Desnecessário dado que `DrawingReference` +
  append já cobrem cross-file.
- **Referência viva (`DrawingReference`):** considerada para o cross-file (editar a cell na
  biblioteca propagaria a todos os elements). Autor escolheu **cópia baked** por robustez e
  arquivo autossuficiente; então `DrawingReference` **não** é usado nesta feature.

## 3. Modelo de dados do GP v3 (verificado no código)

Citações no fork (`source/blender/...`). _Linhas aproximadas — derivam entre versões._

**Drawings vivem num array do ID GreasePencil:**
- `makesdna/DNA_grease_pencil_types.h:476-479` — `GreasePencilDrawingBase **drawing_array;
  int drawing_array_num;`. O ID **é dono** do array; cells são indexadas `0..num-1`.
- `:87-132` — `GreasePencilDrawingBase` (campo `type`: `GP_DRAWING=0` /
  `GP_DRAWING_REFERENCE=1`), `GreasePencilDrawing` (tem `CurvesGeometry geometry`),
  `GreasePencilDrawingReference` (tem `GreasePencil *id_reference` → aponta para OUTRO
  datablock GP; não usado aqui, mas é a base nativa de cross-file por referência).

**Frame → drawing por índice; múltiplos frames podem COMPARTILHAR a mesma cell:**
- `:148-168` — `GreasePencilFrame { int drawing_index; ... }`.
- `blenkernel/intern/grease_pencil.cc:3151` — em `insert_duplicate_frame`,
  `do_instance ? src.drawing_index : <novo índice>`. Com `instance=true` os dois frames
  apontam pro **mesmo** drawing (instancing); `add_user()` no `:3159`.
- Refcount atômico por drawing: `BKE_grease_pencil.hh:844-862` (`add_user`/`remove_user`/
  `is_instanced`/`user_count`); recomputado em `grease_pencil.cc:182`
  (`count_frame_users_for_drawings`).

**É a substituição inteira:** trocar a cell exposta = re-expor outra cell por *instancing*.
⚠️ **Verificado 2026-06-22:** `frame.drawing = outra` **COPIA** a geometria (deixa o frame
independente — `user_count` não sobe), então **não** serve pra compartilhar cells. O que
instancia de verdade é **`frames.copy(..., instance_drawing=True)`** (uc sobe pra 2). A
substituição usa `frames.copy` (remove o key exato se já existir, depois copia-instancia);
`frame.drawing =` é usado **só** pra semear uma cell nova a partir da exposta (aí a cópia é
desejada).

**Criar/duplicar/limpar cells (BKE):**
- `grease_pencil.cc:3045` `add_empty_drawings(n)`; `:3058` `add_duplicate_drawings(n,
  drawing)` (cópia independente — base da **cópia baked** da Fase 2); `:3287`
  `remove_drawings_with_no_users()` (compacta o array e remapeia `drawing_index`).
- ⚠️ **Persistência:** um drawing só sobrevive enquanto `user_count > 0` (`:3313`). Logo as
  variantes **não-expostas precisam de um "banco"** que as segure (ver §4).

**RNA / Python já exposto (a base da Fase 1, sem C++):**
- `makesrna/intern/rna_grease_pencil.cc:821` — `frame.drawing` é ponteiro **read-write**
  (`rna_Frame_drawing_get`/`_set`). `drawing_index` cru **não** é exposto — operamos por
  `frame.drawing`. `:755` — `drawing.user_count` (read-only).
- `makesrna/intern/rna_grease_pencil_api.cc:344` `frames.new(n)`; `:365`
  `frames.remove(n)`; `:388` `frames.copy(from, to, instance_drawing)` (com
  `instance=True` = compartilha a cell); `:415` `frames.move(from, to)`.
- `layer.frames` é coleção iterável/indexável (`:128-160`). **Trabalhamos via `frames`**
  (totalmente exposto), evitando precisar de uma coleção `gp.drawings` crua na Fase 1.

**Thumbnails: não há infra.** Nenhum `PreviewImage`/preview pra drawings de GP no código.
Thumbnails exigiriam render GPU offscreen por cell + cache — por isso ficam pra Fase 3 e a
UI começa por slider/atalhos.

## 4. Como funciona

**Modelo "coluna de cells" (decisão de storage).** As cells de um element vivem como
keyframes da **própria layer**. A cell exposta num frame de animação é o drawing que
aquela keyframe referencia.

**Banco fora-de-range.** Para as variantes não-expostas persistirem (precisam de
`user_count > 0`), elas ficam como keyframes em um **intervalo de frames fora do range de
playback** da mesma layer (ex.: a partir de um `BANK_START` alto/negativo). Isso honra o
modelo "tudo na mesma layer" do Harmony, mantém storage nativo, aparece no dope sheet, e
não é coletado como órfão. A animação no range usa frames que **instanciam** (compartilham)
os drawings do banco.

**Adotar = nunca perder o desenho solto (fix 2026-06-22).** Um desenho já feito é um
keyframe normal **fora do banco** (`user_count` 1). Expor uma cell por cima dele o
**purgaria** (bug reportado: "ao adicionar a 1ª cell perdíamos o desenho"). Primitivo de
correção `ensure_current_banked`: se o desenho exposto **não** é cell ainda, **instancia-o**
no banco (`frames.copy(instance_drawing=True)` — cópia zero, compartilhado). É o "vincular um
desenho existente como cell". Está (a) embutido como **proteção automática** no início de
`expose_cell` e do Add (qualquer troca banca o atual antes), e (b) exposto como operador
`nuclear.cell_adopt` / botão **"Link Current Drawing"** (aparece quando o exposto não é
cell). O Add adota o atual **primeiro** (vira a cell anterior) e só então cria a nova.

**Substituir = re-expor.** Trocar a cell no frame atual via instancing:
`layer.frames.copy(from_frame_number=bank_k, to_frame_number=frame_atual,
instance_drawing=True)` (removendo antes o key exato em `frame_atual`, se houver). O
refcount cuida-se sozinho (a cell anterior cai pra `user_count` 1, a nova sobe pra 2). A
detecção de "qual cell está exposta" é por **`drawing.as_pointer()`** (instancing →
mesmo ponteiro do banco). ⚠️ **Não** usar `frame.drawing = …` para isso (copia).

**Cross-file (cópia baked, Fase 2).** A biblioteca é um (ou mais) **datablock
GreasePencil** numa `.blend` de acervo (cada um um "cell set", ex.: "Bocas"). Importar =
**append** do datablock + **copiar** os drawings desejados pro element. A cópia
cross-datablock é feita por `nf.drawing = src_gp.frame.drawing` (cópia baked completa,
**verificada** — sem precisar de C++; ver Fase 2 em §5).

### Persistência no append do rig (VERIFICADO 2026-06-22 — load-bearing pro pipeline)
O pipeline do autor distribui rigs por **append** (cria o rig em `PERSONAGEM_A.blend`,
coloca na cena via append). As cells, por serem **keyframes do banco dentro do datablock
GreasePencil** (referenciando o `drawing_array` do próprio datablock), **viajam junto no
append**: append copia o datablock inteiro (drawings + frames + instancing). Teste headless
(build→save→append em arquivo limpo): 3 cells sobrevivem, geometria distinta intacta, e a
exposição por instancing é preservada (`user_count` 2). **Zero dependência externa, zero
link quebrado** — o rig é autossuficiente. É exatamente por isso que **cópia baked é a
escolha certa**: link vivo (`DrawingReference`) tornaria o append frágil (a `.blend` da
biblioteca teria de estar acessível em toda cena).

### Reuso da biblioteca entre personagens (semântica)
A biblioteca compartilhada (ex.: `BOCAS.blend`) é uma **fonte de autoria**: carimba-se cells
dela em cada personagem; cada um fica com **cópia independente** (sem colisão — drawings não
são IDs nomeados; só os datablocks GP têm nome, distintos por personagem). Depois de
carimbada, a cell faz parte do rig e anda no append. Trade-off inerente ao baked: editar a
biblioteca **não** propaga a rigs já montados (futuro "Refresh from Library", opcional).
Implicação: a biblioteca é ferramenta de autoria, **não** dependência de runtime → a Fase 2
só precisa **copiar drawings da GP-biblioteca p/ a GP-personagem**, sem link/override/path.

## 5. Faseamento

### Fase 1 — Drawing Substitution por-element (Python puro, **zero C++**)
Testável já no Blender vivo (BlenderMCP TCP `127.0.0.1:9876`), sem rebuild.
- Operadores `*_cell_next` / `*_cell_prev` / `*_cell_set(i)`: reescrevem a cell exposta no
  frame atual (`layer.frames` + `frame.drawing`).
- Banco fora-de-range na própria layer; exposição por instancing.
- UI: slider "cell X/N" + prev/next + atalhos no N-panel/header.
- Novo startup `scripts/startup/nuclear_cell_library.py` (arquivo novo → divergência ~zero).

### Fase 2 — Biblioteca cross-file (cópia baked) — **FEITA, Python puro, ZERO C++**
- ⚠️ **Reviravolta (verificado 2026-06-22):** `frame.drawing = outra_gp.frame.drawing` faz
  cópia **completa de CurvesGeometry ENTRE datablocks** (geometria + `material_index` +
  `cyclic` + `radius` + todos os atributos), independente da fonte. Fidelidade testada
  headless. **Logo o "helper C++" previsto NÃO é necessário** — a Fase 2 inteira é Python.
- `.blend` de acervo = um datablock GP "cell set" (cells como keyframes numa layer).
- **Import:** `bpy.data.libraries.load(filepath, link=False)` appenda o datablock GP; para
  cada frame da layer-fonte cria um bank frame no element e `nf.drawing = src.drawing`
  (baked); remove o datablock temporário; remap de `material_index` por **nome** (append do
  que falta, dedup do que colide, purga de `.001` órfão).
- **Export:** monta um GP temporário com as bank cells (drawings baked + materiais p/
  preservar índices) e `bpy.data.libraries.write(filepath, {tmp})`.
- Funções em `nuclear_cell_library.py`: `material_remap`, `import_cells_from_layer`,
  `import_cells_from_file`, `export_cells_to_file`; operadores `nuclear.cells_import` /
  `nuclear.cells_export` (file browser); box "Library" no N-panel "Cells".

### Fase 3 — Thumbnails (adiado; maior esforço)
- Render GPU offscreen por cell → cache (em `DrawingRuntime` ou `PreviewImage`) → tira de
  miniaturas estilo Harmony. Fora do caminho crítico.

## 6. Arquivos

**Novo (divergência isolada) — TUDO em 1 arquivo, Python puro:**
- `scripts/startup/nuclear_cell_library.py` — substituição (Fase 1) + import/export da
  biblioteca (Fase 2). **Nenhuma costura em C** (o helper C++ previsto foi dispensado: ver
  Fase 2). Risco de merge ~zero.

Naming: operadores `nuclear.cell_*` / `nuclear.cells_*`; UI "Drawing Substitution" / aba
"Cells". (Startup com prefixo de identidade `nuclear_*`.)

## 7. Verificação

Build (só se a Fase 2 entrar): `distrobox enter blender -- bash -lc 'cd .../Nuclear/build
&& ninja && ninja install'`. Teste via BlenderMCP TCP `127.0.0.1:9876` (**nunca**
`script.reload()` na sessão de produção — ver `build-and-test-env`).

1. **Fase 1 (headless/live):** num objeto GP com uma layer, criar N cells no banco
   (frames fora-de-range, cada um com geometria distinta); expor uma no frame atual;
   rodar `cell_next`/`cell_prev`/`cell_set` e conferir que `current_frame.drawing` muda pra
   a cell certa e que `drawing.user_count` sobe (instancing, sem cópia).
2. **Fase 1 (GUI):** scrubar o slider / atalhos e ver o desenho trocar no viewport no
   frame atual, sem afetar outros frames.
3. **Fase 2 (headless 7/7 PASS):** `export_cells_to_file` → `.blend`; em arquivo limpo com
   um material de mesmo nome (colisão), `nuclear.cells_import` → cells copiadas, geometria
   íntegra, material colidente **deduplicado** (sem `.001` órfão), material novo appendado,
   `material_index` remapeado pro slot certo, re-import é **baked** (adiciona, não linka).

## 8. Status

- **2026-06-30 — Fix: biblioteca trata cada parte SEPARADAMENTE (conserta o "dois olhos
  como um só ao dar o append"). VALIDADO COM ARQUIVOS REAIS + GUI.**
  Bug: todo o módulo opera por objeto/grupo, **menos** os operadores de import/export, que
  usavam só `context.object.data` (um objeto). Com dois olhos (dois objetos GP separados, o
  caso real do autor — **sem** cell group), a biblioteca os colapsava num só no append: ou só
  o olho ativo era exportado/preenchido, ou as layers dos dois acabavam empilhadas num objeto
  (sintoma visível nos arquivos reais: `PELE.001`, `2L-OLHOS.001/.002/.003`). Fix (Python
  puro, sem C):
  - Novo `library_objects(context)` define o escopo da biblioteca: a cell group do ativo se
    houver, **senão os objetos GP SELECIONADOS** (o artista seleciona os dois olhos). Não
    depende mais de marcar grupo.
  - `export_group_set` escreve **um datablock GP por objeto** (`<set>__<base>`), marcado com
    `CELL_OBJ_PROP` (base name) + `CELL_ORDER_PROP` (ordem).
  - `import_group_set` **roteia** cada datablock pro objeto de destino pelo base name
    (fallback posicional quando os nomes divergem). Layers casadas por nome (cria as que
    faltam). 0-importado (tudo já presente) é no-op silencioso, **não** erro.
  - Operadores `cells_import`/`cells_export` usam o caminho multi-objeto quando
    `len(library_objects) > 1` + `all_layers`; objeto solto e libs antigas seguem idênticos.
    Painel mostra "N parts (kept separate)".
  Validação headless: grupo 10/10, ungrouped/seleção 9/9, **dados reais 10/10** (export do
  `olho.b.e`+`olho.b.d` de `biblioteca.zip`: 2 datablocks separados, cada olho repreenchido
  com suas 6 layers, round-trip exato dos frames de bank, sem duplicar layers, idempotente).
  GUI validada pelo autor ("está funcional"). **Falta:** empacotar num release (o bin
  instalado de produção ainda tem a versão antiga).

- **2026-06-22:** design aprovado (§2), modelo de dados verificado (§3). **Fases 1 e 2
  IMPLEMENTADAS e validadas headless** (Fase 1 18/18, Fase 2 7/7), tudo em
  `scripts/startup/nuclear_cell_library.py`, **Python puro, ZERO C++, sem rebuild**.
  - Fase 1: banco fora-de-range, substituição por instancing (`frames.copy`), slider no
    N-panel "Cells", `nuclear.cell_step`/`cell_add`/`cell_delete`, keymap `[`/`]`.
  - **Fix anti-perda (11/11 PASS):** `ensure_current_banked` + `nuclear.cell_adopt` ("Link
    Current Drawing") — desenho solto nunca é purgado ao expor cell; Add adota o atual antes.
  - **Fix delete (9/9 PASS):** ao deletar a cell exposta, troca a exposição p/ uma vizinha
    ANTES de remover (senão o auto-protect re-bancava a deletada); deletar a última deixa o
    desenho como loose (arte preservada).
  - Fase 2: `nuclear.cells_import`/`cells_export` (cópia baked cross-file via
    `frame.drawing=` + `libraries.load/write`, remap de material por nome).
  - Persistência no append do rig verificada (cells viajam junto).
  - Sincronizado pro `bin/5.0/scripts/startup/`. **Falta:** validar GUI ao vivo
    (slider/atalhos + file browsers de import/export — instância separada do binário, nunca
    `script.reload()` na produção; ver `build-and-test-env`).
  - **Fase 3 (thumbnails)** segue planejada/adiada.

## 9. Evolução futura

- Thumbnails (Fase 3) e tira de miniaturas estilo Harmony.
- Cells **nomeadas** (hoje a coluna usa índice/nº de frame; um nome por cell ajuda
  lip-sync — exigiria mapa nome→cell, possivelmente custom property na layer).
- Integração no **Peg Graph** (um nó/widget de substituição por element).
- Reuso **cross-object** dentro do personagem (mesmas cells em vários objetos) — hoje cada
  element tem suas cópias; instancing entre objetos exigiria `DrawingReference`.
- Export do element atual → biblioteca (`.blend` de acervo).

Relaciona-se com `NUCLEAR_DIVERGENCE.md`, `CLAUDE.md` (regra de isolar divergência), o
sistema de pegs (`SquashFeature.md`, PegRig) e `CutterFeature.md`.
</content>
</invoke>
