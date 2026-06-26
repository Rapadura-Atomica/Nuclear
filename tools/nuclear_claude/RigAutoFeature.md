# Auto Rig — montagem automática de rig a partir das peças

> Recurso do Nuclear que monta um PegRig completo a partir das peças (objetos Grease
> Pencil) já desenhadas. Implementado 100% em Python sobre a API de PegRig
> (`scripts/startup/nuclear_rig_auto.py` + layout no `scripts/startup/nuclear_peg_graph.py`),
> sem mudança em C. Núcleo validado headless contra `Carolina.blend`.

## Filosofia

O animador "só desenha e anima". O rig se divide numa fronteira **não-uniforme**:

- **Membros e espinha = previsíveis** → montados automaticamente por nome.
- **Face / cabeça / acessórios = leque denso** → ligados em lote pelo animador (seleciona o
  monte, ativa o pai, um clique).
- **Junta / pivô = sempre geométrica** (centróide da sobreposição peça∩pai). O animador
  **nunca** posiciona uma junta na mão.

**Padrão do estúdio — toda peça tem sua própria peg independente.** Cada peça do esqueleto
recebe **duas** pegs: uma **junta** (estrutural, na cadeia, com o pivô da articulação —
quadril/joelho/…) e uma **peg de desenho** (filha da junta, sufixo ` (ctrl)`) à qual o
desenho se liga — assim a peça mantém rotação/translação/escala **próprias**, separadas da
cadeia. As peças não reconhecidas (acessórios, folhas) ganham uma peg própria ligada ao
composite (já é a independente delas). O **Link** prende a peça na **junta** do alvo. Na
montagem manual o rigger tem liberdade total.

## Fluxo (painel "Rig" na barra-N do viewport)

1. **Object Mode** → selecione as peças (ou nada = todas) → **Auto-Build Skeleton**.
   Monta tronco·pescoço·cabeça + braços/pernas espelhados num clique; cada peça restante
   ganha sua peg na raiz.
2. Selecione um leque (ex.: olhos, sobrancelhas, boca, cabelo) e por último **clique na peça
   pai** (ex.: CABECA, que vira a ativa) → **Link Selected to Active**.
3. Repita para acessórios do tronco com **TRONCO** ativo.
4. Refine no **Peg Graph** (arraste links). Botão **Auto Layout** reagrupa o grafo.
5. **Peg Pose** para animar.

## Visualização — Peg Graph agrupado

O grafo se organiza em **frames rotulados por região, na horizontal**: `Tronco · Braço E ·
Braço D · Cabeça · Perna E · Perna D · Soltos`. Cada membro é a sua sub-árvore; os
acessórios-peg ficam em "Soltos" até serem ligados. Roda automático ao montar/ligar e pelo
botão **Auto Layout**.

---

## 📛 Convenção de nomes (para o matcher reconhecer o esqueleto)

O matcher **normaliza** o nome (minúsculas, sem acento, remove `.001`/dígitos finais, separa
o sufixo de lado) e o **núcleo** resultante precisa ser **exatamente** um token conhecido.

### Tokens do esqueleto

| Parte | Canônico (recomendado) | Também aceitos |
| --- | --- | --- |
| Tronco (raiz) | `TRONCO` | torso, corpo, peito, quadril, pelvis, hip, body |
| Pescoço | `PESCOCO` | neck, cuello |
| Cabeça | `CABECA` | head, cabeza |
| Braço | `braco` | brazo, arm, upperarm, umero |
| Antebraço | `antebraco` | antebrazo, forearm |
| Mão | `mao` | mano, hand |
| Coxa | `coxa` | thigh, muslo, femur |
| Canela | `canela` | shin, tibia, espinilla |
| Pé | `pe` | pie, foot |

Acento é ignorado (`CABEÇA` = `CABECA`, `pé` = `pe`).

### Sufixo de lado (membros)

Precisa de um **separador** (`.`, `_`, `-` ou espaço) + a marca:

| Lado | Marcas |
| --- | --- |
| **Esquerda (E)** | `.e` · `.esq` · `.esquerda` · `.l` · `.left` · `.izq` |
| **Direita (D)** | `.d` · `.dir` · `.direita` · `.r` · `.right` · `.der` |

✅ `braco.e`, `coxa_d`, `mao-e`, `Pe.D`  ❌ `bracoe` (sem separador, não separa o lado)

### Conjunto canônico de um bípede (os 15 que viram esqueleto)

```
TRONCO
PESCOCO   CABECA
braco.e     braco.d
antebraco.e antebraco.d
mao.e       mao.d
coxa.e      coxa.d
canela.e    canela.d
pe.e        pe.d
```

### Regras de ouro

1. **Núcleo exato, não pedaço.** Token puro + só o sufixo de lado. `coxa.e` ✓;
   `coxa_grande` ✗; `coxaesquerda` ✗. *(De propósito: `perna_do_oculos` NÃO vira perna,
   `cabelo` NÃO vira cabeça.)*
2. **Membro tem lado; linha de centro não.** Tronco/pescoço/cabeça **sem** sufixo; membros
   **sempre** com `.e`/`.d`.
3. **Um objeto por encaixe.** Se dois objetos normalizam pro mesmo papel+lado, só o
   **primeiro** vira osso; o resto ganha peg própria (ligue na mão). Peça multi-camada deve
   ser **um** objeto GP (com as layers dentro).
4. **Números são ignorados.** `coxa.e.001`, `pe1` funcionam.
5. **Resto = acessório.** Qualquer nome fora da tabela (cabelo, óculos, capa, olho, boca,
   sobrancelha, orelha, nariz…) não some — ganha peg própria e fica em "Soltos", pronto pro
   Link em lote.

> Para estender o dicionário (casar com os nomes reais do estúdio), edite `_ROLE_SYNONYMS`
> em `scripts/startup/nuclear_rig_auto.py`.

---

## Âncoras de código (manutenção)

`scripts/startup/nuclear_rig_auto.py`:
- `OBJECT_OT_nuclear_rig_auto_skeleton` (`object.nuclear_rig_auto_skeleton`) — matcher
  (`_match_role` + `_ROLE_SYNONYMS`/`_PARENT_ROLE`/`_SIDED`) → cadeia de **juntas** +
  **pegs `(ctrl)`** (`_DRAW_PEG_SUFFIX`) + acessórios; pivô por `_joint_world` (sobreposição
  AABB no plano do personagem) com fallback pro centro (`_center_world`).
- `OBJECT_OT_nuclear_rig_link_to_parent` (`object.nuclear_rig_link_to_parent`) — lote
  parent-to-active; prende na **junta** do ativo (pai da peg `(ctrl)`).
- Pivô gravado no frame do peg-pai via `_set_pivot_world` (mesma matemática do Peg Graph).

`scripts/startup/nuclear_peg_graph.py`:
- `compute_grouped_layout(rig)` + `NODE_OT_nuclear_peg_auto_layout` (`node.nuclear_peg_auto_layout`,
  botão **Auto Layout**) — agrupa em frames por região (sub-árvore de cada "limb root");
  rótulos via `_region_label`; espaçamento em `_REGION_COL` / `_REGION_ROW` / `_REGION_GAP`.

Tudo Python sobre a API de PegRig (`bpy.data.pegrigs.new`, `rig.pegs.new(name, parent_index=…)`
— `parent_index` **tem** que ser keyword arg —, `ob.constraints.new('FOLLOW_PEG')`). Sem C.
