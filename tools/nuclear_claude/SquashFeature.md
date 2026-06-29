# SquashFeature.md — plano da feature "Squash" (Nuclear)

> Documento vivo. Plano de implementação do efeito **Squash & Stretch** do Nuclear.
> Mantenha atualizado conforme a feature evolui. Trabalho na branch `feature/squashs`.
>
> Última atualização: 2026-06-15.

---

## 1. O que é o Squash

Dois gizmos no viewport, ligados a **um peg** que o corpo inteiro do personagem segue
(na prática, a **peg master** do rig). Arrastar os gizmos "esmaga" ou "estica" o corpo —
o efeito icônico de cartoon (squash & stretch), com os pés plantados no chão enquanto o
corpo comprime pra cima.

**Decisões de arquitetura (confirmadas com o autor):**
1. **Mecanismo:** o squash é uma **escala não-uniforme com preservação de volume,
   ancorada num ponto, dobrada na matriz local do peg.** Pega "de graça" o caminho do
   Follow Peg — o corpo já segue o peg via matriz 4×4, então esmagar o peg esmaga tudo
   abaixo dele. Squash **afim** do corpo todo (sem bulge/falloff por ponto — isso fica
   como evolução futura, ver §8).
2. **Gizmos:** **topo + base, base plantada.** O gizmo de baixo é a âncora/pivô (fica no
   chão); o de cima é o topo. A distância entre eles vs. o repouso dá o fator de
   squash/stretch, ao longo do eixo base→topo.
3. **Config:** **flag por peg** (`PEGRIGPEG_SQUASH`). Qualquer peg pode ligar squash; na
   prática liga-se na peg master que o corpo inteiro segue. Reusa toda a infra de pegs
   (animação via `adt`, Peg Graph, seleção, transform redirect).

**Por que isso casa com o fork:** a regra de ouro do projeto é *minimizar e isolar a
divergência em C, em arquivos novos*. Este desenho **não toca em nenhum arquivo novo do
upstream** e **não cria nenhum ponto quente novo**: tudo cai em arquivos que o Nuclear já
possui (`DNA_pegrig_*`, `pegrig.cc`, `rna_pegrig.cc`, `object_pegrig.cc`) mais **um arquivo
de startup novo** (`nuclear_squash_gizmo.py`). O Follow Peg constraint **não é alterado** —
o squash viaja pela `world_mat` que ele já consome.

> **Relação com a refatoração da UI** (trabalho paralelo em `refactor/UI`): independentes.
> O squash não edita `bl_ui/*` nem o template Nuclear. A UI do squash (§6) é um painelzinho
> no Peg Graph (Python próprio do fork). Os dois só se encontram na integração futura.

---

## 2. Como o corpo é deformado hoje (a base que vamos reusar)

- **`PegRig`** (`DNA_pegrig_types.h`) é um datablock ID com um array plano de `PegRigPeg`.
  Cada peg tem `translation/rotation/scale/pivot` + `parent_index`.
- **`pegrig.cc:pegrig_peg_local_matrix()`** monta a matriz local do peg (rot+escala em
  torno do `pivot`, depois translação). O solver encadeia:
  `peg->world_mat = parent.world_mat · local`.
- **Follow Peg constraint** (`bFollowPegConstraint`, `CONSTRAINT_TYPE_FOLLOWPEG = 32`,
  `constraint.cc:followpeg_evaluate`) liga um objeto GP a um peg pelo nome e faz:
  ```
  cob->matrix = peg_world · invmat · cob->matrix
  ```
  Ou seja, aplica a matriz 4×4 do peg (incluindo **escala não-uniforme**) ao objeto
  inteiro. **Já existe um caminho de deformação afim do corpo todo via peg** — é nele que
  o squash entra.
- **Gizmos** (`nuclear_curve_gizmo.py`) são `GizmoGroup` em Python, **poll-driven** e
  **tool-independent**: aparecem para o GP ativo, usam `GIZMO_GT_move_3d` com handlers
  `get`/`set`, fazem **auto-key** lendo `scene.tool_settings.use_keyframe_insert_auto`, e
  convivem com os gizmos do Peg Pose por terem polls separados. É o molde exato do gizmo
  de squash.

**Consequência-chave:** como o squash é só um fator a mais dobrado na **matriz local do
peg**, um peg com a flag desligada produz uma `world_mat` byte-idêntica à de hoje. Rigs
existentes, Peg Pose, Peg Graph e o transform redirect ficam **intocados**.

---

## 3. O modelo de dados (DNA) — implementado no P0

Campos novos **anexados ao final** de `PegRigPeg` (em `DNA_pegrig_types.h`) — append puro,
sem reordenar nada (contrato do `.blend`):

```c
float squash_anchor[3];  /* gizmo de baixo, espaço do PAI do peg; também o pivô do squash */
float squash_tip[3];     /* gizmo de cima,  espaço do PAI do peg */
float squash_rest_len;   /* |tip-anchor| capturado no repouso; fator = len_atual / rest_len */
float squash_volume;     /* 0..1: quanto os eixos ortogonais compensam (preservação de área) */
```

Nova flag no `short flag` já existente (hoje só 2 bits usados):

```c
PEGRIGPEG_SQUASH = 1 << 2,
```

**Defaults:** ficam em **`BKE_pegrig_peg_add`** (pegrig.cc), **não** em
`DNA_pegrig_defaults.h` — porque os pegs vivem num array alocado à parte, então o
`_DNA_DEFAULT_PegRig` só cobre a struct `PegRig` (pegs=NULL), e os defaults *por peg*
(scale=1 etc.) já eram aplicados ali. Squash herda esse padrão: `tip=(0,1,0)`,
`rest_len=1`, `volume=1` (eixo vertical unitário, não-degenerado); `anchor=(0,0,0)` vem do
zero-init. Tudo inerte enquanto a flag está desligada.

**Versionamento (`blenloader`): nenhum `do_version` necessário.** Arquivos antigos leem os
campos como zero (reflexão do SDNA preenche os campos novos no fim com zero) e a flag fica
desligada → squash é pulado por completo. Guard de runtime (no P1): `rest_len <= 0` ⇒
trata como identidade/pula.

---

## 4. A matemática do squash (P1)

Tudo no **espaço do pai do peg** (o mesmo espaço de `peg->translation`), para a âncora
ficar "plantada" independentemente da pose/rotação do próprio peg.

```
d  = normalize(tip - anchor)          // eixo do squash (base → topo)
L  = |tip - anchor|                   // comprimento atual
s  = L / rest_len                      // fator: s<1 esmaga, s>1 estica
k  = lerp(1, 1/s, squash_volume)       // compensação ortogonal (preserva área no plano)

S  = T(anchor) · R(d→Y) · diag(k, s, 1) · R(d→Y)⁻¹ · T(-anchor)
```

- **Axis-aligned vertical (ver nota 2026-06-26 na §10):** o squash escala ao longo do **Z**
  (vertical) por `s = (tip.z − anchor.z) / rest_len` e compensa em **X** por `k`; o **eixo Y
  (profundidade) fica preso em 1**. Só a altura vertical conta — o offset horizontal do tip é
  ignorado, então o corpo esmaga **reto** (sem cisalhar/diagonal). Math = `diag(k, 1, s)`
  ancorado.
- `squash_volume = 0` → escala vertical pura (k=1). `= 1` → preserva área no plano de desenho.

A matriz local do peg passa a ser:

```
local' = S · pegrig_peg_local_matrix(peg)     // S "por cima" da pose do peg, ancorada
world  = parent.world_mat · local'
```

> ⚠️ **Risco principal de implementação:** a **ordem de composição e o espaço** (pré- vs
> pós-multiplicar `S`, e em que espaço a âncora vive). O desenho acima (`S` em espaço do
> pai, `local' = S · local`) é o ponto de partida — **validar empiricamente** no passo de
> regressão (§7). Mesma classe de problema que o `nuclear_curve_gizmo.py` já resolveu com
> `curve_ob.matrix_world`.

---

## 5. RNA (`rna_pegrig.cc`) — P1

Expor em `PegRigPeg` (todos com `update`/`tag` que disparam recálculo + redraw):
- `use_squash` (bool, mapeia a flag `PEGRIGPEG_SQUASH`).
- `squash_anchor`, `squash_tip` (float[3]) — **animáveis** (auto-key do gizmo) e
  settáveis do Python (get/set do gizmo).
- `squash_volume` (float 0..1).
- `squash_rest_len` (float, read-only ou settável via operador de reset).
- **`matrix_world` (float[4][4], read-only)** — a `world_mat` resolvida do peg. **Novo,
  mas necessário:** dá ao gizmo um frame limpo para mapear mundo↔espaço-do-pai sem
  reimplementar a math da cadeia de pais em Python.

---

## 6. Operadores e UI — P2

Em `object_pegrig.cc` (domínio de peg — não precisa de arquivo novo; se crescer, extrair
para `object_squash.cc`):

- **`OBJECT_OT_pegrig_squash_enable`** — liga `PEGRIGPEG_SQUASH` no peg ativo, posiciona
  `anchor`/`tip` ao longo do bounding box do(s) GP que seguem o peg, e captura `rest_len`.
- **`OBJECT_OT_pegrig_squash_reset_rest`** — recaptura `rest_len = |tip-anchor|` atual.
- (opcional) **`OBJECT_OT_pegrig_squash_disable`**.

Registro em `object_ops.cc` (ponto quente já existente do PegRig — só somar linhas).

**UI:** botão "Enable Squash" + slider `squash_volume`. Começar pelo **N-panel do Peg
Graph** (`nuclear_peg_graph.py`) — Python puro, zero C.

---

## 7. Garantias de não-interferência (o pedido central do autor)

1. **Peg sem a flag** → `pegrig_peg_local_matrix` faz early-out; `world_mat` byte-idêntica.
2. **Follow Peg constraint:** zero alterações. O squash viaja pela `world_mat`.
3. **Peg Pose / transform redirect:** inalterados (editam translation/rotation/scale).
4. **Peg Graph:** inalterado; peg de squash aparece como peg normal.
5. **Convivência de gizmos:** `NUCLEAR_GGT_squash` é GizmoGroup novo com poll próprio.
6. **Compat `.blend`:** campos anexados, gated por flag, defaults sãos, sem `do_version`.
7. **Superfície de rebase:** arquivos que o Nuclear já possui + um startup novo. **Zero
   pontos quentes novos.** Cresce a §1 do `NUCLEAR_DIVERGENCE.md`, a §2 **não**.

**Regressão a rodar antes de fechar:** PegRig → bind GP → Peg Pose → Peg Graph → modifier
Curve **idêntico** com squash desligado; com squash ligado, esmagar/esticar + auto-key +
reload do `.blend` preserva tudo. Testar também **squash peg + GP com modifier Curve**.

---

## 8. Fases de implementação

| Fase | Entrega | Arquivos | Status |
|---|---|---|---|
| **P0** | DNA: campos + flag + defaults (em `peg_add`). Build limpo, **zero mudança de comportamento**. | `DNA_pegrig_types.h`, `pegrig.cc` (peg_add), `DNA_pegrig_defaults.h` (comentário) | **concluído** (build limpo no distrobox `blender`) |
| **P1** | Math do squash em `pegrig_peg_local_matrix` (gated pela flag) + RNA (`use_squash`, `squash_anchor/tip/volume/rest_len`, `matrix_world` read-only). Testar via console Python. | `pegrig.cc`, `rna_pegrig.cc` | **concluído** (build limpo 2026-06-15) |
| **P2** | Operadores `pegrig_squash_enable` (fit anchor/tip ao bbox dos seguidores + captura rest_len) e `pegrig_squash_reset_rest` + UI (box "Squash & Stretch" no painel **Active Peg**, N-panel do viewport). | `object_pegrig.cc`, `object_intern.hh`, `object_ops.cc`, `nuclear_peg_graph.py` | **concluído** (build 2026-06-15) |
| **P3** | `nuclear_squash_gizmo.py`: GizmoGroup poll-driven `NUCLEAR_GGT_squash` com 2 gizmos (anchor/tip, `GIZMO_GT_move_3d`), mapeamento mundo↔espaço-do-pai, auto-key, overlay da linha do eixo. | novo `scripts/startup/nuclear_squash_gizmo.py` | **concluído** (build 2026-06-15) |
| **P4** | Polish: badge "Squash" no nó do Peg Graph, regressão headless automatizada (math + não-interferência), `NUCLEAR_DIVERGENCE.md` §1 atualizado. | `nuclear_peg_graph.py`, `NUCLEAR_DIVERGENCE.md`, este doc | **concluído** (regressão OK 2026-06-15) |

P0–P1 provam a math antes de investir no gizmo. Cada fase é commitável e reversível.

---

## 9. Riscos e questões em aberto

- **Ordem de composição / espaço da matriz** (§4) — maior risco; resolver em P1.
- **Placement visual do gizmo:** validar via `peg.matrix_world` (novo no RNA) + o
  `matrix_world` do GP seguidor, como o curve gizmo faz.
- **Stretch além do repouso** (`s > 1`): permitir livre. Sem clamp por padrão.
- **Múltiplos GP no mesmo peg:** todos esmagam juntos — é o desejado.
- **Pivô do peg vs âncora do squash:** conceitos distintos; documentar pra não confundir.

---

## 10. Estado atual

- **Branch:** `feature/squashs` (local, criada de `origin/feature/squashs`).
- **Build:** compilado no distrobox `blender` (`cd Nuclear/build && ninja && ninja install`).
- **P0 concluído:** campos DNA + flag `PEGRIGPEG_SQUASH` + defaults em `BKE_pegrig_peg_add`.
- **P1 concluído (2026-06-15):** math do squash dobrada em `pegrig_peg_local_matrix` (gated
  pela flag, `S * local` em espaço do pai, `I + (s-1)d⊗d + (k-1)e⊗e`, Z=1 no plano 2D) +
  RNA em `PegRigPeg`: `use_squash`, `squash_anchor`, `squash_tip` (animáveis), `squash_volume`,
  `squash_rest_len`, e `matrix_world` (read-only). Pronto para validação visual via console.
- **P2 concluído (2026-06-15):** operadores `OBJECT_OT_pegrig_squash_enable` (liga a flag no
  peg ativo, ajusta anchor/tip ao bbox mundial dos GP seguidores mapeado pro espaço do pai, e
  captura `rest_len`) e `OBJECT_OT_pegrig_squash_reset_rest`. UI: box "Squash & Stretch" no
  painel **Active Peg** (N-panel "Peg" do viewport) — botão "Enable Squash" quando off; quando
  on, checkbox + slider `squash_volume` + anchor/tip + rest_len com reset.
- **P3 concluído (2026-06-15):** `scripts/startup/nuclear_squash_gizmo.py` — GizmoGroup
  `NUCLEAR_GGT_squash` (poll: peg controlado com `use_squash`, Object mode), dois rings
  `GIZMO_GT_move_3d` (anchor verde plantado, tip laranja), get/set mapeando mundo↔espaço-do-pai
  via `_peg_world_matrix` replicado, auto-key (`use_keyframe_insert_auto`) e overlay da linha do
  eixo. Self-contained (sem import de `nuclear_peg_graph`).
- **P4 concluído (2026-06-15):** badge "Squash" no nó do peg no Peg Graph
  (`NuclearPegNode.draw_buttons`); `NUCLEAR_DIVERGENCE.md` §1 atualizado (gizmo novo + nota
  de que o squash não cria ponto quente novo na §2); regressão headless automatizada
  (`blender --background --factory-startup`) passando: registro/RNA/gizmo OK, e a math pelo
  caminho Follow Peg dá `diag (0.5, 2.0, 1.0)` para s=2/volume=1, com squash off = identidade.
- **Feature completa (P0–P4).** Evoluções futuras possíveis: bulge/falloff por ponto (§8 do
  plano original), gizmos com overlay mais rico, presets de volume.
- **Correção do plano XZ + AXIS-ALIGNED travado (2026-06-26):** a P1 tinha (a) codificado o
  plano como **XY** (vertical=Y, profundidade=Z) e (b) deformado ao longo do eixo **livre**
  âncora→tip. Os rigs vivem no plano **XZ** (Y=profundidade), então o squash esmagava na
  profundidade (invisível de frente). Iterações no dia: primeiro pro plano XZ com eixo livre
  (`e=(-d.z,0,d.x)`), mas a diagonal cisalhava; depois axis-aligned vertical; o autor chegou a
  pedir a diagonal de volta, mas ela apresentava **inversão aparente do lado** no arrasto do
  gizmo (a deformação seguia certo por valor direto — render tip-direita→inclina-direita —, mas
  a interação ao vivo confundia). **Decisão final: travar no axis-aligned vertical, sem
  diagonal.** Math = `s = (tip.z − anchor.z)/rest_len`, `diag(k, 1, s)` ancorado, **Y preso em
  1**; enable ajusta ao longo de Z (centro X/Y); default `tip = (0,0,1)`; o gizmo trava o tip no
  eixo vertical da âncora (âncora/tip em y=0) e desenha a linha vertical. Arquivos: `pegrig.cc`
  (math + default), `object_pegrig.cc` (enable), `nuclear_squash_gizmo.py` (lock + overlay).
  Sem mudança de DNA/RNA.
  **Binding (rig, não squash):** o `carolina_pegs_atualizada.blend` tinha 19 GP soltos
  (olhos/boca/antebraço, sem Follow Peg) que não herdavam o squash; auto-bindados por
  proximidade ao irmão bindado mais próximo na cópia `_corrigida`. Rest_len das duas pegs de
  squash recapturado como `tip.z − anchor.z` (s=1 em repouso).
- **Squash segue o rig (2026-06-26):** antes o squash era `S · local` com âncora/tip no espaço
  do **pai** → ao mover/posar o próprio peg, o squash ficava pra trás (não acompanhava). Mudado
  para `local · S` com âncora/tip no espaço **local do próprio peg**: agora o squash viaja com o
  peg (mover/rotacionar/escalar o rig carrega o squash junto), e durante o squash em si a base
  segue plantada. Arquivos: `pegrig.cc` (`mat = mat * squash`), `nuclear_squash_gizmo.py`
  (gizmo mapeia pelo world do próprio peg via `_peg_world_matrix(rig, idx)`), `object_pegrig.cc`
  (enable ajusta no espaço local). Migração de `.blend` existentes: remapear âncora/tip keyados
  de parent→local (`local⁻¹ · v`); feito na cópia `_corrigida` da Carolina.
