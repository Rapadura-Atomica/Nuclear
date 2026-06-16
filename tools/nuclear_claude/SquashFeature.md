# SquashFeature.md — plano da feature "Squash" (Nuclear)

> Documento vivo. Plano de implementação do efeito **Squash & Stretch** do Nuclear.
> Mantenha atualizado conforme a feature evolui. Trabalho na branch `feature/squashs`
> (que hoje só carrega a stack de pegs/nuclear — **ainda não há código de squash**;
> partimos do zero em cima dela).
>
> Última atualização: 2026-06-12.

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

## 3. O modelo de dados (DNA)

Campos novos **anexados ao final** de `PegRigPeg` (em `DNA_pegrig_types.h`) — append puro,
sem reordenar nada (contrato do `.blend`):

```c
/* --- Squash (Nuclear) — só usado quando PEGRIGPEG_SQUASH está setado --- */
float squash_anchor[3];  /* gizmo de baixo, espaço do PAI do peg; também o pivô do squash */
float squash_tip[3];     /* gizmo de cima,  espaço do PAI do peg */
float squash_rest_len;   /* |tip-anchor| capturado no repouso; fator = len_atual / rest_len */
float squash_volume;     /* 0..1: quanto os eixos ortogonais compensam (preservação de área) */
```

Nova flag no `short flag` já existente (hoje só 2 bits usados):

```c
PEGRIGPEG_SQUASH = 1 << 2,
```

**Defaults** (`DNA_pegrig_defaults.h` + `dna_defaults.c`): `anchor=(0,0,0)`,
`tip=(0,1,0)`, `rest_len=1`, `volume=1`. Assim, ligar o squash com defaults dá um eixo
vertical unitário sensato; o operador de enable (§6) ajusta o eixo ao bounding box do GP.

**Versionamento (`blenloader`): nenhum `do_version` necessário.** Arquivos antigos leem os
campos como zero e a flag fica desligada → squash é pulado por completo. O único cuidado é
um guard em runtime: `rest_len <= 0` ⇒ trata como 1 (ou pula). Pegs criados depois pegam os
defaults.

---

## 4. A matemática do squash

Tudo no **espaço do pai do peg** (o mesmo espaço de `peg->translation`), para a âncora
ficar "plantada" independentemente da pose/rotação do próprio peg.

```
d  = normalize(tip - anchor)          // eixo do squash (base → topo)
L  = |tip - anchor|                   // comprimento atual
s  = L / rest_len                      // fator: s<1 esmaga, s>1 estica
k  = lerp(1, 1/s, squash_volume)       // compensação ortogonal (preserva área no plano)

S  = T(anchor) · R(d→Y) · diag(k, s, 1) · R(d→Y)⁻¹ · T(-anchor)
```

- `R(d→Y)` é a rotação que alinha o eixo do squash `d` ao eixo Y local (a matriz de
  escala `diag(k, s, 1)` esmaga ao longo de Y e compensa em X; Z=1 porque é cut-out 2D).
- `squash_volume = 0` → escala pura no eixo, sem compensação. `= 1` → preserva área no
  plano de desenho (esmagou Y por `s`, esticou X por `1/s`).

A matriz local do peg passa a ser:

```
local' = S · pegrig_peg_local_matrix(peg)     // S "por cima" da pose do peg, ancorada
world  = parent.world_mat · local'
```

> ⚠️ **Risco principal de implementação:** a **ordem de composição e o espaço** (pré- vs
> pós-multiplicar `S`, e em que espaço a âncora vive). O desenho acima (`S` em espaço do
> pai, `local' = S · local`) é o ponto de partida — **validar empiricamente** no passo de
> regressão (§7). É a mesma classe de problema que o `nuclear_curve_gizmo.py` já resolveu
> com `curve_ob.matrix_world`.

---

## 5. RNA (`rna_pegrig.cc`)

Expor em `PegRigPeg` (todos com `update`/`tag` que disparam recálculo + redraw):
- `use_squash` (bool, mapeia a flag `PEGRIGPEG_SQUASH`).
- `squash_anchor`, `squash_tip` (float[3]) — **animáveis** (auto-key do gizmo) e
  settáveis do Python (get/set do gizmo).
- `squash_volume` (float 0..1).
- `squash_rest_len` (float, read-only ou settável via operador de reset).
- **`matrix_world` (float[4][4], read-only)** — a `world_mat` resolvida do peg. **Novo,
  mas necessário:** dá ao gizmo um frame limpo para mapear mundo↔espaço-do-pai sem
  reimplementar a math da cadeia de pais em Python. (O pai = `matrix_world` do peg pai, ou
  identidade se for root.)

---

## 6. Operadores e UI

Em `object_pegrig.cc` (domínio de peg — não precisa de arquivo novo; se crescer, extrair
para `object_squash.cc`):

- **`OBJECT_OT_pegrig_squash_enable`** — liga `PEGRIGPEG_SQUASH` no peg ativo, posiciona
  `anchor`/`tip` ao longo do bounding box do(s) GP que seguem o peg (base no rodapé, topo
  no teto), e captura `rest_len`. Idempotente.
- **`OBJECT_OT_pegrig_squash_reset_rest`** — recaptura `rest_len = |tip-anchor|` atual,
  tornando a pose corrente o novo neutro (squash volta a 1).
- (opcional) **`OBJECT_OT_pegrig_squash_disable`** — limpa a flag.

Registro em `object_ops.cc` (ponto quente já existente do PegRig — só somar linhas, não é
ponto quente novo).

**UI:** botão "Enable Squash" + slider `squash_volume` num painel. Opções, mais simples
primeiro:
- (a) N-panel do **Peg Graph** (`nuclear_peg_graph.py`) quando um peg está ativo — Python
  puro, zero C. **Recomendado** para começar.
- (b) Painel do Follow Peg constraint (`properties_constraint.py` — a feature/squashs já
  mexe nesse arquivo).

---

## 7. Garantias de não-interferência (o pedido central do autor)

Enumerando por que isto **não atrapalha o workflow de pegs existente**:

1. **Peg sem a flag** → `pegrig_peg_local_matrix` faz early-out e retorna resultado
   idêntico ao de hoje. `world_mat` byte-idêntica. Rigs existentes intocados.
2. **Follow Peg constraint:** zero alterações. O squash viaja pela `world_mat`.
3. **Peg Pose / transform redirect:** inalterados. Editam `translation/rotation/scale`,
   ortogonais aos campos de squash. Dá pra continuar pegando/girando/escalando o peg de
   squash normalmente — o squash é uma camada extra.
4. **Peg Graph:** inalterado; o peg de squash aparece como peg normal. (Opcional: um badge
   visual depois.)
5. **Convivência de gizmos:** `NUCLEAR_GGT_squash` é um GizmoGroup novo com poll próprio
   (só aparece quando o GP ativo segue um peg com `use_squash`). Convive com o gizmo de
   curva e os do Peg Pose exatamente como eles já convivem entre si.
6. **Compat `.blend`:** campos anexados, gated por flag, com defaults, sem `do_version`.
7. **Superfície de rebase:** tudo em arquivos que o Nuclear já possui + um startup novo.
   **Zero pontos quentes novos.** Cresce a §1 do `NUCLEAR_DIVERGENCE.md` (arquivos novos),
   a §2 (pontos quentes) **não**.

**Regressão a rodar antes de fechar:** PegRig → bind GP → Peg Pose → Peg Graph → modifier
Curve **continua idêntico** com squash desligado; e com squash ligado, esmagar/esticar +
auto-key + reload do `.blend` preserva tudo. Testar também a combinação **squash peg + GP
com modifier Curve** (constraint é matriz no objeto, modifier é por ponto — devem compor).

---

## 8. Fases de implementação

| Fase | Entrega | Arquivos |
|---|---|---|
| **P0** | DNA: campos + flag + defaults. Build limpo, **zero mudança de comportamento**. | `DNA_pegrig_types.h`, `DNA_pegrig_defaults.h`, `dna_defaults.c` |
| **P1** | Math do squash em `pegrig_peg_local_matrix` (gated pela flag) + RNA (campos + `matrix_world` read-only). Testar setando campos pelo console Python e ver o corpo esmagar. | `pegrig.cc`, `rna_pegrig.cc` |
| **P2** | Operadores enable/reset + UI (N-panel do Peg Graph). | `object_pegrig.cc`, `object_ops.cc`, `nuclear_peg_graph.py` |
| **P3** | `nuclear_squash_gizmo.py`: dois gizmos (anchor + tip), mapeamento mundo↔espaço-do-pai, auto-key. **É o "feel" da feature.** | novo `scripts/startup/nuclear_squash_gizmo.py` |
| **P4** | Polish: slider `squash_volume`, linhas de overlay (estilo curve gizmo), badge no Peg Graph, passe de regressão, **atualizar `NUCLEAR_DIVERGENCE.md` (§1) e este doc**. | vários |

Cada fase é commitável e reversível de forma independente. P0–P1 provam a math antes de
investir no gizmo.

---

## 9. Riscos e questões em aberto

- **Ordem de composição / espaço da matriz** (§4) — o maior risco; resolver
  empiricamente em P1.
- **Placement visual do gizmo:** os pontos vivem em espaço-de-rig, mas o corpo também leva
  o `invmat` do constraint + o transform do objeto. O gizmo precisa pousar visualmente
  sobre o corpo — validar usando `peg.matrix_world` (novo no RNA) combinado com o
  `matrix_world` do GP seguidor, como o curve gizmo faz.
- **Stretch além do repouso** (`s > 1`): permitir livre (é stretch). Sem clamp por padrão.
- **Múltiplos GP no mesmo peg de squash:** todos esmagam juntos — é o comportamento
  desejado (corpo inteiro).
- **Pivô do peg vs âncora do squash:** são conceitos distintos (o `pivot` existente é o
  centro de rot/escala da pose; a `anchor` é o ponto plantado do squash). Documentar pra
  não confundir o usuário.
- **Peg de squash não-master:** funciona em qualquer peg, mas só faz sentido visual na peg
  master (ou num galho inteiro). A UI pode sugerir, não impedir.

---

## 10. Estado atual

- **Branch:** `feature/squashs` — sem código de squash ainda. Próximo passo: **P0**.
- Plano aprovado: mecanismo via matriz do peg, gizmos topo+base plantada, flag por peg.
