"""Checagem minima das duas partes nao-triviais: o parser (que precisa
lidar com fluxo de bytes parcial e conexao persistente) e a protecao contra
directory traversal. Rode: python3 test_server.py"""

import os
from server import parse_request, resolve_path

# --- parser: requisicao incompleta (recv parcial) ---
req, rest = parse_request(b"GET / HTTP/1.1\r\nHost: x\r\n")  # sem linha em branco
assert req is None, "requisicao incompleta deveria aguardar mais bytes"

# --- parser: requisicao completa + inicio da proxima preservado ---
raw = b"GET /a HTTP/1.1\r\nHost: x\r\n\r\nGET /b HTTP/1.1\r\n"
req, rest = parse_request(raw)
assert req["method"] == "GET" and req["target"] == "/a"
assert rest == b"GET /b HTTP/1.1\r\n", "resto (proxima requisicao) mal preservado"

# --- parser: header sem ':' -> malformado (400) ---
try:
    parse_request(b"GET / HTTP/1.1\r\nHostx\r\n\r\n")
    assert False, "deveria ter levantado ValueError"
except ValueError:
    pass

# --- seguranca: traversal barrado com 403 (inclusive percent-encoded) ---
root = os.path.dirname(os.path.abspath(__file__)) + "/www"
for evil in ["/../server.py", "/..%2f..%2fserver.py", "/%2e%2e/%2e%2e/etc/hosts"]:
    _, err = resolve_path(root, evil)
    assert err == "403 Forbidden", "traversal nao barrado: {}".format(evil)

# --- seguranca: arquivo legitimo resolve ok ---
full, err = resolve_path(root, "/index.html")
assert err is None and full.endswith("/www/index.html")

print("OK: parser e protecao de traversal passaram")
