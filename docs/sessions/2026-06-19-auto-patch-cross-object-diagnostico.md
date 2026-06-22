# Session: Revisão do cross-object auto-patch GP (+ lição de método)

**Date**: 2026-06-19
**Tier**: 2 (light — o "conserto" real é conveniência de operador, não bug de engine)
**Specialist**: general (draw-engine GP)
**Pedido original**: "leia e conserte o cross object" em
`doc/guides/nuclear_auto_patch_validation_b_2026-06-18.md`

## Task

Junta de cutout estilo Harmony: ao sobrepor duas peças GP (ex.: cotovelo), a **linha que invade o fill
da outra peça** deve sumir, formando junta limpa que se mantém no movimento.

## Desfecho (importante: houve um diagnóstico errado no meio)

1. Plano inicial (Tier 2, aprovado): operador `grease_pencil.auto_patch` criar a **máscara recíproca**
   no occluder → corte mútuo bidirecional.
2. Na validação ao vivo, conclui **erradamente** que "o auto-patch é inerte em camadas STROKE / o feature
   está quebrado". Cheguei a documentar isso (depois revertido).
3. **Causa do erro = método de medição**, não o código:
   - A cena `nuclear_autopatch_debug.blend` tem geometria no **plano X-Y → exige vista TOP**; medi de
     **FRONT** (perfil/borda → "bloco preto" → render-diff ~0).
   - No personagem, braço em pose de descanso **não tem sobreposição** → nada a cortar → 0 (ON=OFF
     correto). Self-patch por fill co-localizado também dá 0 enganoso.
4. Re-medido da **vista TOP** correta (caso B, occluder oculto): **o feature FUNCIONA.**

## Evidência da correção (cena de debug, vista TOP, caso B)

| Estado | Δpx | Veredito |
|---|---|---|
| `ap_off` (máscara normal, corta linha+fill) | 7240 | ✅ |
| `ap_on` (auto-patch, mantém fill) | 4849 | ✅ |
| `ap_on` vs `ap_off` (= fill preservado) | 4605 | ✅ |
| PartLower **stroke-only**, máscara normal | 4785 | ✅ corta stroke |

§3–§6 do guia **procedem**. Mod B (occluder oculto via sync diferido) também.

## Lição de método (registrada no guia §10 e na memória)

- Descobrir o **plano da geometria** (`bound_box` world) e renderizar **de frente pra ele**
  (X-Y→TOP, X-Z→FRONT). Conferir com **1 screenshot antes** de confiar em números.
- Garantir **sobreposição real** entre alvo e matte na região visível.
- `render.opengl(view_context=True)` é válido (com cor); **viewport-screenshot pode sair preto** nessa
  cena — não confiar nele.
- Ao reivindicar "validado", **dizer qual vista/câmera**.

## Implementado: modo `mutual` (Tier-2)

`grease_pencil.auto_patch` ganhou a prop booleana **`mutual`** (cross-object): além da máscara no layer
ativo (A→B), cria a **recíproca no occluder** (B→A, `auto_patch+invert`, matte = objeto ativo inteiro;
alvo = layer de mesmo nome no occluder, fallback layer ativa; anti-duplicata). 1 arquivo:
`source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc`. Build incremental ok (binário
20:29).

**Validação ao vivo (cena debug, vista TOP):** uma chamada criou os dois lados; primário corta 4849px,
recíproco 2147px (cada um medido com o outro oculto = caso B); screenshot confirmou linha cortada na
região do matte + fill mantido. Ambos-visíveis = 0 (§5, correto).

## ROOT-CAUSE FIX: matte sofria o depth test da cena

Após o `mutual`, o caso **ambos-visíveis** ainda dava 0 — eu cheguei a atribuir ao §5 (errado). Medição
confiável (processo fresco) mostrou: corta com occluder OCULTO (4133/1139), **0 com ambos visíveis**.
Bisseção (desabilitar o depth test → 0→573) cravou a causa: a matte (`fill_ps`) passa pelo **teste
manual de profundidade** do `gpencil_frag.glsl`; com o occluder VISÍVEL, sua geometria no
`gp_scene_depth_tx` descarta a própria matte na sobreposição → mask vazio → sem corte.

**Fix:** push-constant `gp_in_mask_pass` (=1 no `fill_ps`); o frag pula o scene-depth-test quando matte.
Arquivos: `gpencil_frag.glsl`, `shaders/infos/gpencil_infos.hh`, `gpencil_engine_c.cc`. Validado
(fresh): ambos-visíveis 0→573; visual confirma a costura sumindo com 2 peças cor-pele **visíveis**.

## Lição extra (infra de medição)

O **MCP ao vivo NÃO sincroniza** edições de máscara (API crua) com o draw-engine — fica preso no estado
do arquivo (instrumentação `printf` provou: só processava as máscaras originais). **Validação confiável
= processo fresco** (`blender file --python script.py`), nunca edição+render via MCP.

## Pendências

- **Commit** (não feito) — código (operador + 3 arquivos do fix) + docs, na `feat/gp-masks`.
- Depth-skip aplicado só ao cross-object (`fill_ps`); **same-object** (`mask_bits`/`geom_ps`) com matte
  visível pode precisar de tratamento análogo (não testado).
- Validar em produção (pose/movimento real). Alvo da recíproca (layer de mesmo nome) pode ser revisto
  conforme convenção de nomes dos rigs.

## Arquivos tocados (documentação)

- `doc/guides/nuclear_auto_patch_validation_b_2026-06-18.md` — banner corrigido + **§10 ERRATA** (erro,
  correção, protocolo de medição, pendência).
- `docs/CHANGELOG.md` — nota de re-validação (substituiu o "Known Issues" equivocado).
- `docs/sessions/2026-06-19-auto-patch-cross-object-diagnostico.md` — este arquivo.

## Estado do ambiente

`JulianoHeroiAtualização.blend` aberto no Blender de dev pode estar modificado (testes) e **não salvo** —
**Revert** antes de reusar.
