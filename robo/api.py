"""Porta interna do robô: recebe do assistente os comandos ok / não / postei / status."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, estado

log = logging.getLogger("api")

status_live = {"ao_vivo": False, "titulo": "", "cortes_na_live": 0, "desde": None}


def executar(acao, cid=None):
    acao = (acao or "").lower().strip()
    if acao in ("status", "cortes"):
        pend = [c for c in estado.cortes() if c["status"] in ("pendente", "aprovado")]
        linhas = [f"*Robô de cortes*: {'🔴 gravando ' + status_live['titulo'] if status_live['ao_vivo'] else 'esperando live'}"]
        if status_live["ao_vivo"]:
            linhas.append(f"Cortes nesta live: {status_live['cortes_na_live']}")
        linhas += [f"#{c['id']} {c['status']}: {c.get('titulo', '')}" for c in pend] or ["Nenhum corte pendente."]
        return "\n".join(linhas)

    c = estado.corte(cid) if cid else estado.ultimo_pendente()
    if not c:
        return f"Não achei o corte #{cid}." if cid else "Não tem corte pendente."
    if acao == "ok":
        estado.atualizar(c["id"], status="aprovado")
        return (
            f"✅ Corte #{c['id']} aprovado. Texto pra copiar:\n\n{c.get('descricao') or c.get('titulo', '')}\n\n"
            + (f"🇺🇸 Em inglês:\n\n{c['descricao_en']}\n\n" if c.get("descricao_en") else "")
            + f"Depois de postar, manda *postei {c['id']}* que eu apago da VPS."
        )
    if acao in ("nao", "não"):
        estado.remover(c["id"])
        return f"🗑️ Corte #{c['id']} descartado."
    if acao == "postei":
        estado.remover(c["id"])
        return f"🚀 Boa! Apaguei o corte #{c['id']} da VPS."
    return "Comandos: ok, não, postei (com o número do corte) ou status."


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
