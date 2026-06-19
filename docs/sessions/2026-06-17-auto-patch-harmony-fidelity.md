# Session: Auto-patch nativo — fidelidade ao Toon Boom Harmony (A–D)

**Date**: 2026-06-17
**Tier**: 3 — Full
**Specialist**: general (gráficos/sistemas C++/GLSL)
**Pipeline**: /council (Router → Investigator×5 → Architect+ADR → Specialist → Review → Documenter)

## Task
Ler `doc/guides/nuclear_auto_patch_harmony_fidelity.md` e implementar as melhorias de fidelidade
do auto-patch nativo ao Harmony (modificações A–D), delegando a agentes.

## What Was Done
- **Investigação**: 5 agentes read-only contra um worktree isolado da `feat/gp-masks`
  (`../nuclear-gpmasks`) mapearam o código real (file:line corrigidos) e a prontidão de build.
- **Fase 0 (build-gate)**: build isolado da `feat/gp-masks` provado (build dir `../build_gpmasks`,
  distrobox `blenderdev`, `ninja -j8 && ninja install`). Causa-raiz do 1º fracasso: worktree não
  carrega `lib/` → symlink de `lib/linux_x64` da árvore principal.
- **Mod D** (aviso de ordem coplanar) — feito + compila.
- **Mod A** (matte fill-only via `fill_ps` paralelo) — delegada a agente, revisada, compila.
- **Mod C** (self-patch / layer arbitrário; props matte_source+layer) — feito + compila.
- **Mod B** (relação depsgraph + segundo passe `cache_only` no engine) — delegada a agente,
  revisada (todos os pontos de compile-risk verificados contra headers reais), compila.
- Documentação: ADR, atualização do guia (§4/§5), CHANGELOG, esta sessão, memória.

## Decisions Made
- Ordem **D→A→C→B** por risco/impacto crescente; build entre cada uma para isolar erros.
- A/C/D **sem mudança de DNA** (contrato `.blend` intacto). B só adiciona estado de engine
  transitório + relações de depsgraph (e o `foreach_id` de `mask->object` já existia).
- Mod A via segundo `PassSimple` (não via discard no shader) — mecanismos já entendidos.
- Mod B precisa das DUAS metades (relação + segundo passe); a relação sozinha é inerte porque
  `build_object` marca o referenciado `is_visible=false`.
- Mod D: detectar+avisar (não forçar Z / `show_in_front`, que brigam com pegs / são globais).
- Build limitado a `-j8` e log na home (não `/tmp`, que não é compartilhado de forma estável com
  o container) — a pedido do autor (cuidado com memória; `/tmp` derrubou o log antes).

## Modified Files (na `feat/gp-masks`, worktree, NÃO commitado)
- `source/blender/draw/engines/gpencil/gpencil_engine_private.hh` — campo `fill_ps`, `Set referenced_mattes`, assinaturas `cache_only`/`sync_referenced_mattes`.
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc` — `fill_ps` espelhado; `cache_only` em cache_add; roteamento self-patch; coleta de mattes.
- `source/blender/draw/engines/gpencil/gpencil_engine_c.cc` — mirror fill no `object_sync_do`; `draw_mask` usa `fill_ps`; `sync_referenced_mattes` em `end_sync`.
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` — props matte_source/layer, exec ramificado, aviso de ordem (D).
- `source/blender/depsgraph/intern/builder/deg_builder_relations.cc` — `case ID_GP` relação matte→alvo.

## Architectural Decision
ADR: [`docs/decisions/2026-06-17-auto-patch-harmony-fidelity.md`](../decisions/2026-06-17-auto-patch-harmony-fidelity.md)

## Pendências
- **Validação visual** (domínio do autor): polaridade da máscara; A bate com o Harmony (corte
  pela cor); self-patch (C); e as 3 premissas runtime da Mod B (geometria de objeto oculto
  avaliada, `ObjectRef` sintético válido, keying por `orig_id`).
- **Commit**: as mudanças estão no worktree, não commitadas — aguardando validação.
- Follow-ups: build-on-demand do `fill_ps` (A); dropdown de busca de layer na UI (C).
