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

## Personagem legado: **Convert Armature to Pegs**

Quem já foi rigado com **armature** (o acervo antigo do DPE) não passa pelo matcher de nomes:
a cadeia e os pivôs já existem e foram aprovados pelo animador, e os nomes das peças costumam
estar fora do contrato (`cabelo1.004` é um braço). O botão **Convert Armature to Pegs**
(aparece no painel quando há uma armature no arquivo) reconstrói o mesmo personagem como
PegRig sem tabela nenhuma por personagem:

- **o mapa peça → osso são os vertex groups da peça** — é a única declaração de intenção que
  sobreviveu, e vale mesmo quando os pesos nunca foram pintados (é o caso comum no acervo:
  os grupos existem só como nome);
- **cada osso mantido vira uma peg de junta**, com pivô no *head* do osso em coordenada de
  mundo, e o parentesco copiado da armature. Ossos por onde nada passa são podados;
- **cada peça ganha sua peg de desenho** (sufixo `(ctrl)`) sob a junta, então o animador
  mexe a peça sem sair da articulação;
- **ilhas de ossos desconexas** (cabeça desenhada numa cadeia separada do corpo) são
  religadas no osso mais próximo da ilha principal — sem isso a cabeça não seguiria o tronco;
- a armature é desligada (modifier removido, objeto escondido) e fica no arquivo como legado.

Duas ambiguidades aparecem quando a peça tem **mais de um** vertex group, distinguidas pelo
nome: se os candidatos são **ossos espelhados** (`1pe`/`2pe`, `perna.e`/`perna.d`) a peça foi
duplicada para os dois lados, e as peças concorrentes são casadas com as juntas pela ordem da
esquerda para a direita; senão, vale o candidato que o **nome da própria peça** aponta
(`1olho` entre olho e pupila) e, em último caso, o **ancestral comum** dos candidatos.

⚠️ O arquivo tem que salvar com a ferramenta **Peg Pose** ativa no modo Objeto: `Ctrl+B`
(subir na hierarquia) e `Ctrl+Shift+B` (descer) vivem no keymap dessa ferramenta, não num
keymap global. Rig perfeito + `builtin.select_box` salva = "a hierarquia não funciona".

Fora da GUI, o mesmo caminho em uma linha (`~/dpe_tools/arm2peg/arm2peg.py`, fora do repo):
`arm2peg.py <diretório do personagem>` acha o .blend principal, converte, cria o node tree do
Peg Graph, deixa a Peg Pose ativa e salva `<nome>_pegs.blend` ao lado — sem tocar no original.

## 🏷️ Como as pegs são nomeadas (e por que não pelo nome da peça)

Numa biblioteca legada o nome da peça **mente** com frequência — no acervo do DPE
`1antebraco.002` é uma saia e `cabelo1.004` é um braço. Um grafo nomeado por peça fica
ilegível, então:

- **peg de junta = o PAPEL, em PT**: `Tronco`, `Pescoço`, `Cabeça`, `Ombro.e`, `Braço.e`,
  `Antebraço.e`, `Mão.e`, `Quadril`, `Coxa.d`, `Canela.d`, `Pé.d` (`_ROLE_LABEL`);
- **peça de rosto = o papel também**: `Olho.e`, `Sobrancelha.d`, `Boca`, `Cabelo`
  (`_FACE_LABEL`);
- **peg de desenho = o nome da peça** + `(ctrl)`, para o artista achar o que ele desenhou;
- **acessório solto = o nome da peça**, intocado.

O lado **não** sai do nome: a convenção do estúdio é prefixo numérico (`1braco`/`2braco`) e
qual dígito é a esquerda da tela varia por personagem. `_norm` devolve lado `'?'` nesses casos
e `_resolve_sides` decide pela posição — entre os candidatos que sobrevivem, o mais à esquerda
fica com `.e`. A ordem relativa, não a posição absoluta: um personagem em passada tem os dois
pés do mesmo lado do eixo.

É também assim que uma peça com nome mentiroso é **rejeitada**: membros pares são laterais e
simétricos, então os candidatos mais afastados do eixo do corpo ganham os dois lados e o
intruso central (a saia chamada `1antebraco.002`) cai para os acessórios em vez de virar
antebraço.

Na conversão de armature vale a mesma tabela, com uma trava: o osso só é renomeado se o papel
fechar a conta exata (um por lado). Armature legada costuma ter um osso de deform ao lado do
osso de junta (`1braco` pendurado em `1braco.001`) e os dois lêem como braço — o desempate é
estrutural (**quem tem filho é a junta**), e quando nem isso resolve o osso mantém o nome que o
animador deu, que ao menos é único.

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
| Coxa | `coxa` | perna², thigh, muslo, femur |
| Canela | `canela` | shin, tibia, espinilla |
| Pé | `pe` | pie, foot |

¹ **Ombro e quadril são juntas estruturais**: são criados automaticamente mesmo sem peça
desenhada (ver acima). Desenhá-los é **opcional** — se existir a peça, ela vincula na junta.
² `perna` é como a biblioteca do DPE chama a **coxa** (a peça abaixo dela é sempre uma
`canela`), então vale como sinônimo de coxa, não como a perna inteira.
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

**Prefixo numérico (a convenção do acervo do DPE):** `1braco`/`2braco`, `1_sobrancelha`,
`1pe`/`1pe.001`. É aceito, mas o dígito **não** diz qual lado — vale para 1/2 seguido de letra,
e quem decide E/D é a posição da peça. Também vale para o rosto (`1olho` → `Olho.e`). Peças que
são cópia com nome duplicado (`1pe` e `1pe.001`) entram normalmente nesse jogo.

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
- **Papéis e lados:** `_assign_roles` (esqueleto) e o mesmo caminho no leque de rosto chamam
  `_resolve_sides`, que reparte os slots E/D de um papel e devolve os candidatos rejeitados;
  rótulos em `_ROLE_LABEL`/`_FACE_LABEL` + `_side_label`. Na armature, `_bone_labels`.
- `OBJECT_OT_nuclear_rig_from_armature` (`object.nuclear_rig_from_armature`) — conversão de
  personagem legado. Miolo em `build_pegrig_from_armature()`, chamável headless: bind por
  vertex group (`_resolve_bindings`, com `_mirror_core` para lados e
  `_lowest_common_ancestor`), poda + religação de ilhas em `_kept_bone_tree`. Idempotente —
  limpa PegRigs e Follow Pegs antes de montar.
- Pivô gravado no frame do peg-pai via `_set_pivot_world` (mesma matemática do Peg Graph).

`scripts/startup/nuclear_peg_graph.py`:
- `compute_grouped_layout(rig)` + `NODE_OT_nuclear_peg_auto_layout` (`node.nuclear_peg_auto_layout`,
  botão **Auto Layout**) — **layout vertical anatômico**: coluna central (`_ANAT_SLOT` C) para
  cabeça/tronco/espinha, colunas laterais E/D para os membros (achados descendo *através* das
  juntas estruturais via `_SPINE_ROLES` / `limb_roots_under`); rótulos via `_region_label`;
  espaçamento em `_COL` / `_ROW` / `_TIER_GAP` / `_SIDE_GAP`.

Tudo Python sobre a API de PegRig (`bpy.data.pegrigs.new`, `rig.pegs.new(name, parent_index=…)`
— `parent_index` **tem** que ser keyword arg —, `ob.constraints.new('FOLLOW_PEG')`). Sem C.
