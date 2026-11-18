"""Porta interna do robô: recebe do assistente os comandos ok / não / postei / status."""
import collections
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, estado

log = logging.getLogger("api")

status_lives = {}  # nome do canal -> {"titulo", "cortes", "desde"}
diagnosticos = {}  # nome do canal -> função que devolve o texto de diagnóstico da live


class MemoriaLog(logging.Handler):
    """Guarda as últimas linhas do log para o comando "log" no WhatsApp."""

    def __init__(self, tamanho=200):
        super().__init__()
        self.linhas = collections.deque(maxlen=tamanho)

    def emit(self, record):
        self.linhas.append(self.format(record))


memoria_log = MemoriaLog()


def executar(acao, cid=None):
    acao = (acao or "").lower().strip()
    if acao == "log":
        linhas = [l[15:] if len(l) > 15 else l for l in list(memoria_log.linhas)[-25:]]  # tira a data
        return "*Últimas linhas do log:*\n" + ("\n".join(l[:160] for l in linhas) or "(vazio)")
    if acao == "diag":
        if not diagnosticos:
            return "Nenhuma live sendo gravada agora. Canais vigiados: " + ", ".join(c.split("/")[-1] for c in config.CANAIS)
        return "\n\n".join(f() for f in list(diagnosticos.values()))
    if acao in ("status", "cortes"):
        pend = [c for c in estado.cortes() if c["status"] in ("pendente", "aprovado")]
        linhas = ["*Robô de cortes*: vigiando " + ", ".join(c.split("/")[-1] for c in config.CANAIS)]
        for nome, st in list(status_lives.items()):
            linhas.append(f"🔴 {nome}: {st['titulo'][:60]} ({st['cortes']} cortes)")
        if not status_lives:
            linhas.append("Nenhuma live aberta agora.")
        linhas += [f"#{c['id']} {c['status']}: {c.get('titulo', '')}" for c in pend] or ["Nenhum corte pendente."]
        return "\n".join(linhas)

    c = estado.corte(cid) if cid else estado.ultimo_pendente()
    if not c:
        return f"Não achei o corte #{cid}." if cid else "Não tem corte pendente."
    if acao == "ok":
        estado.atualizar(c["id"], status="aprovado")
        return (
            f"✅ Corte #{c['id']} aprovado. Texto pra copiar:\n\n{c.get('descricao') or c.get('titulo', '')}\n\n"
            + (f"{'🇺🇸 Em inglês' if c.get('extra_idioma') == 'en' else '🇧🇷 Em português'}:\n\n{c['descricao_extra']}\n\n"
               if c.get("descricao_extra") else "")
            + f"Depois de postar, manda *postei {c['id']}* que eu apago da VPS."
        )
    if acao in ("nao", "não"):
        estado.remover(c["id"])
        return f"🗑️ Corte #{c['id']} descartado."
    if acao == "postei":
        estado.remover(c["id"])
        return f"🚀 Boa! Apaguei o corte #{c['id']} da VPS."
    return "Comandos: ok, não, postei (com o número do corte), cortes, diag ou log."


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/comando" or self.headers.get("X-Token") != config.TOKEN_ROBO or not config.TOKEN_ROBO:
            self.send_response(403)
            self.end_headers()
            return
        try:
            corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            resposta = executar(corpo.get("acao"), corpo.get("id"))
            codigo = 200
        except Exception as e:  # nunca derruba o robô por causa de um comando
            log.exception("erro no comando")
            resposta, codigo = f"Erro no robô: {e}", 500
        dados = json.dumps({"texto": resposta}, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *_):
        pass


def iniciar():
    srv = ThreadingHTTPServer(("0.0.0.0", config.PORTA_API), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="api").start()
    log.info("porta interna ouvindo em %s", config.PORTA_API)
    return srv
