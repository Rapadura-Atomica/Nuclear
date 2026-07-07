# Nuclear Store — canal de entrega paga (MVP)

Infra mínima do modelo comercial híbrido (ver ADR
`docs/decisions/2026-07-07-modelo-comercial-hibrido.md`): o **addon é GPL, o que se
vende é o acesso** — download, updates e suporte via canal oficial autenticado por
token de cliente.

## Peças

| Arquivo | Vai para | O quê |
| --- | --- | --- |
| `server/paid.php` | `estacao/paid.php` | endpoint público: lista/entrega por token |
| `server/htaccess-paid` | `estacao/paid/.htaccess` | bloqueia acesso direto ao storage |
| — | `estacao/paid/tokens.json` | token → cliente/direitos (criado pelo `new_token.sh`; **nunca no repo**) |
| — | `estacao/paid/files/*.zip` | os addons/pacotes pagos |
| — | `estacao/paid/paid.log` | log de acesso (auditoria) |
| `new_token.sh` | (local) | gera token e registra no servidor via ssh |

## Deploy inicial (uma vez)

```sh
cd tools/nuclear_store
ssh araga286 'mkdir -p ~/public_html/addon/rapaduraatomica/estacao/paid/files'
scp server/paid.php      araga286:~/public_html/addon/rapaduraatomica/estacao/paid.php
scp server/htaccess-paid araga286:~/public_html/addon/rapaduraatomica/estacao/paid/.htaccess
# conferir o bloqueio ANTES de subir qualquer arquivo pago:
curl -s -o /dev/null -w '%{http_code}\n' https://rapaduraatomica.com.br/estacao/paid/tokens.json   # tem que dar 403
```

> ⚠️ `paid.php` é CÓDIGO em produção: overwrite posterior segue a regra de aprovação
> manual (mesma do `ping.php`). O upload inicial é arquivo novo (aditivo).

## Operação

```sh
# vender um addon: sobe o zip e gera o token do cliente
scp meu-addon.zip araga286:~/public_html/addon/rapaduraatomica/estacao/paid/files/
tools/nuclear_store/new_token.sh "Estudio X" meu-addon.zip

# cliente consome (o User-Agent custom é obrigatório — mod_security devolve 406 pro default do Python):
curl -H 'X-Nuclear-Token: TOKEN' -A 'Nuclear-Store/1.0' \
  'https://rapaduraatomica.com.br/estacao/paid.php'                      # lista (JSON c/ sha256)
curl -H 'X-Nuclear-Token: TOKEN' -A 'Nuclear-Store/1.0' -O \
  'https://rapaduraatomica.com.br/estacao/paid.php?file=meu-addon.zip'   # download

# revogar: remover a chave do tokens.json no servidor (ou pôr "expires" no passado)
```

## Segurança (o que o MVP cobre / não cobre)

- Cobre: token timing-safe (`hash_equals`), expiração opcional, whitelist de nome de
  arquivo (sem traversal), storage fora da web via `.htaccess`, log de acesso.
- Não cobre (aceito no MVP): rate-limit, contagem de downloads, painel de gestão,
  pagamento automatizado (checkout → token é manual por ora). Evoluir quando houver
  volume.

## Futuro (quando valer)

- Cliente embutido no Nuclear ("Inserir chave de licença" → baixa/instala addons
  pagos direto), reusando o `_ssl_context()` do updater.
- Integração de checkout (Gumroad/LemonSqueezy/Stripe) gerando token via webhook.
