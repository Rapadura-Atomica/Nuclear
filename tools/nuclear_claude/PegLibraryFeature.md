# PegLibraryFeature.md — reaproveitar animação de peg entre personagens

> Documento vivo. Plano + decisões de design do **reaproveitamento de animação** entre
> personagens rigados com peg, e do caminho até uma **biblioteca de ações**.
> Implementado 100% em Python sobre a API de PegRig
> (`scripts/startup/nuclear_peg_library.py`), sem mudança em C.
> Núcleo validado headless contra dois rigs sintéticos.
>
> Última atualização: 2026-08-11.

---

## 1. O problema

Um personagem tem uma caminhada pronta. O próximo personagem da série precisa da mesma
caminhada. Hoje isso é reanimar do zero.

Em rig de **armature** isso é o problema clássico de retarget, e é difícil: o `matrix_basis`
de um osso é relativo ao **rest pose** dele, então a mesma rotação local em dois esqueletos
com orientações de repouso diferentes produz poses diferentes. Todo o aparato de retarget
existe para conjugar essa diferença — e ainda assim erra quando a hierarquia diverge.

Em rig de **peg**, esse problema **não existe**. É a observação que sustenta a feature
inteira.

## 2. Por que uma ação de peg é portátil por construção

A matriz local de um peg é `T(t+p) · R · S · T(-p)` (`pegrig.cc`,
`pegrig_peg_local_matrix`). Em repouso — `t=0`, `R=I`, `S=1` — isso colapsa:

```
T(p) · I · I · T(-p)  =  T(p) · T(-p)  =  I
```

**Qualquer que seja o pivô.** Ou seja: o rest pose de todo peg de todo rig é a identidade.
Não existe `B_src` nem `B_tgt` para conjugar. Copiar uma curva de rotação de um personagem
para outro é **exato**, não aproximado.

Isso decorre de uma separação que armature não tem: no PegRig a geometria do personagem vive
nos objetos Grease Pencil, e o rig é delta puro. Na armature o rest pose carrega geometria, e
é isso que contamina a transferência.

**O pivô diferente é a feature, não o erro.** O pivô é geométrico (centróide da sobreposição
peça∩pai, ver `RigAutoFeature.md`), calculado por personagem. Cada um gira o braço no
**próprio** cotovelo. Copiar a rotação e manter o pivô do destino é exatamente o resultado
desejado — o movimento se adapta ao corpo sozinho.

## 3. O nome do peg já é um contrato

O Auto Rig nomeia a junta pelo **papel**, não pela peça (`_ROLE_LABEL` em
`nuclear_rig_auto.py`): `Tronco`, `Pescoço`, `Cabeça`, `Ombro.e`, `Braço.d`, `Antebraço.e`,
`Mão.d`, `Quadril`, `Coxa.e`, `Canela.d`, `Pé.e`. O rosto idem (`_FACE_LABEL`). O
`Convert Armature to Pegs` usa a mesma tabela.

Consequência: dois personagens que passaram pelo Auto-Build Skeleton têm nomes de peg
**idênticos por construção**, não por sorte. O casamento por nome deixa de ser heurística e
vira contrato — o oposto do acervo de armature, onde `cabelo1.004` é um braço.

O casamento aqui é, em ordem: nome exato → dobra de acento/caixa (`BRACO.E` encontra
`Braço.e`, para rigs montados à mão) → opcionalmente o sufixo `.001`. Nome exato nunca é
deslocado por um fallback, e cada peg de destino é reivindicado **no máximo uma vez** — um
fallback ambíguo é descartado, nunca sobrescreve um canal que já casou.

## 4. Política de transferência

O critério é: **a propriedade descreve a atuação ou a anatomia do destino?**

| Classe | Propriedades | O que acontece |
|---|---|---|
| **EXACT** | `rotation`, `scale`, `opacity`, `use_squash`, `squash_volume` | Copiadas cruas. São adimensionais — o mesmo número significa a mesma coisa em qualquer corpo. É onde vive o grosso de uma atuação cutout. |
| **PROPORTIONAL** | `translation` | Está em unidades de mundo. Só é fiel se os dois personagens têm o mesmo tamanho. Ver §5. |
| **RIG_OWNED** | `pivot`, `squash_anchor`, `squash_rest_len` | **Nunca cruzam.** Dizem onde as juntas do destino *estão*, não o que fazem. Copiar reconstruiria a anatomia do destino a partir do corpo da origem. |
| **REMAPPED** | `squash_tip` | Só tem sentido relativo a um valor RIG_OWNED. Transferido como *intenção*. Ver §6. |

### Translação: juntas sim, pegs de desenho não

O padrão do estúdio dá a cada peça **duas** pegs: a **junta** (na cadeia, com o pivô da
articulação) e a **peg de desenho** ` (ctrl)` filha, à qual o desenho se liga. A divisão de
trabalho entre elas resolve a translação sozinha:

- a **junta** carrega a atuação — deslocar o quadril, mover o personagem pela cena;
- o ` (ctrl)` carrega o **encaixe da arte daquela peça específica** — o ajuste que o rigger
  fez para o braço *daquele desenho* fechar no ombro *daquele desenho*.

Copiar a translação de um ` (ctrl)` é pegar o encaixe de um corpo e aplicar em outro:
desencaixa a arte. Então o default (`translation_mode = 'JOINTS'`) copia a translação das
juntas e **segura** a das pegs de desenho. `'ALL'` e `'NONE'` ficam disponíveis para quem
sabe o que está fazendo.

## 5. Proporção: medida, mostrada, nunca aplicada sozinha

Peg não tem `length`. Mas — de novo porque em repouso a cadeia toda é identidade — o `pivot`
de um peg **lê diretamente em coordenadas do rig**. Então a distância entre o pivô de um peg
e o do seu pai *é* o segmento do membro, o análogo exato de `bone.length`.

O fator é a **mediana** das razões destino/origem sobre os pegs casados. Mediana, não média:
um peg raiz ou de prop com pivô arbitrário arrasta uma média para qualquer lugar, e um
segmento ruim não pode reescalar uma atuação inteira.

O default é **não aplicar** (`scale_mode = 'NONE'`). O `Check` calcula e **mostra** a razão
medida ("limbs 2.00x") e o animador decide. Escalar sem pedir é justamente o tipo de coisa
que quebra uma cena sem deixar rastro.

## 6. Squash: transferido como intenção, não como valor

O fator de squash é `s = (tip.z − anchor.z) / rest_len` (`SquashFeature.md`), e tanto
`anchor` quanto `rest_len` pertencem ao rig. Copiar `squash_tip` cru entrega os números de um
personagem alto para um baixo.

O que se transfere é o `s`. Reproduzi-lo no destino dá
`tip.z' = anchor'.z + s · rest'`, que é um mapa **afim** no valor:

```
fator = rest_tgt / rest_src
deslocamento = anchor_tgt.z − fator · anchor_src.z
```

Aplicado a `co.y` e aos dois handles de cada keyframe. Afim só no eixo de valor, então
timing, modo de interpolação e *forma* do handle sobrevivem intactos — a curva mantém o
easing do animador, só muda de amplitude.

Só o componente vertical (índice 2) dirige o squash; os outros são encaixe de arte e ficam
de fora. Se o peg de destino não tem squash configurado (`use_squash` desligado ou
`rest_len` zero), o canal é **pulado e reportado** em vez de escrito como ruído.

## 7. "Do no harm" — as garantias

O princípio operante: *um canal descartado custa ao animador uma correção que ele vê; um
canal transferido errado em silêncio custa uma caçada.* Então:

- **nunca** cria peg no destino — peg que só existe na origem é reportado como ausente;
- **nunca** reparenteia nada;
- **nunca** escreve `pivot`, `squash_anchor` ou `squash_rest_len`;
- **nunca** apaga a ação anterior do destino — ela recebe `use_fake_user` antes da troca, e
  a nova ação nasce em `bpy.data.actions.new()` (que auto-numera), então nada é sobrescrito;
- a ação de origem **não é tocada** (`new_from_fcurve` copia, o original fica intacto);
- todo canal pulado sai no console com o motivo;
- **hierarquia divergente é detectada e reportada, nunca bloqueia.** Se um peg casado pendura
  num pai diferente no destino, a cadeia acumula diferente e a pose vai divergir — mas quem
  sabe se aquele membro importa neste plano é o animador, não a ferramenta.

`Check` e `Reuse` rodam **o mesmo `plan_transfer()`**. O que é mostrado na conferência é
exatamente o que vai acontecer — não há um segundo caminho que possa divergir.

## 8. Fluxo (painel "Reuse Animation" na aba Rig da barra-N)

1. **From** — o personagem com a animação pronta, e qual ação (vazio = a que ele está
   tocando).
2. **To** — o personagem que recebe.
3. **Check** — relata quantos canais cruzam, quantos são pulados e por quê, quais pegs não
   existem no destino, quais penduram em outro lugar, e a proporção medida. Não altera nada.
4. **Reuse Animation** — cria a ação nova no destino e a atribui.

## 9. Implementação

`scripts/startup/nuclear_peg_library.py`. A primitiva central é
`channelbag.fcurves.new_from_fcurve(source, data_path=...)`: copia a f-curve inteira —
keyframes, handles, interpolação, modifiers — trocando só o data_path. Como a transferência é
cópia de curva e não bake, **keyframes esparsos continuam esparsos** e o animador recebe
curvas editáveis, não um key por frame.

Não há `frame_set`, não há `view_layer.update()`, não há laço por frame. A operação é
proporcional ao número de canais, não à duração da cena.

```
plan_transfer()   decide, canal a canal, o que cruza e com que fator/deslocamento afim
apply_transfer()  escreve o plano numa ação nova e atribui ao rig de destino
```

Actions com slot (Blender 5.0): a ação nova recebe
`slots.new('PEGRIG', nome)` + `layers.new()` + `strips.new(type='KEYFRAME')` +
`strip.channelbag(slot, ensure=True)`.

> ⚠️ **Armadilha da API:** `rig.pegs.new()` realoca o array de pegs, então **toda referência
> Python a um peg obtida antes do último `new()` fica pendurada** e escritas nela se perdem
> em silêncio. Ao montar um rig, crie todos os pegs primeiro e só depois busque por nome para
> escrever propriedades. (Custou um teste falso-negativo em `squash_*`.)

## 10. Validação

`build/bin/nuclear -b --factory-startup --python <teste>` monta dois rigs sintéticos
(`Tronco → Braço.e → Braço.e (ctrl)`), com o segundo tendo membros e span de squash **2x**,
anima o primeiro com um canal de cada classe, e confere 30 asserções: casamento de nomes com
acento, pivô nunca escrito, translação de ` (ctrl)` segurada, peg ausente reportado e não
criado, proporção medida = 2.0, remapeamento de squash (2.0→1.0 na origem vira 4.0→2.0 no
destino), ação anterior preservada com fake user, ação de origem intacta, divergência de
hierarquia detectada. Todas passam.

Falta a validação contra dois personagens reais do acervo — é o próximo passo, e é o que vai
dizer o quanto do overlap de nomes o contrato realmente entrega na prática.

## 11. O que isto ainda não é

O modelo implementado é **origem → destino**. Mas se os nomes de peg são canônicos, uma ação
de peg **não pertence a personagem nenhum** — ela só está guardada no `adt` de um `PegRig`
específico por acidente de onde foi criada.

O passo seguinte natural é a **biblioteca de ações**: "aplicar *caminhada_ciclo* neste
personagem", sem falar em origem. Isso casa com o que a `CellLibraryFeature.md` faz para
desenhos, um andar acima — cells são a biblioteca de desenho, ações de peg seriam a
biblioteca de atuação. A camada de decisão (`plan_transfer`) já está escrita para isso: ela
só precisa de um rig de origem para resolver `rest_len` e proporção, e ambos são opcionais.

Outros limites conhecidos:

- **guarda-roupa e acessórios não têm nome canônico.** O `Link Selected to Active` é manual e
  o pai varia por figurino, então essa fatia continua exigindo casamento na mão.
- **peg ausente no destino perde o movimento dele.** Achatar a contribuição do peg ausente
  no filho (compondo as matrizes) é possível e é o único lugar do sistema onde um bake faria
  sentido — não implementado.
- **`squash_anchor` animado** (mover o ponto plantado como atuação) é pulado; é tratado como
  propriedade de rig.
