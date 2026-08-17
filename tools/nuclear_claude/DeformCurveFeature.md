# Deform Curve — assentar, bindar e ligar a curva ao rig

> Painel **Rig ▸ Deform Curve** (`scripts/startup/nuclear_deform_curve.py`), 100% Python
> sobre a API de PegRig e os operadores C de bind do modifier `Curve`. Automatiza o fluxo
> que até aqui era feito à mão (ou por scripts soltos em `~/dpe_tools/arm2peg/`) toda vez
> que um membro precisava dobrar. Validado headless no rig de produção
> `dinossauro_gigante_pegs.blend` (DPE Ep06).

## O problema

Um membro bendy no rig de cutout são **três coisas que precisam concordar**:

1. uma **curva** deitada sobre o desenho, cobrindo-o ponta a ponta;
2. o **bind** do desenho nessa curva — o modifier `Curve` é *no-op silencioso* enquanto não
   estiver bindado (nenhum erro, nenhum aviso; a peça simplesmente nunca dobra);
3. uma **peg dirigida pela ponta da curva**, senão tudo que pende da peça (o antebraço num
   braço, a cabeça e os braços num tronco) fica parado enquanto o desenho arqueia.

Cada uma dessas três tem um jeito silencioso de dar errado, e todas já custaram horas de
produção:

| Sintoma | Causa real |
| --- | --- |
| Peça "desliza rígida" / vira blob | curva sem bind, ou bind colapsado (todo ponto no mesmo `u`) porque a curva está fora do desenho |
| Cabeça sai da gola quando o torso arqueia | sobra de curva ACIMA do desenho (`u_min > 0`) — a receita antiga de span 87% sobra nas duas pontas |
| Peça certa em repouso, errada quando a peg move | curva **parenteada E** com `FOLLOW_PEG` → transformada duas vezes (o operador C de bind parenteia sozinho) |
| Membro solta do corpo depois de "arrumar" a curva | os pontos mudaram e o **rest** dos drivers não foi recarimbado |
| Conserto "não colou" ao reabrir | **Auto Key ligado** (padrão nos arquivos do DPE): a edição virou keyframe e foi reaplicada por cima |

## Os cinco botões

| Operador | O que faz |
| --- | --- |
| `object.nuclear_curve_fit` — **Fit Curve to Drawing** | Mede o desenho pelos **pontos** (não `dimensions`/`bound_box`: o primeiro já vem deformado pelo modifier, o segundo costuma vir degenerado em GP), assenta a curva ponta a ponta (`coverage = 1.0`), binda e recarimba o rest da peg dirigida. Sem curva no modifier, cria uma pelo operador nativo (`greasepencil_curve_setup`, que já parenteia certo). `keep_shape` escala/recentra a curva existente em vez de endireitá-la — a diagonal de uma cauda ou a barriga de uma perna sobrevive. |
| `object.nuclear_curve_bind` — **Bind** / **Bind Again** / **Unbind** | Bind/rebind em lote (`only_unbound` pula quem já está bindado, `unbind` desfaz para medir cru). Reporta a **cobertura** (quanto do desenho a curva alcança) e acusa bind colapsado pelo nome. **Remove o parent que o bind em C acrescenta** quando a curva já segue uma peg. No painel são **dois botões**, não um com checkbox — ver "O botão de bind" abaixo. |
| `object.nuclear_curve_link_peg` — **Link Curve to Rig** | Insere/reusa a peg `<junta>_curva` entre a junta da peça e os filhos dela, com drivers de translação (X/Z) e rotação (Y) lidos da ponta da curva. Deixa de fora a peg de desenho da própria peça (o modifier já a deforma; a peg a moveria de novo). Idempotente: reusa a peg que já é dirigida por essa curva. |
| `object.nuclear_curve_refresh` — **Restamp Rest Pose** | Recarimba o rest dos drivers e o pivô da peg a partir da forma ATUAL da curva. Rodar sempre que os pontos de uma curva-fonte mudarem. |
| `object.nuclear_curve_check` — **Check Deform Curves** | Read-only. Lista cada curva do arquivo com: bindada?, faixa de `u`, span curva×desenho, dupla transformação, peg ligada, rest velho, Auto Key ligado. O relatório fica no painel. |

Todos desligam Auto Key durante a edição e restauram depois, e rebuildam o Peg Graph (a node
tree é um datablock à parte: sem rebuild + `use_fake_user` a peg nova some ao reabrir).

## O botão de bind (revisto em 2026-08-12)

O bind é o interruptor que decide se a curva deforma **alguma coisa** — e o painel tinha um
botão só, "Bind Curves", que não dizia nada disso. Três queixas concretas e o que responde
cada uma:

| Estava | Ficou |
| --- | --- |
| Desbindar exigia clicar em "Bind Curves" e marcar **Unbind** no *Adjust Last Operation* (`F9`) — onde ninguém olha no meio de um rig | **Dois botões**: `Bind`/`Bind Again` e `Unbind`, lado a lado. O Unbind fica **cinza** quando nenhuma peça do alvo está bindada (em vez de sumir, que faria o painel pular ao trocar de seleção) |
| O unbind não tinha nome: `F9` e a busca `F3` liam o `bl_label` do bind e anunciavam "Bind" para quem acabara de desbindar | Operador próprio **`object.nuclear_curve_unbind`** ("Unbind from Curve"), fino — delega o trabalho ao mesmo `nuclear_curve_bind(unbind=True)`, que **segue válido** para os scripts já escritos |
| O rótulo não dizia **em quem** ia mexer, e sem seleção o operador varre o arquivo inteiro (`_gp_targets`) — e o `.blend` **guarda a seleção**, então abrir um rig já mirava numa peça só | Linha `Acts on …` acima dos botões: *the selected piece* / *the 2 selected pieces* / *all 8 visible pieces*. O tooltip (`description()` dinâmica) repete o mesmo alvo, e muda de texto entre bind e unbind |
| Nada distinguia "vou bindar" de "vou rebindar", e um modifier sem bind é **no-op silencioso** | O rótulo vira **Bind Again** quando tudo no alvo já está bindado; com nada bindado o painel diz `not bound — the curve deforms nothing`; pela metade, `5 of 8 bound` |

O estado é lido sobre **todo o conjunto alvo**, não só a peça ativa — medido em 0,04 ms por
redraw (pior caso 0,06 ms, nenhuma bindada, rig de 8 curvas), então cabe no redraw do painel.

O relatório do operador também deixou de falar em `u`: `u 0.998–1.000` parece ótimo para quem
não sabe que bind colapsado vira blob rígido. Agora diz `bound, the curve reaches 100% of the
drawing` ou `bound but COLLAPSED onto 3% of the drawing — … run Fit Curve to Drawing`, e o
resumo sai como WARNING quando alguma peça precisa de atenção.

Teste: `tools/nuclear_rig/selftest_deform_curve_panel.py` roda o `draw()` do painel contra um
layout dublê que registra rótulos, `enabled` e as propriedades de cada operador — nada de GUI, que
esta máquina não tem como levantar (sem Xvfb). Verde em `Quetzalcoatl_pegs` (1 curva, 16/16),
`chula` e `carolina_pegs_atualizada` (2 curvas, todas bindadas, 17/17) e `dinossauro` (8 curvas,
uma solta, 17/17):

```sh
nuclear -b <rig.blend> -P tools/nuclear_rig/selftest_deform_curve_panel.py
```

## Decisões que valem lembrar

- **Ponta a ponta, não 87%.** `u` tem que cobrir ~0..1. `u_min > 0` é literalmente a fração
  de curva sobrando acima do desenho — e é o que descola a cabeça do pescoço, porque a peg
  filha pivoteia no topo da CURVA e anda o deslocamento inteiro, enquanto o topo do desenho
  (em `u > 0`) anda menos.
- **A ponta é o fim da cadeia** (o topo, num membro em pé), e a inclinação que a peg copia é a
  **TANGENTE ali, lida pelo handle do próprio ponto** — é ela que o modifier usa para orientar o
  desenho em `u = 0`. ⚠️ Até 2026-07-31 isto media a **corda** até a extremidade oposta e
  subestimava o giro: nas servas do EP05, deslocar a ponta 0,6 inclina o desenho 32,3° e a corda
  acusa 17,6° — 15° que a cabeça e os braços nunca recebiam, que é o "destoa do resto do corpo".
  Pior dobrando só o ponto do MEIO: nenhuma extremidade se move, a corda não vê giro nenhum e a
  peg fica parada enquanto o desenho inclina os mesmos 32°. Medido no MARTE (EP05) depois do
  conserto: dobra de 0,4 no topo → 21,71°; dobra de 0,4 só no meio → −21,71° (era 0,00°). O medo
  que motivou a corda ("entre vizinhos o ângulo dispara") não se aplica ao handle: ele é a
  inclinação real da curva ali, não uma secante entre dois pontos de controle.
- **Dois padrões de curva, não misturar:** curva **parenteada ao desenho e sem constraint**
  (o que o operador nativo cria) ou curva **com `FOLLOW_PEG` e sem parent** (o legado dos
  rigs convertidos). O bind sempre parenteia; para o segundo padrão o addon desfaz.
- **Curva-fonte de driver ≠ curva-folha.** Mexer nos pontos de uma curva que dirige uma peg
  exige recarimbar o rest — o Fit já faz isso; edições manuais pedem o Restamp.
- **Peça folha não precisa de peg dirigida.** O Check só cobra a peg quando existe algo para
  carregar (padrão de duas pegs: a junta tem filhos além da peg de desenho).

## Estado / validação

Rodado headless no `dinossauro_gigante_pegs.blend`: o Check achou **5 curvas sem bind**
(torso, os dois braços, as duas asas) e spans de 70–86%; o Fit levou o braço esquerdo de um
bind degenerado (`u = [0.000, 0.000]`, o "blob" que o animador via) para `u = [0.024, 0.976]`,
com o antebraço e a mão acompanhando a dobra pelos drivers. Criar uma curva do zero numa peça
sem modifier (coxa) e ligá-la ao rig (`Coxa.e_curva` carregando `Canela.e`) sobreviveu a
save + reload.
