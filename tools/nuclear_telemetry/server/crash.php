<?php
// SPDX-FileCopyrightText: 2026 Blender Authors
// SPDX-FileCopyrightText: 2026 Rapadura Atômica
// SPDX-License-Identifier: GPL-2.0-or-later
//
// Nuclear - endpoint que RECEBE os relatorios de falha (crash) dos clientes.
// Par do ping.php; basta subir em public_html/nuclear/nuclear-api/.
//
// URL final (se o arquivo ficar em public_html/nuclear/nuclear-api/crash.php):
//   https://rapaduraatomica.com.br/nuclear/nuclear-api/crash.php
//
// Grava cada relatorio como um .txt humano-legivel em ./data/crashes/ (protegido
// por .htaccess, fora da vista do navegador). Voce acessa os .txt por FTP / painel
// de arquivos da hospedagem.
//
// Mesmo token compartilhado do ping (X-Nuclear-Token). Nao ha credencial de FTP no
// cliente: o build so faz POST aqui, e o SERVIDOR escreve o arquivo - ele controla
// o nome (sanitizado) e o caminho, sem caminho vindo do cliente.

// ---- configuracao -----------------------------------------------------------

// Segredo compartilhado: o POST precisa mandar o header X-Nuclear-Token igual.
// Mesmo valor do ping.php / cliente. Deixe '' para nao exigir.
$TOKEN = '6a50f72f178f5c02b526418301fea046';

// Pasta dos relatorios (dentro de data/, que ja e negada pelo .htaccess).
$CRASH_DIR = __DIR__ . '/data/crashes';

// Limites de tamanho (defesa contra abuso de disco).
$MAX_LOG_BYTES = 262144;   // 256 KB do backtrace do Blender
$MAX_DESC_BYTES = 4000;    // descricao do usuario
$MAX_FIELD_BYTES = 200;    // campos curtos (estudio, hostname, versao, etc.)

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

// Helpers de saneamento.
function nuclear_str($data, $key, $max) {
    $v = isset($data[$key]) ? $data[$key] : '';
    if (!is_string($v)) {
        $v = '';
    }
    $v = trim($v);
    if (strlen($v) > $max) {
        $v = substr($v, 0, $max);
    }
    return $v;
}

// Slug seguro para compor o NOME do arquivo (nunca confie no cliente para caminho).
function nuclear_slug($s, $fallback) {
    $s = preg_replace('/[^A-Za-z0-9_-]+/', '-', $s);
    $s = trim($s, '-');
    if ($s === '') {
        $s = $fallback;
    }
    return substr($s, 0, 40);
}

$machine_id = nuclear_str($data, 'machine_id', 64);
$machine_id = preg_replace('/[^A-Za-z0-9]/', '', $machine_id); // id e hex
$studio     = nuclear_str($data, 'studio', $MAX_FIELD_BYTES);
$description = nuclear_str($data, 'description', $MAX_DESC_BYTES);
$hostname   = nuclear_str($data, 'hostname', $MAX_FIELD_BYTES);
$username   = nuclear_str($data, 'username', $MAX_FIELD_BYTES);
$version    = nuclear_str($data, 'version', $MAX_FIELD_BYTES);
$crashed_version = nuclear_str($data, 'crashed_version', $MAX_FIELD_BYTES);
$crashed_at = nuclear_str($data, 'crashed_at', $MAX_FIELD_BYTES);
$blender_log = nuclear_str($data, 'blender_log', $MAX_LOG_BYTES);

// Garante a pasta de crashes + nega acesso pela web (defesa em profundidade: os
// logs podem conter caminhos/usuario, nao devem ser servidos pelo navegador).
if (!is_dir($CRASH_DIR)) {
    @mkdir($CRASH_DIR, 0755, true);
}
$htaccess = $CRASH_DIR . '/.htaccess';
if (!file_exists($htaccess)) {
    // Forma compativel com Apache 2.4 (mod_authz_core) e 2.2, sem dar 500 em
    // servidor estrito que nao tenha o mod_access_compat.
    @file_put_contents(
        $htaccess,
        "<IfModule mod_authz_core.c>\n  Require all denied\n</IfModule>\n"
        . "<IfModule !mod_authz_core.c>\n  Deny from all\n</IfModule>\n"
    );
}

// Monta o corpo .txt humano-legivel.
$received = gmdate('c'); // ISO 8601 UTC
$id_short = $machine_id !== '' ? substr($machine_id, 0, 12) : '?';
$lines = array();
$lines[] = 'Nuclear - relatorio de falha';
$lines[] = '============================';
$lines[] = 'Recebido (UTC) : ' . $received;
$lines[] = 'Falha em (UTC) : ' . ($crashed_at !== '' ? $crashed_at : '?');
$lines[] = 'Estudio/resp.  : ' . ($studio !== '' ? $studio : '(nao informado)');
$lines[] = 'Maquina        : ' . ($hostname !== '' ? $hostname : '?') . ' (' . $id_short . ')';
$lines[] = 'Usuario SO     : ' . ($username !== '' ? $username : '?');
$lines[] = 'Versao (agora) : ' . ($version !== '' ? $version : '?');
$lines[] = 'Versao na falha: ' . ($crashed_version !== '' ? $crashed_version : '?');
$lines[] = '';
$lines[] = 'Descricao do usuario:';
$lines[] = ($description !== '' ? $description : '(nao informada)');
$lines[] = '';
$lines[] = '----- Log tecnico do Blender (crash.txt) -----';
$lines[] = ($blender_log !== '' ? $blender_log : '(nenhum arquivo de crash encontrado na maquina)');
$lines[] = '';
$body = implode("\n", $lines);

// Nome do arquivo: <timestamp>_<estudio-ou-host>_<id-curto>.txt - so o servidor
// decide; nada do caminho vem do cliente.
$ts = gmdate('Ymd-His');
$who = nuclear_slug($studio !== '' ? $studio : $hostname, 'sem-estudio');
$idf = nuclear_slug($id_short, 'sem-id');
$filename = $ts . '_' . $who . '_' . $idf . '.txt';
$target = $CRASH_DIR . '/' . $filename;

// Em caso (raro) de colisao no mesmo segundo, acrescenta um sufixo.
$n = 1;
while (file_exists($target)) {
    $target = $CRASH_DIR . '/' . $ts . '_' . $who . '_' . $idf . '_' . $n . '.txt';
    $n++;
}

if (@file_put_contents($target, $body, LOCK_EX) === false) {
    http_response_code(500);
    echo json_encode(array('error' => 'could not store report'));
    exit;
}

echo json_encode(array('ok' => true));
