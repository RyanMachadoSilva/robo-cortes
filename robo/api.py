"""Porta interna do robô: recebe do assistente os comandos ok / não / postei / status."""
import collections
import json
import os
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, estado

log = logging.getLogger("api")

status_lives = {}  # nome do canal -> {"titulo", "cortes", "desde"}
diagnosticos = {}  # nome do canal -> função que devolve o texto de diagnóstico da live
forcadores = {}  # nome do canal -> função que pede um corte do último minuto
_limpeza_pedida = 0.0  # quando pediram "limpar cortes" (precisa confirmar em 2 min)


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
    global _limpeza_pedida
    if acao == "limpar":
        import glob
        import os

        n = len(estado.cortes())
        arquivos = glob.glob(os.path.join(config.PASTA_CORTES, "*.mp4"))
        mb = sum(os.path.getsize(a) for a in arquivos if os.path.exists(a)) / 1e6
        _limpeza_pedida = time.time()
        return (
            f"🧹 Isso vai apagar *{n} cortes* ({len(arquivos)} vídeos, {mb:.0f} MB) da VPS e zerar o contador "
            "(o próximo volta a ser o #1). A gravação da live não é afetada.\n\n"
            "Pra confirmar, manda *confirmar limpeza* em até 2 minutos."
        )
    if acao == "confirmar_limpeza":
        if time.time() - _limpeza_pedida > 120:
            return "Não tem limpeza pendente (ou passou de 2 minutos). Manda *limpar cortes* de novo."
        _limpeza_pedida = 0.0
        n, apagados, bytes_ = estado.limpar_tudo()
        return f"✅ Limpo: {n} cortes e {apagados} vídeos apagados ({bytes_ / 1e6:.0f} MB liberados). Contador zerado."
    if acao == "forcar":
        if not forcadores:
            return "Nenhuma live sendo gravada agora, então não tem o que cortar."
        nome, forcar = next(iter(forcadores.items()))
        forcar()
        return f"✂️ Cortando o último minuto da live do *{nome}*. Deve chegar em 2 a 4 minutos."
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
        if config.DOCUMENTO_NO_OK:
            from . import assistente

            def mandar(c=c):
                for chave, rotulo in (("arquivo", ""), ("arquivo_extra", " (outra versão)"), ("arquivo_en", " (EN)")):
                    if c.get(chave) and os.path.exists(c[chave]):
                        assistente.documento(c[chave], f"📎 Corte #{c['id']}{rotulo} em qualidade original", c["id"])

            threading.Thread(target=mandar, daemon=True).start()
        return (
            f"✅ Corte #{c['id']} aprovado{' (o arquivo original chega em seguida como documento)' if config.DOCUMENTO_NO_OK else ''}. Texto pra copiar:\n\n{c.get('descricao') or c.get('titulo', '')}\n\n"
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
    return "Comandos: ok, não, postei (com o número do corte), cortes, corte agora, limpar cortes, diag ou log."


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
