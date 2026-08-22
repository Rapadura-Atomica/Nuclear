# Exportador `.brb` e arnês de conversão (I3.1 / I3.4)

Ferramentas do **lado Nuclear** do Lote Israel: converter o acervo do estúdio
para o formato `.brb` do Briba Anima, e verificar que a conversão não mente.

Escritas a partir da **especificação** do formato, nunca do código do Briba —
a especificação atravessa a fronteira entre os dois lados; código, nunca.

## O laço

```
arquivo.blend ──[I3.4-arvore-canonica.py]──> árvore ─┐
      │                                               ├─> I3.4-comparar.py ─> veredito
      └──[I3.1-exportar-brb.py]──> .brb ──[I3.4-ler-brb.py]──> árvore ┘
```

| Comando | O que faz | Precisa de |
|---|---|---|
| `./I3.4-rodar.sh` | o laço inteiro sobre as referências | Nuclear + acervo |
| `./I3.4-autoteste.sh` | prova que o arnês passa e reprova quando deve | só Python |

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
| Número mágico | `BRB\0` — **provisório** | o aplicativo recusa o arquivo; falta o valor real |
| Nomes dos campos do manifesto | `magic`, `schema_version`, `project` | inferidos |
| Endianness do buffer de pontos | little-endian, 4 floats por ponto | não confirmado |

## O que o exportador ainda não faz

Níveis 3 e 4 — peça, rig e atuação. As entidades correspondentes seguem
pendentes do padrão de rig na própria especificação, e escrevê-las antes disso
seria construir sobre alvo móvel.

Máscara de camada não existe nos níveis 1 e 2. O vínculo **não se perde**: vai
inteiro para `mascaras.json` dentro do container, com o sinalizador de inversão
e o objeto de origem, de modo que a conversão seja reversível quando o formato
ganhar máscara.
