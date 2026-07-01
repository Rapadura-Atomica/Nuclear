<?php
// SPDX-FileCopyrightText: 2026 Blender Authors
// SPDX-FileCopyrightText: 2026 Rapadura Atômica
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Nuclear - painel de admin (apelido + regiao por maquina). Versao PHP para
// hospedagem compartilhada (HostGator etc.), par do ping.php. Suba este arquivo
// junto com ping.php e index.php em public_html/nuclear/.
//
// URL final (se o arquivo ficar em public_html/nuclear/admin.php):
//   https://rapaduraatomica.com.br/nuclear/admin.php
//
// Paridade com app.py:
//   - mesmo banco SQLite de ./data/telemetry.sqlite (o que o ping.php alimenta);
//   - alias/region sao a fonte da verdade: definidos aqui, nunca sobrescritos por
//     um ping de heartbeat;
//   - "online" = visto nos ultimos NUCLEAR_ONLINE_SECS segundos E ultimo evento
//     diferente de "shutdown".
//
// SEGURANCA - leia antes de subir:
//   A senha de admin sai SO do ambiente (NUCLEAR_ADMIN_TOKEN). NAO ha valor padrao
//   e NADA de senha hardcoded neste arquivo - ele vai para o repositorio publico.
//   Sem o segredo configurado, /admin fica DESLIGADO (responde 503). Em hospedagem
//   compartilhada, defina a variavel no painel ou via .htaccess:
//       SetEnv NUCLEAR_ADMIN_TOKEN "sua-senha-forte"
//   (o token de PING e publico de fato - vai embutido no cliente; a senha de admin
//   NAO e, mantenha-a fora do Git e rotacione se algum valor ja vazou.)

// ---- configuracao -----------------------------------------------------------

// Usuario do admin (nao e segredo). Pode trocar por env tambem.
$ADMIN_USER = getenv('NUCLEAR_ADMIN_USER');
if ($ADMIN_USER === false || $ADMIN_USER === '') {
    $ADMIN_USER = 'admin';
}

// Senha do admin: SOMENTE do ambiente, sem default funcional (fail-closed).
$ADMIN_PASSWORD = getenv('NUCLEAR_ADMIN_TOKEN');
if ($ADMIN_PASSWORD === false) {
    $ADMIN_PASSWORD = '';
}

// Segundos desde o ultimo ping para ainda contar como "online". Bate com o
// ONLINE_SECS do app.py (default 600 = 10 min).
$ONLINE_SECS = (int) getenv('NUCLEAR_ONLINE_SECS');
if ($ONLINE_SECS <= 0) {
    $ONLINE_SECS = 600;
}

// Mesmo banco que o ping.php escreve (subpasta data/, fora da vista do navegador).
$DB_PATH = __DIR__ . '/data/telemetry.sqlite';

// -----------------------------------------------------------------------------

// Escapa para HTML (todas as saidas passam por aqui).
function h($s) {
    return htmlspecialchars((string) $s, ENT_QUOTES, 'UTF-8');
}

// Credenciais do Basic Auth. Em FastCGI/CGI (comum em HostGator) o servidor NAO
// preenche PHP_AUTH_USER sozinho - o header Authorization precisa ser lido na mao
// (e repassado via .htaccess: `RewriteRule .* - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]`).
function nuclear_basic_auth_creds() {
    if (isset($_SERVER['PHP_AUTH_USER'])) {
        $pw = isset($_SERVER['PHP_AUTH_PW']) ? $_SERVER['PHP_AUTH_PW'] : '';
        return array($_SERVER['PHP_AUTH_USER'], $pw);
    }
    $hdr = '';
    foreach (array('HTTP_AUTHORIZATION', 'REDIRECT_HTTP_AUTHORIZATION') as $k) {
        if (!empty($_SERVER[$k])) {
            $hdr = $_SERVER[$k];
            break;
        }
    }
    if ($hdr !== '' && stripos($hdr, 'Basic ') === 0) {
        $decoded = base64_decode(substr($hdr, 6), true);
        if ($decoded !== false && strpos($decoded, ':') !== false) {
            list($u, $p) = explode(':', $decoded, 2);
            return array($u, $p);
        }
    }
    return array(null, null);
}

// Confere usuario + senha em tempo constante. Fail-closed: sem segredo, nega.
function nuclear_admin_authed($user, $pass, $admin_user, $admin_password) {
    if ($admin_password === '') {
        return false;
    }
    if ($user === null) {
        return false;
    }
    $ok_user = hash_equals($admin_user, (string) $user);
    $ok_pass = hash_equals($admin_password, (string) $pass);
    return $ok_user && $ok_pass;
}

function nuclear_admin_challenge() {
    header('WWW-Authenticate: Basic realm="Nuclear admin"');
    http_response_code(401);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Autenticacao necessaria.';
    exit;
}

// Migracao idempotente: garante as colunas alias/region em bancos antigos.
function nuclear_ensure_columns($pdo) {
    $cols = array();
    foreach ($pdo->query('PRAGMA table_info(machines)')->fetchAll(PDO::FETCH_ASSOC) as $c) {
        $cols[] = $c['name'];
    }
    if (!in_array('alias', $cols, true)) {
        $pdo->exec('ALTER TABLE machines ADD COLUMN alias TEXT');
    }
    if (!in_array('region', $cols, true)) {
        $pdo->exec('ALTER TABLE machines ADD COLUMN region TEXT');
    }
}

// ---- porta de seguranca ------------------------------------------------------

// Admin desligado quando nao ha segredo configurado: 503 explicito (sem porta dos
// fundos por senha vazia, sem 401 sem fim).
if ($ADMIN_PASSWORD === '') {
    http_response_code(503);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Admin desativado: defina NUCLEAR_ADMIN_TOKEN no ambiente para habilitar.';
    exit;
}

list($auth_user, $auth_pass) = nuclear_basic_auth_creds();
if (!nuclear_admin_authed($auth_user, $auth_pass, $ADMIN_USER, $ADMIN_PASSWORD)) {
    nuclear_admin_challenge();
}

// ---- banco -------------------------------------------------------------------

try {
    $pdo = new PDO('sqlite:' . $DB_PATH);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    // Mesmo schema do ping.php - garante a tabela mesmo se o admin abrir antes de
    // qualquer ping.
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS machines (
            machine_id TEXT PRIMARY KEY,
            hostname   TEXT,
            username   TEXT,
            version    TEXT,
            last_event TEXT,
            first_seen TEXT,
            last_seen  TEXT,
            alias      TEXT,
            region     TEXT
        )'
    );
    nuclear_ensure_columns($pdo);
} catch (Exception $ex) {
    http_response_code(500);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Erro de banco.';
    exit;
}

// ---- POST: salvar apelido/regiao ou remover ----------------------------------

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $machine_id = isset($_POST['machine_id']) ? trim($_POST['machine_id']) : '';
    $action = isset($_POST['action']) ? $_POST['action'] : 'save';
    if ($machine_id !== '') {
        if ($action === 'delete') {
            $stmt = $pdo->prepare('DELETE FROM machines WHERE machine_id = :id');
            $stmt->execute(array(':id' => $machine_id));
        } else {
            $alias = isset($_POST['alias']) ? trim($_POST['alias']) : '';
            $region = isset($_POST['region']) ? trim($_POST['region']) : '';
            $stmt = $pdo->prepare(
                'UPDATE machines SET alias = :a, region = :r WHERE machine_id = :id'
            );
            $stmt->execute(array(
                ':a' => ($alias === '' ? null : $alias),
                ':r' => ($region === '' ? null : $region),
                ':id' => $machine_id,
            ));
        }
    }
    // PRG: redireciona para evitar reenvio do form no refresh.
    header('Location: ' . strtok($_SERVER['REQUEST_URI'], '?'), true, 303);
    exit;
}

// ---- GET: lista as maquinas --------------------------------------------------

$rows = $pdo->query('SELECT * FROM machines ORDER BY last_seen DESC')->fetchAll(PDO::FETCH_ASSOC);
$now = time();
$machines = array();
foreach ($rows as $r) {
    $online = false;
    $last = isset($r['last_seen']) ? strtotime($r['last_seen']) : false;
    if ($last !== false) {
        $age = $now - $last;
        $online = ($age <= $ONLINE_SECS) && ($r['last_event'] !== 'shutdown');
    }
    $r['online'] = $online;
    $machines[] = $r;
}

header('Content-Type: text/html; charset=utf-8');
?>
<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nuclear — admin de máquinas</title>
  <style>
    :root { color-scheme: dark; }
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
           background: #15171c; color: #e6e8eb; margin: 0; padding: 2rem; }
    h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
    .sub { color: #9aa0a6; margin-bottom: 1.5rem; font-size: .9rem; }
    .sub a { color: #2ecc71; }
    table { width: 100%; border-collapse: collapse; background: #1e2128;
            border-radius: 10px; overflow: hidden; }
    th, td { text-align: left; padding: .6rem .8rem; border-bottom: 1px solid #2a2e37;
             vertical-align: middle; }
    th { color: #9aa0a6; font-weight: 600; font-size: .8rem; text-transform: uppercase;
         letter-spacing: .03em; }
    tr:last-child td { border-bottom: none; }
    .dot { display: inline-block; width: .6rem; height: .6rem; border-radius: 50%;
           margin-right: .4rem; vertical-align: middle; }
    .on  { background: #2ecc71; box-shadow: 0 0 8px #2ecc71aa; }
    .off { background: #5a606b; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #9aa0a6;
            font-size: .82rem; }
    input[type=text] { background: #15171c; color: #e6e8eb; border: 1px solid #2a2e37;
            border-radius: 6px; padding: .4rem .5rem; width: 11rem; font: inherit; }
    button { font: inherit; border: 0; border-radius: 6px; padding: .42rem .8rem;
             cursor: pointer; }
    .save { background: #2ecc71; color: #0c1a10; font-weight: 600; }
    .del  { background: transparent; color: #e06b6b; border: 1px solid #5a3030; }
    .empty { color: #9aa0a6; padding: 2rem 0; }
  </style>
</head>
<body>
  <h1>Nuclear — admin de máquinas</h1>
  <div class="sub">
    Defina <strong>apelido</strong> e <strong>região</strong> para localizar as suas máquinas.
    Esses rótulos são preservados a cada ping. · <a href="index.php">ver painel público</a>
  </div>

<?php if (!empty($machines)): ?>
  <!-- Forms ficam fora da tabela; os campos das células os referenciam pelo
       atributo form= (HTML5). Isso evita o <form> inválido dentro de <tr>. -->
<?php foreach ($machines as $i => $m): ?>
  <form id="f-<?php echo $i; ?>" method="post">
    <input type="hidden" name="machine_id" value="<?php echo h($m['machine_id']); ?>">
  </form>
<?php endforeach; ?>
  <table>
    <thead>
      <tr>
        <th>Status</th><th>Máquina</th><th>Apelido</th><th>Região</th><th></th>
      </tr>
    </thead>
    <tbody>
<?php foreach ($machines as $i => $m): ?>
      <tr>
        <td><span class="dot <?php echo $m['online'] ? 'on' : 'off'; ?>"></span></td>
        <td>
          <?php echo h($m['hostname'] ? $m['hostname'] : '—'); ?>
          <div class="mono"><?php echo h(substr($m['machine_id'], 0, 12)); ?> · <?php echo h($m['username'] ? $m['username'] : '—'); ?> · v<?php echo h($m['version'] ? $m['version'] : '—'); ?></div>
        </td>
        <td><input form="f-<?php echo $i; ?>" type="text" name="alias" value="<?php echo h($m['alias']); ?>" placeholder="ex: Estação Anim 01"></td>
        <td><input form="f-<?php echo $i; ?>" type="text" name="region" value="<?php echo h($m['region']); ?>" placeholder="ex: CEARÁ"></td>
        <td style="white-space:nowrap">
          <button form="f-<?php echo $i; ?>" class="save" name="action" value="save">Salvar</button>
          <button form="f-<?php echo $i; ?>" class="del" name="action" value="delete"
                  onclick="return confirm('Remover esta máquina do painel?')">Remover</button>
        </td>
      </tr>
<?php endforeach; ?>
    </tbody>
  </table>
<?php else: ?>
  <div class="empty">Nenhuma máquina registrada ainda.</div>
<?php endif; ?>
</body>
</html>
