# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- **Tab Paint: ferramentas de brush e Lasso Fill (2026-07-06).** As categorias
  **Draw/Erase/Fill/Tint** não trocavam/aplicavam porque usavam `wm.tool_set_by_id`; no
  Blender 5.0 os brushes GP são **assets read-only** e a operação vem do **tipo do brush**
  (`get_stroke_operation`), não da ferramenta — além de **Draw e Tint** apontarem pro mesmo
  `builtin.brush` (Tint nunca virava tint). Agora `_BRUSH_TABS` mapeia os tipos e
  `nuclear.brush_tab` seta `brush.gpencil_brush_type` (+ garante `builtin.brush` ativo), o
  mesmo mecanismo que o toggle de Smudge já usa. O **Lasso Fill** não perde mais o brush: além
  da `NuclearLassoFillTool` da toolbar, há agora um **botão "Lasso Fill" na aba Brushes** que
  roda o modal **sem trocar de ferramenta**, então o brush ativo e seus controles permanecem
  (o fill em si já renderizava e já usava a cor do brush — confirmado ao vivo).
  Só `scripts/startup/nuclear_paint_toolkit.py`.
  (ver [ADR](decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md))

### Added
- **Tab Paint: modo Blur/Dissolve + raio e força do smudge (2026-07-06).** Segundo modo de
  smudge — `GPAINT_BRUSH_TYPE_BLUR` (novo append em `eBrushGPaintType`, roteado a
  `new_smooth_operation`) — que **dissolve/relaxa** traços existentes; botão "Blur / Dissolve
  Mode" ao lado de "Smudge Mode" + slider **Strength**. Corrigido no mesmo esforço: (a) o
  **raio** do smudge/blur não escalava porque as ops de sculpt leem o tamanho via
  `BKE_brush_size_get` (unified-aware) e `use_unified_size` vinha ligado → agora o GP paint
  desliga o unified size e `brush.size` (painel + cursor) passa a valer; (b) o **blur não fazia
  nada** porque `SmoothOperation` só age sob `sculpt_mode_flag & APPLY_*` → o toggle liga
  `use_edit_position`/`use_edit_strength` ao entrar em Blur; (c) o **cursor** (bolinha) de
  SMUDGE/BLUR não aparecia (raio 0 em `paint_cursor.cc`) → agora usa `brush.size/2`. Seams C
  (DNA + RNA + case + cursor) registradas no `NUCLEAR_DIVERGENCE.md`. Arquivos:
  `DNA_brush_enums.h`, `rna_brush.cc`, `grease_pencil_draw_ops.cc`, `paint_cursor.cc`,
  `nuclear_paint_toolkit.py`. Exige rebuild.
  (ver [ADR](decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md))

### Removed
- **Tab Paint: grunge texture (2026-07-06).** Removida a pedido do usuário: sai a UI/operador
  Python (`nuclear.gp_add_tip_texture` + botão "Grunge Texture") e reverte-se o fallback C
  não commitado em `grease_pencil_paint.cc` (volta ao HEAD, que mantém a amostragem de
  `brush->mtex.tex` — inerte, pois GP não expõe `mtex` via Python).
  (ver [ADR](decisions/2026-07-06-gp-paint-toolkit-remaining-fixes.md))

- **Peg Graph perdia o layout do rigger (2026-06-24).** O arranjo dos nós (posições e frames) se
  perdia ao dar **Sync**/Add Peg, ao criar **frames** com **F** (`node.join_named`) e — pior — ao
  **exportar o rig para outro arquivo**. Causas: `rebuild()` recriava a árvore lendo
  `node.location` (que é **relativo ao frame**, fazendo nós emoldurados saltarem) e **não recriava
  os frames** destruídos pelo `nodes.clear()`; e o layout vivia só no node tree, que **não viaja
  com o `PegRig`** num append/link. Fix (Python puro, sem C/DNA): o layout vira um snapshot JSON
  numa ID-property do rig (`nuclear_peg_graph_layout`) — que acompanha o datablock no export —,
  passa a usar `location_absolute` em todo lugar, e `rebuild()` recria os frames + parenteamento.
  Captura no início do `rebuild()` (antes do clear, pulando árvore vazia) e num handler `save_pre`
  (garante o caso de export). Validado headless: 15/15 asserts. Só
  `scripts/startup/nuclear_peg_graph.py`. (ver [ADR](decisions/2026-06-24-peg-graph-layout-persistence.md))

### Added
- **Integração Auto-Patch + Envelope na mainline `Nuclear` (2026-06-23).** Juntadas numa única
  branch (`integration/autopatch-envelope`, depois trazida para `Nuclear`) as duas features GP
  refinadas que viviam em branches separadas — o **Auto-Patch** engine-based (`feat/gp-masks`,
  com Mod A/B/C/D, modo `mutual` e o depth-fix `gp_in_mask_pass`) e o **Envelope/Contour** modifier
  (`integration/gp-contour-1.1`, com operador nativo de envelope + cage Bézier) — coexistindo com o
  **Cutter Modifier** que a mainline já tinha. Build limpo + smoke test headless: os 3 sistemas
  registram (`GREASE_PENCIL_MASK`, `GREASE_PENCIL_CONTOUR`, operador `grease_pencil.auto_patch`).
  Conflito de slot de modifier resolvido: **Contour realocado de eType 88 → 89** (88 fica com o
  Cutter/Mask, já na mainline). Não publicado (sem bump de `NUCLEAR_BUILD` — fica para o release).
  (ver [ADR](decisions/2026-06-23-merge-autopatch-envelope-nuclear.md))
  - Arquivos de conflito resolvidos: `gpencil_engine_c.cc`, `gpencil_cache_utils.cc`,
    `gpencil_engine_private.hh`, `shaders/infos/gpencil_infos.hh`, `grease_pencil_layers.cc`,
    `DNA_modifier_types.h`, `nuclear_peg_graph.py`, `BKE_blender_version.h`, `NUCLEAR_DIVERGENCE.md`,
    `docs/CHANGELOG.md`, `doc/guides/nuclear_auto_patch_harmony_fidelity.md`.
- **Changed:** botão/operador do Auto-Patch renomeado de "Auto-Patch (Toon Boom)" para **"Auto-Patch"**
  (label + tooltip), em `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc`.
- Auto-patch nativo (GP) — fidelidade ao Toon Boom Harmony: matte só do fill (A), paridade com
  occluder oculto via relação de depsgraph + segundo passe no engine (B), self-patch / matte de
  layer arbitrário (C) e aviso de ordem de desenho coplanar (D). Implementado e compilando na
  `feat/gp-masks` (worktree, não commitado); validação visual pendente
  (ver [ADR](decisions/2026-06-17-auto-patch-harmony-fidelity.md)).
  - Arquivos afetados (na `feat/gp-masks`): `gpencil_engine_private.hh`, `gpencil_cache_utils.cc`,
    `gpencil_engine_c.cc`, `grease_pencil_layers.cc`, `deg_builder_relations.cc`;
    doc `doc/guides/nuclear_auto_patch_harmony_fidelity.md`.
- Self-serve de release: subcomandos `bump`/`verify-zip`/`check-manifest` no
  `nuclear_release.py` e o script orquestrador `tools/nuclear_release.sh`, que encadeia
  bump → build opcional (`--build`) → empacotar → verificar regras de ouro #3/#4 →
  manifesto → publicar (com confirmação) → lembrete de CLAUDE.md → commit, para
  programadores rodarem um release sem precisar do agente Claude.
  - Arquivos afetados: `tools/nuclear_release.py`, `tools/nuclear_release.sh` (novo),
    `.claude/agents/nuclear-release.md`, `tools/nuclear_claude/CLAUDE.md`.

### Changed
- Ícone do aplicativo (logo Nuclear) no `.desktop` e na taskbar: arte do autor em
  `release/freedesktop/icons/scalable/apps/blender.svg` (+ variante `*-symbolic.svg`),
  mantendo os nomes de arquivo para não divergir o `CMakeLists.txt`. `.desktop` rebrandizado
  (Name=Nuclear, 2D Animation, `StartupWMClass=Nuclear`) no template do repo e na `.desktop`
  gerada pelo `instalarNuclear.sh`. `app_id` Wayland → "Nuclear" (`GHOST_SystemWayland.cc`);
  WM_CLASS X11 já era "Nuclear" via título → ícone associa na taskbar.
  - Arquivos afetados: `release/freedesktop/icons/scalable/apps/blender.svg`,
    `release/freedesktop/icons/symbolic/apps/blender-symbolic.svg`,
    `release/freedesktop/blender.desktop`, `tools/nuclear_install/instalarNuclear.sh`,
    `intern/ghost/intern/GHOST_SystemWayland.cc`, `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md`.
- Set de ícones da UI: os 773 SVGs em `release/datafiles/icons_svg/` trocados pela arte
  própria do Nuclear (redesenho 16×16 baseado em stroke, no lugar do set Inkscape preenchido
  do upstream). Match de nomes 1:1 → nenhuma edição de C/CMake/Python; o pipeline existente
  (`SVG_FILENAMES_NOEXT` → `data_to_c_simple` → `svg_icons.cc`, render nanosvg) embute o novo
  set no rebuild. **Correção de escala:** os SVGs vinham `viewBox="0 0 16 16"` sem `width`,
  e o rasterizador de ícones do Blender (`blf_glyph.cc`, `scale = size/1600`) espera fonte
  ~1600px → colapsavam para 1 pixel (invisíveis, reportado pelo usuário). Fix de dados:
  `width="1600" height="1600"` nos 773 (nanosvg escala o conteúdo ×100). Provado com teste C
  do nanosvg antes do rebuild. Reversível via `git checkout`.
  - **Iteração V2 (NÃO commitado — working tree, aguardando aprovação do tamanho):** arte
    trocada por `icones_svgV2` (set atual) e ícones **aumentados por normalização individual**
    — cada SVG reenquadrado num `viewBox` quadrado centrado no próprio conteúdo (medido via
    nanosvg, stroke incluído) para preencher ~86% do cell (vs ~67-74% antes), uniforme, sem
    distorção (viewBox quadrado) nem corte; cap de zoom 1.6× protege ícones minúsculos (45
    capados), 1 vazio pulado, `ipo_elastic` (transbordava) reenquadrado. Alvo de fill (86%)
    é parâmetro ajustável (`/tmp/normalize_icons.py`, var `T`). Buildado e renderizando.
  - Arquivos afetados: `release/datafiles/icons_svg/*.svg` (773),
    `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md`.
- Branding visual (Blender→Nuclear) no título da janela e nos diálogos de baixo nível que
  disparam no startup, **antes** do seam de tradução do template — por isso editados em C e
  não via `bpy.app.translations`: título inicial da janela principal (`NUCLEAR_NAME`),
  títulos e mensagens dos diálogos de suporte de GPU, o diálogo de tarefa Win32 e o título
  da janela do player de animação standalone. O `applicationName` "Blender" enviado ao
  Vulkan/XR foi deliberadamente preservado (drivers podem keyar workarounds nele).
  splash.png já estava resolvida; `.desktop`, ícones e URLs `docs.blender.org` ficam para
  ciclos futuros.
  - Arquivos afetados: `source/blender/windowmanager/intern/wm_window.cc`,
    `source/blender/windowmanager/intern/wm_platform_support.cc`,
    `intern/ghost/intern/GHOST_SystemWin32.cc`,
    `source/blender/windowmanager/intern/wm_playanim.cc`,
    `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md`.
- Separadas, em branches independentes, as duas features que o commit `90ac371` havia fundido:
  o modifier GP Contour (envelope) e as masks nativas (auto-patch). Cada metade agora é
  cherry-pickável isoladamente — `feat/gp-contour` e `feat/gp-masks`, ambas a partir do pai
  real `8d7e310` (ver [ADR](decisions/2026-06-17-separar-contour-e-masks.md)).
  - Arquivos afetados nesta linha: `doc/guides/nuclear_auto_patch_nativo.md`.

### Fixed
- `doc/guides/nuclear_auto_patch_nativo.md` §3: caminho de `grease_pencil_layers.cc` corrigido
  para `source/blender/editors/grease_pencil/intern/` (faltava `editors/`).
