# Handoff — Nuclear 1.7.1/b14: perdas de dados (pegs, prefs) + crash do Outliner (2026-07-27)

## Objetivo

O usuário abriu a sessão dizendo que a nova versão do Nuclear "retrocedeu" o rebrand
`blender` → Nuclear. A investigação partiu disso e desembocou em **três perdas de dados reais**
em produção, todas corrigidas e publicadas na **1.7.1 / NUCLEAR_BUILD 14**.

## Estado atual

**Tudo commitado na branch `Nuclear` e presente no `origin`** (working tree limpo).
Commits desta sessão, do mais antigo para o mais novo:

| commit | o quê |
|---|---|
| `5650284a200` | crash do Outliner + ruído de log do auto-key + `bezt[-1]` + updater cria o `.desktop` |
| `e19bb623119` | `verify-zip` reprova pacote sem poda |
| `bec553b0122` | **pegs**: Follow Peg passa a contar usuário no PegRig |
| `09b76ec32f3` | **prefs**: instância antiga não sobrescreve mais preferências novas |
| `3f6a91902eb` | release 1.7.1 / build 14 |

⚠️ `origin/Nuclear` já tem `3f6a91902eb`, mas **esta sessão nunca deu `git push`** — provavelmente
uma sessão Claude paralela empurrou (ver memória `parallel-claude-sessions-git-branch-collision`).
Confirmado com `git ls-remote origin refs/heads/Nuclear`. Antes de commitar qualquer coisa nova,
cheque `git branch --show-current` e o reflog.

### Publicado e verificado

- **Nuclear 1.7.1 (Beta), build 14**, no ar em `https://rapaduraatomica.com.br/estacao/`.
- zip = **357.337.194 bytes (340 MB)**, sha256
  `1481548d02db95a9e7520438033febdd0afc0dc06a27c91217814217355cbdaa`.
  Zip no servidor == manifesto == resposta pública (os três conferidos).
- Backup da b13 no servidor: `nuclear.zip.bak-pre-1.7.1`.
- **Update testado ponta a ponta**: o b13 detectou, baixou, validou checksum e aplicou.
  Esta máquina (192.168.0.19) está em `~/Nuclear/versions/1.7.1-b14`, `current` apontando para lá.
  O apply também rodou o cleanup pendente desde a b12 (removeu `~/.cache/blender`).
- `ping.php` / `instalarNuclear.sh` **não** foram tocados (deploy de código segue manual).

### O que foi consertado (todos validados com repro antes/depois)

1. **Pegs sumindo** (a queixa mais grave). `followpeg_id_looper` em
   `source/blender/blenkernel/intern/constraint.cc` reportava o PegRig com `is_reference = false`
   (`IDWALK_CB_NOP`), **sem contar usuário**. No take real da Carolina: 4 objetos seguindo o rig e
   `users = 1`. Quando o último usuário contado saía (o `NuclearPegTree` "Peg Graph"), o rig ia a
   zero e era descartado no save **com as 80 pegs**. Repro: remover o Peg Graph + salvar → antes
   `pegrigs=0`, depois `pegrigs=1 pegs=80`. Torna obsoleto o workaround `use_fake_user=True`.
2. **Preferências resetando** (addons/atalhos). Prefs são gravadas inteiras a partir do estado em
   memória, sem merge — a última instância a gravar vence, e uma janela aberta há horas escreve o
   estado de quando abriu. Agora o mtime do `userpref.blend` é rastreado e o save **automático**
   (saída) pula quando o disco está mais novo; **"Save Preferences" explícito continua forçando**.
3. **Crash do Outliner** (SIGSEGV real, coredump na .29 após 1h23 de trabalho).
   `tree_element_id_type_to_index()` repassava o `-1` de `BKE_idtype_idcode_to_index()` e o
   chamador fazia `merged->num_elements[-1]++` — escrita fora dos limites que corrompia o array
   vizinho do `MergedIconRow`, levando a deref de nulo em `outliner_draw_iconrow_doit`.
4. **Pacote inflado**: a b13 foi empacotada à mão e pulou a poda (578 MB). Voltou a 340 MB, e o
   `verify-zip` agora **reprova** pacote com peso morto.

### A queixa original do rebrand: era o lançador, não o código

A máquina `bazzite-2` (192.168.0.29) nunca recebeu o `Nuclear.desktop`; abria pelo shim `blender`,
então menu/systemd/journal diziam "blender" com binário e UI corretamente em Nuclear. Instalei o
lançador lá e aposentei dois órfãos de set/2025 como `.orfao.bak`. A raiz (`_refresh_desktop` só
reescrevia, nunca criava) foi corrigida — mas **só age a partir do update que PARTIR da b14**,
porque quem aplica é o updater da versão em execução.

## Próximos passos

1. **Perguntar ao usuário sobre as duas pendências abaixo** (ele ainda não respondeu).
2. Se ele autorizar a poda de backups do servidor:
   `ssh araga286 'cd ~/public_html/addon/rapaduraatomica/estacao && ls -l nuclear.zip.bak*'`
   — manter os 2-3 mais recentes, apagar o resto.
3. **Crash não investigado**: SIGSEGV de 16/07 na .29 em `GHOST_GetDPIHint` ←
   `WM_window_dpi_set_userdef` ← `wm_window_close` ← `WM_window_open` ← `render_view_open`
   (abrir/fechar a janela de render OpenGL). Coredump guardado lá:
   `ssh 192.168.0.29 'coredumpctl info 11517'`. Stack diferente do crash do Outliner.
4. Opcional: o pacote publicado **não tem** `pyclipper`, `triangle`, `skimage` — já não estavam
   nem na b13. Se algum recurso depende deles, está faltando desde antes; a regra de ouro nº4 do
   CLAUDE.md ainda os lista.

## Decisões tomadas (e por quê)

- **`is_reference = true` no Follow Peg** → o PegRig é um ID de *dado*, igual à Action do Action
  constraint (que passa `true`); só o *objeto*-alvo passa `false`, convenção do upstream contra
  ciclos. REJEITADO: continuar com `use_fake_user` como workaround — mascara a causa.
- **Guard de prefs só no caminho automático** → o explícito é pedido do usuário e deve vencer.
  REJEITADO: avisar na UI a cada conflito (incomodaria no uso normal) e recarregar sozinho
  (descartaria o que a instância tinha).
- **Gate de peso morto no `verify-zip`, não só no `nuclear_release.sh`** → a b13 vazou justamente
  por ter sido empacotada à mão, fora do script. O gate casa por allow-list de feature, espelhando
  `nuclear_prune_package.sh`; libs que o 2D USA (OpenColorIO, OpenImageIO, OpenEXR) não são
  acusadas, mesmo ausentes do NEEDED direto.
- **`NO_KEY_NEEDED` rebaixado a `CLOG_DEBUG`**, não removido → o evento continua visível com
  `--log "*anim*" --log-level 4`.
- **Publicar em duas fases** (`nuclear.zip.new` → conferir sha no servidor → `mv`) → evita janela
  com zip corrompido/parcial servido em produção.

## Pegadinhas / lições desta sessão

- ⚠️ **O `bin/` do `build_nuclear_2d` NÃO tem as deps Python do fork.** O `ninja install` não as
  instala — foram postas por fora um dia. O primeiro zip da b14 saiu sem `scipy` e o `verify-zip`
  reprovou (regra de ouro nº4). Copiei `scipy` + `scipy.libs` + dist-info (142 MB) do pacote
  publicado para o `bin/` **e** para o staging. O `bin/` agora os tem, mas **confira sempre**.
  Sem `scipy` o Auto Rig quebra (fit de Procrustes).
- `tools/nuclear_release.sh` **pede confirmação interativa** e aborta sem tty — em sessão headless,
  rode os passos do §5 do CLAUDE.md manualmente (bump → build → smoke → stamp → staging+poda →
  zip → manifest → verify → publish).
- `_update_available()` do updater lê a global `_latest`, preenchida por fetch assíncrono. Em
  headless ela é `None` e a função retorna `False` — **não é bug**. Chame `nu._fetch_worker()`
  antes de testar.
- Testar persistência de preferências exige **duas instâncias reais**; um único processo headless
  sempre "persiste" e esconde o problema.
- O usuário roda **várias instâncias do Nuclear ao mesmo tempo**. Enquanto houver janela em build
  ≤ b13 aberta, ela ainda sobrescreve as prefs ao fechar (foi o que apagou 4 addons dele às 21:05,
  durante esta sessão; reabilitei `asset_manager`, `blender_mcp_addon`, `dpe_render_setup`,
  `entremeio`).
- Duas janelas no mesmo `.blend` continuam perigosas: o guard de hoje é **só para preferências**,
  não para arquivos de trabalho.
- Detalhes duráveis já estão na memória: `nuclear-prefs-duas-instancias`, `maquina-bazzite2-lan-29`,
  `nuclear-auto-update`, `nuclear-auto-rig-contrato`. **Não duplicar aqui.**

## Estado do take da Carolina (`DPE_EP06_C12T67`)

Caminho: `~/Dropbox/Projetos/DragaoeoPocoEncantado/2_Producao/Longa/Ep06/DPE_EP06_C12/DPE_EP06_C12T67/blend_files/DPE_EP06_C12T67.blend`

O usuário trocou a versão da personagem e **salvou às 21:05**, o que resolveu o dano sozinho:
agora são 51 constraints Follow Peg com **os 51 ligados** ao rig novo `carolina_heroi.001`
(80 pegs, `users=51`) e **zero objetos órfãos**. Antes eram 59 constraints com só 4 ligados, e os
4 viviam justamente nos 8 objetos órfãos (que o Blender não salva).

Sobrou o rig antigo `carolina_heroi` (80 pegs, `users=1`, sustentado só pelo Peg Graph) — resíduo.
Os 8 órfãos foram perdidos no save; se precisarem ser recuperados, o `.blend1` de 21:05 é o backup
da gravação anterior.

Existe um script de reparo testado (religa constraints órfãos pelo `peg_name`) em
`/tmp/claude-1001/-var-home-rapaduraatomica/240c9033-79d3-4f91-9584-85ef12be402d/scratchpad/reparo.py`
— **provavelmente não é mais necessário**, e o scratchpad é volátil; o algoritmo é trivial de
reescrever (para cada constraint `FOLLOW_PEG` com `rig is None` e `peg_name` válido, `c.rig = rig`).

## Arquivos e comandos relevantes

- `source/blender/blenkernel/intern/constraint.cc` — `followpeg_id_looper` (fix das pegs).
- `source/blender/blenkernel/intern/blendfile.cc` — `g_userpref_mtime_seen`,
  `BKE_blendfile_userdef_write_all_ex()` (guard de prefs).
- `source/blender/windowmanager/intern/wm_init_exit.cc` — chama o guard com `force = false`.
- `source/blender/editors/space_outliner/outliner_draw.cc` — `tree_element_id_type_to_index()`.
- `scripts/startup/nuclear_update.py` — `_install_desktop()` / `_refresh_desktop()`.
- `tools/nuclear_release.py` — `verify-zip` com o gate de peso morto.
- `tools/nuclear_claude/CLAUDE.md` §10 — estado do release (atualizado).
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — as 3 seams novas registradas.

```sh
# build (container distrobox `blender`, preset 2D já configurado)
distrobox enter blender -- bash -lc 'nice /usr/bin/ninja -C ~/Documentos/GitHub/build_nuclear_2d -j2'
# smoke gate 2D (obrigatório antes de empacotar)
~/Documentos/GitHub/build_nuclear_2d/bin/nuclear -b --factory-startup --python tools/smoke_nuclear2d.py
# formatação (rodar de dentro do repo)
distrobox enter blender -- bash -lc 'cd ~/Documentos/GitHub/Nuclear && make format PATHS="..."'
# acesso à 2ª máquina (sshd vive desligado lá; pedir `sudo systemctl enable --now sshd` no teclado)
ssh 192.168.0.29
```

## Pendências que dependem do usuário

1. **Reiniciar o Nuclear** para as janelas abertas passarem a rodar a b14 (o `current` já aponta
   para ela; as janelas antigas seguem na b13).
2. **Rig `carolina_heroi` antigo** no T67: apagar (é resíduo) ou marcar `Fake User` para guardar.
3. **Backups do servidor**: 11 arquivos `nuclear.zip.bak*` somando **9,5 GB**, disco a **89%**
   (181 GB livres). Precisa de autorização para podar — é dado de produção.
4. **Worker fantasma na .29**: `painel-worker-blender.service` foi **desabilitado** nesta sessão
   (crash-loop HTTP 401, token placeholder `dev-worker-token-trocar`, sem `build_take.py`). A
   estação de build real é a .19 (`bazzite-nuclear`). Confirmar que era mesmo descartável.
5. **Os 8 objetos órfãos** perdidos no save do T67: decidir se vale recuperar do `.blend1`.
