<?php
// SPDX-FileCopyrightText: 2026 Blender Authors
// SPDX-FileCopyrightText: 2026 Rapadura Atômica
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Nuclear - endpoint que RECEBE os pings de presenca dos clientes Nuclear.
// Versao PHP para hospedagem compartilhada (HostGator etc.): basta subir este
// arquivo em public_html/nuclear/ - nao precisa de Python, venv nem Passenger.
//
// URL final (se o arquivo ficar em public_html/nuclear/ping.php):
//   https://rapaduraatomica.com.br/nuclear/ping.php
//
// Guarda os dados num SQLite dentro de ./data/ (protegido por .htaccess).
//
// Alem de registrar a presenca, a resposta inclui o manifesto de atualizacao
// (estacao/version.json) sob a chave "update", para que o cliente possa, se
// quiser, descobrir a ultima versao pelo mesmo ping que ja faz. O cliente
// nuclear_update.py tambem le esse manifesto direto, entao isto e um bonus
// (permite ao painel saber quem esta desatualizado).

// ---- configuracao -----------------------------------------------------------

// Segredo compartilhado: o ping precisa mandar o header X-Nuclear-Token igual.
// Tem que bater com o SHARED_TOKEN do cliente Nuclear. Deixe '' para nao exigir.
$TOKEN = '6a50f72f178f5c02b526418301fea046';

// Caminho do banco SQLite (fora da vista do navegador, na subpasta data/).
$DB_PATH = __DIR__ . '/data/telemetry.sqlite';

// Manifesto de atualizacao. Fica em estacao/version.json, dois niveis acima
// (nuclear-api/ -> nuclear/ -> docroot -> estacao/).
$MANIFEST_PATH = __DIR__ . '/../../estacao/version.json';

// Preenchimento automatico de regiao por GeoIP. So roda UMA vez, quando a
// maquina e vista pela primeira vez (INSERT). O painel de admin sempre tem a
// palavra final - um valor manual nunca e sobrescrito pelo ping. Coloque false
// para nao consultar o servico externo.
$GEOIP_AUTOFILL = true;

// -----------------------------------------------------------------------------

header('Content-Type: application/json');

// So aceita POST.
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(array('error' => 'method not allowed'));
    exit;
}

// Confere o token (se houver um configurado).
$sent_token = isset($_SERVER['HTTP_X_NUCLEAR_TOKEN']) ? $_SERVER['HTTP_X_NUCLEAR_TOKEN'] : '';
if ($TOKEN !== '' && !hash_equals($TOKEN, $sent_token)) {
    http_response_code(401);
    echo json_encode(array('error' => 'unauthorized'));
    exit;
}

// Le o corpo JSON.
$raw = file_get_contents('php://input');
$data = json_decode($raw, true);
if (!is_array($data)) {
    $data = array();
}

$machine_id = isset($data['machine_id']) ? trim($data['machine_id']) : '';
if ($machine_id === '') {
    http_response_code(400);
    echo json_encode(array('error' => 'machine_id required'));
    exit;
}

$hostname = isset($data['hostname']) ? substr($data['hostname'], 0, 200) : '';
$username = isset($data['user'])     ? substr($data['user'], 0, 200)     : '';
$version  = isset($data['version'])  ? substr($data['version'], 0, 100)  : '';
$event    = isset($data['event'])    ? substr($data['event'], 0, 50)     : '';
$ts = gmdate('c'); // ISO 8601 em UTC, ex: 2026-06-09T22:00:00+00:00

// Garante a pasta data/.
$data_dir = __DIR__ . '/data';
if (!is_dir($data_dir)) {
    @mkdir($data_dir, 0755, true);
}

// Le o manifesto de atualizacao (se existir) para devolver na resposta.
function nuclear_read_manifest($path) {
    if (!is_readable($path)) {
        return null;
    }
    $manifest = json_decode(file_get_contents($path), true);
    if (is_array($manifest) && isset($manifest['build'])) {
        return $manifest;
    }
    return null;
}

// IP real do cliente (respeitando proxy/CDN como Cloudflare na frente).
function nuclear_client_ip() {
    foreach (array('HTTP_CF_CONNECTING_IP', 'HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR') as $k) {
        if (!empty($_SERVER[$k])) {
            // X-Forwarded-For pode vir como "cliente, proxy1, proxy2".
            $parts = explode(',', $_SERVER[$k]);
            return trim($parts[0]);
        }
    }
    return '';
}

// Regiao (estado) a partir do IP. Granularidade de estado e o que e confiavel;
// cidade pequena erra muito. Falha em silencio (timeout curto) para nunca
// atrasar nem quebrar o ping.
function nuclear_geoip_region($ip) {
    if ($ip === '' || $ip === '127.0.0.1' || $ip === '::1' || strpos($ip, '192.168.') === 0 || strpos($ip, '10.') === 0) {
        return null;
    }
    $url = 'http://ip-api.com/json/' . urlencode($ip) . '?fields=status,regionName&lang=pt-BR';
    $ctx = stream_context_create(array('http' => array('timeout' => 2)));
    $resp = @file_get_contents($url, false, $ctx);
    if ($resp === false) {
        return null;
    }
    $j = json_decode($resp, true);
    if (is_array($j) && isset($j['status']) && $j['status'] === 'success' && !empty($j['regionName'])) {
        return $j['regionName'];
    }
    return null;
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

try {
    $pdo = new PDO('sqlite:' . $DB_PATH);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
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

    // Maquina nova? So entao preenchemos a regiao por GeoIP (uma vez na vida).
    $exists = $pdo->prepare('SELECT 1 FROM machines WHERE machine_id = :id');
    $exists->execute(array(':id' => $machine_id));
    $is_new = ($exists->fetchColumn() === false);

    $region = ($is_new && $GEOIP_AUTOFILL) ? nuclear_geoip_region(nuclear_client_ip()) : null;

    // UPSERT: insere, ou atualiza se a maquina ja existe (mantendo o first_seen).
    // alias e region NAO entram no DO UPDATE: rotulos definidos no admin sao a
    // fonte da verdade e nunca sao sobrescritos por um ping de heartbeat.
    $stmt = $pdo->prepare(
        'INSERT INTO machines (machine_id, hostname, username, version, last_event, first_seen, last_seen, region)
         VALUES (:id, :h, :u, :v, :e, :fs, :ls, :rg)
         ON CONFLICT(machine_id) DO UPDATE SET
             hostname   = excluded.hostname,
             username   = excluded.username,
             version    = excluded.version,
             last_event = excluded.last_event,
             last_seen  = excluded.last_seen'
    );
    $stmt->execute(array(
        ':id' => $machine_id, ':h' => $hostname, ':u' => $username,
        ':v' => $version, ':e' => $event, ':fs' => $ts, ':ls' => $ts, ':rg' => $region,
    ));

    $response = array('ok' => true);
    $manifest = nuclear_read_manifest($MANIFEST_PATH);
    if ($manifest !== null) {
        $response['update'] = $manifest;
    }
    echo json_encode($response);
} catch (Exception $ex) {
    http_response_code(500);
    echo json_encode(array('error' => 'server error'));
}
