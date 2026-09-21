#!/usr/bin/env python3
"""Servidor HTTP/1.1 sobre sockets TCP (Trabalho 1 - Lab Redes).

Implementa GET e HEAD, conexoes persistentes (HTTP/1.1) com timeout de
conexao ociosa, protecao contra directory traversal e concorrencia via
thread por conexao. Nenhuma biblioteca de HTTP do lado servidor e usada:
o parsing e a montagem das mensagens sao feitos na mao.
"""

import argparse
import os
import socket
import threading
from email.utils import formatdate
from urllib.parse import unquote

SERVER_NAME = "T1-LabRedes/1.0"
IDLE_TIMEOUT = 5  # segundos de ociosidade antes de fechar a conexao (Parte 2)

# Content-Type por extensao (os obrigatorios do enunciado).
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript",
    ".json": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
}


def content_type_for(path):
    ext = os.path.splitext(path)[1].lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


def build_response(status, body=b"", extra_headers=None, include_body=True):
    """Monta os bytes da resposta HTTP. Content-Length sempre reflete o
    tamanho real do corpo, inclusive em erros e em HEAD (onde o corpo e
    omitido mas o Content-Length continua o do GET correspondente)."""
    headers = {
        "Date": formatdate(usegmt=True),      # IMF-fixdate em GMT (RFC 9110)
        "Server": SERVER_NAME,
        "Content-Length": str(len(body)),
    }
    if extra_headers:
        headers.update(extra_headers)
    head = "HTTP/1.1 {}\r\n".format(status)
    head += "".join("{}: {}\r\n".format(k, v) for k, v in headers.items())
    head += "\r\n"
    data = head.encode("latin-1")
    if include_body:
        data += body
    return data


def error_response(status, extra_headers=None, include_body=True):
    body = "<html><body><h1>{}</h1></body></html>".format(status).encode()
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if extra_headers:
        headers.update(extra_headers)
    return build_response(status, body, headers, include_body)


def resolve_path(root, target):
    """Traduz o request-target em um caminho de arquivo seguro dentro de
    root. Retorna (caminho_absoluto, None) se ok, ou (None, status) se deve
    responder erro. realpath() resolve '..' e symlinks, entao qualquer
    tentativa de sair de root e barrada com 403."""
    path = unquote(target.split("?", 1)[0].split("#", 1)[0])
    root_real = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root_real, path.lstrip("/")))
    if full != root_real and not full.startswith(root_real + os.sep):
        return None, "403 Forbidden"
    if os.path.isdir(full):
        full = os.path.join(full, "index.html")
    if not os.path.isfile(full):
        return None, "404 Not Found"
    return full, None


def parse_request(buffer):
    """Recebe o buffer acumulado e tenta extrair UMA requisicao completa.
    Retorna (requisicao, resto) onde requisicao e um dict ou None se ainda
    nao chegou o fim dos cabecalhos (\r\n\r\n). resto sao os bytes que
    sobraram (inicio da proxima requisicao numa conexao persistente).
    Levanta ValueError se a requisicao for malformada (-> 400)."""
    sep = buffer.find(b"\r\n\r\n")
    if sep == -1:
        return None, buffer  # cabecalhos ainda incompletos, precisa de mais recv
    header_block = buffer[:sep].decode("latin-1")
    rest = buffer[sep + 4:]
    lines = header_block.split("\r\n")

    parts = lines[0].split(" ")
    if len(parts) != 3:
        raise ValueError("request line invalida")
    method, target, version = parts

    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            raise ValueError("header sem ':'")
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    # Consome o corpo (se houver Content-Length) para nao dessincronizar a
    # conexao persistente. GET/HEAD normalmente nao tem corpo, mas um cliente
    # pode enviar um; precisamos remove-lo do fluxo.
    body_len = int(headers.get("content-length", 0) or 0)
    if len(rest) < body_len:
        return None, buffer  # corpo ainda incompleto
    rest = rest[body_len:]

    return {"method": method, "target": target, "version": version,
            "headers": headers}, rest


def handle_request(req, root):
    """Produz (bytes_resposta, deve_fechar) para uma requisicao ja parseada."""
    method = req["method"]
    close = req["headers"].get("connection", "").lower() == "close"
    conn_header = {"Connection": "close"} if close else {"Connection": "keep-alive"}

    if method not in ("GET", "HEAD"):
        headers = dict(conn_header, Allow="GET, HEAD",
                       **{"Content-Type": "text/html; charset=utf-8"})
        body = b"<html><body><h1>405 Method Not Allowed</h1></body></html>"
        return build_response("405 Method Not Allowed", body, headers), close

    full, err = resolve_path(root, req["target"])
    if err:
        return error_response(err, conn_header), close

    with open(full, "rb") as f:
        body = f.read()
    headers = dict(conn_header, **{"Content-Type": content_type_for(full)})
    # HEAD: mesmos cabecalhos do GET (inclusive Content-Length), sem corpo.
    return build_response("200 OK", body, headers, include_body=(method == "GET")), close


def handle_connection(conn, addr, root):
    conn.settimeout(IDLE_TIMEOUT)
    buffer = b""
    try:
        while True:
            # Processa todas as requisicoes ja completas no buffer (pipelining
            # / conexao persistente) antes de voltar a ler do socket.
            while True:
                try:
                    req, buffer = parse_request(buffer)
                except ValueError:
                    conn.sendall(error_response("400 Bad Request",
                                                {"Connection": "close"}))
                    return
                if req is None:
                    break
                response, close = handle_request(req, root)
                conn.sendall(response)
                if close:
                    return
            data = conn.recv(4096)
            if not data:
                return  # cliente fechou
            buffer += data
    except socket.timeout:
        pass  # conexao ociosa: fecha silenciosamente
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Servidor HTTP/1.1 sobre TCP")
    parser.add_argument("--port", type=int, required=True, help="porta (>1024)")
    parser.add_argument("--root", required=True, help="diretorio raiz a servir")
    args = parser.parse_args()

    root = os.path.realpath(args.root)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", args.port))  # todas as interfaces, nao loopback
    server.listen(64)
    print("Servindo {} em 0.0.0.0:{}".format(root, args.port))
    try:
        while True:
            conn, addr = server.accept()
            # Thread por conexao: uma requisicao lenta nao bloqueia as demais.
            t = threading.Thread(target=handle_connection, args=(conn, addr, root),
                                 daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nEncerrando.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
