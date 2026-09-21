# T1 - Servidor HTTP/1.1 sobre sockets TCP

Laboratorio de Redes de Computadores - Escola Politecnica PUCRS

Servidor HTTP/1.1 escrito diretamente sobre a API de sockets TCP, sem
nenhuma biblioteca de HTTP do lado servidor. Parsing e montagem das
mensagens sao feitos manualmente. Apenas biblioteca padrao do Python 3.

## Execucao

Nao ha etapa de compilacao (Python interpretado):

```
python3 server.py --port 8080 --root ./www
```

Argumentos de linha de comando:

| Argumento | Descricao |
|-----------|-----------|
| `--port`  | Porta TCP de escuta (usar porta alta, > 1024). Obrigatorio. |
| `--root`  | Diretorio raiz a ser servido. Obrigatorio. |

O servidor faz bind em `0.0.0.0` (todas as interfaces), de modo que pode
ser acessado por outras maquinas da rede. Encerre com Ctrl-C.

## Funcionalidades

**Parte 1 - servidor**
- Metodos `GET` e `HEAD`; qualquer outro retorna `405` com `Allow: GET, HEAD`.
- Parser que acumula o fluxo de bytes ate `\r\n\r\n` e preserva o que sobra
  para a proxima requisicao (lida com `recv()` parcial ou multiplo).
- Percent-decoding no caminho (`%20` -> espaco).
- Codigos: `200`, `400` (request line/header invalido), `403` (traversal),
  `404`, `405`.
- Respostas com `Content-Length` correto (inclusive em erros e HEAD),
  `Content-Type` por extensao, `Date` em IMF-fixdate GMT e `Server`.
- Protecao contra directory traversal via `realpath()` (barra `..`,
  symlinks e variantes percent-encoded com `403`).
- Concorrencia: uma thread por conexao. Escolha justificada abaixo.

**Parte 2 - conexoes persistentes**
- Persistente por padrao (HTTP/1.1); fecha ao receber `Connection: close`,
  respondendo com o mesmo cabecalho.
- Timeout de conexao ociosa de 5 s (`IDLE_TIMEOUT` em `server.py`).
- Suporta multiplas requisicoes em sequencia na mesma conexao.

## Estrategia de concorrencia

Thread por conexao (`threading.Thread`, daemon). Justificativa: o modelo e
simples de explicar e implementar corretamente, cada conexao tem seu proprio
buffer e estado de parsing sem compartilhamento, e o `settimeout` por socket
resolve o timeout ocioso de forma natural. Como o gargalo aqui e I/O de rede
(nao CPU), o GIL do Python nao e limitante. Uma requisicao lenta ocupa apenas
sua thread; as demais continuam sendo atendidas.

## Teste rapido (local)

```
python3 test_server.py                 # checa parser e protecao de traversal
python3 server.py --port 8080 --root ./www &
curl -i http://127.0.0.1:8080/         # 200
curl -I http://127.0.0.1:8080/logo.png # HEAD, sem corpo
curl -i -X DELETE http://127.0.0.1:8080/            # 405
curl -i --path-as-is http://127.0.0.1:8080/../server.py  # 403
```

## Estrutura

```
server.py        # servidor (arquivo unico)
test_server.py   # checagem do parser e da protecao de traversal
www/             # diretorio de teste (index.html + logo.png + style.css)
capturas/        # .pcapng dos cenarios C1/C2 (gerados na medicao entre maquinas)
```

## Medicao Parte 2 (entre maquinas distintas)

A medir com Wireshark ativo (filtro `tcp.port == <porta>`), entre duas
maquinas reais (nao localhost):

- Registrar RTT medio (`ping`) antes.
- C1: 10 requisicoes ao mesmo recurso, cada uma com `Connection: close`.
- C2: 10 requisicoes na mesma conexao persistente.
- Salvar `capturas/c1.pcapng` e `capturas/c2.pcapng`.
