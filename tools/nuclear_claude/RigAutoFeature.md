# Auto Rig — montagem automática de rig a partir das peças

> Recurso do Nuclear que monta um PegRig completo a partir das peças (objetos Grease
> Pencil) já desenhadas. Implementado 100% em Python sobre a API de PegRig
> (`scripts/startup/nuclear_rig_auto.py` + layout no `scripts/startup/nuclear_peg_graph.py`),
> sem mudança em C. Núcleo validado headless contra `Carolina.blend`.

## Filosofia

O animador "só desenha e anima". O rig se divide numa fronteira **não-uniforme**:

- **Membros e espinha = previsíveis** → montados automaticamente por nome.
- **Rosto e cabelo = leque denso, mas reconhecível** → casados por nome contra a ontologia
  facial (`_FACE_SYNONYMS`) e auto-parentados na junta da **cabeça**, sem clique nenhum.
- **Guarda-roupa / acessórios (óculos, roupa, props) = ainda em lote** → ligados pelo
  animador (seleciona o monte, ativa o pai, um clique) — o pai varia por figurino, não só
  por anatomia, então fica de fora do reconhecimento automático por ora.
- **Junta / pivô = sempre geométrica** (centróide da sobreposição peça∩pai). O animador
  **nunca** posiciona uma junta na mão — vale também pro rosto.

**Padrão do estúdio — toda peça tem sua própria peg independente.** Cada peça do esqueleto
recebe **duas** pegs: uma **junta** (estrutural, na cadeia, com o pivô da articulação —
quadril/joelho/…) e uma **peg de desenho** (filha da junta, sufixo ` (ctrl)`) à qual o
desenho se liga — assim a peça mantém rotação/translação/escala **próprias**, separadas da
cadeia. As peças não reconhecidas (acessórios, folhas) ganham uma peg própria ligada ao
composite (já é a independente delas). O **Link** prende a peça na **junta** do alvo. Na
montagem manual o rigger tem liberdade total.

**Juntas estruturais (pelve / ombro) — sempre criadas, mesmo sem desenho.** A cadeia dos
membros não pendura direto no tronco: as pernas passam por uma **pelve** (`Quadril`) e os
braços por um **ombro/clavícula** (`Ombro.e`/`Ombro.d`). Essas juntas são **pegs sem
desenho** (articulação pura, estilo os 37 joints estruturais da `Carolina.blend`),
**sintetizadas automaticamente** quando um membro passa por elas — não exigem que o artista
desenhe uma peça "quadril"/"ombro". Cadeia resultante:
`pé → canela → coxa → Quadril → TRONCO` e `mão → antebraço → braço → Ombro.e/d → TRONCO`.
O pivô da junta estrutural = **média dos encaixes dos filhos** (o quadril fica no ponto médio
dos dois encaixes de coxa; cada coxa continua pivotando no seu próprio encaixe com o tronco).
Em repouso a matriz local de cada peg é identidade, então inserir a pelve **não move** nada.
Se o artista *desenhar* uma peça "quadril"/"ombro" (sinônimos abaixo), ela vira o desenho
dessa junta como qualquer outra peça (padrão de duas pegs). Configuração em `_STRUCT_JOINTS`.

**Rosto (Tier 2) — o leque da cabeça também é automático.** Peças reconhecidas pela
ontologia facial (`_FACE_SYNONYMS`: olho, sobrancelha, pupila, boca, nariz, orelha, cabelo,
franja, trança, bochecha, queixo, barba/bigode, dente, língua, pálpebra, cílio — PT + poucos
sinônimos EN/ES) **auto-parentam na junta da CABEÇA** — sem passar por "Soltos" nem precisar
de `Link Selected to Active`. Como é um leque (não uma cadeia), cada peça ganha **uma única
peg** (sem o sufixo `(ctrl)` — já é folha, já é independente), com pivô geométrico contra a
peça de cabeça mais próxima. Se o artista não desenhou "CABECA", a âncora recua pro ancestral
desenhado mais próximo (pescoço, depois tronco) usando o mesmo mecanismo de colapso das
juntas não-estruturais — se nada da espinha foi desenhado, a peça de rosto cai solta como
antes. Guarda-roupa/acessórios (óculos, roupa, props) **não** entram aqui — o pai varia por
figurino, então continuam em `Link Selected to Active`. Validado headless contra
`Carolina_strokes.blend`: 19 peças (`olho.*`, `sob.*`, `pupila.*`, `boca`, `NARIZ`,
`orelha.*`, `cabelo`) casaram e auto-parentaram em CABECA; guarda-roupa (`oculos`, `bandana`,
`manga.*`...) seguiu solto como antes.

## Fluxo (painel "Rig" na barra-N do viewport)

1. **Object Mode** → selecione as peças (ou nada = todas) → **Auto-Build Skeleton**.
   Monta tronco·pescoço·cabeça + braços/pernas espelhados num clique; o leque de rosto/cabelo
   auto-parenta na cabeça; cada peça restante (guarda-roupa/acessórios) ganha sua peg na raiz.
2. Selecione um leque de guarda-roupa (ex.: óculos, chapéu, roupa) e por último **clique na
   peça pai** (ex.: CABECA ou TRONCO, que vira a ativa) → **Link Selected to Active**.
3. Repita para outros acessórios.
4. Refine no **Peg Graph** (arraste links). Botão **Auto Layout** reagrupa o grafo.
5. **Peg Pose** para animar.

## Visualização — Peg Graph vertical anatômico

O grafo se organiza numa **silhueta corporal vertical** (a convenção dos riggers: lê-se de
**baixo pra cima = pé → cabeça** e de **cima pra baixo = cabeça → pé**):

- **Coluna central** (x≈0): `Cabeça` no topo, `Tronco` abaixo (a pelve/ombros ficam *dentro*
  do corpo central, não viram região própria).
- **Coluna esquerda (E, x<0):** `Braço E` na altura do tronco, `Perna E` abaixo.
- **Coluna direita (D, x>0):** `Braço D`, `Perna D`.
- **Soltos:** frame à direita com os acessórios ainda não ligados.

Cada região desce em cadeia (profundidade → pra baixo). Os frames ficam **bem espaçados**
(`_TIER_GAP` vertical, `_SIDE_GAP` horizontal). Roda automático ao montar/ligar e pelo botão
**Auto Layout**. As juntas estruturais (pelve/ombro) são reconhecidas pelo nome
(`Quadril`/`Ombro.*` → sinônimos) e tratadas como espinha, então os membros são achados
descendo *através* delas.

---

## 📛 Convenção de nomes (para o matcher reconhecer o esqueleto)

O matcher **normaliza** o nome (minúsculas, sem acento, remove `.001`/dígitos finais, separa
o sufixo de lado) e o **núcleo** resultante precisa ser **exatamente** um token conhecido.

### Tokens do esqueleto

| Parte | Canônico (recomendado) | Também aceitos |
| --- | --- | --- |
| Tronco (raiz) | `TRONCO` | torso, corpo, peito, body |
| Pescoço | `PESCOCO` | neck, cuello |
| Cabeça | `CABECA` | head, cabeza |
| Ombro/clavícula¹ | `ombro` | clavicula, shoulder, hombro |
| Braço | `braco` | brazo, arm, upperarm, umero |
| Antebraço | `antebraco` | antebrazo, forearm |
| Mão | `mao` | mano, hand |
| Quadril/pelve¹ | `quadril` | pelvis, hip, bacia, cadera |
| Coxa | `coxa` | thigh, muslo, femur |
| Canela | `canela` | shin, tibia, espinilla |
| Pé | `pe` | pie, foot |

¹ **Ombro e quadril são juntas estruturais**: são criados automaticamente mesmo sem peça
desenhada (ver acima). Desenhá-los é **opcional** — se existir a peça, ela vincula na junta.
Acento é ignorado (`CABEÇA` = `CABECA`, `pé` = `pe`).

### Tokens do rosto e cabelo (Tier 2 — auto-parentam em CABECA)

| Parte | Canônico | Também aceitos | Lado? |
| --- | --- | --- | --- |
| Sobrancelha | `sobrancelha` | sob, eyebrow, ceja | sim |
| Olho | `olho` | eye, ojo, globo | sim |
| Pupila/íris | `pupila` | pupil, iris | sim |
| Pálpebra | `palpebra` | eyelid, parpado | sim |
| Cílio | `cilio` | eyelash, cilios, pestana | sim |
| Nariz | `nariz` | nose | não |
| Boca | `boca` | mouth | não |
| Lábio | `labio` | lip, labios | não |
| Dente | `dente` | tooth, teeth, dentes | não |
| Língua | `lingua` | tongue, lengua | não |
| Orelha | `orelha` | ear, oreja | sim |
| Bochecha | `bochecha` | cheek, mejilla | sim |
| Queixo | `queixo` | chin, menton | não |
| Bigode | `bigode` | mustache, bigote | não |
| Barba | `barba` | beard | não |
| Cabelo | `cabelo` | hair, pelo, cabello | não |
| Franja | `franja` | bangs, fleco | não |
| Trança | `tranca` | braid, trenza | sim |

Mesma regra de núcleo exato + separador de lado do esqueleto. Sinônimos em `_FACE_SYNONYMS`
(`nuclear_rig_auto.py`). Guarda-roupa/acessórios (óculos, chapéu, roupa, props) **não** estão
nesta tabela de propósito — o pai varia por figurino, então continuam pelo
`Link Selected to Active`.

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
5. **Rosto casado = auto-parenta em CABECA, sem restrição de "um por encaixe".** Diferente
   do esqueleto, o rosto não é cadeia — `olho.d`, `olho.d.001`, `olho.d.002`… todos casam e
   viram pegs próprias sob a cabeça (não existe "só o primeiro vira osso" aqui).
6. **Resto = acessório.** Qualquer nome fora das duas tabelas (óculos, capa, roupa, props…)
   não some — ganha peg própria e fica em "Soltos", pronto pro Link em lote.

> Para estender o dicionário do esqueleto edite `_ROLE_SYNONYMS`; para o rosto,
> `_FACE_SYNONYMS` — ambos em `scripts/startup/nuclear_rig_auto.py`.

---

## Âncoras de código (manutenção)

`scripts/startup/nuclear_rig_auto.py`:
- `OBJECT_OT_nuclear_rig_auto_skeleton` (`object.nuclear_rig_auto_skeleton`) — matcher
  (`_match_role` + `_ROLE_SYNONYMS`/`_PARENT_ROLE`/`_SIDED`) → **nós de junta** resolvidos por
  `ensure_node` (uma junta por peça casada + **juntas estruturais** de `_STRUCT_JOINTS`,
  pelve/ombro, materializadas quando um membro passa por elas; papéis não-estruturais sem peça
  colapsam) → cadeia + **pegs `(ctrl)`** (`_DRAW_PEG_SUFFIX`) + **leque de rosto** (Tier 2) +
  acessórios. Pivô da peça por `_joint_world` contra o ancestral **desenhado** mais próximo
  (pula estruturais); pivô da junta estrutural = média dos encaixes dos filhos; fallback pro
  centro (`_center_world`).
- **Leque de rosto (Tier 2):** `_match_face_role` + `_FACE_SYNONYMS`/`_FACE_SIDED` — sem
  `_PARENT_ROLE` próprio, é sempre filho direto da âncora `face_anchor_key = ensure_node("head",
  None)` (reusa o colapso da cadeia: cabeça → pescoço → tronco → solto). Cada peça casada vira
  **uma peg só** (sem `(ctrl)`), pivô por `_joint_world` contra o objeto da âncora.
- `OBJECT_OT_nuclear_rig_link_to_parent` (`object.nuclear_rig_link_to_parent`) — lote
  parent-to-active; prende na **junta** do ativo (pai da peg `(ctrl)`).
- Pivô gravado no frame do peg-pai via `_set_pivot_world` (mesma matemática do Peg Graph).

`scripts/startup/nuclear_peg_graph.py`:
- `compute_grouped_layout(rig)` + `NODE_OT_nuclear_peg_auto_layout` (`node.nuclear_peg_auto_layout`,
  botão **Auto Layout**) — **layout vertical anatômico**: coluna central (`_ANAT_SLOT` C) para
  cabeça/tronco/espinha, colunas laterais E/D para os membros (achados descendo *através* das
  juntas estruturais via `_SPINE_ROLES` / `limb_roots_under`); rótulos via `_region_label`;
  espaçamento em `_COL` / `_ROW` / `_TIER_GAP` / `_SIDE_GAP`.

Tudo Python sobre a API de PegRig (`bpy.data.pegrigs.new`, `rig.pegs.new(name, parent_index=…)`
— `parent_index` **tem** que ser keyword arg —, `ob.constraints.new('FOLLOW_PEG')`). Sem C.
