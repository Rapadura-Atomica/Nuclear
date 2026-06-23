---
tier: 3
specialist: general
task: "Localizar as versões mais recentes das features autopatch (feat/gp-masks) e envelope (integration/gp-contour-1.1), juntar as duas resolvendo conflitos, e integrar o resultado na versão mais atual do Nuclear (branch Nuclear). Extra: na feat/gp-masks, remover o nome 'Toon Boom' do botão do Auto-Patch."
date: "2026-06-22"
repo: "/var/home/rapaduraatomica/Documentos/GitHub/Nuclear"
worktree_gpmasks: "/var/home/rapaduraatomica/Documentos/GitHub/nuclear-gpmasks"
---

## Investigation

### Project Context
Fork Nuclear do Blender 5.0 (origin git@github.com:Rapadura-Atomica/Nuclear.git). Repo único com worktree `nuclear-gpmasks` para a branch `feat/gp-masks`. As duas features pedidas vivem em branches separadas, ambas datadas 2026-06-22:
- **Autopatch** = `feat/gp-masks` (HEAD `e336f1474c3`). Implementação ENGINE-BASED (não é modifier): oclusão de costura no draw engine GP. Operador "Auto-Patch (Toon Boom)".
- **Envelope** = `integration/gp-contour-1.1` (HEAD `6da0d2184c7`). Modifier `MOD_grease_pencil_contour.cc` + operador nativo Envelope + cage por curva Bézier + controles em Object Mode.

A branch `Nuclear` (`7ad3a045fa1`, "Refac & Fix new Icons", 2026-06-22) é a MAINLINE/alvo de deploy: tem branding/ícones, auto-update, e um **Cutter Modifier** próprio (`MOD_grease_pencil_mask.cc`, commit 775e831f7db) — um sistema de máscara baseado em MODIFIER, distinto das duas features. Nenhuma das duas features está na mainline ainda.

### Relevant Files
Sobreposição A∩B (15 arquivos; conflito real concentrado em 5 do draw engine):
- `source/blender/draw/engines/gpencil/gpencil_engine_c.cc` — **CONFLITO**; carrega máscaras do A e hooks do contour do B; contém os 3 fixes conhecidos (matpool clamp, blend fix, depth-fix gp_in_mask_pass).
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` — **CONFLITO**.
- `source/blender/draw/engines/gpencil/gpencil_engine_private.hh` — **CONFLITO**.
- `source/blender/draw/engines/gpencil/shaders/infos/gpencil_infos.hh` — **CONFLITO** (slots de UBO/textura dos dois lados).
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` — **CONFLITO**; aqui está o botão Auto-Patch (linha 1463 `ot->name = "Auto-Patch (Toon Boom)"`).
- Auto-merge limpo: `grease_pencil.cc`, `shaders/gpencil_frag.glsl`.
- DNA/RNA compartilhados: `DNA_grease_pencil_types.h`, `rna_grease_pencil.cc`, `rna_grease_pencil_api.cc`.

Botão "Toon Boom" (user-facing) → `grease_pencil_layers.cc:1463` `ot->name = "Auto-Patch (Toon Boom)"` e tooltip em :1466. Demais ocorrências de "Toon Boom" são comentários de código (não-UI).

### Conflitos medidos (git merge-tree, dry-run)
- **A ↔ B**: 5 conflitos (os 5 arquivos de draw engine acima).
- **B → Nuclear**: 4 conflitos — `DNA_modifier_types.h` (slot de enum do modifier — colide com o Cutter), `BKE_blender_version.h` (bump trivial), `nuclear_peg_graph.py`, `NUCLEAR_DIVERGENCE.md` (doc).
- **A → Nuclear**: 3 conflitos — `nuclear_auto_patch_harmony_fidelity.md` (add/add), `docs/CHANGELOG.md` (add/add), `nuclear_peg_graph.py`.

### Arquitetura de máscara por ref (decisivo)
| ref | MOD_contour.cc | MOD_mask.cc (Cutter) | máscara via engine |
|---|---|---|---|
| feat/gp-masks (A) | — | — | SIM (auto-patch) |
| integration/gp-contour-1.1 (B) | SIM | — | — |
| Nuclear (mainline) | — | SIM | — |
São TRÊS sistemas conceitualmente distintos (Cutter modifier, Auto-Patch engine, Envelope deformer). Coexistem, mas disputam os mesmos arquivos de engine.

### Riscos
- **Colisão de enum de modifier** (Contour vs Cutter em `DNA_modifier_types.h`) → quebra compat de .blend. Mitigar: IDs append-only distintos.
- **Perder os 3 fixes do engine** (matpool clamp; blend fix `897dcc4f519`; depth-fix `gp_in_mask_pass` `e3a4f264bf2`) na resolução. Mitigar: grep pós-merge.
- **Build longo + validação GPU** (distrobox blenderdev, ninja -j3 nice; RX 580/rusticl). Validação confiável = PROCESSO FRESCO (MCP não ressincroniza máscaras), GP medido da vista TOP, garantir overlap.
- Slots de UBO/textura duplicados em `gpencil_infos.hh` ao unir os dois lados.

### Gaps
Branch de integração nova (não existe). Resolução manual dos 5 conflitos de engine. Build + validação visual das 3 features juntas. Bump de versão/manifesto (agente nuclear-release) — fora do escopo desta sessão salvo pedido.

## Plan

### Chosen Approach
Criar branch de integração a partir da **mainline Nuclear** (alvo de deploy) e fazer merge sequencial: primeiro `integration/gp-contour-1.1` (mais aditivo, mais perto da Nuclear), depois `feat/gp-masks`. Cada conflito é resolvido UMA vez, já no sistema de coordenadas final (com o Cutter da Nuclear presente). Antes, aplicar o ajuste do botão na `feat/gp-masks`.

### Why This Approach
merge-tree confirma poucos conflitos por etapa (4 e depois os 5 de engine). Mergear A+B numa base antiga (ddf6a9) e só depois rebasar na Nuclear obrigaria resolver os mesmos arquivos de engine DUAS vezes (uma contra a base antiga, outra contra o Cutter da Nuclear) — retrabalho e falsa sensação de pronto. Branch é reversível.

### Execution Order
1. **(gp-masks) Remover "Toon Boom" do botão**: no worktree nuclear-gpmasks, `grease_pencil_layers.cc:1463` → `ot->name = "Auto-Patch"`; ajustar tooltip :1466 removendo "Toon Boom style". Commit na feat/gp-masks.
2. `git switch -c integration/autopatch-envelope Nuclear` (no repo Nuclear).
3. `git merge integration/gp-contour-1.1` → resolver 4 conflitos. Cuidado no `DNA_modifier_types.h` (slot do Contour ≠ Cutter, append-only).
4. `git merge feat/gp-masks` → resolver os 5 conflitos de engine unindo: Cutter (Nuclear) + Contour (B) + Auto-Patch (A). Preservar os 3 fixes do engine.
5. **Build** no distrobox blenderdev (ninja -j3 nice). Corrigir erros de compilação (provável: slots de shader, includes).
6. **Validação** em processo fresco: máscaras (auto-patch), envelope deformer e cutter funcionando juntos; vista TOP; overlap garantido.
7. Documenter: CHANGELOG + ADR + sessão.

### Files to Modify (resolução de conflito)
- 5 arquivos de draw engine GP (lista acima) — união das três contribuições.
- `DNA_modifier_types.h`, `DNA_grease_pencil_types.h`, `rna_grease_pencil*.cc` — união de slots/flags.
- `grease_pencil_layers.cc` — botão Auto-Patch (rename) + merge.
- Docs: CHANGELOG.md, NUCLEAR_DIVERGENCE.md, nuclear_peg_graph.py.

### Files NOT to Touch
- Binário portátil `~/Nuclear/` e datafiles LFS (stubs) — não tocar; build sai do repo.
- `MOD_grease_pencil_mask.cc` (Cutter da Nuclear) — preservar como está; não é o autopatch.

### Required Tests / Validation
- Build limpa compila.
- Auto-Patch corta linha mantendo fill, com 2 peças visíveis (processo fresco).
- Envelope: criar envelope 1-clique + Bind deforma via curva Bézier.
- Cutter Modifier continua funcionando (não regrediu).
- Botão aparece como "Auto-Patch" (sem "Toon Boom").

### Plan Risks
Ver seção Riscos da investigação (enum modifier; 3 fixes; build/validação GPU; slots de shader).

## ADR Draft

**ADR: Integração Auto-Patch (engine) + Envelope/Contour (modifier) sobre a mainline Nuclear**

- **Context**: Duas features GP refinadas em branches separadas (engine-based autopatch; contour/envelope modifier) precisam coexistir e ser entregues na mainline Nuclear, que já tem um terceiro sistema de máscara (Cutter Modifier) e edita os mesmos arquivos de draw engine.
- **Decision**: Branch de integração a partir de `Nuclear`; merge sequencial B (contour) → A (gp-masks), resolvendo conflitos uma única vez no contexto final. Ajuste do botão "Auto-Patch" feito antes, na `feat/gp-masks`.
- **Consequences**: Nuclear passa a ter 3 sistemas distintos (Cutter/Auto-Patch/Envelope) que dividem o engine GP — resolução de conflito precisa preservar os 3 fixes conhecidos e os slots de shader de todos. Reversível via branch. Requer build no distrobox e validação visual em processo fresco.
- **Alternatives considered**: (1) Merge A+B em base antiga e depois rebase na Nuclear — rejeitado: resolve engine 2x. (2) Octopus merge das 3 pontas — rejeitado: sem validação incremental. (3) Cherry-pick dos ~18 commits — rejeitado: mais eventos de conflito que 2 merges.
