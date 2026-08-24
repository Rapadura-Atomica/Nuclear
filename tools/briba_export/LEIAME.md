# Exportador `.brb`, relatório de fidelidade e modo lote (I3.1 a I3.4)

Ferramentas do **lado Nuclear** do lote de aposentadoria do fork: converter o acervo do estúdio
para o formato `.brb` do Briba Anima, e verificar que a conversão não mente.

Escritas a partir da **especificação** do formato, nunca do código do Briba —
a especificação atravessa a fronteira entre os dois lados; código, nunca.

## O laço

```
arquivo.blend ──[I3.4-arvore-canonica.py]──> árvore ─┐
      │                                               ├─> I3.4-comparar.py ─┐
      └──[I3.1-exportar-brb.py]──> .brb ──[I3.4-ler-brb.py]──> árvore ──────┤
                                     │                                      │
                                     └── relatorio-de-fidelidade.json ───────┤
                                          (o que o conversor DECLAROU)      │
                                                                            v
                                                     I3.2-relatorio-fidelidade.py
                                                     o que veio · o que se perdeu
                                                     o que conferir · perda CALADA
```

O I3.2 cruza duas fontes independentes: o que o conversor declarou de si mesmo
(dentro do `.brb`) e o que a comparação observou. Diferença observada onde o
conversor não avisou nada é **perda calada**, e reprova — é literalmente o
critério de aceite do lote.

| Comando | O que faz | Precisa de |
|---|---|---|
| `./I3.3-lote.py --lista L --saida D --verificar` | converte o acervo inteiro, sem intervenção | Nuclear + acervo |
| `./I3.4-rodar.sh` | o laço sobre as cinco referências | Nuclear + acervo |
| `./I3.2-relatorio-fidelidade.py` | relatório por arquivo e consolidado | só Python |
| `./I3.1-recarimbar-brb.py` | troca o carimbo do container sem reconverter | só Python |
| `./I3.4-autoteste.sh` | prova que o arnês passa e reprova quando deve | só Python |
| `./I3.2-autoteste.py` | prova que o relatório reprova perda calada e que a recarimbagem é reversível | só Python |

## Modo lote (I3.3)

```sh
./I3.3-lote.py --dir ~/acervo/Projeto --saida ~/lote-brb --verificar
./I3.3-lote.py --lista lista.txt --saida ~/lote-brb --continuar   # retomar
```

Um Nuclear por vez, de propósito: cada instância come RAM e dois em paralelo
numa estação de 16 GB derrubam a noite inteira. Cada arquivo tem prazo
(`--prazo`, 10 min), e arquivo que falha vira linha no registro em vez de parar
a fila. O registro (`lote-registro.jsonl`) é gravado e sincronizado a cada
arquivo — estação que reinicia às 4h da manhã retoma com `--continuar`.

Varre `.blend` **e** `.nuc`; pula backup `.blend1`, lixeira e cópia de conflito
do Dropbox (essas são decisão humana pendente, não acervo).

O CI roda o **autoteste**, não o laço: extrair e exportar exigem o binário do
Nuclear e os arquivos do acervo, e nenhum dos dois cabe num runner. Ver
`.github/workflows/i34-brb.yml`.

## As árvores de referência são anonimizadas

Este repositório é público, e as árvores vêm de produções do estúdio. Elas
passam por `I3.4-anonimizar.py` antes de entrar aqui: caminho de arquivo, nome
de objeto, de camada e de máscara viram pseudônimos estáveis.

**A estrutura fica intacta** — é ela que o teste exercita: quadros em espera,
máscaras (com o vínculo preservado entre camadas), biblioteca de poses fora da
linha do tempo, convenção de linha e preenchimento em camadas separadas.

| Referência | Por que está aqui |
|---|---|
| `ref-01-era-3.3-armature` | a era mais antiga do acervo, pesada em geometria por traço |
| `ref-02-era-4.4-armature` | era intermediária, muitos objetos com poucos traços |
| `ref-03-pegrig-linha-fill-pt` | linha e preenchimento separados; pequena, roda em segundos |
| `ref-04-pegrig-completo` | a mais rica: quadros em espera **e** biblioteca de poses |
| `ref-05-minimo` | o canário — se este reprovar, não é caso de canto |

A lista dos arquivos de origem é local (não versionada, por conter caminhos do
acervo). Para regerar: rodar `I3.4-arvore-canonica.py` sobre eles e anonimizar.

## Lacunas da especificação encontradas na prática

Descobertas exportando e tentando abrir no aplicativo de verdade. Nenhuma está
no documento do formato, e todas são necessárias para escrever um conversor:

| Lacuna | O que foi adotado | Como apareceu |
|---|---|---|
| Método de compressão do ZIP | **armazenado**, sem compressão | o aplicativo recusa entrada comprimida |
| Número mágico | `BRB\0` — **suposição declarada** | o aplicativo recusa o arquivo; falta o valor real |
| Nomes dos campos do manifesto | `magic`, `schema_version`, `project` | inferidos |
| Endianness do buffer de pontos | little-endian, 4 floats por ponto | não confirmado — **a única que não dá erro** |
| `actions/` × `performances/` | `performances/` | a própria spec marca como pendência |

Nenhuma delas é constante de código, e é de propósito: **o Briba ainda está
sendo escrito**, então nem tirar o valor de um arquivo que ele mesmo salvou é
possível hoje. O número mágico sai de `BRB_MAGIC`; quando o valor real for
fixado, o acervo já convertido **não precisa reconverter** — `I3.1-recarimbar-brb.py`
troca o carimbo, o nome dos campos e o nome da pasta dentro do container em
segundos por arquivo, deixando geometria e CBOR byte a byte iguais aos que já
foram conferidos:

```sh
./I3.1-recarimbar-brb.py --ver ~/lote-brb/brb/personagem.brb
./I3.1-recarimbar-brb.py ~/lote-brb/brb --magic 'BRBA' --backup
./I3.1-recarimbar-brb.py ~/lote-brb/brb --pasta 'performances/=actions/'
./I3.1-recarimbar-brb.py ~/lote-brb/brb --trocar-bytes
./I3.1-recarimbar-brb.py ~/lote-brb/brb --ordem-campos x,y,tempo,pressao
```

As duas últimas cobrem o buffer de pontos, que era a única suposição fora do
alcance da recarimbagem — e a mais perigosa, porque endianness trocada não faz
o leitor recusar nada: o arquivo abre e o desenho sai com coordenada absurda.
O buffer é um vetor achatado de float32, então trocar a ordem de bytes é uma
transformação de 4 em 4 bytes e trocar a ordem dos campos é uma permutação de
16 em 16 — nenhuma das duas mexe em offset, e o CBOR continua apontando para os
mesmos lugares. Buffer truncado é **recusado** em vez de transformado: mexer num
vetor já quebrado só espalha o estrago.

`--ver` também serve de diagnóstico: decodifica o primeiro ponto nas duas ordens
de bytes e mostra lado a lado. Coordenada de desenho fica na casa das unidades,
e a leitura errada devolve absurdo — dá para saber qual é a certa sem ter um
leitor do outro lado.

```
1o ponto  little-endian (0.165, 1.536, 1, 0)
          big-endian    (2.24e+24, -2.469e-19, 4.601e-41, 0)
```

Enquanto o valor não for confirmado, todo `.brb` sai com um achado `SUSPEITO`
de número mágico no relatório de fidelidade — a suposição fica escrita dentro
do próprio arquivo, não só na cabeça de quem exportou.

## O que o exportador ainda não faz

Níveis 3 e 4 — peça, rig e atuação. As entidades correspondentes seguem
pendentes do padrão de rig na própria especificação, e escrevê-las antes disso
seria construir sobre alvo móvel.

Máscara de camada não existe nos níveis 1 e 2. O vínculo **não se perde**: vai
inteiro para `mascaras.json` dentro do container, com o sinalizador de inversão
e o objeto de origem, de modo que a conversão seja reversível quando o formato
ganhar máscara.
