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
- `source/blender/modifiers/intern/MOD_grease_pencil_curve.cc`

### Modifier Grease Pencil "Cutter" (máscara cross-object, estilo Toon Boom — ver `CutterFeature.md`)
- `source/blender/modifiers/intern/MOD_grease_pencil_mask.cc` — injeta as strokes do objeto-matte
  como layer oculta (opacity 0) na GP avaliada e liga uma `GreasePencilLayerMask` nativa, para
  recortar um objeto pela silhueta de outro (ex.: pupila dentro do olho). Sem `.hh` (sem helper
  compartilhado nem operator). Reaproveita 100% do pipeline de máscara nativo (sem mexer no
  draw engine).

### Modifier Grease Pencil "Contour" / Envelope (deform MVC + cage Bézier, estilo Toon Boom)
- `source/blender/modifiers/MOD_grease_pencil_contour.hh` — `contour_sample_cage()` compartilhada (modifier + operadores)
- `source/blender/modifiers/intern/MOD_grease_pencil_contour.cc` — modifier Contour (MVC, cage mesh ou Bézier, bind)

### Add-ons / scripts de startup
- `scripts/startup/nuclear_curve_gizmo.py` — gizmos de deform de curva no viewport
- `scripts/startup/nuclear_peg_graph.py` — node editor da hierarquia de pegs
- `scripts/startup/nuclear_squash_gizmo.py` — gizmos de squash & stretch (anchor/tip) no viewport
- `scripts/startup/nuclear_cell_library.py` — Drawing Substitution (Fase 1): banco de cells fora-de-range + slider/atalhos (ver `CellLibraryFeature.md`)
- `scripts/startup/nuclear_telemetry.py` — telemetria de presença (→ rapaduraatomica.com.br)

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
| `source/blender/editors/animation/anim_filter.cc` | PegRig no filtro de dados de animação |
| `source/blender/depsgraph/intern/builder/deg_builder_nodes.cc` | nodes de PegRig |
| `source/blender/depsgraph/intern/builder/deg_builder_relations.cc` | dependências de PegRig |
| `source/blender/makesrna/intern/rna_constraint.cc` | RNA do Follow Peg constraint |
| `source/blender/makesrna/intern/makesrna.cc` | registro de `rna_pegrig` |
| `source/blender/makesrna/intern/rna_main.cc` | `pegrigs` na Main |

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
| `source/blender/editors/object/object_modifier.cc` | operadores `OBJECT_OT_greasepencil_contour_bind` + `OBJECT_OT_greasepencil_envelope_setup` (silhueta convex-hull → Bézier cíclica → bind → controles empty+hook em Object Mode) |
| `source/blender/editors/object/object_intern.hh` | decls dos 2 operadores |
| `source/blender/editors/object/object_ops.cc` | `WM_operatortype_append` dos 2 operadores |
| `source/blender/draw/engines/overlay/overlay_empty.hh` | `Empties::object_sync`: empties desenham com `ob->color` custom (≠ branco, não-selecionado) em vez do cinza do tema — para tingir os controles do envelope (anchor laranja / handle ciano) |

### Tool / UI Python
| Arquivo | O que foi adicionado |
|---|---|
| `scripts/startup/bl_ui/space_toolsystem_toolbar.py` | tool `builtin.peg_pose` ("Peg Pose") + keymap |
| `scripts/startup/bl_operators/wm.py` | menu `WM_MT_splash_about`: Version/Date/Hash/Branch literais + linha "Nuclear, a derivative of Blender" (branding do About) |

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
- [feito] **Set de ícones da UI (773 SVGs)** — `release/datafiles/icons_svg/*.svg` substituídos pela arte própria do autor (redesenho 16×16 baseado em *stroke*, `fill=none stroke=#fff`, vs. o original Inkscape 1100×1100 preenchido). Match de nomes 1:1 com o set upstream → **zero edição de C/CMake/Python**: o `CMakeLists.txt` (`source/blender/editors/datafiles/`, `SVG_FILENAMES_NOEXT` ≈186, `data_to_c_simple` ≈1005) embute cada SVG via `svg_icons.cc`, renderizado por nanosvg em runtime. Verificação estática: nenhum recurso fora do nanosvg (sem `<style>`/`class`/`<use>`/`<defs>`/gradiente/`currentColor`); só `path`/`circle`/`rect`/`ellipse`/`g`; todos com `viewBox`. **GOTCHA DE ESCALA (resolvido):** o rasterizador de ícones (`blf_glyph.cc:384`, `scale = gc->size / 1600.0f`) assume o SVG-fonte num canvas ~**1600px** (os ícones originais do Blender têm `width/viewBox` 1100–1700). Os do autor vinham `viewBox="0 0 16 16"` **sem `width`** → nanosvg reporta `image->width=16` (`scaleToViewbox`: `sx = image->width/viewWidth`) → `dest_w = ceil(16·size/1600) ≈ 1px` → **ícone colapsa para 1 pixel (invisível)**. Provado com teste C standalone do próprio nanosvg (broken: 16×16→dest 1×1, 1px; fixed: 1600×1600→dest 46×46, 604px). **Fix de dados (zero C):** adicionado `width="1600" height="1600"` em cada um dos 773 (mantendo `viewBox 16` → nanosvg escala conteúdo e stroke ×100). Reversível via `git checkout -- release/datafiles/icons_svg/`. **NOTA:** os SVGs-mestre do autor (fora do repo) também precisam do `width/height` senão um re-import reintroduz o bug. **ESTADO COMMITADO:** commit `620f37d` traz a arte **V1** com o fix `width=1600` (viewBox 16, fill ~67-74%). **NÃO COMMITADO (working tree, 2026-06-22):** arte **V2** (`icones_svgV2`, set atual) + **normalização de tamanho por ícone** — cada SVG reenquadrado num `viewBox` quadrado centrado no conteúdo (bbox medido via nanosvg incluindo metade do stroke) para preencher ~86% do cell, uniforme, sem distorção (viewBox quadrado) nem corte; cap de zoom 1.6× (45 ícones), 1 vazio pulado, `ipo_elastic`/overflow reenquadrado. Buildado e renderizando; pendente aprovação do tamanho pelo autor (alvo de fill é ajustável). Gotcha de fundo: zoom UNIFORME não serve porque os ícones têm tamanhos inconsistentes (maioria ~67%, ~7 já em ~95%) — só a normalização individual aumenta os pequenos sem cortar os cheios. NÃO inclui os 150 *geometry icons* `.dat` (`release/datafiles/icons/`, fonte `icons_blend/toolbar.blend`) nem o ícone do app (freedesktop/Windows) — esses seguem pendentes abaixo.
- [feito] `windowmanager/intern/wm_splash_screen.cc` — About: título "Nuclear" (≈476), nome/descrição do operador "About Nuclear" (≈499/501), e logo do Blender trocado pela arte da splash (reusa `wm_block_splash_image`, ≈453-471)
- [feito] `scripts/startup/bl_operators/wm.py` — menu About: Version/Date/Hash/Branch + linha de licença Nuclear
- [feito] `source/creator/creator_args.cc` — prints de versão usam `NUCLEAR_VERSION_STRING` (≈599, 621, 627, 656, 1340) + doc do `--version` → "Print Nuclear version"
- [feito] `windowmanager/intern/wm_init_exit.cc` — "Nuclear quit" (≈697)
- [feito] `release/datafiles/splash.png` — splash trocada por arte interna do autor (fora desta sessão)
- [feito] **Strings residuais via truque de tradução** (template `Nuclear/__init__.py`, locale `en_US`, SEM editar C; valida com `pgettext_iface`): "Blender Version", "Blender Drivers Editor", "Blender Info Log", "Load Factory Blender Preferences" → Nuclear. O template força `use_translate_interface=True` + `language='en_US'`. Isso **substitui** a necessidade de editar `screen_ops.cc`/`wm_files.cc` para essas strings — não viram pontos quentes.
- [feito] `scripts/startup/bl_operators/wm.py` — About: versão agora derivada via `_bpy._nuclear_version_string()` (não diverge mais do CLI); botões reorganizados → removidos Donate e Blender Store; "What's New" → GitHub releases do Nuclear; "Nuclear Website" → rapaduraatomica.com.br; Credits e License mantidos em blender.org (atribuição + GPL, por exigência legal)
- [ ] `windowmanager/intern/wm_splash_screen.cc` — URLs do manual ainda pendentes (≈391, 396, instalação macOS/Windows)
- [ ] `release/windows/icons/winblender.{ico,rc}` — RC tem "Blender Foundation"/"ProductName: Blender"
- [feito] **Ícone do app + `.desktop` + taskbar** — `release/freedesktop/icons/scalable/apps/blender.svg` e `.../symbolic/apps/blender-symbolic.svg` trocados pela arte própria do autor (mantidos com os nomes `blender*.svg` de propósito: renomear exigiria editar `source/creator/CMakeLists.txt`, hotspot de rebase — o ramo portátil `WITH_INSTALL_PORTABLE=ON` instala esses arquivos na **raiz** do install, que o empacotamento leva e o instalador referencia). `release/freedesktop/blender.desktop` rebrandizado (Name=Nuclear, GenericName=2D Animation, Comment, Keywords 2D, `Categories=Graphics;2DGraphics;`, `StartupWMClass=Nuclear`). `tools/nuclear_install/instalarNuclear.sh` → `Nuclear.desktop` agora com `StartupWMClass=Nuclear` + GenericName 2D. **Associação do ícone na taskbar:** WM_CLASS X11/XWayland = "Nuclear" (vem do título da janela, `GHOST_WindowX11.cc:264` copia de `title`); `app_id` Wayland nativo = "Nuclear" (`GHOST_SystemWayland.cc:9350`, fallback trocado de "blender"). **Pendente:** `org.blender.Blender.metainfo.xml` (AppStream, não é a taskbar); validação visual pós-build.
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
