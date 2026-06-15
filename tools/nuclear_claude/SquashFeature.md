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

- `R(d→Y)` alinha o eixo do squash `d` ao Y local; `diag(k, s, 1)` esmaga ao longo de Y e
  compensa em X (Z=1 porque é cut-out 2D).
- `squash_volume = 0` → escala pura no eixo. `= 1` → preserva área no plano de desenho.

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
| **P0** | DNA: campos + flag + defaults (em `peg_add`). Build limpo, **zero mudança de comportamento**. | `DNA_pegrig_types.h`, `pegrig.cc` (peg_add), `DNA_pegrig_defaults.h` (comentário) | **em andamento** |
| **P1** | Math do squash em `pegrig_peg_local_matrix` (gated pela flag) + RNA (campos + `matrix_world`). Testar via console Python. | `pegrig.cc`, `rna_pegrig.cc` | pendente |
| **P2** | Operadores enable/reset + UI (N-panel do Peg Graph). | `object_pegrig.cc`, `object_ops.cc`, `nuclear_peg_graph.py` | pendente |
| **P3** | `nuclear_squash_gizmo.py`: dois gizmos, mapeamento mundo↔espaço-do-pai, auto-key. | novo `scripts/startup/nuclear_squash_gizmo.py` | pendente |
| **P4** | Polish: slider `squash_volume`, overlay de linhas, badge no Peg Graph, regressão, **atualizar `NUCLEAR_DIVERGENCE.md` (§1) e este doc**. | vários | pendente |

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
- **P0 em andamento:** campos DNA + flag `PEGRIGPEG_SQUASH` + defaults em `BKE_pegrig_peg_add`
  aplicados. Falta **build limpo** (distrobox `nuclear-build`) confirmando zero regressão,
  e então commit do P0. Próximo: **P1** (math + RNA).
