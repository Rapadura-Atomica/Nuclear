---
tier: 3
specialist: general
task: "Consertar os pontos restantes do toolkit de pintura GP do Nuclear (nuclear-paint-tab-toolkit.md): (1) remover grunge texture, (2) ferramentas de brush Draw/Erase/Fill/Tint funcionarem + Lasso Fill sem brush, (4) SMUDGE ajustável + 2º modo dissolver/borrar, (5) desenho selecionado em perspectiva (quick-edit ou alternativa)"
date: "2026-07-06"
scope: "1 + 2 (+ lasso fill) + 4 (prioridade) + 5. NÃO inclui 3 (primitivas com textura)."
---

## Investigation

## 🔍 Investigation Report

### Project Context
O toolkit de pintura GP vive em `scripts/startup/nuclear_paint_toolkit.py` (791 linhas, startup script, não addon) + seams em C já commitadas (tab Paint, picker Krita, smudge, textura de bico). Branch atual `feat/gp-paint-toolkit` (HEAD `35fbb73`), base `ef66742` (sem tema/launcher). Há **2 arquivos com mudanças não commitadas**: `nuclear_paint_toolkit.py` (fill_color no mirror, stabilizer no header) e `grease_pencil_paint.cc` (fallback C do grunge — o `memcpy(MTex)` que amostra "Nuclear Grunge Tex" quando `brush->mtex.tex==null`). Confirmei o diff C ao vivo: está exatamente como a memória descreve.

### Relevant Files
- `scripts/startup/nuclear_paint_toolkit.py` — todos os operadores/painéis Python. Pontos-chave:
  - `_BRUSH_TABS` (l.34-39): **AQUI está o bug do ponto 2**. `("Draw","builtin.brush")`, `("Erase","builtin_brush.Erase")`, `("Fill","builtin_brush.Fill")`, `("Tint","builtin.brush")` — **Draw e Tint apontam para o MESMO `builtin.brush`**, e os IDs `builtin_brush.*` não trocam o *tipo* do brush em modo GP paint no 5.0.
  - `NUCLEAR_OT_brush_tab` (l.329-342): faz `wm.tool_set_by_id(name=self.tool_id)` — abordagem errada pro 5.0.
  - `NUCLEAR_OT_smudge_toggle` (l.345-357): **o padrão CERTO já existe aqui** — escreve `brush.gpencil_brush_type = 'DRAW'/'SMUDGE'` direto no brush ativo, e isso FUNCIONA (validado ao vivo).
  - `NUCLEAR_OT_add_tip_texture` (l.363-397) + `_GRUNGE_TEX_NAME` (l.360): grunge a REMOVER (ponto 1).
  - `NUCLEAR_PT_paint_brushes.draw` (l.568-596): a UI que mostra a linha de categorias (l.577-579) + botão "Smudge Mode" (l.589) + botão "Grunge Texture" (l.595-596, a REMOVER).
  - `NUCLEAR_OT_lasso_fill._create_fill` (l.500-556): cria stroke via `add_strokes`, seta `material_index`/`fill_color`/`fill_opacity` e radius 0.01. **NÃO associa brush** — o traço nasce sem vínculo de brush (bug reportado).
- `source/blender/editors/sculpt_paint/grease_pencil_draw_ops.cc` — `get_stroke_operation` (l.92-123): o switch que roteia `gpencil_brush_type` → operação. `case GPAINT_BRUSH_TYPE_SMUDGE` (l.119-121) → `new_grab_operation`. **É aqui que entra o 2º modo do smudge (ponto 4).**
- `source/blender/editors/sculpt_paint/grease_pencil_paint.cc` — `PaintOperationExecutor` (~l.690): o fallback C do grunge (não commitado). **Decidir: reverter (ponto 1) ou deixar inerte.**
- `source/blender/editors/sculpt_paint/grease_pencil_intern.hh` (l.220-243): catálogo de operações disponíveis. Relevante pro ponto 4: `new_smooth_operation(stroke_mode, bool)` (l.228) e `new_vertex_blur_operation()` (l.239) são candidatos ao "2º modo dissolver/borrar".
- `source/blender/makesdna/DNA_brush_enums.h` — `GPAINT_BRUSH_TYPE_SMUDGE = 4` (append). O 2º modo precisaria de `= 5`.
- `source/blender/makesrna/intern/rna_brush.cc` — `rna_enum_brush_gpencil_types_items` (item SMUDGE já lá).

### Identified Patterns
- **5.0: brush = asset linkado read-only.** `paint.brush` é read-only; `asset_activate` de brush local falhou historicamente. O que FUNCIONA e é o padrão-ouro do fork: escrever **`brush.gpencil_brush_type`** direto no brush ativo (o smudge toggle prova). Toda troca de "modo de pincel" deve seguir isso, NÃO `wm.tool_set_by_id`.
- **Seam C mínima + registro:** cada divergência em C é append no enum + item RNA + case no switch, registrada em `NUCLEAR_DIVERGENCE.md`. Sem DNA reorder, sem versionamento (append em enum é seguro).
- **Validação de pincel GP = usuário desenhando** (scriptar `GREASE_PENCIL_OT_brush_stroke` via MCP volta PASS_THROUGH). Recentes/textura/etc. validam em **processo fresco**, nunca em reload em cadeia (timers-zumbi).

### Reusable Code
- `NUCLEAR_OT_smudge_toggle.execute` — o mecanismo `brush.gpencil_brush_type = ...` é reusável tanto pro conserto do ponto 2 (Draw/Erase/Fill/Tint) quanto pra ciclar o 2º modo do smudge.
- `new_grab_operation` (já roteado) — base do smudge; o 2º modo pluga o mesmo jeito com `new_smooth_operation`.
- `_gp_paint_brush(context)` (l.63) — helper central de acesso ao brush ativo.

### Impacted Dependencies
- Trocar `brush_tab` de `tool_set_by_id`→`gpencil_brush_type` afeta só o operador + a linha de UI (l.577-579). Precisa mapear label→tipo do enum RNA (`DRAW`/`ERASE`/`FILL`/`TINT`).
- Ponto 4 (2º modo) exige **rebuild C** de `build_nuclear_full`: mexe em `DNA_brush_enums.h` + `rna_brush.cc` + `grease_pencil_draw_ops.cc`. É o único rebuild da rodada.
- Ponto 1 (remover grunge): se só esconder UI → Python puro (sem build). Se reverter o C → o `grease_pencil_paint.cc` volta ao estado commitado (`git checkout`), sem rebuild se o binário atual já não tiver o fallback compilado — **CHECAR se o binário em uso já tem o fallback**; se tiver, reverter exige rebuild.

### Identified Risks
- **Rebuild C caro (~build_nuclear_full).** Mitigar: agrupar TODAS as mudanças C (ponto 4 + eventual reversão do grunge) num único rebuild. Checar `free -m` antes (memória: sessões DPE paralelas). Ver [[ram-blender-sessoes-paralelas]].
- **`tool_set_by_id` pode ser necessário pra Erase/Fill de verdade** (Erase e Fill são ferramentas com keymap próprio, não só tipo de brush). Risco: mudar tudo pra `gpencil_brush_type` pode quebrar o comportamento de Fill (que usa `do_fill_guides`). Mitigar: investigar na fase de implementação se Fill/Erase precisam da ferramenta OU só do tipo; possivelmente híbrido (tipo p/ Draw/Tint, ferramenta p/ Erase/Fill).
- **Lasso Fill "sem brush":** o traço de fill em GP v3 não referencia brush por natureza; o sintoma real precisa ser reproduzido ao vivo (o fill pode simplesmente não renderizar por falta de `show_fill`/material correto, e o usuário interpretou como "sem brush"). Mitigar: reproduzir em sessão fresca antes de decidir o fix.
- **Ponto 5 (perspectiva) é design, não código pronto.** Risco de escopo estourar. Mitigar: entregar como proposta no ADR + protótipo Python leve (não bloquear a rodada nele).
- **Timers-zumbi** ao validar via reload. Mitigar: validar sempre em processo fresco (`cp` addon → limpar `__pycache__` → relançar).

### Gaps / What Needs to Be Created
- Mapa label→`gpencil_brush_type` correto pro 5.0 (e decisão híbrido tipo-vs-ferramenta pra Erase/Fill).
- Novo valor de enum `GPAINT_BRUSH_TYPE_*` pro 2º modo do smudge (ex.: `_SMEAR`/`_BLUR = 5`) + item RNA + case no switch → `new_smooth_operation`.
- Reprodução ao vivo do bug do Lasso Fill pra determinar o fix exato.
- Proposta de "editar desenho selecionado em perspectiva" (ponto 5).

---

## Plan

## 📐 Implementation Plan

### Chosen Approach
Consertar a família "brush não troca/aplica" (pontos 2 + Lasso) migrando de `wm.tool_set_by_id` para o padrão-ouro do fork (`brush.gpencil_brush_type`, possivelmente híbrido pra Erase/Fill); remover o grunge (ponto 1) escondendo a UI Python e revertendo o fallback C não commitado; e adicionar o 2º modo do smudge (ponto 4) como um novo valor de enum roteado a `new_smooth_operation` — tudo num **único rebuild C**. O ponto 5 entra como proposta+protótipo leve, sem bloquear.

### Why This Approach
A própria base de código já prova (smudge toggle) que escrever `gpencil_brush_type` funciona no 5.0 onde `tool_set_by_id`/asset_activate falham (Investigation → "Identified Patterns"). Agrupar as mudanças C num rebuild só respeita o custo alto do `build_nuclear_full` e a restrição de RAM. Reverter o grunge C (não commitado) é a opção mais limpa e reversível vs. deixar código morto no motor.

### Execution Order
1. **Ponto 1 — grunge (Python + C):** remover `NUCLEAR_OT_add_tip_texture`, `_GRUNGE_TEX_NAME` e o botão "Grunge Texture" (l.360, 363-397, 594-596) do Python; `git checkout` no `grease_pencil_paint.cc` (reverte o fallback não commitado). Se o binário em uso já tiver o fallback compilado, entra no rebuild do passo 4.
2. **Ponto 2 — brush tabs (Python):** reescrever `NUCLEAR_OT_brush_tab` + `_BRUSH_TABS` para setar `brush.gpencil_brush_type` (Draw/Tint) e decidir Erase/Fill (tipo vs. ferramenta) após reproduzir ao vivo. Corrigir o Tint que hoje = Draw.
3. **Lasso Fill (Python):** reproduzir o bug em processo fresco; garantir que o stroke criado tenha brush/material/fill válidos e renderize.
4. **Ponto 4 — 2º modo smudge (C, REBUILD):** `DNA_brush_enums.h` novo enum (`= 5`), item RNA em `rna_brush.cc`, case no switch de `grease_pencil_draw_ops.cc` → `new_smooth_operation`; UI: o toggle/linha cicla Draw→Smudge→(2º modo). Rebuild `build_nuclear_full` (checar `free -m` antes). Reverter grunge C no mesmo build.
5. **Ponto 5 — perspectiva (proposta + protótipo):** operador Python leve que orienta o desenho selecionado à câmera/perspectiva (sem C), como POC; documentar alternativas no ADR.
6. **Validação ao vivo em processo fresco** (matar Blender, `cp` addon pro bin, limpar `__pycache__`, relançar) — recentes/tools/smudge/lasso/grunge-sumiu.
7. **Registrar seams C** novas no `NUCLEAR_DIVERGENCE.md`; commit(s) na `feat/gp-paint-toolkit`.

### Files to Modify
- `scripts/startup/nuclear_paint_toolkit.py` — pontos 1, 2, lasso, 5, UI.
- `source/blender/makesdna/DNA_brush_enums.h` — novo `GPAINT_BRUSH_TYPE_*` (ponto 4).
- `source/blender/makesrna/intern/rna_brush.cc` — item RNA do novo tipo.
- `source/blender/editors/sculpt_paint/grease_pencil_draw_ops.cc` — case no switch.
- `source/blender/editors/sculpt_paint/grease_pencil_paint.cc` — reverter fallback grunge.
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — registrar a nova seam.

### Files NOT to Touch
- Seams C já commitadas da tab Paint / picker Krita / textura de bico (só a de grunge muda).
- Sistema de auto-update / versão (rodada de feature, não release).

### Resulting Interface / Contract
- Linha de categorias na tab Paint troca o **tipo do brush ativo** (comportamento consistente com o toggle de smudge).
- Smudge vira um ciclo de 2 modos (smear via grab + dissolver/borrar via smooth).
- Grunge some da UI e do motor.
- Lasso Fill produz preenchimento visível e válido.

### Required Tests
- Processo fresco: Draw/Erase/Fill/Tint realmente trocam e pintam.
- Smudge modo 1 (smear) e modo 2 (dissolve) arrastam/borram traços existentes.
- Lasso Fill cria fill visível tingido pela cor do brush; espelha com symmetry.
- Grunge Texture não aparece mais na UI; strokes normais sem modulação espúria.
- Build C: `ninja` RC 0; smoke headless (o novo tipo de brush registra).

### Plan Risks
- Erase/Fill podem exigir a ferramenta (keymap), não só o tipo → resolver na implementação (possível híbrido).
- Reverter grunge C pode forçar rebuild se já compilado no binário atual.
- Ponto 5 pode não ter solução Python-only satisfatória → entregar como proposta, não bloquear a rodada.

---

### ❌ Discarded Alternative: Manter `wm.tool_set_by_id` e "consertar" os tool IDs
- **O que seria:** achar os IDs corretos de ferramenta de brush GP no 5.0 e usar `tool_set_by_id`.
- **Por que descartado:** no 5.0 a ferramenta genérica é `builtin.brush` e o *tipo* vem do brush asset ativo; trocar ferramenta não troca tipo de brush confiavelmente. O próprio fork já contornou isso via `gpencil_brush_type` (smudge). Insistir na ferramenta reintroduz o bug.

### ❌ Discarded Alternative: Deixar o fallback C do grunge inerte (sem reverter)
- **O que seria:** só esconder a UI Python; o `grease_pencil_paint.cc` fica com o `memcpy(MTex)` dormindo (só ativa se existir o datablock).
- **Por que descartado:** deixa código morto numa seam de motor upstream-mantida, contra a diretriz "minimize e isole divergência C". Reverter o não commitado é mais limpo e reversível.

### ❌ Discarded Alternative: Ponto 5 via editor externo (Quick Edit clássico)
- **O que seria:** exportar o desenho selecionado, editar em app externo, reimportar.
- **Por que descartado:** o usuário quer editar *em perspectiva dentro do Nuclear*; export/reimport é fluxo de texture-paint, não cut-out 2D. Proposta melhor: orientar/projetar o desenho selecionado na view perspectiva nativamente.

---

## 📄 ADR Draft: Consertar o toolkit de pintura GP — troca de brush por tipo, remoção do grunge, 2º modo de smudge

**Context**: A tab Paint tinha 4 pontos pendentes: ferramentas de brush que não trocavam/aplicavam (e Lasso Fill sem brush), um grunge texture que o usuário quer remover, um smudge que precisa de 2º modo, e a demanda de editar desenho em perspectiva. A raiz do bug de troca de brush é o uso de `wm.tool_set_by_id` num 5.0 onde brush é asset e o tipo mora em `brush.gpencil_brush_type`.

**Decision**: Padronizar toda troca de "modo de pincel" via `brush.gpencil_brush_type` (o padrão que o smudge toggle já prova); remover o grunge da UI e reverter seu fallback C não commitado; adicionar um 2º modo de smudge como novo valor de enum roteado a `new_smooth_operation`; entregar o "editar em perspectiva" como proposta+POC Python.

**Consequences**: Fica mais fácil (comportamento de brush consistente e testável; menos divergência C viva). Fica mais difícil / custa: um rebuild `build_nuclear_full` (agrupado) e registro de nova seam no `NUCLEAR_DIVERGENCE.md`. Erase/Fill podem precisar de tratamento híbrido tipo-vs-ferramenta a decidir na implementação.

**Alternatives considered**: ver seção "Discarded Alternatives" acima.

[Note: o Documenter finaliza e move isto para docs/decisions/]
