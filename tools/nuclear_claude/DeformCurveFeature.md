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
| `object.nuclear_curve_bind` — **Bind Curves** | Bind/rebind em lote (`only_unbound` pula quem já está bindado, `unbind` desfaz para medir cru). Reporta `u_min–u_max` e marca bind degenerado. **Remove o parent que o bind em C acrescenta** quando a curva já segue uma peg. |
| `object.nuclear_curve_link_peg` — **Link Curve to Rig** | Insere/reusa a peg `<junta>_curva` entre a junta da peça e os filhos dela, com drivers de translação (X/Z) e rotação (Y) lidos da ponta da curva. Deixa de fora a peg de desenho da própria peça (o modifier já a deforma; a peg a moveria de novo). Idempotente: reusa a peg que já é dirigida por essa curva. |
| `object.nuclear_curve_refresh` — **Restamp Rest Pose** | Recarimba o rest dos drivers e o pivô da peg a partir da forma ATUAL da curva. Rodar sempre que os pontos de uma curva-fonte mudarem. |
| `object.nuclear_curve_check` — **Check Deform Curves** | Read-only. Lista cada curva do arquivo com: bindada?, faixa de `u`, span curva×desenho, dupla transformação, peg ligada, rest velho, Auto Key ligado. O relatório fica no painel. |

Todos desligam Auto Key durante a edição e restauram depois, e rebuildam o Peg Graph (a node
tree é um datablock à parte: sem rebuild + `use_fake_user` a peg nova some ao reabrir).

## Decisões que valem lembrar

- **Ponta a ponta, não 87%.** `u` tem que cobrir ~0..1. `u_min > 0` é literalmente a fração
  de curva sobrando acima do desenho — e é o que descola a cabeça do pescoço, porque a peg
  filha pivoteia no topo da CURVA e anda o deslocamento inteiro, enquanto o topo do desenho
  (em `u > 0`) anda menos.
- **A ponta é o fim da cadeia** (o topo, num membro em pé), e a referência de inclinação é a
  extremidade OPOSTA, não o ponto vizinho: entre vizinhos o ângulo dispara.
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
