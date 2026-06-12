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

### Add-ons / scripts de startup
- `scripts/startup/nuclear_curve_gizmo.py` — gizmos de deform de curva no viewport
- `scripts/startup/nuclear_peg_graph.py` — node editor da hierarquia de pegs
- `scripts/startup/nuclear_telemetry.py` — telemetria de presença (→ rapaduraatomica.com.br)

### Application Template Nuclear (a "costura" de UI — P0/P1/P2)
- `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` — seam central. Contém:
  - **Seam 1 (tradução):** `_TRANSLATIONS` (branding Blender→Nuclear, locale en_US) +
    `_ensure_interface_translation` (força `use_translate_interface`/`language`).
  - **Seam 2 (classes):** `_HIDDEN_CLASSES` (unregister reversível) / `_NUCLEAR_CLASSES`
    (registra `NUCLEAR_MT_logo` = menu da logo, e `NUCLEAR_MT_view`).
  - **Seam 3 (header overrides — Fase A):** troca em runtime métodos de header e restaura no
    `unregister` (`_orig_draws`): `TOPBAR_MT_editor_menus.draw` (menu curado File/Edit/View/
    Render/Help, sem Blender/Window), `TOPBAR_HT_upper_bar.draw_left` (logo Nuclear clicável →
    `NUCLEAR_MT_logo` + esconde abas de workspace), `VIEW3D_HT_header.draw` (só o mode selector).
  - **Logo:** `nuclear_logo.png` carregada via `bpy.utils.previews` (load no `register`,
    unload no `unregister`).
  - **Canvas (Fase A):** `_update_startup_canvas` trava VIEW_3D na câmera e esconde
    floor/eixos/grid/cursor/gizmos (overlays GP ficam).
  > ⚠️ **Acoplamento de runtime (não é conflito de merge, mas vigiar no rebase):** os
  > monkeypatches do Seam 3 dependem dos nomes de classe (`TOPBAR_MT_editor_menus`,
  > `VIEW3D_HT_header`) e da assinatura de `draw` do upstream. Se o upstream renomear/
  > refatorar esses headers, os overrides param de aplicar (degradam de forma silenciosa,
  > não quebram). Conferir a cada subida de versão.
- `scripts/startup/bl_app_templates_system/Nuclear/startup.blend` — **base** copiada do
  `2D_Animation`; regenerar de dentro do Nuclear com o layout 2D/cut-out final
- `scripts/startup/bl_app_templates_system/Nuclear/nuclear_logo.png` — logo (de `~/nuclear.svg`,
  256×256) mostrada no canto do topbar

### Meta / contexto de projeto (docs do fork)
- `CLAUDE.md` (raiz) — ponteiro fino que importa `tools/nuclear_claude/CLAUDE.md`
- `tools/nuclear_claude/CLAUDE.md` — contexto canônico do projeto (sincronizado entre máquinas)
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — este registro
- `tools/nuclear_claude/NUCLEAR_UI_LAYOUT.md` — spec do P2 (layout-alvo do mockup)
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

---

## 3. Branding (subconjunto de pontos quentes + dados)

Pontos onde a identidade "Blender" aparece. Itens marcados [feito] já foram alterados;
os demais são pendências do plano de rebranding.

- [feito] `BKE_blender_version.h` — `NUCLEAR_NAME` / `NUCLEAR_VERSION_STRING`
- [feito] `windowmanager/intern/wm_window.cc` — título da janela
- [feito] `windowmanager/intern/wm_splash_screen.cc` — About: título "Nuclear" (≈476), nome/descrição do operador "About Nuclear" (≈499/501), e logo do Blender trocado pela arte da splash (reusa `wm_block_splash_image`, ≈453-471)
- [feito] `scripts/startup/bl_operators/wm.py` — menu About: Version/Date/Hash/Branch + linha de licença Nuclear
- [feito] `source/creator/creator_args.cc` — prints de versão usam `NUCLEAR_VERSION_STRING` (≈599, 621, 627, 656, 1340) + doc do `--version` → "Print Nuclear version"
- [feito] `windowmanager/intern/wm_init_exit.cc` — "Nuclear quit" (≈697)
- [feito] `release/datafiles/splash.png` — splash trocada por arte interna do autor (fora desta sessão)
- [feito] **Strings residuais via truque de tradução** (template `Nuclear/__init__.py`, locale `en_US`, SEM editar C; valida com `pgettext_iface`): "Blender Version", "Blender Drivers Editor", "Blender Info Log", "Load Factory Blender Preferences" → Nuclear. O template força `use_translate_interface=True` + `language='en_US'`. Isso **substitui** a necessidade de editar `screen_ops.cc`/`wm_files.cc` para essas strings — não viram pontos quentes.
- [feito] `scripts/startup/bl_operators/wm.py` — About: versão agora derivada via `_bpy._nuclear_version_string()` (não diverge mais do CLI); botões reorganizados → removidos Donate e Blender Store; "What's New" → GitHub releases do Nuclear; "Nuclear Website" → rapaduraatomica.com.br; Credits e License mantidos em blender.org (atribuição + GPL, por exigência legal)
- [ ] `windowmanager/intern/wm_splash_screen.cc` — URLs do manual ainda pendentes (≈391, 396, instalação macOS/Windows)
- [ ] `release/windows/icons/winblender.{ico,rc}` — RC tem "Blender Foundation"/"ProductName: Blender"
- [ ] `release/freedesktop/icons/.../blender.svg` + `.desktop`
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
