# Handoff — seleção de pegs no viewport (hit-test do Grease Pencil) — 2026-08-04

## Objetivo

O usuário relatou: **"clico numa peça do rig e vem outra"**, e depois **"as masks ainda aparecem
e as pegs continuam destoantes dos objetos"**. A meta é fazer o clique (e o contorno de seleção)
no viewport corresponderem ao desenho que o artista vê, num rig cut-out 2D de Grease Pencil.

Nada foi commitado. Tudo vive na working tree do repo `~/Documentos/GitHub/Nuclear`, branch
`Nuclear` (HEAD `e189ca8ee59`).

## Estado atual

**Diagnóstico completo (contexto que não se redescobre sozinho — detalhes na memória
`nuclear-selecao-peg-diverge-do-render`).** Eram QUATRO causas somadas, não uma:

1. **Duas ordens de profundidade sem relação.** O engine GP pinta os objetos ordenados pela
   profundidade da **origem** do objeto (`gpencil_cache_utils.cc:54`) e limpa o depth buffer entre
   eles — a geometria não decide nada. O prepass de seleção resolvia pelo `gl_FragCoord.z`
   **geométrico** do traço, porque o fragment shader pula o depth plane sob `SELECT_ENABLE`.
2. **Tolerância de 14 px** do pick (`mixed_bones_object_selectbuffer`): abre larga e só estreita
   quando mais de um objeto responde — num rig denso, a peça vizinha roubava o clique. Era a
   **maior** fonte de erro (19 de 21 no rig de referência), não a ordem.
3. **Masks ignoradas no hit-test** — o corte só existe no engine (`draw_mask`). Num rig cut-out
   isso é a maioria do desenho: 21 das 23 masks do dinossauro recortam a camada de cor pela de
   linha, então a área clicável era o fill **bruto**, que extravasa o contorno. É o que o usuário
   sentia como "a peg não bate com o objeto".
4. **Objetos auxiliares** (deform curves) ficam por cima da arte e disputavam o clique.

**Implementado e medido (build atual em `~/Documentos/GitHub/build_nuclear_2d/bin/nuclear`):**

- Ordem do clique alinhada à do render (`compute_selection_depth_planes` reconstrói o sort do
  engine; o **vertex** shader grava a profundidade sob `SELECT_ENABLE`, porque no fragment o
  upstream não pode — quebra o early depth test).
- Tolerância: `object_selectbuffer_tight()` começa em 2 px e só alarga (5, 14) se **nada**
  responder. Só no Pick Peg; o `view3d.select` padrão não foi tocado.
- Ciclo no Pick Peg (clicar de novo desce para a peça de trás) + propriedade `location` no
  operador (é assim que o teste automatizado dispara cliques).
- Camada com `opacity < 1e-4` deixa de ser clicável (`is_visible()` do upstream só olha HIDE).
- Mask **do mesmo objeto**: atalho sem rasterizar nada — o que sobrevive à mask é subconjunto do
  matte, e o select id é por objeto, então basta não desenhar a camada mascarada.
- Mask **cross-object**: corte real por **stencil** (matte escreve `ref`, camada desenha com
  `STENCIL_EQUAL`, num `PassSimple`). Vale para clique e contorno.
- Deform curves: `selectbuffer_prefer_grease_pencil()` descarta hits que não são desenho quando
  algum desenho respondeu.

**Números — clique REAL na GUI** (script `teste_clique_gui.py`, grade de 18 px, "defensável" =
topo da pilha ou linha da peça a ≤4 px):

| rig | antes (build 17) | agora |
|---|---|---|
| Atena | 73,1% | **96,2%** |
| Dinossauro | 56,5% | **89,1%** |
| Lala | 22,2% | **83,3%** |
| Carolina | 59,5% | **76,0%** |

Regressão conferida: smoke 2D **ALL PASS** e render **idêntico pixel a pixel** (360.000 px, diff
máx 0,0) contra o binário publicado.

**⚠️ O que está em aberto e é uma decisão do usuário.** O corte por stencil é uma **troca**, não
ganho puro: zera os erros de mask nos 4 rigs (inclusive `detalhe.torso`, o caso que o usuário
apontou), mas corta um pouco mais que o real e cobra em tolerância. Comparado com o estado
"só atalho local, sem stencil": Atena e Lala **idênticos**; dinossauro 91,3% → 89,1%; Carolina
80,2% → **76,0%** (tolerância 0 → 15). O usuário foi perguntado se quer perseguir esses 15 pontos
da Carolina ou fechar assim — **ainda não respondeu**.

## Próximos passos

1. **Aguardar a decisão do usuário** sobre a troca acima. Para reverter o stencil e voltar aos
   91,3%/80,2% (com o cross-object errado de novo), basta `gather_stencil_mattes()` em
   `source/blender/draw/engines/overlay/overlay_grease_pencil.hh` devolver `false` sempre.
2. Se for perseguir os 15 pontos da Carolina: a suspeita **não investigada** é que o matte
   rasteriza silhueta ligeiramente menor que a real — o shader não faz `discard` em modo seleção
   e o depth plane do matte é computado à parte. Comece comparando a área do matte no stencil com
   a área do fill do objeto matte.
3. Commitar. Mensagem em **inglês**, Conventional Commit, **sem** linha `Co-Authored-By`
   (regra do usuário). Sugestão: `fix(overlay): make Grease Pencil picking match what is drawn`.
   ⚠️ **Commitar SÓ os arquivos desta frente** (lista abaixo) — a working tree tem outra frente
   misturada.
4. Só depois, se o usuário quiser, publicar release (agente `nuclear-release`; regras em
   `tools/nuclear_claude/CLAUDE.md` §5-10, e **pushar antes de buildar**).

## Decisões tomadas (e por quê)

- **Profundidade escrita no VERTEX shader, não no fragment.** O upstream desligou o depth plane em
  seleção porque reescrever `gl_FragDepth` quebra o early depth test exigido. No vertex é exato: o
  plano é planar em world space, então interpolar z/w cai na mesma profundidade.
- **Tolerância apertada só no Pick Peg.** Mexer na cascata do `view3d.select` afetaria a seleção
  de malhas e ossos em todo o Blender — divergência grande com upstream, sem ganho para o 2D.
- **REJEITADO — afundar os objetos-matte para trás de tudo.** Parecia resolver "o cutter rouba o
  clique", mas na prática o matte é o **próprio desenho** (na receita da pupila, o olho recorta a
  pupila): rebaixá-lo jogava o olho para trás do corpo. O teste de ordem pegou (8 pares
  divergentes na Carolina). Não há como separar "cutter puro" de "desenho que também serve de
  matte" sem marcação explícita do artista.
- **REJEITADO — pular a camada mascarada também no caso cross-object.** O matte responde com outro
  select id, e em `detalhe.torso` a camada mascarada é a **única** com conteúdo: a peça ficaria
  sem contorno e sem área clicável.
- **Onion skin: desligado no arquivo do dinossauro, não no código.** Não era bug — as camadas têm
  frames em 1 e 3, então no frame 1 o onion desenhava a pose do frame 3 (as "manchas lilás").
  Backup em `dinossauro_backup_pre-onion-off_2026-08-04.nuc`; volta pelo toggle "Onion" no header.

## Pegadinhas / lições desta sessão

- **A causa que eu subestimei era a maior.** O diagnóstico inicial apontou a ordem de profundidade
  como culpada; ao medir o clique real, 19 dos 21 erros vinham da **tolerância de 14 px**. Medir o
  comportamento real mudou a prioridade — não confie só na leitura de código.
- **A métrica estava cega para o que faltava.** O primeiro teste comparava com "topo da pilha
  pelos fills", que também ignora mask — por isso os números pareciam bons enquanto o usuário via
  o contrário. Corrigir a métrica veio antes de corrigir o código.
- **⚠️ Capturar o viewport por script NÃO funciona nesta máquina.** `screen.screenshot_area`
  devolve framebuffer obsoleto/corrompido (chuvisco colorido, e overlays que continuam aparecendo
  mesmo com `show_overlays = False`). Perdi bastante tempo tirando conclusões visuais dessas
  imagens. `render.opengl` sai limpo mas **não inclui overlays**, então não serve para conferir
  contorno/gizmo. **Para validar qualquer coisa visual, peça a captura ao usuário.**
- **A falha do stencil não era do stencil.** Na primeira tentativa as camadas mascaradas *sumiam*
  (91,3% → 68,1%) e tudo apontava para o stencil. Era o **plano de profundidade**: cada
  `draw_grease_pencil` registra um plano novo, e a camada recortada — um draw separado — ganhava
  profundidade própria ATRÁS da própria peça, onde o depth test a matava. Correção: draws do mesmo
  objeto compartilham um plano (`GreasePencilDepthPlane.object`).
- `--debug-gpu-compile-shaders` **crasha neste build** (`Error source not found:
  osd_patch_basis.glsl`, OpenSubdiv OFF no preset 2D). É **pré-existente**, idêntico no binário
  publicado — não é regressão. Por isso o GLSL foi validado disparando seleções reais na GUI.
- O tipo do shader no framework de draw é `gpu::Shader *`, não `GPUShader *` (custou um build).

## Arquivos e comandos relevantes

**Arquivos DESTA frente (os únicos a commitar):**
- `source/blender/draw/engines/overlay/overlay_grease_pencil.hh` — o grosso: ordem de
  profundidade, atalho de mask local, corte por stencil, filtro de camada.
- `source/blender/draw/engines/overlay/overlay_prepass.hh` — caminho do clique.
- `source/blender/draw/engines/overlay/overlay_outline.hh` — caminho do contorno.
- `source/blender/draw/engines/overlay/overlay_private.hh` — campos novos no depth plane.
- `source/blender/draw/engines/overlay/shaders/overlay_depth_only_gpencil_vert.glsl` — grava a
  profundidade sob `SELECT_ENABLE`.
- `source/blender/editors/space_view3d/view3d_select.cc` — tolerância apertada, ciclo, preferência
  por Grease Pencil.
- `source/blender/editors/include/ED_view3d.hh` — declaração da variante com ciclo.
- `source/blender/editors/object/object_pegrig.cc` — Pick Peg com ciclo + `location`.
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — registro da divergência (obrigatório pelo
  CLAUDE.md; já atualizado com tudo acima).

**⚠️ Arquivos modificados por OUTRA frente — NÃO commitar junto:**
`scripts/startup/nuclear_deform_curve.py`, `scripts/startup/nuclear_rig_auto.py`,
`source/blender/editors/object/object_modifier.cc`, `source/blender/makesdna/DNA_modifier_types.h`,
`source/blender/modifiers/MOD_grease_pencil_curve.hh`,
`source/blender/modifiers/intern/MOD_grease_pencil_curve.cc`,
`tools/nuclear_claude/DeformCurveFeature.md`, `tools/nuclear_claude/RigAutoFeature.md`.
São trabalho de Deform Curve / bind (rest samples), de outra sessão.

**Comandos:**
```sh
# build (container distrobox; ~10 min porque headers do overlay tocam muita coisa)
distrobox enter blender -- bash -lc 'cd ~/Documentos/GitHub/build_nuclear_2d && \
  nice -n15 /usr/bin/ninja -j2 install'

# gate obrigatório
~/Documentos/GitHub/build_nuclear_2d/bin/nuclear -b --factory-startup \
  --python ~/Documentos/GitHub/Nuclear/tools/smoke_nuclear2d.py

# teste do clique REAL (abre GUI por ~10 s, usa --factory-startup para não tocar as prefs)
cd <scratchpad> && ~/Documentos/GitHub/build_nuclear_2d/bin/nuclear --factory-startup \
  <rig.nuc> --python teste_clique_gui.py     # resultado em resultado_clique.txt
```

**Scripts de medição** (no scratchpad da sessão, `/tmp/claude-1001/.../scratchpad/` — **copie para
um lugar durável se quiser reusar**): `teste_clique_gui.py` (clique real na GUI, o mais
importante), `diag_ordem.py` (as duas profundidades), `diag_mask.py` (área clicável vs visível),
`diag_pivos.py` (pivô da peg vs bbox das peças), `render_ab.py` + `cmp_px.py` (A/B de render).

**Rigs de teste:**
- `~/Dropbox/.../9_ArquivosDeRig_PersonagensSecundarios/EP6/Dinossauro/dinossauro.nuc` — o mais
  duro (origens todas em Y=0, 23 masks, 8 deform curves).
- `~/Dropbox/.../9_ArquivosDeRig_PersonagensSecundarios/EP05/ATENA/atena_pegs.blend`
- `~/Downloads/carolina_pegs_atualizada.blend` — 44 masks, o que mais sente o stencil.
- `~/Downloads/conversão/lala/lala_atualizada.nuc`

## Pendências que dependem do usuário

- **Decidir a troca do stencil**: manter (mask cross-object correta, ~2-4 pontos de custo em
  tolerância na Carolina e no dinossauro) ou reverter (mais preciso no geral, `detalhe.torso`
  volta a responder fora do desenho). A pergunta foi feita e não respondida.
- **Autorizar o commit** (e se quiser, o release).
- Teste na mão: o dinossauro ficou aberto na GUI (PID 438626 nesta sessão) com tudo aplicado.
- Decisão de workflow, à parte: as 8 deform curves do rig continuam clicáveis onde não há desenho
  por baixo. Se elas nunca devem competir pelo clique, é outra mudança.
