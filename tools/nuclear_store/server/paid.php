<?php
/**
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Nuclear — canal de entrega paga (entitlement por token).
 *
 * Layout no servidor (mesmo dir do estacao/):
 *   estacao/paid.php            <- este arquivo (endpoint publico)
 *   estacao/paid/.htaccess      <- "Require all denied" (nada ali e servido direto)
 *   estacao/paid/tokens.json    <- token -> {client, addons, expires}
 *   estacao/paid/files/*.zip    <- os addons/pacotes pagos
 *
 * API:
 *   GET paid.php                            (com token)  -> JSON: lista do que o token da direito
 *   GET paid.php?file=meu-addon.zip         (com token)  -> stream do arquivo, se entitled
 *   Token via header X-Nuclear-Token (preferido) ou ?token=...
 *
 * tokens.json:
 *   { "<token>": { "client": "Estudio X", "addons": ["meu-addon.zip"] | "*",
 *                  "expires": "2027-01-01" (opcional) } }
 *
 * Clientes HTTP: mande um User-Agent proprio (o mod_security do host devolve 406
 * para o "Python-urllib/x.y" default — mesma pegadinha da telemetria).
 */

header('X-Content-Type-Options: nosniff');

const PAID_DIR   = __DIR__ . '/paid';
const TOKENS     = PAID_DIR . '/tokens.json';
const FILES_DIR  = PAID_DIR . '/files';
const ACCESS_LOG = PAID_DIR . '/paid.log';

function deny(int $code, string $msg): void {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['error' => $msg]);
    exit;
}

function log_access(string $client, string $what): void {
    $line = sprintf("%s\t%s\t%s\t%s\n",
        gmdate('c'), $_SERVER['REMOTE_ADDR'] ?? '-', $client, $what);
    @file_put_contents(ACCESS_LOG, $line, FILE_APPEND | LOCK_EX);
}

// --- autenticacao -----------------------------------------------------------
$token = $_SERVER['HTTP_X_NUCLEAR_TOKEN'] ?? ($_GET['token'] ?? '');
if ($token === '' || !is_string($token)) {
    deny(401, 'token ausente');
}

$raw = @file_get_contents(TOKENS);
$tokens = $raw !== false ? json_decode($raw, true) : null;
if (!is_array($tokens)) {
    deny(503, 'catalogo indisponivel');
}

$entry = null;
foreach ($tokens as $known => $meta) {           // comparacao timing-safe
    if (is_string($known) && hash_equals($known, $token)) {
        $entry = $meta;
        break;
    }
}
if ($entry === null) {
    log_access('-', 'DENY token invalido');
    deny(403, 'token invalido');
}

$client = (string)($entry['client'] ?? 'sem-nome');
if (!empty($entry['expires']) && strtotime((string)$entry['expires']) < time()) {
    log_access($client, 'DENY token expirado');
    deny(403, 'token expirado');
}

$entitled = $entry['addons'] ?? [];
$all      = ($entitled === '*');

// --- sem ?file= : lista o que o token da direito ------------------------------
$file = $_GET['file'] ?? '';
if ($file === '') {
    $available = [];
    foreach (glob(FILES_DIR . '/*') ?: [] as $path) {
        $name = basename($path);
        if ($all || (is_array($entitled) && in_array($name, $entitled, true))) {
            $available[] = ['file' => $name, 'size' => filesize($path),
                            'sha256' => hash_file('sha256', $path)];
        }
    }
    log_access($client, 'LIST');
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['client' => $client, 'addons' => $available]);
    exit;
}

// --- com ?file= : entrega -----------------------------------------------------
if (!is_string($file) || !preg_match('/^[A-Za-z0-9][A-Za-z0-9._-]*$/', $file)) {
    deny(400, 'nome de arquivo invalido');
}
if (!$all && !(is_array($entitled) && in_array($file, $entitled, true))) {
    log_access($client, "DENY $file (sem direito)");
    deny(403, 'este token nao da direito a este arquivo');
}
$path = FILES_DIR . '/' . $file;
if (!is_file($path)) {
    deny(404, 'arquivo nao encontrado');
}

log_access($client, "GET $file");
header('Content-Type: application/octet-stream');
header('Content-Disposition: attachment; filename="' . $file . '"');
header('Content-Length: ' . filesize($path));
readfile($path);
