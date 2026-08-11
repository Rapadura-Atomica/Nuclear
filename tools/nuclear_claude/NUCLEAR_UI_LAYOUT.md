# Nuclear — Layout-alvo da UI (spec do P2)

> ## ⏸️ PONTO DE PARADA — pausa em 2026-06-12 (LER PRIMEIRO AO RETOMAR)
>
> **Onde paramos:** P2 (reforma de UI) completo + **Xsheet Toon Boom** até **T5 (parcial)**.
> Tudo via o template `scripts/startup/bl_app_templates_system/Nuclear/__init__.py` (Seams 1–7),
> reversível, sem editar `bl_ui` in-place. Pequenas edições de branding em C (ver DIVERGENCE).
> **Nada commitado/pushed** — o usuário faz os commits/push (NUNCA commitar sem ele pedir).
>
> **Estado do Xsheet (timeline Toon Boom — Seam 7):** grade células×camadas desenhada em **GPU**
> por cima do Dope Sheet, mapeada pelo **view2d nativo** (alinha com régua/agulha nativas).
> Gestos: clique=frame+camada · arrastar=scrub · **Ctrl+clique**=criar/apagar exposição ·
> **Alt+arrastar**=mover · **Shift+Alt+arrastar**=duplicar · clique nos quadrados=vis/lock.
> Mostra nº do desenho (com zoom), linhas a cada 5 frames, fantasma no drag. Onion skin
> toggle no header do viewport.
>
>
> **Desde 2026-08-11 o Xsheet mora em `scripts/modules/nuclear_xsheet.py`**, não mais
> dentro do `Nuclear/__init__.py` — os templates **2D Animation** e **Storyboarding**
> chamam o mesmo módulo e ganham a MESMA timeline. Só a timeline: o transport (+KF/-KF,
> play, campos de frame) continua sendo override de header do template Nuclear, e nos
> outros dois o footer nativo de playback fica no lugar. Trazido do fork privado
> Nuclear-Ditivado, que já rodava a versão com seleção de células em bloco.
> **Próximos passos (em ordem):**
> 1. **T5.1** — seleção de células (refletir/editar `frame.select`) + nome custom do desenho.
> 2. **TODO antigos** (ver fim do arquivo): tools custom **Seleção/Câmera** (Fase B; Onion já
>    virou toggle), **"+" de abas persistente**, **View menu rico**.
> 3. Wire real de **Asset Pro/TimeOffset** quando esses addons existirem (1 linha em
>    `_NUCLEAR_LAUNCHERS`).
>
> **Como buildar/rodar/ver (fluxo desta máquina):**
> - Editar `__init__.py` → `python3 -m py_compile <arquivo>` → instalar:
>   `distrobox enter nuclear-build -- bash -lc 'cd /var/home/rapaduraatomica/Nuclear-git/build_linux && ninja install'`
>   (Python-only não precisa recompilar C; mudou C → o mesmo `ninja install` recompila.)
> - Rodar com o template ativo: `… bin/blender --app-template Nuclear`.
> - **Validar headless**: `… bin/blender --background --app-template Nuclear --python /tmp/x.py`
>   (NÃO chamar `register()` de novo — o template já registra; daria erro de tradução dupla).
> - **Screenshot p/ eu mesmo ver** (não há MCP de print): o Blender tira o próprio print —
>   `bpy.ops.screen.screenshot(filepath=...)` num `bpy.app.timers` (≈3 s) sob
>   `temp_override(window=...)`. Recortar/ampliar com `magick`. `spectacle` do host pega a
>   janela errada (terminal por cima).
> - **Gotchas de shell:** `pkill -f "bin/blender"` **auto-mata o próprio comando** (o padrão
>   aparece no argv) → usar o truque `pkill -f "[b]in/blender"`. `quit_blender()` sai com código
>   144 (inofensivo; o PNG é gerado). NÃO juntar `pkill`+heredoc no mesmo comando (aborta).
> - **C/branding** roda no container `nuclear-build` (host Bazzite imutável não tem toolchain).
>
> **Princípio inviolável:** divergência mora em arquivos novos / no template; ao tocar arquivo
> do upstream, registrar em `NUCLEAR_DIVERGENCE.md`. Overrides de header/keymap/tema são
> **acoplamento de runtime** (dependem de nomes do upstream) — conferir a cada rebase.

> Spec da reforma de UI, derivada do mockup do autor
> (`~/Downloads/UI_NUCLEAR_INFORMACOES.png`). É o roteiro concreto do **P2** do plano:
> esconder/realocar/curar a UI nativa do Blender para a "cara" do Nuclear, **sem remover
> função** e preferindo a costura do template (Python) a editar C.
>
> Meta acordada: alcançar **≥60%** do mockup. Idioma: **inglês** (sem tradução por ora).
> Janela/workspace **único** (sem as abas Layout/Modeling/etc. do Blender).

## Decisões travadas (2026-06-12)

- **Color Palette** = **materiais do Grease Pencil** (cada swatch = uma parte: Line, Pele,
  Cabelo, Iris_olho…). Mapeia na lista de materiais do GP, não na Palette de brush.
- **"+" para adicionar abas em runtime** = **fora do v1**. Painel direito com conjunto
  **fixo** de abas. O sistema de abas adicionáveis (custom, provável C) fica pra fase
  posterior.
- **Timeline** = **só keyframes** (estilo Dope Sheet). Sem handles de interpolação
  editáveis (os handles verde/roxo do mockup são decorativos). Graph Editor não entra no v1.
- **Linha "ADDONS"** (Item/Tools/Asset Pro/TimeOffset) = **barra de lançadores de
  addons/ferramentas Nuclear**, não categorias de N-panel.

## Mapa região → nativo → ação

Mecanismo: **[T]** = costura do template (`Nuclear/__init__.py`, hide/relocate Python) ·
**[N]** = arquivo novo (addon/painel `nuclear_*.py`) · **[B]** = startup.blend (layout) ·
**[C]** = exige C (ponto quente — registrar no DIVERGENCE).

| # | Região | Nativo | Ação | Mec. | Custo |
|---|---|---|---|---|---|
| 1 | Logo (sup. esq.) | ícone "Blender menu" do topbar | trocar/remover | [T]/[C] | 🟢 |
| 2 | MODOS "Draw Mode" | seletor de modo GP (`object.mode_set`) | realocar ao topbar, curar p/ modos GP | [T] | 🟢 |
| 3 | MENU File/Edit/View/Render/Help | `TOPBAR_MT_editor_menus` | esconder Blender/Window; manter os 5 | [T] | 🟢 |
| 4 | ADDONS Item/Tools/Asset Pro/TimeOffset | — | barra custom de lançadores de addon | [N] | 🟡 |
| 5 | ÁREA DE TRABALHO (canvas+moldura) | `VIEW_3D` na câmera | lock câmera, esconder gizmos/overlays 3D | [T]/[B] | 🟢 |
| 6 | FERRAMENTAS (toolbar vertical) | toolbar GP Draw (`space_toolsystem_toolbar.py`) | curar: brush/seleção/onion/câmera/borracha/balde/linha | [T] | 🟡 |
| 7 | ABAS Propriedades/Reference/Library | `PROPERTIES` + Asset Browser + ref. images | container multi-aba (fixo) à direita | [T]/[B] | 🟠 |
| 8 | ABA Node View e Materiais | editor de nós / props de material | aba no painel direito | [T]/[B] | 🟠 |
| 9 | Color Palette (Line/Pele/Cabelo…) | **materiais do GP** | realocar lista de materiais como paleta nomeada | [N] | 🟡 |
| 10 | "+" adicionar abas | — | **adiado** (fora do v1) | [C] | 🔴 |
| 11 | + KF / − KF | inserir/remover keyframe GP | botões no header de transporte | [N] | 🟢 |
| 12 | Áudio / scrubbing | áudio da cena + `use_audio_scrub` | toggles no header | [N] | 🟢 |
| 13 | PLAY/PAUSE/AVANÇAR | transporte (`screen.animation_play`, frame jump) | header de transporte custom | [N] | 🟢 |
| 14 | DEFINIR FRAMES (Frame/Start/End) | frame atual + `frame_start`/`end` | campos no header | [N] | 🟢 |
| 15 | CAMADAS Drawings/Rigs | camadas GP / canais Dope Sheet | coluna esquerda da timeline | [T] | 🟡 |
| 16 | TIMELINE | `DOPESHEET_EDITOR` (modo GP) | embaixo, simplificada (só keyframes) | [T]/[B] | 🟡 |

## Ordem de implementação proposta (barato→caro, sempre verificável)

1. **Fase A — Topbar & canvas** (#1,2,3,5): menus curados, modo Draw no topo, viewport
   travado na câmera com overlays/gizmos 3D escondidos. Tudo [T]/[B]. Maior "wow" por menos
   esforço. **✅ FEITO (2026-06-12)** — via Seam 3 do `Nuclear/__init__.py`:
   - #3 Menu curado **File/Edit/View/Render/Help** (override de `TOPBAR_MT_editor_menus.draw`;
     remove menu "Blender" e "Window"). View = `NUCLEAR_MT_view` (fullscreen/maximize por ora).
   - #2 **Draw Mode** isolado no header do viewport (override de `VIEW3D_HT_header.draw` →
     só o mode selector; some View/Select/Add/Object/shading/gizmos do header).
   - #5 Canvas: `_update_startup_canvas` trava na câmera + esconde floor/eixos/grid/cursor/gizmos.
   - #1 **Logo** Nuclear **clicável** no canto sup. esq. (override de `TOPBAR_HT_upper_bar.draw_left`):
     `nuclear_logo.png` (de `~/nuclear.svg`, 256×256) via `bpy.utils.previews`, desenhada como
     `layout.menu` → `NUCLEAR_MT_logo` (Splash Screen, About Nuclear, Install Application
     Template, submenu System: Reload Scripts/Memory Statistics/Debug Menu/Redraw Timer/
     Clean Up Space Data/Clean Up Operator Presets — reusa o `TOPBAR_MT_blender_system`).
     O mesmo override **esconde as abas de workspace** (app de workspace único; mantém o
     "Back to Previous" no fullscreen).
   - Validado headless (register→patch→logo→canvas→unregister→restore+unload, sem exceção).
   - **Fase A fechada — sem pontas soltas.**
2. **Fase B — Toolbar** (#6): curar a toolbar vertical do GP Draw ao set do mockup.
   **✅ FEITO (2026-06-12)** — via **Seam 4** do `Nuclear/__init__.py`:
   - Troca reversível da entrada `'PAINT_GREASE_PENCIL'` de `VIEW3D_PT_tools_active._tools`
     (dict de classe salvo/restaurado). Set curado: **brush · borracha (Erase) · balde (Fill)
     · grupo linha** (line default; polyline/box/circle/arc/curve no dropdown) **· eyedropper**.
   - "Esconder não remover": tools ocultos (cursor/trim/interpolate) saem só da barra; os
     operadores seguem acessíveis por menu/atalho.
   - Validado headless (idnames conferidos + restauração ao unregister).
   - **Fase B fechada.** Seleção/Onion/Câmera **não são tools do Draw mode** → ver TODO.
3. **Fase C — Timeline & camadas** (#15,16,11,12,13,14): Dope Sheet simplificado embaixo +
   header de transporte custom (KF/áudio/play/frames).
   **✅ FEITO (2026-06-12)** — via **Seam 3** do template (refino do plano: a curadoria é
   **gated ao template Nuclear**, então mora no Seam 3, não num addon global de `scripts/startup/`
   — senão vazaria pro Blender padrão):
   - #16/#15 **Dope Sheet em modo GPENCIL** embaixo (`_update_startup_timeline` força `mode='GPENCIL'`
     em toda área `DOPESHEET_EDITOR`) → canais de camada com olho/cadeado (#15) + keyframes (#16),
     ambos nativos.
   - #11/#12/#13/#14 **Transporte minimal** no topo do Dope Sheet (override de `DOPESHEET_HT_header.draw`
     só no modo GPENCIL; outros modos caem no original salvo): **Mute/Scrub** (áudio) ·
     **+KF/−KF** · **REW/Play-Pause/FF** · **Frame/Start/End**.
   - **+KF/−KF** = `grease_pencil.insert_blank_frame` / `grease_pencil.delete_frame`.
     ⚠️ Se "+KF" deveria *duplicar o desenho atual* em vez de inserir quadro em branco, trocar
     por `grease_pencil.frame_duplicate` (decisão de produto — confirmar).
   - Validado headless (patch + fallback + mode-set + restauração).
   - **Pendência da Fase C:** no `startup.blend` regenerado, manter o **footer** do Dope Sheet
     **desligado** (`DOPESHEET_HT_playback_controls`) p/ não duplicar o transporte. Botões de
     add/remove camada saíram do header (transporte os substituiu); camadas seguem geridas pelos
     canais (olho/cadeado) — readicionar ao header se fizer falta.
4. **Fase D — Painel direito** (#7,8,9): container multi-aba fixo (Propriedades/Reference/
   Library/Color/Node) + materiais GP como paleta nomeada. Item mais alto do v1.
   **Decisão (revisada p/ 100% do mockup, C liberado):** abas REAIS que trocam o tipo de
   editor da área (não mais "Properties curado + empilhados", que foi reprovado por ser
   aproximação). **Paleta Color** = aba Material (lista de materiais nativa).
   **✅ CÓDIGO FEITO (2026-06-12)** — Python, sem C ainda:
   - **Tab strip** (`_draw_nuclear_tabs`) prependado nos headers de `PROPERTIES_HT_header`,
     `IMAGE_HT_header`, `NODE_HT_header`, `FILEBROWSER_HT_header` (Seam 3). Abas:
     **Properties**(PROPERTIES/TOOL) · **Reference**(IMAGE_EDITOR) · **Library**(ASSETS) ·
     **Color**(PROPERTIES/MATERIAL) · **Peg Graph**(`NuclearPegTree` — o node editor de pegs
     do `nuclear_peg_graph.py`, não o shader genérico) + **"+"** (`NUCLEAR_MT_add_tab`).
   - `NUCLEAR_OT_set_area_tab` troca `area.ui_type` (e `context` p/ Properties). A barra
     aparece em TODOS os editores-alvo → nunca fica preso numa aba.
   - **Dois boxes do mockup** = duas áreas-direita empilhadas, cada uma com a strip completa,
     parkadas em abas diferentes (Propriedades em cima, Color/Peg Graph embaixo). Resolve sem C.
   - #7 Properties segue curado (`_update_startup_properties`: Tool/Object/Modifiers/Effects/
     Data/Material; 14 abas escondidas) — vira o conteúdo das abas Properties/Color.
   - #9 **Paleta Color = lista limpa** (`NUCLEAR_PT_color_palette` + `NUCLEAR_UL_color_palette`,
     Properties/material). Cada linha: **swatch de cor arredondado** (cor habilitada do material
     — stroke se `show_stroke`, senão fill; arredondado pelo tema) + **nome do material**
     renomeável inline ("para que a cor serve", ex. "Line Personagem 1"). **Removido:** ghost/
     hide/lock e as linhas/marks de Stroke/Fill. Mantido +/− e mover (discretos). Painéis
     verbosos de material (`MATERIAL_PT_gpencil_*`) escondidos via `_HIDDEN_CLASS_NAMES`.
     O **"+" usa `NUCLEAR_OT_palette_add`** (cria material GP real, não slot vazio) — senão a
     cor não era editável (bug corrigido 2026-06-12). Editar a cor = clicar no swatch (color
     picker). Edição de **fill** separada ainda não exposta (decisão: só swatch base por ora).
   - **Abas por-box (o "bloco C") — FEITO SEM DNA:** conjuntos nomeados (`_TABSETS`: "main" =
     Propriedades/Reference/Library; "shading" = Color/Peg Graph) atribuídos por posição no load
     (`_assign_tabsets`: top-right="main", abaixo="shading"; `_resolve_tabset` por índice de
     área). Bate o mockup (boxes com abas distintas) **sem tocar na `ScrArea`/DNA** → risco de
     rebase zero. Default "all" quando não há 2 áreas-alvo.
   - Validado headless (palette reg/restore, painéis escondidos/restaurados, props de cor,
     resolução de tab-set, troca de editor).
   - **Pendências/divergências (ver TODO):** (a) o "+" troca p/ tipos extras mas **não persiste**
     lista custom; (b) **visual pílula** das abas/botões = C de widgets; (c) startup.blend:
     criar as 2 áreas-direita (a atribuição main/shading é automática por posição).
### Fase T — Timeline estilo Toon Boom (Xsheet) — INCREMENTO GRANDE, em andamento

Refatoração drástica da timeline pra grade de células (Xsheet do Toon Boom): células por
camada×frame, cheia=exposição/desenho, vazia=sem. **Arquitetura:** render custom em **GPU**
(Python) por cima da área Dope Sheet de baixo + (futuro) operador modal pra interação. Gated
ao template, sem C. Ref.: mockup + Toon Boom Harmony.
- **T1 — render read-only ✅ FEITO (2026-06-12)** — Seam 7: `_xsheet_draw` (draw_handler
  POST_PIXEL em `SpaceDopeSheetEditor`). Grade camada×frame, exposição (`key`/`hold` via
  `_xsheet_exposed`), régua de frames, playhead, nomes das camadas; fundo opaco cobre o dope
  sheet nativo. Lê `ob.data.layers[].frames[].frame_number`. Cap de 400 frames (perf).
- **T2 — ✅ FEITO** — realce da camada ativa + coluna do frame atual + indicadores vis/lock por
  camada (estado; clicáveis no T3).
- **T3 — interação modal ✅ FEITO (read/navega)** — `NUCLEAR_OT_xsheet_click` + keymap LEFTMOUSE
  no Dopesheet (poll-gated). Clique em célula = frame + camada ativa; arrastar = scrub; clique
  nos quadrados vis/lock = alterna; clique no nome = ativa camada.
- **Correção de alinhamento (2026-06-12):** a "agulha errada" era o **indicador de frame nativo**
  (desenhado por cima, não-cobrível) vs minha grade fixa. **Fix:** mapear X pelo **view2d nativo**
  (`_xsheet_fx`) — célula/agulha/régua/indicador num só sistema. Canais nativos escondidos. Scroll/
  zoom nativos de brinde. **Falta T4** (criar/mover/apagar exposição).
- **T4 — edição ✅ FEITO (criar/apagar)** — `NUCLEAR_OT_xsheet_toggle` + keymap **Ctrl+LEFTMOUSE**:
  alterna a exposição da célula (`layer.frames.new/remove`), por layer+frame, UNDO, respeita lock.
- **T4.1 — mover/duplicar ✅ FEITO** — `NUCLEAR_OT_xsheet_drag` + keymap **Alt+arrastar = mover**
  (`layer.frames.move`), **Shift+Alt+arrastar = duplicar** (`layer.frames.copy`); ambos preservam
  o desenho, com **fantasma** de preview (`_xsheet_drag` lido pelo draw), UNDO, respeita lock.
- **T5 — polish ✅ FEITO (parcial)** — **número do desenho** (índice do keyframe) dentro da célula
  quando larga o bastante; **linha de grupo a cada 5 frames** (ênfase); cores Toon Boom navy.
  **Falta T5.1:** seleção de células (reflexo de `frame.select`) + nome custom do desenho.
> Limites T1: read-only, sem scroll (layout fixo), interação vem no T3. Cap de frames evita
> lag; virtualizar se o range for grande.

5. **Fase E — Barra ADDONS** (#4): lançadores Asset Pro/TimeOffset/etc.
   **✅ FEITO (2026-06-12) — DINÂMICA** via Seam 3, override de `VIEW3D_HT_tool_header.draw`
   (linha abaixo do "Draw Mode"; brush settings moram no painel direito, então a linha fica
   livre). **Conceito:** os painéis que addons registram no N-panel (lateral direita) são
   trazidos pro HEADER aqui — a lateral "sobe" pro topo e a barra **cresce/encolhe** conforme
   addons entram/saem. `_sidebar_categories()` enumera as categorias VIEW_3D/UI a cada draw
   (live); para cada uma, `layout.popover_group(...)` desenha os painéis que passam no poll do
   modo atual (fica enxuto). Categorias atuais: Animation/Item/Peg(PegRig)/Tool/View.
   `show_region_tool_header=True` garantido no canvas.
   > Perf: enumeração por-draw varre `bpy.types` (~centenas). Se pesar, cachear e refrescar
   > no load/registro. Nota: a categoria/contexto passados ao `popover_group` podem precisar de
   > ajuste fino por modo — validar visualmente quais painéis aparecem.

## TODO — restante p/ 100% de fidelidade (C/estrutura liberados; alvo é o mockup integral)

> Não são mais "adiados por escopo" — são o trabalho restante pra bater 100% do mockup,
> sequenciados do mais barato ao mais caro.

- **"+" persistente (#10)** — hoje o "+" só troca p/ tipos extras. Pra ser abas custom
  persistentes do usuário: guardar uma lista por-área (CollectionProperty) e reconstruir a
  strip dela. (O subconjunto fixo por-box já está resolvido via `_TABSETS`/`_assign_tabsets`.)
- ~~Subconjunto de abas por box~~ — **FEITO** sem DNA (conjuntos nomeados por posição;
  ver Fase D). Identidade por-área em C só seria necessária se quiser tab-sets arbitrários
  arrastáveis pelo usuário.
- ~~Formato dos widgets (visual pílula/arredondado) via C~~ — **RESOLVIDO via TEMA**, sem C.
  O tema expõe `roundness` (0..1) por grupo de widget + cores → o look pílula/navy do mockup
  é dado, não `interface_widgets.cc`. Ver **Seam 6** (tema Nuclear). C de widgets só seria
  necessário pra formatos que o tema não expressa (não é o caso do mockup).
- **Toolbar: Seleção / Onion Skin / Câmera** (lista do mockup, fora do Draw mode):
  - *Seleção* — vive no Edit mode do GP. Integrar via troca de modo ou tool custom.
  - *Onion Skin* — toggle de overlay; vira tool/operador custom na toolbar.
  - *Câmera* — sem tool nativo; tool custom (posicionar/travar câmera). Definir comportamento.
- **View menu rico** — `NUCLEAR_MT_view` só tem fullscreen/maximize (o que funciona do
  topbar). Enriquecer (frame all/ver câmera) precisa de operador-ponte com contexto de viewport.

## startup.blend — REGENERADO (2026-06-12) ✅

Regenerado por script (data API headless, não GUI manual) e salvo em
`scripts/startup/bl_app_templates_system/Nuclear/startup.blend`. Base = 2D_Animation;
mudança-chave: o **OUTLINER (topo-direita) virou um 2º PROPERTIES** → coluna direita com
**duas áreas Properties empilhadas** = os dois boxes de abas do mockup. Backup do 2D base em
`Nuclear-git/nuclear_startup_2Dbase.blend.bak` (fora do repo). Estado por tela "2D Animation":

- [x] **Centro:** VIEW_3D travado na câmera, grid/gizmos off (baked + reforçado no load).
- [x] **Embaixo:** Dope Sheet modo GPENCIL, **footer off** (`show_region_footer=False`) — o
      transporte fica no header (override Nuclear), sem duplicar.
- [x] **Direita:** 2 áreas Properties — top = set "main" (default tab Properties/Tool), baixo =
      set "shading" (default tab Color/Material) via `_apply_default_tabs`. As abas
      Reference/Library/Node estão na strip; o usuário troca quando quiser (não precisam ser
      áreas físicas separadas — cada box troca de editor pela aba).
- [x] **Esquerda:** toolbar GP Draw curada (no modo Draw).
- Workspaces: mantidos "2D Animation" + "2D Full Canvas" (tabs escondidas pelo código).
- "2D Full Canvas" segue como modo de desenho sem distrações (viewport + dope sheet).

> Re-regenerar: rodar de novo o script de regeneração OU ajustar na GUI e
> `wm.save_mainfile(filepath=<startup.blend do template>)`. Depois `ninja install`.

## Notas

- "Esconder" = reversível via os Seams do template (`unregister_class` / override de draw /
  toggles de space), **nunca** deletar o registro em C (3D fica no código).
- **Acoplamento de runtime:** os overrides de header/toolbar dependem de nomes de classe e
  assinaturas do upstream — conferir no rebase (ver `NUCLEAR_DIVERGENCE.md`).
