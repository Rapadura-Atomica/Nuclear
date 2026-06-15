<!--
Keep this document short & concise.
-->

Nuclear
=======

![Nuclear](https://rapaduraatomica.com.br/addon/rapaduraatomica/nuclear/images/splash-v1.0.png "Nuclear")

**Nuclear** é o software de animação desenvolvido pelo estúdio cearense **Rapadura Atômica**.

Conta com modificações internas e um repositório de addons próprios que agilizam o
**workflow 2D**, inspirados em ferramentas já consolidadas do mercado.

> 🧪 **Versão beta** — novas funções estão em desenvolvimento ativo.

Orgulhosamente derivado do [Blender](https://www.blender.org).

Para desenvolvedores
--------------------

O Nuclear tem um sistema de **auto-update** embutido (avisa e instala novas versões
sozinho) e um **subagente do Claude Code** que cuida de todo o ciclo de release.

- **Publicar uma atualização:** abra o Claude Code neste repositório e chame o agente
  `nuclear-release` (ex.: _"sobe uma atualização patch com a correção X"_). Ele cuida do
  bump de versão, build, empacotamento, manifesto e publicação, seguindo as regras de ouro.
  O agente vive em [`.claude/agents/nuclear-release.md`](.claude/agents/nuclear-release.md)
  — quem clona o repo já o recebe automaticamente.
- **Como tudo funciona** (modelo de versão, manifesto, servidor, troubleshooting):
  [`tools/nuclear_claude/CLAUDE.md`](tools/nuclear_claude/CLAUDE.md).

> Publicar exige acesso ao repositório **e** ao servidor de distribuição (SSH). Sem o SSH
> dá pra gerar o pacote localmente, mas não publicar.

Links
-----

- 🌐 **Site principal:** https://rapaduraatomica.com.br
- ☢️ **Nuclear:** https://rapaduraatomica.com.br/nuclear
- 📚 **Documentação e backlog:** _em desenvolvimento_

Licença
-------

Por ser derivado do Blender, o Nuclear como um todo é licenciado sob a
**GNU General Public License, versão 3**. Arquivos individuais podem ter
licenças diferentes, porém compatíveis.

Veja [blender.org/about/license](https://www.blender.org/about/license) para detalhes.
