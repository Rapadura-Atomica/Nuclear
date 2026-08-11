# Registro de Divergência — Nuclear (fork de Blender 5.0.0)

> Documento vivo. Lista toda a divergência deste fork em relação ao Blender upstream.
> **Estratégia de sync: rebase a cada release** (5.0 → 5.1 → …). Este arquivo é o
> checklist a percorrer em CADA subida de versão.
>
> Princípio: divergência em **arquivos novos** tem risco de merge ~zero; divergência
> **dentro de arquivos do upstream** ("pontos quentes") conflita e precisa ser revista
> a cada rebase. Manter o máximo de divergência futura na forma de arquivos novos.
>
> _Os números de linha são aproximados (capturados no levantamento) e tendem a
> derivar entre versões — use-os como pista, não como verdade._

---

## 1. Arquivos NOVOS (risco de merge ~zero)

Adicionados pelo Nuclear; o upstream não os conhece, então não conflitam. Só exigem
revisão se as APIs do core que eles consomem mudarem.

### Sistema PegRig (rig por "pegs", estilo cut-out)
- `source/blender/makesdna/DNA_pegrig_types.h` — tipos `PegRig`, `PegRigPeg`
- `source/blender/makesdna/DNA_pegrig_defaults.h` — defaults de `PegRig`
- `source/blender/blenkernel/BKE_pegrig.hh` — API pública do peg rig
- `source/blender/blenkernel/intern/pegrig.cc` — implementação (criação/pegs/world matrices/anim)
- `source/blender/editors/object/object_pegrig.cc` — operadores `object.pegrig_*`
- `source/blender/editors/transform/transform_convert_pegrig.cc` — redireciona transform de objetos bound para seus pegs
- `source/blender/makesrna/intern/rna_pegrig.cc` — RNA de `PegRig`/pegs

### Modifier Grease Pencil "Curve" (deform arc-length, estilo Toon Boom)
- `source/blender/modifiers/MOD_grease_pencil_curve.hh`
- `source/blender/modifiers/intern/MOD_grease_pencil_curve.cc` — + botões **Reset All / Reset Selected** no painel (operador `OBJECT_OT_greasepencil_curve_reset`).
- `source/blender/editors/object/object_modifier.cc` — operadores `OBJECT_OT_greasepencil_curve_setup` + `..._curve_bind` + **`..._curve_reset`**. O reset usa a custom-prop `nuclear_curve_rest` (array float, 9 por ponto Bézier) carimbada na **Deform Curve** na criação (`curve_store_rest`) e refeita no Bind; modos `ALL` (curva inteira) e `SELECTED` (pontos selecionados via flags `f1/f2/f3` do `BezTriple`, knot também reseta handles), escreve em `editnurb` no Edit Mode / `cu->nurb` no Object Mode; `OPERATOR_PASS_THROUGH` quando nada selecionado (preserva Alt+R nativo). Decls em `object_intern.hh`, append em `object_ops.cc`.
- `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` — `_register_curve_reset_keymap`: Alt+R no keymap `Object Mode` (mode=`ALL`) e `Curve` edit-mode (mode=`SELECTED`).

### Modifier Grease Pencil "Cutter" (máscara cross-object, estilo Toon Boom — ver `CutterFeature.md`)
- `source/blender/modifiers/intern/MOD_grease_pencil_mask.cc` — injeta as strokes do objeto-matte
  como layer oculta (opacity 0) na GP avaliada e liga uma `GreasePencilLayerMask` nativa, para
  recortar um objeto pela silhueta de outro (ex.: pupila dentro do olho). Sem `.hh` (sem helper
  compartilhado nem operator). Reaproveita 100% do pipeline de máscara nativo (sem mexer no
  draw engine).

### Modifier Grease Pencil "Contour" / Envelope (deform MVC + cage Bézier, estilo Toon Boom)
- `source/blender/modifiers/MOD_grease_pencil_contour.hh` — `contour_sample_cage()` compartilhada (modifier + operadores)
- `source/blender/modifiers/intern/MOD_grease_pencil_contour.cc` — modifier Contour (MVC, cage mesh ou Bézier, bind)

### Add-on Storyboard & Animatic (empacotado desde a 1.7.8/b21)

- `scripts/addons_core/nuclear_storyboard/` — **cópia** do add-on; o repositório-fonte é
  `~/Documentos/GitHub/nuclear-storyboard` (sem remote até aqui). Sincronizar SEMPRE por
  `python3 make_release.py --para-o-nuclear <repo do Nuclear>` de lá, que usa a mesma
  lista de arquivos do zip (sem testes, sem `__pycache__`) e apaga o destino antes de
  copiar — arquivo que saiu do add-on continuaria aqui e viajaria no release.
  ⚠️ **A cópia empacotada GANHA do symlink de desenvolvimento** em
  `~/.config/Nuclear/5.0/scripts/addons/`: depois desta mudança, um Nuclear buildado
  carrega o add-on de dentro dele, não do repositório. Editar o repo e não ver efeito no
  binário é o esperado — falta o sync. **Não cria ponto quente na §2**, mas veja o
  `blendfile.cc` abaixo (nasce habilitado) e a aba do Properties na §2.

### Add-ons / scripts de startup
- `scripts/startup/nuclear_curve_gizmo.py` — gizmos de deform de curva no viewport
- `scripts/startup/nuclear_peg_graph.py` — node editor da hierarquia de pegs (+ `compute_grouped_layout` / operador `node.nuclear_peg_auto_layout` "Auto Layout": agrupa o grafo em frames por região do corpo — Braço D/E, Cabeça, Perna D/E, Tronco, Soltos — empacotados horizontalmente, derivados da hierarquia)
- **Overlay de seleção do rig no viewport** (`nuclear_peg_graph.py`, 2026-08-05) — a peg e o objeto
  passam a ter CORES DIFERENTES, no esquema do Harmony: **verde = peg** (o pivô, as outras pegs e a
  arte que ela move) e **azul = objeto selecionado** (o outline nativo, que o tema Nuclear já pinta
  de azul). Antes o overlay da peg usava `(0.16, 0.58, 1.00)` contra uma seleção de tema
  `(0.15, 0.55, 1.00)` — a MESMA cor, então não havia distinção nenhuma para o artista fazer.
  Junto, três correções na forma que a peg mostra:
  (1) lê o objeto **avaliado**, então Deform Curve/Contour/qualquer modifier e a troca de célula da
  Cell Library entram — lendo `ob.data` a forma ficava onde o desenho estava ANTES de deformar
  (medido: 1,95 unidade de erro no `rabo` do dinossauro);
  (2) o contorno deixou de ser um **convex hull** (que numa mão atravessa por cima dos dedos e numa
  boca tapa a abertura) e passou a ser o **próprio traço do desenho**, exato por construção e uma
  marca de tipo diferente do outline fino, que é o que separa peg de objeto ao olhar;
  (3) respeita **masks**: camada coberta por matte do mesmo objeto é pulada (mesmo critério do
  `layer_is_covered_by_own_mattes` em C++, com as mesmas recusas — cross-object, invertida,
  Auto-Patch, matte que não desenha, e a salvaguarda de masks encadeadas), e o caso **cross-object**
  é RECORTADO de verdade contra a área do matte (rasteriza o matte numa grade de tela, inunda o
  exterior, o que sobra é o interior). Medido: sem o filtro, 36% do traço realçado do dinossauro
  estava sob mask; `detalhe.torso` corta 51%, `antebraco.e` 64%, e as pupilas 0% (estão inteiras
  dentro do olho — o controle de que não corta o que não deve).
  Custo: 182 ms → **1,4 ms** por redraw (leitura em bloco via `foreach_get`/`curve_offsets` +
  projeção NumPy; peça com modifier nunca é cacheada, porque deforma sem mexer em `matrix_world`).
  ⚠️ O `_load_post` **tem** que continuar `@bpy.app.handlers.persistent`: sem o decorador o handler
  é descartado ao carregar arquivo e todo o `_load_post` do peg_graph morre em silêncio (keymap do
  Ctrl+B, msgbus da peg ativa, limpeza de caches). Ele também liga `show_outline_selected` (com um
  tick de atraso, senão as screens ainda são as do arquivo anterior): esse flag é salvo DENTRO do
  arquivo e os rigs de produção foram gravados com ele off, o que deixava só o verde na tela.
- `scripts/startup/nuclear_squash_gizmo.py` — gizmos de squash & stretch (anchor/tip) no viewport
- `scripts/startup/nuclear_cell_library.py` — Drawing Substitution (Fase 1): banco de cells fora-de-range + slider/atalhos (ver `CellLibraryFeature.md`)
- `scripts/startup/nuclear_rig_auto.py` — Auto Rig ("esqueleto auto + ligação em lote"): operador `object.nuclear_rig_auto_skeleton` (casa peças por nome contra ontologia humanoide PT → monta espinha+membros num clique; não-casados ficam soltos) + `object.nuclear_rig_link_to_parent` (prende os selecionados sob o peg do ativo, padrão parent-to-active) + painel `VIEW3D_PT_nuclear_rig_auto` (aba "Rig"). Junta/pivô sempre geométrica (centróide da sobreposição filho∩pai). Python puro sobre a API de PegRig; refino no Peg Graph. Padrão do estúdio: **toda peça ganha uma peg** (não-reconhecidas viram peg raiz no composite). Validado headless vs `Carolina.blend` (56 pegs = 15 esqueleto + 41 acessório, pivôs nas juntas). Sem tool de toolbar (não edita `space_toolsystem_toolbar.py`). Doc: `tools/nuclear_claude/RigAutoFeature.md` (inclui a convenção de nomes). **Não cria ponto quente novo na §2.**
- `scripts/startup/nuclear_deform_curve.py` — **Deform Curve** (painel `VIEW3D_PT_nuclear_deform_curve`, aba "Rig"): fecha o fluxo da curva de deformação que era feito à mão/por scripts soltos. `object.nuclear_curve_fit` (mede o DESENHO pelos pontos — `dimensions` mente porque já vem deformado — e assenta a curva ponta a ponta, criando-a pelo operador nativo `greasepencil_curve_setup` quando não existe; `keep_shape` só escala/recentra, preservando a silhueta que o artista deu), `object.nuclear_curve_bind` (bind/rebind em lote; **remove o parent que o bind em C acrescenta quando a curva já segue uma peg**, senão ela é transformada duas vezes), `object.nuclear_curve_link_peg` (peg `<junta>_curva` entre a junta e os filhos + drivers de translação/rotação lidos da ponta da curva = o que o `curva_para_peg.py` fazia à mão), `object.nuclear_curve_refresh` (recarimba o rest dos drivers depois de mexer nos pontos — sem isso o membro solta do corpo) e `object.nuclear_curve_check` (relatório read-only: sem bind, bind colapsado, curva sobrando/curta, dupla transformação, peg não ligada, rest velho). Todos desligam Auto Key durante a edição (ligado por padrão nos arquivos do DPE, keya e reverte a edição em silêncio) e rebuildam o Peg Graph. Python puro sobre PegRig + os operadores C de bind. Validado headless no rig real `dinossauro_gigante_pegs.blend` (5 curvas sem bind achadas, braço passou de `u=[0,0]` degenerado a `u=[0.02,0.98]`, curva nova+peg na coxa, tudo sobrevivendo ao save/reload). Doc: `tools/nuclear_claude/DeformCurveFeature.md`. **Não cria ponto quente novo na §2.**
- `scripts/startup/nuclear_telemetry.py` — telemetria de presença (→ rapaduraatomica.com.br)
- `scripts/startup/nuclear_theme.py` — aplica o tema Nuclear (navy + "pill"/roundness) **globalmente** via `@persistent load_post` handler + apply no register, para que TODOS os templates (Nuclear, 2D Animation, Storyboarding) compartilhem a identidade — antes o tema morava só no `Nuclear/__init__.py` (Seam 6) e era revertido ao trocar de template, deixando 2D Animation/Storyboarding cinza. Só dado de tema (inclui `roundness` por widget), zero C. O bloco Seam 6 foi removido do `__init__.py` (dono único agora é este arquivo). **Não cria ponto quente na §2.**
- `scripts/startup/nuclear_paint_toolkit.py` — kit de pintura GP na **tab Paint** (`bl_context="paint"`, ver §2): painéis Brushes (categorias + preview + toggle Smudge), Color (picker + swatches recentes via Palette), Size (px), Stabilizer, Symmetry (espelho ao vivo por dados). Timer captura cor pintada + default px; `load_post` default VertexColor. **Cria pontos quentes na §2** (a tab e o picker precisam de C).

### Application Template Nuclear (a "costura" de UI — P0/P1/P2)
- `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` — seam central. Contém:
  - **Seam 1 (tradução):** `_TRANSLATIONS` (branding Blender→Nuclear, locale en_US) +
    `_ensure_interface_translation` (força `use_translate_interface`/`language`).
  - **Seam 2 (classes):** `_HIDDEN_CLASS_NAMES` (esconde por nome, reversível — inclui os
    `MATERIAL_PT_gpencil_*` verbosos p/ a aba Color ficar compacta) / `_NUCLEAR_CLASSES`
    (`NUCLEAR_MT_logo`, `NUCLEAR_MT_view`, `NUCLEAR_OT_set_area_tab` = troca tipo de editor,
    `NUCLEAR_MT_add_tab` = menu "+", `NUCLEAR_PT_color_palette` + `NUCLEAR_UL_color_palette` =
    paleta Color limpa (swatch arredondado + nome renomeável; sem ghost/hide/lock nem Stroke/Fill),
    `NUCLEAR_OT_palette_add` = "+" da paleta que cria um material GP real (não slot vazio — senão
    não dava p/ editar)).
  - **Seam 3 (header overrides — Fase A):** troca em runtime métodos de header e restaura no
    `unregister` (`_orig_draws`): `TOPBAR_MT_editor_menus.draw` (menu curado File/Edit/View/
    Render/Help, sem Blender/Window), `TOPBAR_HT_upper_bar.draw_left` (logo Nuclear clicável →
    `NUCLEAR_MT_logo` + esconde abas de workspace), `VIEW3D_HT_header.draw` (mode selector + toggle **Onion** via `overlay.use_gpencil_onion_skin`),
    `DOPESHEET_HT_header.draw` (Fase C: no modo GPENCIL desenha o transporte minimal Nuclear —
    Mute/Scrub, +KF/−KF, REW/Play/FF, Frame/Start/End; outros modos caem no original).
    `_update_startup_timeline` força `DOPESHEET_EDITOR.mode='GPENCIL'` (camadas + keyframes).
    `VIEW3D_HT_tool_header.draw` (Fase E: barra ADDONS **dinâmica** — `_sidebar_categories`
    enumera as categorias do N-panel e `popover_group` traz cada uma pro header; cresce/encolhe
    com os addons. Ex.: categoria "Peg" do PegRig aparece sozinha).
  - **Properties (Fase D):** `_update_startup_properties` usa os toggles nativos
    `SpaceProperties.show_properties_*` (importa `bl_ui.space_properties.tab_list`) p/ manter só
    Tool/Object/Modifiers/Effects/Data/Material e esconder o resto. Paleta Color = aba Material.
  - **Abas do painel direito (Fase D — 100%):** `_draw_nuclear_tabs` prependado (via Seam 3)
    nos headers `PROPERTIES_HT_header`/`IMAGE_HT_header`/`NODE_HT_header`/`FILEBROWSER_HT_header`
    → strip Properties/Reference/Library/Color/Node + "+". `NUCLEAR_OT_set_area_tab` troca
    `area.ui_type`. Cada área-direita é independente (2 áreas = 2 boxes do mockup). Mesmo aviso
    de acoplamento de runtime (nomes dos headers + enum `ui_type`).
  - **Abas por-box sem DNA:** `_TABSETS` (main/shading/all) + `_assign_tabsets` (atribui por
    posição da área no load) + `_resolve_tabset` (por índice) + `_apply_default_tabs` (parkeia
    cada box na 1ª aba: main→Properties/Tool, shading→Color/Material). Dá os subconjuntos
    distintos do mockup sem custom data na `ScrArea` (sem mudança de formato de arquivo).
  - **Seam 4 (toolbar — Fase B):** troca reversível da entrada `'PAINT_GREASE_PENCIL'` de
    `VIEW3D_PT_tools_active._tools` (dict de classe salvo em `_orig_tools`, restaurado no
    `unregister`). Set curado: brush/borracha/balde/grupo-linha/eyedropper. Mesmo aviso de
    acoplamento de runtime do Seam 3 (depende de `VIEW3D_PT_tools_active._tools` e dos defs
    `_defs_grease_pencil_paint.*` do upstream — se sumirem, deixa o toolbar nativo intacto).
  - **Logo:** `nuclear_logo.png` carregada via `bpy.utils.previews` (load no `register`,
    unload no `unregister`).
  - **Canvas (Fase A):** `_update_startup_canvas` trava VIEW_3D na câmera e esconde
    floor/eixos/grid/cursor/gizmos (overlays GP ficam).
  - **Seam 7 (Xsheet Toon Boom):** mapeia X pelo **view2d nativo** (`region.view2d` via
    `_xsheet_fx`/`_xsheet_layout`) → células/agulha alinham com a régua e o indicador de frame
    nativos (que é desenhado por cima e não dá p/ cobrir); ganha scroll/zoom nativos. Canais
    nativos escondidos (`show_region_channels=False`) p/ não duplicar a coluna de camadas.
    `_xsheet_draw` (draw_handler POST_PIXEL em
    `SpaceDopeSheetEditor`/WINDOW, gated a modo GPENCIL + objeto GP) desenha em GPU a grade
    camada×frame: célula cheia=exposição, marca forte no keyframe, barra de hold, régua+playhead+
    nomes. Cobre o Dope Sheet nativo com fundo opaco. `_enable_xsheet`/`_disable_xsheet` no
    register/unregister. Imports `gpu`/`blf`/`gpu_extras` guardados (`_GPU_OK`). **T2:** realce
    camada ativa/coluna do frame + vis/lock. **T3:** `NUCLEAR_OT_xsheet_click` (LEFTMOUSE) p/
    clique→frame/camada, scrub e toggles vis/lock (poll/hit em `_xsheet_poll`/`_xsheet_hit`).
    **T4:** `NUCLEAR_OT_xsheet_toggle` (Ctrl+LEFTMOUSE) cria/apaga exposição via
    `layer.frames.new/remove`, UNDO, respeita lock. **T4.1:** `NUCLEAR_OT_xsheet_drag`
    (Alt+arrastar=mover `frames.move`; Shift+Alt=duplicar `frames.copy`; ghost via `_xsheet_drag`).
    **T5:** nº do desenho na célula + linha de grupo a cada 5 frames. Keymap Dopesheet = 4 itens.
    **Falta T5.1** (seleção/nome custom).
    nos grupos de widget e backgrounds dos editores; originais salvos em `_THEME_BACKUP` e
    restaurados no `unregister`. **O look pílula/arredondado é TEMA (dado), não C** — não houve
    edição de `interface_widgets.cc`. (Tema é pref global; o template aplica/reverte ao ativar.)
  > ⚠️ **Acoplamento de runtime (não é conflito de merge, mas vigiar no rebase):** os
  > monkeypatches do Seam 3 dependem dos nomes de classe (`TOPBAR_MT_editor_menus`,
  > `VIEW3D_HT_header`) e da assinatura de `draw` do upstream. Se o upstream renomear/
  > refatorar esses headers, os overrides param de aplicar (degradam de forma silenciosa,
  > não quebram). Conferir a cada subida de versão.
- `scripts/startup/bl_app_templates_system/Nuclear/startup.blend` — **regenerado (2026-06-12)**
  a partir do 2D_Animation: OUTLINER→PROPERTIES (2 boxes Properties à direita), dopesheet
  GPENCIL c/ footer off, viewport na câmera. Backup do base em `Nuclear-git/nuclear_startup_2Dbase.blend.bak`
- `scripts/startup/bl_app_templates_system/Nuclear/nuclear_logo.png` — logo (de `~/nuclear.svg`,
  256×256) mostrada no canto do topbar

### Squash & Stretch (extensão do PegRig — ver `SquashFeature.md`)
Feita **inteiramente dentro de arquivos do fork que já existem** + um startup novo
(`nuclear_squash_gizmo.py` acima). **Não cria nenhum ponto quente novo na §2.**
- `DNA_pegrig_types.h` — campos `squash_anchor/tip/rest_len/volume` + flag `PEGRIGPEG_SQUASH`
- `pegrig.cc` — defaults inertes em `peg_add` + a math (gated) em `pegrig_peg_local_matrix`
- `rna_pegrig.cc` — `use_squash`, `squash_*` e `matrix_world` (read-only)
- `object_pegrig.cc` — `object.pegrig_squash_enable` / `object.pegrig_squash_reset_rest`
- `nuclear_peg_graph.py` — box "Squash & Stretch" no painel Active Peg + badge no nó do peg


### Meta / contexto de projeto (docs do fork)
- `CLAUDE.md` (raiz) — ponteiro fino que importa `tools/nuclear_claude/CLAUDE.md`
- `tools/nuclear_claude/CLAUDE.md` — contexto canônico do projeto (sincronizado entre máquinas)
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — este registro
- `tools/nuclear_claude/NUCLEAR_UI_LAYOUT.md` — spec do P2 (layout-alvo do mockup)
- `tools/nuclear_claude/CellLibraryFeature.md` — plano da Drawing Substitution + biblioteca de cells (estilo Toon Boom)
- `tools/nuclear_claude/readme.txt` — notas para devs humanos

> **Diretriz:** novas features Nuclear devem nascer aqui (arquivos `*_pegrig.*`,
> `*_nuclear*`, `nuclear_*.py`, novos modifiers), não como edições espalhadas.

---

## 1b. Arquivos do upstream REMOVIDOS (reaparecem no rebase — re-remover)

Deleções de arquivos que o upstream mantém. No rebase eles voltam e precisam ser
removidos de novo. (Não removem funcionalidade — apenas presets de workspace.)

- `scripts/startup/bl_app_templates_system/Sculpting/` — template removido (desnecessário ao build 2D)
- `scripts/startup/bl_app_templates_system/VFX/` — template removido
- `scripts/startup/bl_app_templates_system/Video_Editing/` — template removido

> Templates mantidos: `2D_Animation` (base do Nuclear), `Storyboarding`, `Nuclear`.

---

## 2. PONTOS QUENTES — edições dentro de arquivos do upstream (CONFLITAM no rebase)

Cada item abaixo é uma edição em arquivo que o upstream também mantém. Revisar todos a
cada rebase. Quando possível, migrar a lógica para arquivo novo + uma "costura" mínima.

### Integração do PegRig no core
| Arquivo | O que foi adicionado |
|---|---|
| `source/blender/blenkernel/BKE_main.hh` | `PegRig` na Main database |
| `source/blender/blenkernel/intern/constraint.cc` | "Follow Peg Constraint (Nuclear)" |
| `source/blender/makesdna/DNA_constraint_types.h` | `bFollowPegConstraint`, `CONSTRAINT_TYPE_FOLLOWPEG` (=32) |
| `source/blender/editors/object/object_ops.cc` | registro dos operadores `object.pegrig_*` |
| `source/blender/editors/object/object_modifier.cc` | pegs no modifier context |
| `source/blender/editors/transform/transform_convert.cc` | suporte ao peg transform workflow |
| `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` | `GREASE_PENCIL_OT_peg_pick`, `GREASE_PENCIL_OT_peg_select_parent` |
| `source/blender/editors/animation/anim_filter.cc` | PegRig no filtro de dados de animação; **deform curves do modifier "Curve" sob o objeto do desenho** (mesmo padrão do PegRig, em `animdata_filter_dopesheet_ob`: sem isso as keys da curva ficam invisíveis no Dope Sheet, porque quem se seleciona é o desenho e a Action mora no data-block da curva). Requer `DNA_modifier_types.h` no include list. **Não** se tocou no modo Grease Pencil do editor: o upstream avisa ali que listar F-Curves exigiria mexer em quase todo operador que testa `ANIMCONT_GPENCIL` (seleção, delete, snap, copy/paste), e o canal apareceria sem poder ser editado — a saída foi abrir os arquivos com rig em modo Dope Sheet (`scripts/startup/nuclear_timeline_mode.py`) |
| `source/blender/depsgraph/intern/builder/deg_builder_nodes.cc` | nodes de PegRig |
| `source/blender/depsgraph/intern/builder/deg_builder_relations.cc` | dependências de PegRig |
| `source/blender/makesrna/intern/rna_constraint.cc` | RNA do Follow Peg constraint |
| `source/blender/makesrna/intern/makesrna.cc` | registro de `rna_pegrig` |
| `source/blender/makesrna/intern/rna_main.cc` | `pegrigs` na Main |

### Opacidade de objeto e de peg (herdada pela cadeia do rig)
Opacidade animável no objeto e na peg, multiplicada por cima da opacidade própria de cada
layer de GP. Fadear uma peg fadeia tudo sob ela, então o Master Peg é o controle de
"personagem inteiro" que o fluxo cut-out espera. Implementado 2026-08-11; selftest headless
em `tools/nuclear_rig/selftest_opacity.py` (32 checagens).

⚠️ **A armadilha, se este bloco for re-aplicado num rebase:** a contribuição da peg **não**
pode ser dobrada dentro de `Object::opacity`. A cópia avaliada não é refrescada quando só
parâmetros mudam, então a multiplicação cai sobre o produto da avaliação anterior e acumula —
cada mexida no slider escurecia a peça de novo (1.0 → 0.8 → 0.8×0.5 → …) e, como o fator
nunca passa de 1, ela só decaía para o preto e não voltava nem com a peg em 1.0. Daí o campo
runtime separado, que a constraint **atribui** em vez de multiplicar.

| Arquivo | O que foi adicionado |
|---|---|
| `source/blender/makesdna/DNA_object_types.h` | `Object::opacity` nos bytes do antigo `_pad2` (o struct não cresce) |
| `source/blender/makesdna/DNA_object_defaults.h` | `.opacity = 1.0f` |
| `source/blender/blenkernel/BKE_object_types.hh` | `ObjectRuntime::peg_opacity` (runtime, default 1.0) — a metade que vem da peg, **atribuída**, nunca multiplicada dentro de `opacity` |
| `source/blender/blenkernel/intern/constraint.cc` | `followpeg_evaluate` grava `peg_opacity` na cópia avaliada |
| `source/blender/blenkernel/intern/pegrig.cc` | `pegrig_solve_peg` resolve `world_opacity` pela cadeia de pais (produto, clampado) |
| `source/blender/makesdna/DNA_pegrig_types.h` | `PegRigPeg::opacity` (autorada) + `world_opacity` (runtime) |
| `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` | `grease_pencil_layer_final_opacity_get` multiplica layer × objeto × peg; vale para render, não só viewport |
| `source/blender/blenloader/intern/versioning_500.cc` | migração (500, 123) — sem ela o elenco inteiro abre invisível |
| `source/blender/blenkernel/BKE_blender_version.h` | `BLENDER_FILE_SUBVERSION` 122 → 123 |
| `source/blender/makesrna/intern/rna_object.cc` | RNA `opacity` + `opacity_resolved` (getter runtime, read-only) |
| `source/blender/makesrna/intern/rna_pegrig.cc` | RNA `opacity` + `opacity_resolved` da peg |
| `source/blender/makesdna/DNA_space_types.h` | `SpaceOutliner::show_restrict_flags2` — segundo word de flags, porque `show_restrict_flags` é `char` e o último bit foi para a coluna de lock |
| `source/blender/makesdna/DNA_space_enums.h` | `eSpaceOutliner_ShowRestrictFlag2` / `SO_RESTRICT2_OPACITY` |
| `source/blender/editors/space_outliner/outliner_draw.cc` | coluna de opacidade (NumSlider + ícone de estado) |
| `source/blender/editors/space_outliner/outliner_utils.cc` | a coluna conta na largura das colunas da direita |
| `source/blender/editors/space_outliner/space_outliner.cc` | coluna ligada por padrão em Outliner novo |
| `source/blender/makesrna/intern/rna_space.cc` | RNA `show_restrict_column_opacity` |
| `scripts/startup/bl_ui/properties_object.py` | `opacity` no painel Object ▸ Display |
| `scripts/startup/bl_ui/space_outliner.py` | toggle da coluna no popover de filtro |

**Conhecido, não corrigido:** ao abrir arquivo salvo, `world_opacity` volta do disco e só
re-resolve quando algo tagga o rig — o campo é runtime mas mora no DNA. Conserto pendente de
decisão (ou o campo para de persistir, ou o load força um solve).

### Registro do modifier "Cutter" (`eModifierType_GreasePencilMask`)
Costuras de 1 linha para plugar o modifier novo (mesmo padrão que o "Curve" usou — antes não
documentado). No rebase, re-aplicar cada uma:
| Arquivo | O que foi adicionado |
|---|---|
| `source/blender/makesdna/DNA_modifier_types.h` | `eModifierType_GreasePencilMask = 88` + struct `GreasePencilMaskModifierData` + enum de flags |
| `source/blender/makesdna/DNA_modifier_defaults.h` | bloco `_DNA_DEFAULT_GreasePencilMaskModifierData` |
| `source/blender/makesdna/intern/dna_defaults.c` | `SDNA_DEFAULT_DECL_STRUCT` + `SDNA_DEFAULT_DECL` do struct |
| `source/blender/modifiers/MOD_modifiertypes.hh` | `extern ModifierTypeInfo modifierType_GreasePencilMask;` |
| `source/blender/modifiers/intern/MOD_util.cc` | `INIT_TYPE(GreasePencilMask);` |
| `source/blender/modifiers/CMakeLists.txt` | `intern/MOD_grease_pencil_mask.cc` |
| `source/blender/makesrna/intern/rna_modifier.cc` | item no enum, `RNA_MOD_OBJECT_SET`, filtros material/vgroup, `rna_def_modifier_grease_pencil_mask` + chamada |
| `source/blender/makesrna/intern/rna_object.cc` | `rna_GreasePencil_object_poll` (poll p/ ponteiro de objeto GP) |
| `source/blender/makesrna/intern/rna_internal.hh` | declaração de `rna_GreasePencil_object_poll` |
| `scripts/startup/bl_ui/properties_data_modifier.py` | `GREASE_PENCIL_MASK` no menu Add (categoria Generate) |
| `source/blender/blenkernel/BKE_blender_version.h` | `BLENDER_FILE_SUBVERSION` 119→120 (struct DNA novo; sem `do_version`) |

### Modifier Grease Pencil "Contour" / Envelope (registro do modifier + operadores + overlay)
| Arquivo | O que foi adicionado |
|---|---|
| `source/blender/makesdna/DNA_modifier_types.h` | `eModifierType_GreasePencilContour` (=32→**89**, realocado de 88 p/ não colidir com o Cutter/Mask); struct `GreasePencilContourModifierData` (object/strength/flag + **bind_co/bind_verts_num**); enum `GreasePencilContourFlag` (CONFORMAL, **BOUND**) |
| `source/blender/makesdna/DNA_modifier_defaults.h` | `_DNA_DEFAULT_GreasePencilContourModifierData` |
| `source/blender/makesdna/intern/dna_defaults.c` | 2 decls (`SDNA_DEFAULT_DECL_STRUCT` + entrada na lista) |
| `source/blender/modifiers/MOD_modifiertypes.hh` | `extern ModifierTypeInfo modifierType_GreasePencilContour` |
| `source/blender/modifiers/intern/MOD_util.cc` | `INIT_TYPE(GreasePencilContour)` |
| `source/blender/modifiers/CMakeLists.txt` | `intern/MOD_grease_pencil_contour.cc` + `MOD_grease_pencil_contour.hh` na lista SRC |
| `source/blender/makesrna/intern/rna_modifier.cc` | item de enum; **setter custom** `rna_GreasePencilContourModifier_object_set` (aceita `OB_MESH` **ou** `OB_CURVES_LEGACY`); `rna_def_modifier_grease_pencil_contour` + chamada |
| `source/blender/blenkernel/intern/grease_pencil.cc` | `case` do Contour em `influence_data_from_modifier` |
| `source/blender/editors/object/object_modifier.cc` | operadores `OBJECT_OT_greasepencil_contour_bind` + `OBJECT_OT_greasepencil_envelope_setup` + `OBJECT_OT_greasepencil_spine_controllers` + `OBJECT_OT_greasepencil_contour_toggle_controls` + **`OBJECT_OT_greasepencil_contour_reset`** (silhueta convex-hull → Bézier cíclica → bind → controles empty+hook em Object Mode). O reset usa a custom-prop `nuclear_envelope_rest` (float3) carimbada em cada controlador na criação (`envelope_store_rest`) como pose de descanso **e** marcador de "isto é um controlador"; modos `ALL` (via Hooks da cage) e `SELECTED` (seleção; âncora também reseta seus handles filhos); quando nada elegível, retorna `OPERATOR_PASS_THROUGH` p/ não roubar o Alt+R nativo |
| `source/blender/editors/object/object_intern.hh` | decls dos operadores (incl. `..._contour_reset`) |
| `source/blender/editors/object/object_ops.cc` | `WM_operatortype_append` dos operadores (incl. `..._contour_reset`) |
| `source/blender/draw/engines/overlay/overlay_empty.hh` | `Empties::object_sync`: empties desenham com `ob->color` custom (≠ branco, não-selecionado) em vez do cinza do tema — para tingir os controles do envelope (anchor laranja / handle ciano) |
| `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` | `_register_envelope_reset_keymap`: keymap **addon** em `Object Mode` ligando **Alt+R** → `object.greasepencil_contour_reset` (mode=`SELECTED`); poll/PASS_THROUGH deixam o Alt+R nativo (clear rotation) intacto fora dos controladores |

### Tool / UI Python
| Arquivo | O que foi adicionado |
|---|---|
| `scripts/startup/bl_ui/space_toolsystem_toolbar.py` | tool `builtin.peg_pose` ("Peg Pose") + keymap |
| `scripts/startup/bl_operators/wm.py` | menu `WM_MT_splash_about`: Version/Date/Hash/Branch literais + linha "Nuclear, a derivative of Blender" (branding do About) |
| `scripts/startup/bl_ui/space_topbar.py` | `TOPBAR_MT_file_new.draw_ex`: 3 seams pequenas — (a) reordena `paths` com `Nuclear` sempre primeiro; (b) **remove o item "General"** (o `wm.read_homefile` com `app_template=""`) do menu/splash/Ctrl+N; (c) ícone `OUTLINER_OB_GREASEPENCIL` p/ o template `Nuclear`. Deixa só os 3 templates 2D (Nuclear, Storyboarding, 2D Animation) no `File > New`. **Acoplamento de runtime:** depende dos nomes de template `Nuclear`/`2D_Animation` e da estrutura do `draw_ex`; degrada sem quebrar se o upstream refatorar. Reversível via git. |

### Tela inicial: projetos recentes como grade de thumbnails (estilo Krita)
A lista textual de recentes da splash virou uma **grade de miniaturas** — o animador
reconhece o take pelo desenho em vez de ler nomes quase idênticos
(`DPE_EP06_C12T19` vs `DPE_EP06_C12T19_B`). Usa o thumbnail que o **próprio arquivo já
carrega** (cabeçalho do `.blend`/`.nuc`, mesmo que o tooltip do upstream já exibia) — não
renderiza nada novo, então não custa nada no save. PRD: `PRD-nuclear-thumbs-projetos-recentes.md`.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/editors/interface/templates/interface_template_recent_files.cc` | `uiTemplateRecentFiles()` ganhou o parâmetro `columns`: **0 = comportamento do upstream** (lista textual, código intocado num ramo do `if`), **>0 = grade** de tiles `WM_OT_open_mainfile` com o thumbnail como preview icon + nome sem extensão embaixo. Infra nova no mesmo arquivo: cache de ícones por caminho (`blender::Map`, validado por mtime, LRU de 100, ícone gerenciado via `BKE_icon_imbuf_create` que assume a posse do `ImBuf`), leitura via `IMB_thumb_read(THB_LARGE)` → fallback `BLO_thumbnail_from_file`, e *letter-box* do thumbnail num buffer quadrado (preview icons são desenhados esticados em região quadrada; sem isso um 16:9 fica achatado). Sem thumbnail → placeholder `ICON_FILE_BLEND`/`ICON_FILE_BACKUP`; arquivo sumido → `ICON_FILE_HIDDEN` (o tooltip do upstream já dizia "File Not Found"). |
| `source/blender/editors/include/UI_interface_c.hh` | assinatura `uiTemplateRecentFiles(uiLayout *, int rows, int columns)` |
| `source/blender/makesrna/intern/rna_ui_api.cc` | `template_recent_files` ganhou o argumento `columns` (default 0 = lista) |
| `scripts/startup/bl_operators/wm.py` | `WM_MT_splash.draw`: o split "New File \| Recent" virou empilhado — templates numa **linha** no topo, recentes ocupando a **largura toda** logo abaixo (`template_recent_files(rows=8, columns=4)`), que é o que dá espaço pros tiles |

### Boot no template Nuclear (`--app-template Nuclear` no launcher)
O Blender **não** entra em nenhum app template no boot (nem restaura do userpref) —
só via `--app-template <id>`. Para o produto abrir sempre no template Nuclear, a flag
vai no comando de lançamento (dado/launcher, zero C):
| Arquivo | O que foi alterado |
|---|---|
| `release/freedesktop/blender.desktop` | `Exec=blender %f` → `Exec=blender --app-template Nuclear %f` |
| `tools/nuclear_install/instalarNuclear.sh` | `.desktop` gerado: `Exec=$CURRENT_LINK/blender --app-template Nuclear %F` |
| `scripts/startup/nuclear_update.py` | `_repoint_desktop`: reescreve o `Exec` mantendo `--app-template Nuclear %F` (antes dropava args E o `%F` a cada update) |
> ⚠️ **Server-side pendente:** o `instalarNuclear-versionado.sh` (só no servidor, não versionado) precisa da mesma flag no `.desktop` que gera — deploy manual.

### Branding (ver seção 3)
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/blenkernel/BKE_blender_version.h` | `NUCLEAR_NAME`, `NUCLEAR_VERSION_STRING`, `NUCLEAR_VERSION_STRING_NO_NAME` |
| `source/blender/windowmanager/intern/wm_window.cc` | título de janela usa `NUCLEAR_NAME` (≈559, 644) |
| `source/blender/python/intern/bpy.cc` | expõe `_bpy._nuclear_version_string()` (versão do fork sem o nome) p/ o About derivar do header |

### Extensão de arquivo `.nuc` (Fase 1 — rebrand de formato, SEM mexer no magic)

Torna `.nuc` a extensão padrão dos arquivos criados no Nuclear, mantendo `.blend` legados
plenamente abríveis. **Decisão (2026-06-25): apenas Camada A (extensão + MIME).** NÃO se
trocou o magic de 7 bytes (`BLENDER`), então um `.nuc` é **byte-idêntico** a um `.blend` —
round-trip perfeito e ainda abrível pelo Blender vanilla se renomeado. Isso bloqueia só a
abertura *acidental* (associação do SO), não a deliberada. A "Fase 2" (trocar o magic p/
`NUCLEAR` + leitura dual-magic + "Export to .blend") fica documentada como evolução futura,
NÃO implementada — tem custo de lock-in do ecossistema e ~5 pontos quentes no `blenloader`.

| Arquivo | O que foi alterado |
|---|---|
| `source/blender/blenkernel/intern/blendfile.cc` | `BKE_blendfile_extension_check`: array `ext_test` ganhou `.nuc`/`.nuc.gz` (linchpin único — reconhecimento no browser, no `wm_save_mainfile_check` e em `library_path_explode` passam todos por aqui) |
| `source/blender/windowmanager/intern/wm_files.cc` | 4 spots: `wm_filepath_default` (nome "Untitled" novo → `.nuc`), `wm_save_mainfile_check` (extensão default ao salvar nome sem extensão → `.nuc`; um `.blend` existente é reconhecido e mantido), e 2 labels de diálogo "Untitled" |
| `scripts/modules/_bpy_internal/freedesktop.py` | `NUCLEAR_MIME = "application/x-nuclear"`; pacote MIME renomeado `x-blender.xml`→`nuclear.xml` agora declara DOIS `<mime-type>` (blender `*.blend` + nuclear `*.nuc`, glob-only — sem `<magic>`, pois o magic on-disk ainda é `BLENDER`); `.thumbnailer` cobre os dois MIME |
| `release/freedesktop/blender.desktop` | `MimeType=application/x-nuclear;application/x-blender;` (ambos abrem no Nuclear) |
| `tools/nuclear_install/instalarNuclear.sh` | `.desktop` reivindica os dois MIME + novo bloco que escreve `~/.local/share/mime/packages/nuclear.xml` e roda `update-mime-database` (antes só `update-desktop-database`) |
| `scripts/startup/nuclear_cell_library.py` | arquivo do fork: `filter_glob` de import/export → `*.nuc;*.blend`; default de export `cells.blend`→`cells.nuc` |

**Deliberadamente NÃO alterado** (escopo Fase 1): autosave/`quit.blend`/`_crash.blend`
(`wm_files.cc` ~2083/2310/2313 seguem `.blend` — internos de recovery, nunca documento do
usuário; o diálogo de recover filtra por `FILE_TYPE_BLENDER` que já inclui `.nuc`), sufixo
`.asset.blend`, e backups `.blend1` (`file_is_blend_backup` casa literal ".blend"). Rótulos
de filtro em `rna_space.cc` ("Filter Blender"/"Show .blend files") **devem ir pelo truque de
tradução** no template Nuclear (`_TRANSLATIONS`), não por edição em C — fecha o item pendente
do §3 sem virar ponto quente.

### Ferramentas de pintura GP (tab Paint + picker Krita + brushes Smudge/Blur)

Suporte C para o `nuclear_paint_toolkit.py` (§1). Nenhum mexe em DNA de struct nem exige
versionamento — só **append de enums** e um **drawflag runtime**; rebase = re-aplicar cada seam.

| Arquivo | O que foi alterado |
|---|---|
| `source/blender/makesdna/DNA_space_enums.h` | `BCONTEXT_PAINT = 20` (append em `eSpaceButtons_Context`, antes de `BCONTEXT_TOT`) |
| `source/blender/makesrna/intern/rna_space.cc` | item `PAINT` em `buttons_context_items[]` + `"show_properties_paint"` no `filter_items` de `rna_def_space_properties_filter` (ambos tamanho `BCONTEXT_TOT`, em lockstep) |
| `source/blender/editors/space_buttons/buttons_context.cc` | `buttons_context_path_paint()` (gate GP + `OB_MODE_PAINT_GREASE_PENCIL`) + `case BCONTEXT_PAINT` no switch de `buttons_context_path` |
| `source/blender/editors/space_buttons/space_buttons.cc` | `add_tab(BCONTEXT_PAINT)` (após Material) + `case BCONTEXT_PAINT: return "paint"` (a string do `bl_context`) + `"show_properties_paint"` no menu de visibilidade |
| `source/blender/editors/include/UI_interface_c.hh` | `UI_BUT_HSV_TRIANGLE = 1 << 28` (drawflag runtime, bit livre) |
| `source/blender/editors/interface/interface_intern.hh` | declara `ui_hsvtriangle_pos_from_vals` / `ui_hsvtriangle_vals_from_pos` |
| `source/blender/editors/interface/interface_widgets.cc` | helpers de geometria + `ui_draw_but_HSVTRIANGLE` (anel de matiz + triângulo SV fixo) + branch no topo de `ui_draw_but_HSVCIRCLE` |
| `source/blender/editors/interface/interface_handlers.cc` | branch em `ui_numedit_but_HSVCIRCLE` (banda do anel→hue, interior→sat/val baricêntrico) |
| `source/blender/editors/interface/regions/interface_region_color_picker.cc` | `ui_colorpicker_circle`: OR do flag quando `U.color_picker_type == USER_CP_CIRCLE_HSV` |
| `source/blender/editors/interface/templates/interface_template_color_picker.cc` | idem no picker inline + `WHEEL_SIZE` 5→7 (picker maior) |
| `source/blender/makesdna/DNA_brush_enums.h` | `GPAINT_BRUSH_TYPE_SMUDGE = 4` **e `GPAINT_BRUSH_TYPE_BLUR = 5`** (appends em `eBrushGPaintType`) |
| `source/blender/makesrna/intern/rna_brush.cc` | itens `SMUDGE` **e `BLUR`** em `rna_enum_brush_gpencil_types_items` |
| `source/blender/editors/sculpt_paint/grease_pencil_draw_ops.cc` | `get_stroke_operation`: `case GPAINT_BRUSH_TYPE_SMUDGE → greasepencil::new_grab_operation(stroke_mode)` (reusa o grab do sculpt) **e `case GPAINT_BRUSH_TYPE_BLUR → greasepencil::new_smooth_operation(stroke_mode)` (reusa o smooth do sculpt p/ dissolver/borrar no modo paint)** |
| `source/blender/editors/sculpt_paint/paint_cursor.cc` | `grease_pencil_brush_cursor_draw`: seta `pixel_radius = brush->size/2` p/ `GPAINT_BRUSH_TYPE_SMUDGE`/`_BLUR` (senão o anel do cursor fica raio 0 = invisível) |
| `source/blender/editors/sculpt_paint/grease_pencil_paint.cc` | `PaintOperationExecutor` (~690): quando `brush->mtex.tex` existe, `BKE_brush_sample_tex_3d` na posição em world-space modula `opacity` → traços texturizados (textura de bico) |

### Aba Storyboard no Properties (`BCONTEXT_STORYBOARD`) — 2026-08-10

Hospeda a **coluna de planos** do add-on `nuclear_storyboard` (repo separado,
`~/Documentos/GitHub/nuclear-storyboard`): os painéis registram com
`bl_context="storyboard"` e o add-on cai sozinho na sidebar quando a aba não existe
(`boardpanel.tab_available()` pergunta ao **enum do RNA**, não à versão do Nuclear — então
atualizar o add-on antes do binário não deixa o artista sem board). **Mesma receita de 4
arquivos da tab Paint acima**, sem DNA de struct e sem versionamento (só append de enum:
`visible_tabs` já nasce com todos os bits ligados e o `versioning_450` faz o mesmo para
arquivos antigos). Rebase = re-aplicar cada seam.

| Arquivo | O que foi alterado |
|---|---|
| `source/blender/makesdna/DNA_space_enums.h` | `BCONTEXT_STORYBOARD = 21` (append em `eSpaceButtons_Context`, antes de `BCONTEXT_TOT`) |
| `source/blender/makesrna/intern/rna_space.cc` | item `STORYBOARD` (ícone `ICON_SEQ_SEQUENCER`) em `buttons_context_items[]` + `"show_properties_storyboard"` no `filter_items` de `rna_def_space_properties_filter` (ambos tamanho `BCONTEXT_TOT`, em lockstep) |
| `source/blender/editors/space_buttons/space_buttons.cc` | `add_tab(BCONTEXT_STORYBOARD)` + `add_spacer()` **no topo** de `ED_buttons_tabs_list` (antes de `BCONTEXT_TOOL`: no Nuclear o board é o que o artista olha o dia inteiro), **os dois sob `buttons_context_has_panels("storyboard")`** (helper novo no mesmo arquivo) + `case BCONTEXT_STORYBOARD: return "storyboard"` (a string do `bl_context`) + `"show_properties_storyboard"` no menu de visibilidade, pulado pelo mesmo helper |
| `source/blender/editors/space_buttons/buttons_context.cc` | **duas** edições em `buttons_context_path`: `case BCONTEXT_STORYBOARD` no switch, junto de `BCONTEXT_SCENE`/`RENDER`/`OUTPUT` (o board é da CENA, não do objeto ativo — a coluna tem de aparecer com nada selecionado, inclusive num take vazio, que é justo quando o artista clica no plano seguinte), **e** `BCONTEXT_STORYBOARD` no `ELEM(...)` que decide quem NÃO recebe o view layer empurrado por cima |

⚠️ **A pegadinha que custou um rebuild: aba some da lista SEM ERROR NENHUM.** Sem o segundo
ponto no `buttons_context.cc`, `buttons_context_path` empurra o *view layer* por cima da cena
para toda aba fora daquele `ELEM(...)`; o path termina no view layer,
`buttons_context_path_scene` devolve false, o bit nunca entra em `pathflag` e
`ED_buttons_tabs_list` descarta a aba calada — o enum do RNA simplesmente volta sem
`STORYBOARD`. **Headless não pega**: o item do enum existe e `show_properties_storyboard` é
True; a filtragem acontece ao **desenhar a região**, então só abrindo a GUI se vê. Uma aba
nova que resolva pela cena precisa entrar nos DOIS lugares.

| `source/blender/blenkernel/intern/blendfile.cc` | `"nuclear_storyboard"` na lista de add-ons de `BKE_blendfile_userdef_from_defaults()` — o storyboard nasce LIGADO numa instalação nova, senão o artista instala o Nuclear e não acha o board (e, com o gate abaixo, nem a aba). ⚠️ **Só vale para quem não tem `userpref.blend`**: quem ATUALIZA de uma versão anterior mantém as prefs dele e precisa ligar o add-on uma vez em `Preferences ▸ Add-ons`. |

⚠️ **E por resolver pela cena, o bit está SEMPRE em `pathflag`** — com ou sem o add-on
instalado. Sem trava, todo Nuclear que levasse a aba mostraria uma aba **vazia** a quem
nunca ouviu falar de storyboard. Daí o `buttons_context_has_panels()`: varre
`paneltypes` do `ARegionType` do Properties (via `BKE_spacetype_from_id` +
`BKE_regiontype_from_id`) e a aba só entra na lista quando existe painel registrado com
aquele `bl_context`. Registrar o painel é o que liga a aba; desabilitar o add-on a apaga
sozinha. **Nenhuma aba nativa passa por esse gate** — todas têm painéis embutidos.
Regressão coberta por `tests/gui_tab_gate.py` no repo do add-on (precisa de JANELA).
⚠️ Para perguntar "esta aba existe?" pelo Python, **escreva** em `space.context` e veja se
levanta `TypeError`: ler `space.bl_rna.properties["context"].enum_items` devolve a lista
ESTÁTICA (o `bl_rna` é da classe, não daquele espaço) e diz que a aba existe sempre.

### PERDA DE CONFIG: duas instâncias brigando pelo `userpref.blend` (2026-07-27)
Relato do usuário: "estou perdendo addons adicionados e atalhos configurados". Causa: as
preferências vivem inteiras em memória e são escritas inteiras, sem merge — a última instância
a gravar vence, e uma janela aberta há horas grava o estado de quando abriu, desfazendo o que
foi configurado numa instância mais nova. É comportamento do upstream, não do fork; o gatilho
é `U.runtime.is_dirty`, que coisas banais marcam (asset shelf, atribuir atalho por menu de
contexto). Reproduzido com duas instâncias reais: addon habilitado em B desaparecia quando A
fechava.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/blenkernel/intern/blendfile.cc` | `g_userpref_mtime_seen` (static) guarda o mtime do `userpref.blend` como este processo o viu — na leitura e a cada escrita própria. Novo `BKE_blendfile_userdef_write_all_ex(reports, force)`: com `force = false`, se o arquivo no disco está **mais novo** que o visto, a escrita é **pulada** (log de WARNING, retorno `true` — não é erro). `BKE_blendfile_userdef_write_all()` agora é um wrapper com `force = true`, então todo chamador existente (o operador "Save Preferences") mantém o comportamento de sempre. |
| `source/blender/blenkernel/BKE_blendfile.hh` | declara `BKE_blendfile_userdef_write_all_ex` e `BKE_blendfile_userdef_mtime_track` |
| `source/blender/windowmanager/intern/wm_files.cc` | após ler o userpref do usuário no boot, chama `BKE_blendfile_userdef_mtime_track(filepath_userdef)` |
| `source/blender/windowmanager/intern/wm_init_exit.cc` | o save **automático** na saída passa `force = false` — é o único caminho que perde configuração alheia; o explícito segue forçando |

### PERDA DE CONFIG (a causa principal): o app template zerava as preferências (2026-07-28)
A briga entre instâncias (acima) era só metade. O lançador abre com `--app-template Nuclear`, e
`wm_homefile_read_ex` carrega as preferências *do template*; quando o template não tem
`userpref.blend` próprio, o upstream cai em `BKE_blendfile_userdef_from_defaults()` e passa isso
para `BKE_blender_userdef_app_template_data_set`, que faz **`VALUE_SWAP` de `addons`,
`user_keymaps`, `user_keyconfig_prefs`, `themes`, `uistyles`, `uifonts` e `keyconfigstr`**. Ou
seja: **toda abertura pelo lançador trocava addons/atalhos/tema pelos de fábrica**, e o save
automático na saída (`U.runtime.is_dirty`) tornava a perda permanente. **Nenhum** dos três
templates do Nuclear tem `userpref.blend`, então isso valia para todos. Reproduzido: salvar prefs
com um addon habilitado → reabrir **sem** `--app-template` mostra o addon, reabrir **com** não.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/windowmanager/intern/wm_files.cc` | removido o fallback `userdef_template = BKE_blendfile_userdef_from_defaults()` quando o template não traz `userpref.blend` (nem em `config/<template>/`, nem no dir do template no sistema). Sem preferências próprias, o template não tem nada a restaurar — as do usuário ficam intactas. ⚠️ Trade-off registrado no comentário: sair de um template **com** preferências para um **sem** mantém as do primeiro; nenhum template do Nuclear está nessa situação hoje. |

### Template inicial do lançador: `Nuclear` → `2D_Animation` (2026-07-28)
Pedido do usuário: o Nuclear devia iniciar no ambiente **2D Animation**, não no template
`Nuclear`. Trocado o `--app-template` nos quatro lugares que geram o `.desktop` —
`release/freedesktop/Nuclear.desktop`, `tools/nuclear_install/instalarNuclear.sh`,
`tools/nuclear_install/instalarNuclear-wizard.sh` e `scripts/startup/nuclear_update.py` (nova
constante `_APP_TEMPLATE`, usada pelo fallback e pelos dois pontos de reescrita do Exec).
⚠️ Consequência: o `__init__.py` do template `Nuclear` (remap de labels, topbar próprio, abas
Properties/Reference/Library/Color/Peg Graph) **não roda mais** — a UI passa a ser a do
2D Animation nativo. O template `Nuclear` continua no pacote e volta a valer trocando a
constante de volta. Como o `_refresh_desktop` reescreve o `Exec` a cada update, as máquinas
pegam a troca no update que **partir** de um build com esta mudança.

### PERDA DE DADOS: o Follow Peg não contava usuário no PegRig (2026-07-27)
Relato do usuário: "estou perdendo as pegs" no take `DPE_EP06_C12T67` (Carolina, Ep06 C12).
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/blenkernel/intern/constraint.cc` | `followpeg_id_looper()` reportava o ponteiro `data->rig` com `is_reference = false` → `IDWALK_CB_NOP`, ou seja **sem contar usuário**. O PegRig é um ID de *dado* (como a Action do Action constraint, que passa `true` — só o *objeto*-alvo passa `false`, convenção do upstream contra ciclos). Efeito no arquivo real: 4 objetos seguindo o rig e `users = 1`; assim que o último usuário contado saía (o `NuclearPegTree` "Peg Graph"), o rig caía a zero usuários e era **silenciosamente descartado no save, levando as 80 pegs**. Reproduzido e corrigido: remover o Peg Graph e salvar dava `pegrigs=0` antes, `pegrigs=1 pegs=80` depois. Torna obsoleto o workaround de `use_fake_user=True`. |

### Robustez: crash do Outliner + ruído de log do auto-key (2026-07-27)
Achados investigando a estação de animação `bazzite-2` (192.168.0.29): um SIGSEGV no
redraw do Outliner depois de ~1h23 de trabalho e dezenas de warnings "Could not insert
key" durante a animação normal. **Candidatos a enviar upstream** — nada aqui é específico
do Nuclear.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/editors/space_outliner/outliner_draw.cc` | **Causa do crash.** `tree_element_id_type_to_index()` repassava o **-1** que `BKE_idtype_idcode_to_index()` devolve para um idcode desconhecido; o chamador então fazia `merged->num_elements[-1]++` e `merged->tree_element[-1] = te` — escrita fora dos limites que corrompe o fim do array vizinho do `MergedIconRow`, deixando um `num_elements[…] != 0` com `tree_element[…] == nullptr` e, no desenho, um deref de nulo em `outliner_draw_iconrow_doit` (frame #0 da stack do coredump). Fix em 3 camadas: (a) `id_index < 0` cai no bucket genérico `INDEX_ID_GR`; (b) o bucket `INDEX_ID_OB` valida `ob != nullptr` e `ob->type` dentro de `[0, OB_TYPE_MAX)`; (c) guard de `te`/`store_elem` nulos no topo de `outliner_draw_iconrow_doit` (roda a cada redraw — melhor perder um ícone que a janela). |
| `source/blender/animrig/intern/action.cc` | `NO_KEY_NEEDED` deixou de ser `CLOG_WARN` e virou `CLOG_DEBUG`. Com "Only Insert Needed" (ligado por padrão no auto-key), pular um canal cujo valor não mudou é o comportamento **pretendido** — mas cada auto-key logava uma linha "Could not insert key into FCurve …" por componente parado (`rotation_quaternion[2]`, `location[1]`, …), o que lê como keyframe perdido e polui o log de sessões longas. Os demais resultados seguem em WARN. |
| `source/blender/animrig/intern/fcurve.cc` | `insert_vert_fcurve()` chamava `BKE_fcurve_active_keyframe_set(fcu, &fcu->bezt[a])` **antes** de testar `a < 0`; no caminho de falha isso indexa `bezt[-1]`. Checagem movida para antes do uso. |

### PERDA DE DADOS: `I` no Dope Sheet apagava o elenco inteiro (2026-07-31)
Relato do usuário: pôs keyframes em 1/5/7, mudou a interpolação para constante, apertou **I**
no frame 4 — e o personagem sumiu. Rastreado com uma sessão instrumentada (log de
`wm.operators`): o operador era `ACTION_OT_keyframe_insert`, +128 keyframes, peças visíveis
43 → 0. **Candidato a enviar upstream.**
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/editors/space_action/action_edit.cc` | `insert_action_keys()` derivava `grease_pencil_hold_previous` de **"Additive Drawing"** (`GP_TOOL_FLAG_RETAIN_LAST`). Esse flag é **off por padrão de fábrica**, e com ele off `insert_grease_pencil_key()` cai no ramo "insert a blank frame": o `I` insere keyframe **vazio** em cada canal que toca, apagando o desenho dali em diante. Com `type='ALL'` (o default do menu) isso é *todo canal visível de todo objeto listado* — num elenco cut-out, o personagem inteiro em uma tecla. Medido no rig de referência: 670→798 keyframes, 43 peças visíveis → **0**. Agora `grease_pencil_hold_previous` é sempre `true`: inserir keyframe **segura o desenho exposto** (comportamento Toon Boom). `insert_grease_pencil_key` segue inserindo branco quando não há o que segurar (sem frame ativo, ou end frame). O flag mantém a outra função — semear um frame recém-desenhado com os traços anteriores (`grease_pencil_draw_ops.cc`). O caminho GP legado (`ANIMTYPE_GPLAYER`, anotações) não foi tocado. |

### PERDA DE DADOS: o Interpolate do GP apagava camadas (2026-07-31)
Achado investigando o relato acima (operador diferente, mesmo sintoma de "sumiu o desenho").
**Candidato a enviar upstream** — nada específico do Nuclear; morde aqui porque peça de rig
cut-out mistura camadas de linha animadas com fills segurados.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/editors/sculpt_paint/grease_pencil_interpolate.cc` | **Duas causas.** (a) `InterpolateOpData::from_operator()` só usava `find_curve_mapping_from_index()` como um OR global (`found_mapping`) e mantinha no `layer_mask` **toda** camada — inclusive as sem intervalo interpolável. `..._init()` então inseria nelas um BREAKDOWN **vazio** e `..._update()` sobrescrevia com geometria vazia; como só o *Cancel* restaura, confirmar deixava a camada em branco. Agora o mask é reduzido às camadas com mapeamento — a garantia que o `GREASE_PENCIL_OT_interpolate_sequence` já tinha via `if (!interval) return;`. (b) `..._invoke()` chamava só `..._status_indicators()`: o `init` apenas *cria* os keyframes (vazios) e o modal só os preenche no primeiro `MOUSEMOVE`, então invocar pelo menu e confirmar de imediato esvaziava **todos** os alvos. Passa a chamar `..._update()`. Medido no rig de referência: 4 keyframes vazios na `boca` antes, 0 depois. |

### A seleção não empilhava as peças como o render (2026-08-04)
Relato do usuário: "clico numa peça e vem outra, às vezes diverge muito do desenho".
Duas ordens sem relação nenhuma. **Render:** o engine GP ordena os objetos pela profundidade
da **origem** (`gpencil_object_cache_add`, `camera_z`) e limpa o depth buffer **entre**
objetos (`Instance::draw_object`) — pintura pura, a geometria não decide nada. **Clique:** o
prepass de seleção resolvia pelo `gl_FragCoord.z` **geométrico** do traço (o fragment shader
pula o `gp_depth_plane` sob `SELECT_ENABLE`), com desempate por distância ao cursor
(`select_lib.glsl`, `SELECT_PICK_NEAREST`). Medido: `carolina_pegs_atualizada.blend` 22,2%
dos 90 pares sobrepostos **invertidos** (`CAPUZ` com 1,62 de diferença entre as duas
profundidades); `lala_atualizada.nuc` (saída do `arm2peg`, todas as origens em Y=0) com
98,6% dos pares empatados no render — nenhuma correlação. **Candidato a enviar upstream.**
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/draw/engines/overlay/overlay_grease_pencil.hh` | `compute_depth_planes()` ganha o caminho `compute_selection_depth_planes()`: com todos os objetos já sincronizados, reconstrói a ordem do engine (stable sort por `dot(view.forward(), origem)`, cuja estabilidade reproduz o desempate pela ordem de sync) e dá a cada objeto um plano numa profundidade distinta que a segue. A profundidade própria é mantida quando já é estritamente maior que a do objeto de trás — só empates são afastados, pelo passo `max(extensão, 1) * 1e-4`, para não reordenar GP contra o resto da cena. `draw_grease_pencil()` passa a gravar `object_origin` no plano e, **só em modo seleção**, a pular camadas com `opacity < 1e-4` — `TreeNode::is_visible()` olha apenas o flag HIDE, então camada 100% transparente seguia clicável. |
| `source/blender/draw/engines/overlay/overlay_private.hh` | `GreasePencilDepthPlane` ganha `object_origin`. |
| `source/blender/draw/engines/overlay/shaders/overlay_depth_only_gpencil_vert.glsl` | Sob `SELECT_ENABLE`, projeta o vértice sobre `gp_depth_plane` e escreve o resultado em `gl_Position.z`. É a contrapartida do que o fragment shader faz fora da seleção — lá ele **não pode** (reescrever `gl_FragDepth` quebra o early depth test exigido), mas no vertex é exato: o plano é planar em world space, então a interpolação de z/w cai na mesma profundidade. |
| `source/blender/editors/space_view3d/view3d_select.cc` | Novo `object_selectbuffer_tight()`: a cascata do upstream (`mixed_bones_object_selectbuffer`) **abre** em raio 14 px e só estreita quando mais de um objeto responde, então uma peça vizinha a uma dúzia de pixels ganhava um clique que caiu dentro de outra — num rig cut-out isso era a **maior** fonte de erro (19 de 21 no rig de referência). A nova cascata começa em 2 px e só alarga (5, 14) quando **nada** responde, preservando a tolerância de quem clica no vazio. `ed_view3d_give_base_under_cursor_ex()` ganha `use_cycle`, que combina essa cascata com o desempate por movimento do cursor — novo `ED_view3d_give_base_under_cursor_cycle()`. O select padrão (`view3d.select`) **não** foi tocado. |
| `source/blender/editors/include/ED_view3d.hh` | Declaração de `ED_view3d_give_base_under_cursor_cycle()`. |
| `source/blender/editors/object/object_pegrig.cc` | `pegrig_pick` usa a variante acima e vira `invoke`+`exec` com propriedade `location` (mesmo padrão do `VIEW3D_OT_select`), o que também o torna chamável por script — é como o teste de ponta a ponta dispara cliques. Clicar de novo no mesmo ponto desce para a peça de trás; antes, um pick errado não tinha saída. |

**Medido no clique de verdade** (GUI, 60 pontos amostrados sobre a Carolina; "defensável" = a peça
que veio é o topo da pilha ou tem uma linha passando a ≤4 px do pixel):

Métrica final (a que enxerga o recorte da mask; "defensável" = topo da pilha, ou linha da peça a
≤4 px do pixel):

| rig | acerto antes | acerto depois | ORDEM | TOLERÂNCIA |
|---|---|---|---|---|
| Dinossauro Gigante | 56,5% | **91,3%** | 25 → **0** | 5 → 3 |
| Atena | 73,1% | **96,2%** | 4 → **0** | 8 → **0** |
| Carolina | 59,5% | **80,2%** | 9 → 1 | 13 → **0** |
| Lala | 22,2% | **83,3%** | 27 → 6 | 3 → **0** |

Regressão conferida: smoke 2D ALL PASS e render do rig **idêntico pixel a pixel** (360.000 px,
diferença máxima 0,0) contra o binário publicado — o conserto vive todo no caminho de seleção.
⚠️ `--debug-gpu-compile-shaders` **crasha neste build** (`Error source not found:
osd_patch_basis.glsl`, OpenSubdiv está OFF no preset 2D) — comportamento **pré-existente**,
idêntico no binário publicado; por isso a validação do GLSL foi feita disparando seleções reais
na GUI.

### O hit-test ignorava as masks (2026-08-04)
Relato: "as masks ainda aparecem e as pegs continuam destoantes dos objetos" — duas frases para
o mesmo defeito. O corte da mask só existe no engine (`draw_mask`), e `draw_grease_pencil` do
overlay não consulta `GreasePencilLayerMask`/`use_masks()`. No rig cut-out isso é a *maioria* do
desenho: **21 das 23 masks do dinossauro** recortam a camada de cor pela camada de linha, então a
área clicável de cada peça era o fill **bruto**, que extravasa muito além do contorno. Medido na
Carolina: 56,2% da área clicável das camadas com mask é buraco invisível (`manga.d` 70,8%,
`antebraco.e` 80,6%).

Rasterizar a máscara no select pass exigiria stencil ou textura + `discard`, reabrindo a questão
do early depth test que o upstream contornou. **Não é preciso quando a mask é subtrativa dentro
de um objeto:** o que sobrevive à mask é subconjunto da área do matte, e o select id é **por
objeto** — então o matte já responde por cada um desses pixels, e basta *não desenhar* a camada
mascarada. A área clicável fica intacta onde o desenho aparece, e some exatamente o excedente
invisível.
| Arquivo | O que foi alterado |
|---|---|
| `source/blender/draw/engines/overlay/overlay_grease_pencil.hh` | `layer_is_covered_by_own_mattes()` + `mask_target_is_drawn()`: o atalho só vale se **toda** mask da camada (própria e herdada de grupo/peg) for positiva, local ao objeto e apontar para um nó de fato desenhado — mask invertida mostra área FORA do matte, e matte cross-object responde com outro id. Salvaguarda em `draw_grease_pencil()`: masks encadeiam (linha mascarada pela cor que ela mascara de volta), e descartar *todas* as camadas deixaria o objeto sem área clicável nenhuma, então o atalho só se aplica enquanto sobrar camada respondendo. |

**Continua em aberto:** matte **cross-object**. No dinossauro sobram 3 pontos, todos da camada
`detalhe.torso/Layer.002`, recortada pelos objetos `torso.004` e `pelvis.004`. Essa peça tem uma
**única** camada com conteúdo (1 stroke de 316 pontos) e 47,5% de excedente (21.887 px de área
bruta contra 11.498 visíveis) — pular a camada a deixaria sem contorno e sem área clicável, e o
matte responde por outra peça, então só o corte real resolve.

### Corte de mask cross-object por stencil — TENTADO E REMOVIDO (2026-08-04 → 2026-08-05)
A ideia era rasterizar o matte no stencil e desenhar a camada mascarada com
`DRW_STATE_STENCIL_EQUAL`, para o clique respeitar o recorte que hoje só existe no engine
(`draw_mask`). Foi implementado em `abeb1eb392f` e **removido em seguida**: não funcionava, e
mesmo depois de consertado ficava pior que não cortar. Fica registrado porque a causa é uma
armadilha do framework de draw que qualquer tentativa futura vai encontrar.

⚠️ **Por que não funcionava: `PassSimple` não carrega select id.** Os pares matte→camada viviam
num `PassSimple`, escolhido por causa da ordem de draw garantida. Mas
`SelectMap::select_bind(PassSimple &)` **não** liga `use_custom_ids` nem vincula `SELECT_ID_IN` —
só a sobrecarga de `PassMain` faz isso, e `use_custom_ids` só é consumido pelo `DrawMultiBuf`
(de `PassMain`), nunca pelo `DrawCommandBuf` (de `PassSimple`). O shader faz
`select_id_set(drw_custom_id())` e recebia lixo, então **nenhuma camada recortada registrava
hit**: elas não eram recortadas, eram apagadas do hit-test. Medido na Carolina (grade de 10 px):
`antebraco.d` 13→0 cliques, `manga.d` 21→1, `1olho.005` 4→0; os cliques órfãos caíam na cascata
de tolerância (2→5→14 px) e iam parar em peças distantes (`TRONCO` 1→17, `cabelo` 84→159).
A prova de que era isso e não o stencil nem a profundidade: desligar o teste de stencil e
desligar o teste de profundidade davam **exatamente** o mesmo número (78,9% nos três casos).

**O conserto existe e foi validado**, para quem retomar: mattes num `PassSimple` (não precisam de
id — são desenhados com `select_invalid_id()` justamente para não responderem) e camadas num
`PassMain` submetido logo depois; a ordem fica garantida *entre* as duas submissões, que é tudo
que o stencil exige. Com **bits** de stencil no lugar de valores (`state_stencil(bit, bit, 0xFF)`
no matte, `state_stencil(0x00, bit, bit)` na camada), a ordem *dentro* de cada pass deixa de
importar e os mattes de todos os cortes dividem um buffer sem clear entre eles — 8 cortes por
frame, com os conjuntos de mattes deduplicados (a Carolina tem 10 camadas recortadas mas só 6
conjuntos distintos). Assim `antebraco.e`, `ant.casaco.e`, `1olho.002` e `1olho.005` voltaram ao
valor de referência.

**Mesmo assim foi removido, porque continua pior que não cortar:**

| rig | sem corte | corte quebrado (`abeb1eb`) | corte consertado |
|---|---|---|---|
| Carolina | **87,2%** | 78,9% | 80,8% |
| Dinossauro | **80,0%** | — | 76,8% |

A causa é a interação com a cascata de tolerância do pick: área removida pelo corte vira ponto
sem resposta, o raio alarga até 14 px e traz uma peça **longe** — erro pior do que a peça vizinha
que responderia sem o corte. Cortar só passa a valer junto com uma política de tolerância
diferente (não alargar quando o corte foi quem esvaziou o ponto), e isso é outra frente.

**O atalho local continua valendo** (`layer_is_covered_by_own_mattes`): ele não rasteriza nada,
só deixa de desenhar a camada cuja área o matte do mesmo objeto já representa. É o que os
números acima já incluem.

**Método de medição** (vale reusar — a métrica anterior era cega para isto): `teste_clique_gui.py`
em `~/dpe_tools/gp_pick_test/` dispara `object.pegrig_pick(location=)` numa grade sobre a GUI, e
levanta a área visível de cada peça por **diferença de render** — esconde a peça, redesenha o
viewport num `GPUOffScreen`, compara os pixels. O ground truth sai do próprio engine, então já
traz masks, ordem de render e opacidade, sem remontar nada disso em Python. ⚠️ É preciso
`view_layer.update()` entre esconder e redesenhar, senão o depsgraph não reavalia e os dois
shots saem idênticos. Medidas e conclusões em `~/dpe_tools/gp_pick_test/medidas/RESULTADOS.md`.

⚠️ Achado à parte, não tratado: rigs com **deform curves** têm objetos `Curve` visíveis (8 no
dinossauro) que também respondem ao clique. São controles, não desenho — decisão de workflow.

**Auto-Patch respeitado pelo atalho (2026-08-05).** `GP_LAYER_MASK_AUTO_PATCH` corta só o traço
e mantém o fill (`gp_mask_bypass`, `gpencil_engine_c.cc`), então o matte **não** responde pela
camada — o colour art sobrevive ao corte inteiro. `layer_is_covered_by_own_mattes()` tratava esse
flag como mask comum e teria tirado área que o artista vê. Junto: o teste de `HIDE` passou a vir
**primeiro**, senão uma mask desativada que fosse cross-object ou invertida derrubava o atalho de
graça, sem cortar nada. Provado com `teste_auto_patch.py` (liga o flag em memória e recompara os
cliques na mesma sessão): na Carolina `coque` 168→174 e `cabelofrente.2` 51→52 voltam a responder;
com o flag desligado os quatro rigs medem exatamente o mesmo de antes.

**Tentado e revertido:** afundar para trás de tudo os objetos usados como matte cross-object.
Parecia resolver "o cutter rouba o clique", mas na prática o matte é o **próprio desenho** (na
receita da pupila, o olho recorta a pupila) — rebaixá-lo jogava o olho para trás do corpo
inteiro. O teste de ordem pegou: 8 pares divergentes na Carolina, todos envolvendo um matte.
Não há como separar "cutter puro" de "desenho que também serve de matte" sem marcação
explícita do artista; e com a ordem já alinhada ao render o caso original não morde, porque o
matte fica atrás de quem ele corta, que é onde o artista o vê.

### Cadeado por collection e por objeto no Outliner (2026-08-07)
Pedido do autor: um sistema de "cadeamento" por collection no seletor padrão do Outliner.
Escopo escolhido por ele: **trava tudo** (seleção + edição + desenho), **coluna própria sempre
visível**, e **collection e objeto com herança**.

**A decisão que segura o resto: o lock IMPLICA `hide_select`.** Em vez de reimplementar bloqueio
de clique, `COLLECTION_LOCKED`/`OB_LOCKED` chegam ao `Base` como `BASE_LOCKED` e o sync **limpa
`BASE_SELECTABLE`**. Com isso, clique no viewport, box-select, Select All, Outliner
(`base_select` testa o flag) e canais de animação já recusam a peça travada sem nenhuma linha
nova — e o pass de seleção do draw manager (`draw_context.cc`, `should_draw_object`) **pula**
objetos não-selecionáveis, então o clique **atravessa** a peça travada e pega a de trás, que é o
comportamento de cadeado do Harmony. O `Pick Peg` não precisou de mudança nenhuma por isso.

⚠️ **O lock é RESTRITIVO, ao contrário da visibilidade do upstream.** `flag_from_collection`
acumula capacidades por OR, então um objeto em duas collections fica visível se *qualquer* uma
o permite. Para o lock isso daria "travado porém selecionável": adotou-se **travado vence**, e
`BKE_base_eval_flags` limpa `BASE_SELECTABLE` no fim para os dois nunca discordarem.

| Arquivo | O que foi alterado |
|---|---|
| `source/blender/makesdna/DNA_collection_types.h` | `COLLECTION_LOCKED = (1 << 7)`. ⚠️ **Último bit livre** do `uint8_t flag` — o bit 2 é deprecated e sujo em arquivos antigos, então um próximo flag de collection precisa de campo novo, não desse bit. |
| `source/blender/makesdna/DNA_object_types.h` | Campo `char lock_flag` tomado do antigo `_pad3[1]` (struct não cresce) + enum `OB_LOCKED = 1 << 0`. O lock próprio do objeto é separado do herdado, então a peça o mantém ao sair da collection. |
| `source/blender/makesdna/DNA_layer_types.h` | `BASE_LOCKED = (1 << 12)` (runtime, derivado). |
| `source/blender/makesdna/DNA_space_enums.h` | `SO_RESTRICT_LOCK = (1 << 7)` — último bit livre do `char show_restrict_flags`; bit 7 em campo `char` tem precedente upstream (`VPaint.flag`). |
| `source/blender/blenkernel/intern/layer.cc` | `BASE_LOCKED` entra em `g_base_collection_flags`; `layer_collection_objects_sync` lê `COLLECTION_LOCKED` do `collection_restrict` (que já acumula ancestrais → **herança de graça**); `BKE_base_eval_flags` aplica `OB_LOCKED` e limpa `BASE_SELECTABLE` (o deselect de não-selecionáveis, logo abaixo, tira a peça da seleção). Novo `BKE_object_is_locked(scene, view_layer, ob)`. |
| `source/blender/blenkernel/BKE_layer.hh` | Declaração de `BKE_object_is_locked`. |
| `source/blender/makesrna/intern/rna_collection.cc` | `Collection.is_locked` + setter `rna_Collection_is_locked_set` (reusa `rna_Collection_flag_set`, que já protege a master collection) e o update `rna_Collection_flag_update`, que faz `BKE_main_collection_sync`. |
| `source/blender/makesrna/intern/rna_object.cc` | `Object.is_locked`; e os **quatro** callbacks `editable` de transform (location/scale/rotation_euler/rotation_4d) recusam quando travado. ⚠️ Esses são `itemeditable` (por eixo): a UI cinza é real, mas `is_property_readonly` passa índice −1 e **não** os consulta — logo é gate de UI, não de script. O que impede a peça de se mover de fato é ela não poder ser selecionada. |
| `source/blender/makesrna/intern/rna_space.cc` | `SpaceOutliner.show_restrict_column_lock`. |
| `source/blender/editors/screen/screen_ops.cc` | `ed_object_locked()` + gate em `ED_operator_object_active_editable_ex`. **É o chokepoint que bloqueia trocar de modo** — `object_mode_set_poll` passa por aqui —, então não se entra em draw/edit/sculpt numa peça travada. |
| `source/blender/editors/grease_pencil/intern/grease_pencil_ops.cc` | Gate em `active_grease_pencil_poll`, ancestral comum dos polls de **todos** os modos GP (paint/edit/sculpt/weight/vertex/selection). É o que impede desenhar numa peça que já estava em draw mode quando foi travada. |
| `source/blender/editors/transform/transform_convert_pegrig.cc` | `createTransPegRigPeg` e o autokey do aftertrans recusam objeto travado. ⚠️ **Necessário porque este converter lê o objeto ATIVO, não a seleção** — travar desseleciona, mas não desativa, então sem isto o Peg Pose ainda posaria a peça travada. |
| `source/blender/editors/space_outliner/outliner_draw.cc` | Coluna do cadeado (`ICON_UNLOCKED`→`ICON_LOCKED`, consecutivos no `UI_icons.hh`) nas linhas de collection e de objeto, clonando o padrão da coluna Selectable: offset, esmaecido por herança via `RestrictPropertiesActive` (collection travada apaga os cadeados e **também os toggles de seleção** abaixo dela, coerente com o lock implicar `hide_select`), Shift=recursivo e Ctrl=isolar pelos helpers genéricos já existentes. |
| `source/blender/editors/space_outliner/outliner_utils.cc` | `outliner_right_columns_width` conta a coluna nova (no bloco `SO_SCENES`, que recebe o fallthrough de `SO_VIEW_LAYER`) — sem isso o `BLI_assert` do desenho quebra e a faixa de clique das colunas fica errada. |
| `source/blender/editors/space_outliner/space_outliner.cc` | `SO_RESTRICT_LOCK` ligado por padrão em outliners novos. |
| `source/blender/blenloader/intern/versioning_500.cc` | Subversion **121 → 122**: liga `SO_RESTRICT_LOCK` nos `SpaceOutliner` de arquivos antigos, senão os cadeados só apareceriam depois de o artista mexer no popover de filtro. |
| `scripts/startup/bl_ui/space_outliner.py` | A coluna nova no popover "Restriction Toggles" (modos View Layer e Scenes). |

---

### Sequência de imagens com três dígitos, não quatro (2026-08-10)
Pedido do autor: o Render Playblast (e o render de sequência em geral) numerava os arquivos com
quatro dígitos (`0000`, `0001`) e o estúdio quer três (`000`, `001`).

Isso **já era configurável** sem código — `ensure_digits()` (`BLI_path_frame`) só acrescenta os
`#` automáticos quando o nome do arquivo não tem nenhum, então um output path terminado em `###`
sempre mandou na largura. A divergência é só sobre o **default**, para o artista não ter que
digitar `#` em cada take.

| Arquivo | O que foi alterado |
|---|---|
| `source/blender/blenkernel/intern/image_format.cc` | `do_makepicstring` passa `NUCLEAR_IMAGE_SEQUENCE_DIGITS` (3) a `BLI_path_frame` em vez do literal `4` do upstream. Uma linha + a define no topo do arquivo. |

Alcance: `do_makepicstring` é o funil de **todo** nome de sequência de imagem — render final
(`pipeline.cc`), Render Playblast/OpenGL (`render_opengl.cc`, três chamadas) e o
`scene.render.frame_path()` da API Python (`rna_scene_api.cc`), que é por onde isto se testa
headless. ⚠️ **Não** cobre: o nome do arquivo de **vídeo** do ffmpeg, que embute o range
(`movie_write.cc`, `BLI_path_frame_range(..., 4)` — continua `0001-0250`), nem os exportadores
que numeram por conta própria (OBJ, dynamic paint, USD/volume). Foram deixados como estão: são
outro artefato, não a sequência que o artista entrega.

Comportamento preservado: `#` explícito no output path continua vencendo e definindo a própria
largura, e frame que passa da folga sai inteiro (frame 1000 com padding 3 → `1000`), porque o
`%.*d` do `BLI_path_frame` trata os dígitos como mínimo, não como máximo. ⚠️ Consequência aceita
pelo autor: renders antigos com quatro dígitos e novos com três convivem desalinhados na mesma
pasta, e quem quiser o padrão antigo escreve `####` no caminho.

---

## 3. Branding (subconjunto de pontos quentes + dados)

Pontos onde a identidade "Blender" aparece. Itens marcados [feito] já foram alterados;
os demais são pendências do plano de rebranding.

- [feito] `BKE_blender_version.h` — `NUCLEAR_NAME` / `NUCLEAR_VERSION_STRING`
- [feito] `windowmanager/intern/wm_window.cc` — título da janela (re-escrita ≈559/644 + título literal inicial na criação da janela ≈1043 agora `NUCLEAR_NAME`)
- [feito] `windowmanager/intern/wm_platform_support.cc` — diálogos de suporte de GPU: títulos `NUCLEAR_NAME " - "` (≈144/175) e mensagens "…better Nuclear compatibility." / "…may improve Nuclear support" / "Nuclear will now close." (≈164/198/211/222). Editado em C porque disparam no startup, antes do seam de tradução. Adicionado `#include "BKE_blender_version.h"`. (A URL `docs.blender.org` ≈74 segue pendente — ver abaixo.)
- [feito] `intern/ghost/intern/GHOST_SystemWin32.cc` — título do diálogo de tarefa Win32 `L"Nuclear"` (≈2864). Windows-only, não-testado em build local.
- [feito] `windowmanager/intern/wm_playanim.cc` — título da janela do player de animação standalone "Nuclear Animation Player" (≈1879)
- [nota] **NÃO alterar** o `applicationName` "Blender" passado ao Vulkan/XR (`intern/ghost/intern/GHOST_ContextVK.cc` ≈394/396, `GHOST_XrContext.cc` ≈104, `GHOST_XrGraphicsBindingVulkan.cc` ≈162) — drivers podem keyar workarounds nesse nome; não é user-facing.
- [feito] **Pasta de config/cache do usuário `blender` → `Nuclear`** (2026-07-06, 1.5.0). Config dir: `intern/ghost/intern/GHOST_SystemPathsUnix.cc` (`getSystemDir` ≈39 + `getUserDir` XDG ≈88 e `~/.config` ≈93 → `/Nuclear/`; a raiz pré-2.64 `~/.blender` ≈74 é dead code, não mexida), `GHOST_SystemPathsWin32.cc` (≈35/56 `\Nuclear\`), `GHOST_SystemPathsCocoa.mm` (≈33 `%s/Nuclear/%s`). Cache dir: `source/blender/blenkernel/intern/appdir.cc` (bloco `caches_root` ≈218-228, os 3 ramos WIN32/APPLE/linux → `"Nuclear"`). **Não afeta a descoberta de scripts/datafiles bundled** (build portátil acha por caminho relativo ao binário, não via config/system dir). **Migração** (para não zerar settings de quem já rodava): `scripts/startup/nuclear_update.py::_migrate_legacy_config` (copia `.config/blender/<ver>`→`.config/Nuclear/<ver>` no apply, idempotente) + `tools/nuclear_install/instalarNuclear.sh` (mesma cópia + path de addons corrigido p/ `Nuclear`). **Deferido na época** (nome do binário, `blender.svg`, `release/freedesktop/*`): FEITO em 2026-07-08 — ver a entrada "Rename do executável e artefatos" acima. Migração Win/mac segue pendente. Ver memória `[[nuclear-rebrand-blender-name]]`.
- [feito] **Set de ícones da UI (773 SVGs)** — `release/datafiles/icons_svg/*.svg` substituídos pela arte própria do autor (redesenho 16×16 baseado em *stroke*, `fill=none stroke=#fff`, vs. o original Inkscape 1100×1100 preenchido). Match de nomes 1:1 com o set upstream → **zero edição de C/CMake/Python**: o `CMakeLists.txt` (`source/blender/editors/datafiles/`, `SVG_FILENAMES_NOEXT` ≈186, `data_to_c_simple` ≈1005) embute cada SVG via `svg_icons.cc`, renderizado por nanosvg em runtime. Verificação estática: nenhum recurso fora do nanosvg (sem `<style>`/`class`/`<use>`/`<defs>`/gradiente/`currentColor`); só `path`/`circle`/`rect`/`ellipse`/`g`; todos com `viewBox`. **GOTCHA DE ESCALA (resolvido):** o rasterizador de ícones (`blf_glyph.cc:384`, `scale = gc->size / 1600.0f`) assume o SVG-fonte num canvas ~**1600px** (os ícones originais do Blender têm `width/viewBox` 1100–1700). Os do autor vinham `viewBox="0 0 16 16"` **sem `width`** → nanosvg reporta `image->width=16` (`scaleToViewbox`: `sx = image->width/viewWidth`) → `dest_w = ceil(16·size/1600) ≈ 1px` → **ícone colapsa para 1 pixel (invisível)**. Provado com teste C standalone do próprio nanosvg (broken: 16×16→dest 1×1, 1px; fixed: 1600×1600→dest 46×46, 604px). **Fix de dados (zero C):** adicionado `width="1600" height="1600"` em cada um dos 773 (mantendo `viewBox 16` → nanosvg escala conteúdo e stroke ×100). Reversível via `git checkout -- release/datafiles/icons_svg/`. **NOTA:** os SVGs-mestre do autor (fora do repo) também precisam do `width/height` senão um re-import reintroduz o bug. **ESTADO COMMITADO:** commit `620f37d` traz a arte **V1** com o fix `width=1600` (viewBox 16, fill ~67-74%). **NÃO COMMITADO (working tree, 2026-06-22):** arte **V2** (`icones_svgV2`, set atual) + **normalização de tamanho por ícone** — cada SVG reenquadrado num `viewBox` quadrado centrado no conteúdo (bbox medido via nanosvg incluindo metade do stroke) para preencher ~86% do cell, uniforme, sem distorção (viewBox quadrado) nem corte; cap de zoom 1.6× (45 ícones), 1 vazio pulado, `ipo_elastic`/overflow reenquadrado. Buildado e renderizando; pendente aprovação do tamanho pelo autor (alvo de fill é ajustável). Gotcha de fundo: zoom UNIFORME não serve porque os ícones têm tamanhos inconsistentes (maioria ~67%, ~7 já em ~95%) — só a normalização individual aumenta os pequenos sem cortar os cheios. NÃO inclui os 150 *geometry icons* `.dat` (`release/datafiles/icons/`, fonte `icons_blend/toolbar.blend`) nem o ícone do app (freedesktop/Windows) — esses seguem pendentes abaixo.
- [feito] `windowmanager/intern/wm_splash_screen.cc` — About: título "Nuclear" (≈476), nome/descrição do operador "About Nuclear" (≈499/501), e logo do Blender trocado pela arte da splash (reusa `wm_block_splash_image`, ≈453-471); **rótulo de versão no canto da splash usa `NUCLEAR_VERSION_STRING_COMPACT` (=`1.6.0`) em vez de `BKE_blender_version_string()` (=`5.0.0`)** — 2026-07-08, ≈315. Novo macro em `BKE_blender_version.h` (M.M.P sem nome/stage). ⚠️ Barra de status (canto inf. dir.) ainda mostra `5.0.0` (`BKE_blender_version_string_compact()`), pendente.
- [feito] `scripts/startup/bl_operators/wm.py` — menu About: Version/Date/Hash/Branch + linha de licença Nuclear
- [feito] `source/creator/creator_args.cc` — prints de versão usam `NUCLEAR_VERSION_STRING` (≈599, 621, 627, 656, 1340) + doc do `--version` → "Print Nuclear version"
- [feito] `windowmanager/intern/wm_init_exit.cc` — "Nuclear quit" (≈697)
- [feito] `release/datafiles/splash.png` — splash trocada por arte interna do autor (fora desta sessão)
- [feito] `release/datafiles/startup.blend` — cena de boot de fábrica trocada pela do template **Nuclear** (cópia de `scripts/startup/bl_app_templates_system/Nuclear/startup.blend`). Abrir sem arquivo / `--factory-startup` cai direto na cena 2D do Nuclear (não no cubo 3D). O `datatoc` assa este arquivo no binário → **exige rebuild**. Reversível via `git checkout Nuclear -- release/datafiles/startup.blend`. Par com a edição de `space_topbar.py` acima (§2, Tool / UI Python).
- [feito] **Strings residuais via truque de tradução** (template `Nuclear/__init__.py`, locale `en_US`, SEM editar C; valida com `pgettext_iface`): "Blender Version", "Blender Drivers Editor", "Blender Info Log", "Load Factory Blender Preferences" → Nuclear. O template força `use_translate_interface=True` + `language='en_US'`. Isso **substitui** a necessidade de editar `screen_ops.cc`/`wm_files.cc` para essas strings — não viram pontos quentes.
- [feito] `scripts/startup/bl_operators/wm.py` — About: versão agora derivada via `_bpy._nuclear_version_string()` (não diverge mais do CLI); botões reorganizados → removidos Donate e Blender Store; "What's New" → GitHub releases do Nuclear; "Nuclear Website" → rapaduraatomica.com.br; Credits e License mantidos em blender.org (atribuição + GPL, por exigência legal)
- [ ] `windowmanager/intern/wm_splash_screen.cc` — URLs do manual ainda pendentes (≈391, 396, instalação macOS/Windows)
- [ ] `release/windows/icons/winblender.{ico,rc}` — RC tem "Blender Foundation"/"ProductName: Blender"
- [feito] **Ícone do app + `.desktop` + taskbar** — `release/freedesktop/icons/scalable/apps/blender.svg` e `.../symbolic/apps/blender-symbolic.svg` trocados pela arte própria do autor (2026-07-08: renomeados p/ `nuclear.svg`/`nuclear-symbolic.svg` junto com o rename do executável — o CMake foi editado de qualquer jeito). `release/freedesktop/blender.desktop` rebrandizado (Name=Nuclear, GenericName=2D Animation, Comment, Keywords 2D, `Categories=Graphics;2DGraphics;`, `StartupWMClass=Nuclear`). `tools/nuclear_install/instalarNuclear.sh` → `Nuclear.desktop` agora com `StartupWMClass=Nuclear` + GenericName 2D. **Associação do ícone na taskbar:** WM_CLASS X11/XWayland = "Nuclear" (vem do título da janela, `GHOST_WindowX11.cc:264` copia de `title`); `app_id` Wayland nativo = "Nuclear" (`GHOST_SystemWayland.cc:9350`, fallback trocado de "blender"). Metainfo AppStream: FEITO em 2026-07-08 (`org.rapaduraatomica.Nuclear.metainfo.xml`). **Pendente:** validação visual pós-build.
- [feito] **Rename do executável e artefatos `blender*` → `nuclear*` (2026-07-08).** O que era o item "Deferido" do rebrand da 1.5.0. Binário instalado agora é **`nuclear`** (o *target* CMake continua `blender` — só `OUTPUT_NAME` muda, minimiza divergência).
  - **CMake:** `source/creator/CMakeLists.txt` — `OUTPUT_NAME nuclear` (≈355, todas as plataformas; macOS re-sobrescreve p/ `Blender` no bloco APPLE, bundle deferido), `nuclear-launcher` (Win), `BLENDER_BIN` → `nuclear`/`bin/nuclear`/`nuclear.exe`, install do **shim de compat `blender`** (novo `release/bin/blender`, forward pro `nuclear`), renames de install (desktop/ícones/system-info), man page `nuclear.1`, manifests Win `RENAME nuclear*.exe.manifest`, `RENAME nuclear.pdb`; `source/blender/blendthumb/CMakeLists.txt` — `OUTPUT_NAME nuclear-thumbnailer`; raiz `CMakeLists.txt` — `BLENDER_WIN_APPID` `nuclear.X.Y`/"Nuclear X.Y"; `tests/CMakeLists.txt` — `TEST_BLENDER_EXE` → `nuclear`; `source/creator/blender_launcher_win32.c` — spawna `L"nuclear.exe"` (Win não testado em build local).
  - **release/:** `git mv` `bin/blender-launcher`→`bin/nuclear-launcher`, `bin/blender-softwaregl`→`bin/nuclear-softwaregl` (ambos `BF_PROGRAM="nuclear"`), `freedesktop/blender.desktop`→`freedesktop/Nuclear.desktop` (Exec=`nuclear --app-template Nuclear %f`, Icon=`nuclear`, traduções "3D Modeler" removidas; basename `Nuclear.desktop` CASA com o `app_id` Wayland "Nuclear" — requisito do GHOST, ver #101805), ícones →`nuclear.svg`/`nuclear-symbolic.svg`, `scripts/blender-system-info.sh.in`→`nuclear-system-info.sh.in`, `org.blender.Blender.metainfo.xml`→`org.rapaduraatomica.Nuclear.metainfo.xml` (conteúdo reescrito p/ Nuclear), `text/readme.html` reescrito.
  - **Python/UI:** `doc/manpage/blender.1.py` (.TH NUCLEAR, aceita `--version` "Nuclear "), `scripts/modules/_bpy_internal/freedesktop.py` (registro MIME/desktop/thumbnailer com os nomes novos), `scripts/startup/bl_operators/wm.py` (splash: links blender.org→Nuclear, sem "Donate to Blender"; preset `BLENDER`→rapaduraatomica; tooltips "of Blender"→Nuclear; fallback tema/keymap), temas `git mv` `Blender_Dark/Light.xml`→`Nuclear_Dark/Light.xml` (sem ref em código; label persiste só como dado de tema), template Nuclear: override do `TOPBAR_MT_help` (links curados) + dict de tradução ("Blender File View" etc.), `source/creator/creator_args.cc` (Usage/help/erros user-facing→Nuclear; env vars `BLENDER_*` mantidas), `interface_template_recent_files.cc` (tooltip "Nuclear {ver}").
  - **Updater/tooling (aceitam OS DOIS nomes):** `scripts/startup/nuclear_update.py` (`_EXE_NAMES`/`_exe_in`), `tools/nuclear_release.py`, `tools/nuclear_release.sh` (smoke `bin/nuclear`), `tools/nuclear_prune_package.sh`, `tools/nuclear_install/instalarNuclear.sh` + `instalarNuclear-wizard.sh` (este também ganhou `--app-template Nuclear` no Exec, faltava).
  - ⚠️ **REGRA DE TRANSIÇÃO:** o zip de release TEM que conter o shim `Nuclear/blender` enquanto existir máquina em build ≤10 — o updater ANTIGO procura um arquivo `blender` dentro do zip e falha sem ele (e o shim é arquivo comum, sobrevive ao `zipfile.extractall`; symlink NÃO sobreviveria).
  - **Keyconfig renomeado "Blender" → "Nuclear" (2026-07-08, mesmo dia):** `git mv` `scripts/presets/keyconfig/Blender.py`→`Nuclear.py` e `Blender_27x.py`→`Legacy_27x.py` (idname deriva do filename); macro `WM_KEYCONFIG_STR_DEFAULT` "Nuclear" em `DNA_windowmanager_types.h` (≈152 — TEM que casar c/ o filename do preset, senão o preset cria um 2º keyconfig em vez de popular o default; runtime vira "Nuclear"/"Nuclear addon"/"Nuclear user"); `bpy/utils/__init__.py::keyconfig_init` default "Nuclear" + mapa legado; **migração de prefs** em `versioning_userdef.cc` (bloco Nuclear no fim do `blo_do_versions_userdef`, INCONDICIONAL e idempotente — o fork não gasta subversion do upstream; replace exact-match em `keyconfigstr` + `user_keyconfig_prefs` preserva keymap ativo e select-mouse/spacebar). ⚠️ Risco aceito: addon de terceiro que use o literal `keyconfigs["Blender"]` quebra (o padrão `keyconfigs.addon`/`.default` continua ok).
  - **Deferidos conscientes:** bundle macOS `Blender.app` (sem build p/ validar; deploy é Linux), env vars `BLENDER_USER_*`/`BLENDER_SYSTEM_*` (superfície programática, tipo `bpy`), domínio gettext `blender.mo`, `snap/` (não distribuído), `share/blender` do install não-portátil, appName Vulkan/XR (nota acima).
- [ ] `makesrna/intern/rna_space.cc` — "Filter Blender*" (≈7479, 7486, 7535) — descrevem o formato `.blend`; decisão pendente (renomear p/ Nuclear ou manter)
- [ ] `windowmanager/intern/wm_platform_support.cc` — URL docs.blender.org (≈74)
- [ ] `blenkernel/intern/preferences.cc` — URLs extensions.blender.org (≈224, 226)
- [ ] `source/creator/buildinfo.c`, `source/creator/CMakeLists.txt` — metadados de build/RC

> **Preferir o "truque de tradução"** (`bpy.app.translations`, registrado no
> `__init__.py` do template Nuclear) para renomear rótulos de UI em massa SEM editar
> `IFACE_()` no C — reduz pontos quentes de branding.

> **Legal:** manter avisos de licença GPL e a atribuição "derivado do Blender". Remover
> a *marca registrada* "Blender" da identidade do produto, mas preservar o crédito.

---

## 4. Procedimento de rebase (a cada nova release do upstream)

1. Criar branch de rebase a partir da tag da nova versão do upstream.
2. Trazer primeiro os **arquivos novos** (seção 1) — devem aplicar limpos; só ajustar se
   uma API do core que eles usam mudou.
3. Reaplicar os **pontos quentes** (seção 2) um a um, conferindo cada conflito contra a
   intenção descrita aqui.
4. Reaplicar **branding** (seção 3).
5. Build (`build_files/utils/make_utils.py` / `make`) e rodar a verificação de regressão
   do cut-out (PegRig → bind GP → Peg Pose → Peg Graph → modifier Curve).
6. Atualizar este documento com qualquer nova divergência introduzida no ciclo.

---

_Atualizado a partir do levantamento de UI/branding. Plano completo em
`~/.claude/plans/infelizmente-para-meu-azar-cryptic-rivest.md`._
