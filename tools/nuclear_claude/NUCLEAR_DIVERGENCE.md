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

### Modifier Grease Pencil "Contour" / Envelope (deform MVC + cage Bézier, estilo Toon Boom)
- `source/blender/modifiers/MOD_grease_pencil_contour.hh` — `contour_sample_cage()` compartilhada (modifier + operadores)
- `source/blender/modifiers/intern/MOD_grease_pencil_contour.cc` — modifier Contour (MVC, cage mesh ou Bézier, bind)

### Add-ons / scripts de startup
- `scripts/startup/nuclear_curve_gizmo.py` — gizmos de deform de curva no viewport
- `scripts/startup/nuclear_peg_graph.py` — node editor da hierarquia de pegs
- `scripts/startup/nuclear_telemetry.py` — telemetria de presença (→ rapaduraatomica.com.br)

### Application Template Nuclear (a "costura" de UI — P0)
- `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` — seam: handler de
  startup + pontos de extensão para tradução-remap e de/registro de painéis (vazios até P1/P2)
- `scripts/startup/bl_app_templates_system/Nuclear/startup.blend` — **base** copiada do
  `2D_Animation`; regenerar de dentro do Nuclear com o layout 2D/cut-out final

### Meta / contexto de projeto (docs do fork)
- `CLAUDE.md` (raiz) — ponteiro fino que importa `tools/nuclear_claude/CLAUDE.md`
- `tools/nuclear_claude/CLAUDE.md` — contexto canônico do projeto (sincronizado entre máquinas)
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — este registro
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

### Modifier Grease Pencil "Contour" / Envelope (registro do modifier + operadores + overlay)
| Arquivo | O que foi adicionado |
|---|---|
| `source/blender/makesdna/DNA_modifier_types.h` | `eModifierType_GreasePencilContour` (=32→**88**); struct `GreasePencilContourModifierData` (object/strength/flag + **bind_co/bind_verts_num**); enum `GreasePencilContourFlag` (CONFORMAL, **BOUND**) |
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
| `source/blender/blenkernel/BKE_blender_version.h` | `NUCLEAR_NAME`, `NUCLEAR_VERSION_STRING` |
| `source/blender/windowmanager/intern/wm_window.cc` | título de janela usa `NUCLEAR_NAME` (≈559, 644) |

---

## 3. Branding (subconjunto de pontos quentes + dados)

Pontos onde a identidade "Blender" aparece. Itens marcados [feito] já foram alterados;
os demais são pendências do plano de rebranding.

- [feito] `BKE_blender_version.h` — `NUCLEAR_NAME` / `NUCLEAR_VERSION_STRING`
- [feito] `windowmanager/intern/wm_window.cc` — título da janela
- [feito] `windowmanager/intern/wm_splash_screen.cc` — About: título "Nuclear" (≈476), nome/descrição do operador "About Nuclear" (≈499/501), e logo do Blender trocado pela arte da splash (reusa `wm_block_splash_image`, ≈453-471)
- [feito] `scripts/startup/bl_operators/wm.py` — menu About: Version/Date/Hash/Branch + linha de licença Nuclear
- [ ] `windowmanager/intern/wm_splash_screen.cc` — URLs do manual ainda pendentes (≈391, 396); botões de link do About (Donate/Credits/Store/Website) ainda apontam para blender.org
- [ ] `source/creator/creator_args.cc` — prints "Blender %s" (≈599, 622, 627, 656, 1340)
- [ ] `windowmanager/intern/wm_init_exit.cc` — "Blender quit" (≈697)
- [ ] `release/datafiles/splash.png` (fonte: `splash_template.xcf`) — ou env `BLENDER_CUSTOM_SPLASH` / `splash.png` no diretório do template
- [ ] `release/windows/icons/winblender.{ico,rc}` — RC tem "Blender Foundation"/"ProductName: Blender"
- [ ] `release/freedesktop/icons/.../blender.svg` + `.desktop`
- [ ] `editors/screen/screen_ops.cc` — "Blender Drivers Editor", "Blender Info Log" (≈6437, 6494)
- [ ] `windowmanager/intern/wm_files.cc` — "Load Factory Blender Preferences" (≈2782)
- [ ] `makesrna/intern/rna_space.cc` — "Filter Blender*" (≈7479, 7486, 7535)
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
