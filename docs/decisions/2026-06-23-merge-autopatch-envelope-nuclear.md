# ADR: Integração Auto-Patch (engine) + Envelope/Contour (modifier) sobre a mainline Nuclear

**Date**: 2026-06-23
**Status**: Accepted
**Context**: fork Nuclear (Blender 5.0) — subsistema Grease Pencil

## Context

Duas features GP refinadas viviam em branches separadas e precisavam coexistir e ser
entregues na branch mainline `Nuclear`:

- **Auto-Patch** (`feat/gp-masks`, HEAD `e336f1474c3`): oclusão de costura *engine-based*
  (sem modifier), com as modificações de fidelidade ao Harmony Mod A/B/C/D, modo `mutual`
  e o depth-fix `gp_in_mask_pass`. Operador `grease_pencil.auto_patch`.
- **Envelope/Contour** (`integration/gp-contour-1.1`, HEAD `6da0d2184c7`): modifier
  `MOD_grease_pencil_contour.cc` (deform MVC, cage mesh **ou** curva Bézier) + operador
  nativo de envelope (silhueta convex-hull → Bézier cíclica → bind) + controles em Object Mode.

A mainline `Nuclear` (`7ad3a045fa1`) já trazia um **terceiro** sistema de máscara — o
**Cutter Modifier** (`MOD_grease_pencil_mask.cc`, modifier-based) — além de branding/ícones
e o auto-update. Nenhuma das duas features estava na mainline. Ambas divergiram de uma base
comum (`ddf6a9ca7c5`, 2026-06-11) que já tinha uma versão inicial das máscaras de engine, e
foram re-derivadas (não compartilham o commit fundido `90ac371`), então o git via a base
antiga e os arquivos de draw engine GP conflitavam de verdade (15 arquivos sobrepostos,
18 hunks em 5 arquivos de engine).

## Decision

Criar uma branch de integração a partir da **mainline `Nuclear`** (alvo de build/deploy) e
fazer **merge sequencial**: primeiro `integration/gp-contour-1.1` (envelope, mais aditivo /
mais perto da Nuclear), depois `feat/gp-masks` (auto-patch). Cada conflito resolvido **uma
única vez**, já no contexto final (com o Cutter presente). O resultado validado foi então
trazido para a branch `Nuclear`.

Decisões pontuais de conflito:
- **Slot de modifier**: o Cutter já estava na mainline como `eModifierType_GreasePencilMask = 88`;
  o Contour, que também reivindicava 88, foi **realocado para 89** (append-only, sem quebrar
  compat de `.blend` do Cutter). Doc de divergência atualizada.
- **`nuclear_peg_graph.py`**: a mainline dirige os mattes pelo **Cutter modifier** (implementação
  mais nova e deliberada do mesmo masking cross-object); as branches traziam a versão
  engine-based herdada da base antiga. Mantida a versão da mainline (não perde funcionalidade).
- **`BKE_blender_version.h`**: mantida a versão mais alta da mainline (1.3.0 / build 4); o bump
  de release fica para o agente `nuclear-release`.
- **Arquivos de engine** (5): resolvidos como **união 3-way** preservando as três contribuições
  e, em especial, os fixes conhecidos do auto-patch (matpool clamp, blend fix `897dcc4f519`,
  depth-fix `gp_in_mask_pass` `e3a4f264bf2`, deferred sync `referenced_mattes`).
- **Botão**: o operador do Auto-Patch foi renomeado de "Auto-Patch (Toon Boom)" para "Auto-Patch".

## Alternatives Considered

### Merge A+B numa base antiga e só depois rebase na Nuclear
- **Pros**: isola a junção das duas features antes de encarar a mainline.
- **Cons**: obriga a resolver os mesmos 5 arquivos de engine **duas vezes** (contra a base
  antiga e depois contra o Cutter da Nuclear).
- **Why discarded**: retrabalho e falsa sensação de "pronto" na primeira resolução.

### Octopus merge das três pontas de uma vez
- **Pros**: um único comando.
- **Cons**: sem validação incremental; conflitos de três lados ao mesmo tempo.
- **Why discarded**: impossível isolar qual lado introduziu cada regressão.

### Cherry-pick dos ~18 commits das duas features sobre a Nuclear
- **Pros**: histórico linear.
- **Cons**: cada commit com edições sobrepostas de engine vira um evento de conflito.
- **Why discarded**: muito mais eventos de conflito que 2 merges.

## Consequences

### Positive
- A mainline `Nuclear` passa a ter os três sistemas GP coexistindo: **Cutter** (modifier),
  **Auto-Patch** (engine seam patch) e **Envelope/Contour** (deformer).
- Build limpo (ninja, RC 0) + smoke test headless confirmam o registro dos três.
- Resolução de conflito num único sistema de coordenadas; reversível (foi feita em branch).

### Negative / Trade-offs
- Três mecanismos que mexem nos mesmos arquivos de draw engine aumentam o acoplamento —
  qualquer rebase futuro contra upstream precisa reconciliar os três (registrado no
  `NUCLEAR_DIVERGENCE.md`).
- Validação **visual** das máscaras 2D (corte de linha mantendo fill, com peças visíveis)
  ainda depende de inspeção humana em processo fresco — o smoke test cobre só o registro.

## Affected Files
- `source/blender/makesdna/DNA_modifier_types.h` (Contour 88→89)
- `source/blender/draw/engines/gpencil/{gpencil_engine_c.cc,gpencil_cache_utils.cc,gpencil_engine_private.hh,shaders/infos/gpencil_infos.hh}`
- `source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc` (merge + rename do botão)
- `scripts/startup/nuclear_peg_graph.py`, `source/blender/blenkernel/BKE_blender_version.h`
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md`, `docs/CHANGELOG.md`,
  `doc/guides/nuclear_auto_patch_harmony_fidelity.md`
