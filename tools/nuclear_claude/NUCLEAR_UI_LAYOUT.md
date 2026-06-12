# Nuclear — Layout-alvo da UI (spec do P2)

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
3. **Fase C — Timeline & camadas** (#15,16,11,12,13,14): Dope Sheet simplificado embaixo +
   header de transporte custom (KF/áudio/play/frames) como addon novo.
4. **Fase D — Painel direito** (#7,8,9): container multi-aba fixo (Propriedades/Reference/
   Library/Color/Node) + materiais GP como paleta nomeada. Item mais alto do v1.
5. **Fase E — Barra ADDONS** (#4): lançadores Asset Pro/TimeOffset/etc.
6. **Adiado:** "+" abas adicionáveis (#10) e o que precisar de C de verdade.

## TODO — adiado (fim da lista; só mexer quando uma fase exigir ou por decisão explícita)

- **"+" abas adicionáveis em runtime no painel direito (#10)** — não existe nativo;
  provável C. Fora do v1; conjunto fixo de abas até lá.
- **View menu rico** — `NUCLEAR_MT_view` hoje só tem maximizar/fullscreen (entradas que
  funcionam no contexto do topbar). Enriquecer (frame all/câmera/etc.) quando existir um
  contexto de viewport Nuclear que faça esses operadores funcionarem do topo.

## Notas

- O layout físico (quais editores abertos, tamanhos, câmera) mora no **startup.blend** do
  template — regenerar de dentro do Nuclear (File > Defaults > Save Startup) quando a Fase A
  estiver definida.
- "Esconder" = `unregister_class` reversível via o seam `_HIDDEN_CLASSES`, **nunca**
  deletar o registro em C (3D fica no código).
