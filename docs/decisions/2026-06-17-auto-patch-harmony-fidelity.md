# ADR: Melhorias de fidelidade do auto-patch nativo ao Toon Boom Harmony (A–D)

**Date**: 2026-06-17
**Status**: Accepted (implementado; validação visual pendente)
**Context**: fork Nuclear / Grease Pencil v3 (engine de render GP, depsgraph, operador, RNA)

## Context

O auto-patch nativo (branch `feat/gp-masks`) acerta o *espírito* do Auto Patch do Harmony —
sumir a linha dupla na junta mantendo o fill — mas diverge na mecânica em quatro pontos
(ver `doc/guides/nuclear_auto_patch_harmony_fidelity.md` §3):

1. O matte é a **silhueta inteira** (linha+fill) do occluder, então o corte segue a borda do
   **traço**, não da **cor** (Harmony usa o Colour Art / fill).
2. O patch é **subtrativo** e depende da **ordem de desenho** do occluder estar na frente.
3. Exige **dois objetos** GP — não há **self-patch** de junta interna nem matte de layer arbitrário.
4. Depende do occluder **visível/avaliado**; occluder oculto → `object_to_tgp` devolve null →
   patch não acontece (Harmony funciona pela **conexão**, mesmo com a fonte oculta).

A branch nunca tinha sido compilada isolada (era "validação pendente" no ADR de
2026-06-17 que separou Contour e Masks).

## Decision

Implementar as quatro modificações na `feat/gp-masks`, atrás de um **gate de build**, na ordem
**Fase 0 (build) → D → A → C → B** (risco/impacto crescente), cada uma como divergência mínima e
isolada, **preservando o contrato `.blend`** (zero mudança de DNA em A/C/D; B só adiciona estado
de engine transitório e relações de depsgraph). Cada modificação foi compilada antes da seguinte.

- **A — Matte fill-only.** Pass `fill_ps` paralelo por `tLayer` que espelha o setup do `geom_ps`
  mas recebe só os drawcalls de FILL; `draw_mask` submete `fill_ps` para os mattes cross-object
  (fallback `geom_ps`). Arquivos: `gpencil_engine_private.hh`, `gpencil_cache_utils.cc`,
  `gpencil_engine_c.cc`.
- **B — Paridade com occluder oculto.** (1) Relação de depsgraph matte→alvo em
  `deg_builder_relations.cc` (`case ID_GP`, modelada no precedente `bevobj`), com guard de
  self/datablock-compartilhado; (2) segundo passe `cache_only` no engine
  (`Instance::sync_referenced_mattes`, chamado em `end_sync`) que resolve o objeto avaliado
  (`DEG_get_evaluated`), monta um `ObjectRef` sintético e cacheia o occluder em `object_to_tgp`
  **sem** adicioná-lo às listas de desenho. O `foreach_id` de `mask->object` já existia.
- **C — Self-patch / layer arbitrário.** Operador ganhou props `matte_source` (OCCLUDER/SELF) e
  `layer`; poll relaxado (dois objetos só em OCCLUDER); self-patch (`object == ob` + AUTO_PATCH)
  roteado pelo caminho `mattes` (que com A usa fill-only e não rejeita o próprio layer).
- **D — Aviso de ordem de desenho.** Warning não-bloqueante quando occluder e peça remendada são
  coplanares (Δz < 1e-4) e o occluder não está "In Front".

O trabalho foi conduzido via o pipeline `/council` (Tier 3): investigação por agentes
read-only → arquitetura → implementação (A e B delegadas a agentes especialistas, revisadas
por diff + build) → documentação.

## Alternatives Considered

### Mod A via discard no fragment shader (push-constant novo)
- **Pros**: menos código que um segundo pass.
- **Cons**: o frag não tem um bit único "é stroke"; renderizaria strokes só para descartá-los
  (desperdício) e mexeria na interface do shader (validável só em runtime).
- **Why discarded**: o `fill_ps` no CPU usa só mecanismos já entendidos (PassSimple/draw), risco
  conceitual menor.

### Mod B só com a relação de depsgraph (sem o segundo passe no engine)
- **Pros**: metade do código.
- **Cons**: `build_object` de um objeto referenciado o marca `is_visible=false` → o iterador de
  draw não o entrega ao engine → `object_to_tgp` continua sem ele → **patch ainda não funciona**.
- **Why discarded**: a relação sozinha não entrega benefício visível; as duas metades são
  necessárias.

### Mod D forçando Z / `show_in_front` ao criar o patch
- **Cons**: mexer em `location.z` briga com pegs/`FollowPeg`; `show_in_front` é absoluto (frente
  de tudo).
- **Why discarded**: detectar+avisar é seguro, idiomático e não mexe em transform.

### Implementar direto na `integration/1.1-ui-squash`
- **Why discarded**: o código do auto-patch não vive nessa branch (foi separado para
  `feat/gp-masks`); trabalhar na branch certa mantém a cherry-pickability.

## Consequences

### Positive
- Auto-patch fica visualmente mais próximo do Harmony (corte pela cor, self-patch de junta
  interna, paridade com fonte oculta).
- A `feat/gp-masks` agora **compila isolada** (prova empírica que faltava).
- A/C/D não tocam DNA → zero risco de formato `.blend`.

### Negative / Trade-offs
- **Mod B tem premissas só confirmáveis em runtime** (geometria de objeto oculto avaliada;
  `ObjectRef` sintético; keying por `orig_id`) — ver guia §5. É a de maior risco.
- **Mod A v1** grava o `fill_ps` para todo layer todo frame (drawcalls de fill duplicados); há
  TODO de build-on-demand.
- **Mod C** expõe a escolha de layer como campo de texto no painel de redo (sem dropdown de
  busca ainda) — polimento de UI pendente.
- Build de ~20–40 min entra no ciclo; o git worktree precisa de symlink de `lib/`.

## Affected Files
- `source/blender/draw/engines/gpencil/gpencil_engine_private.hh`
- `source/blender/draw/engines/gpencil/gpencil_cache_utils.cc`
- `source/blender/draw/engines/gpencil/gpencil_engine_c.cc`
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc`
- `source/blender/depsgraph/intern/builder/deg_builder_relations.cc`
- (doc) `doc/guides/nuclear_auto_patch_harmony_fidelity.md`

> Tudo na `feat/gp-masks` (worktree `../nuclear-gpmasks`), **não commitado** — aguardando
> validação visual antes do commit.
