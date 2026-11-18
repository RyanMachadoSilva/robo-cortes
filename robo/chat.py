"""Lê o chat da live do YouTube em tempo real e passa as mensagens para o detector.

Tenta primeiro o chat-downloader; se ele falhar (quebra quando o YouTube muda), usa o leitor de chat
do próprio yt-dlp, que grava o chat num arquivo enquanto a live acontece.
"""
import glob
import json
import logging
import os
import subprocess
import threading
import time

from . import config

log = logging.getLogger("chat")


def _textos(obj):
    """Acha as mensagens de texto dentro do JSON do chat do YouTube (qualquer formato)."""
    if isinstance(obj, dict):
        for chave in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
            r = obj.get(chave)
            if isinstance(r, dict):
                runs = (r.get("message") or {}).get("runs") or []
                yield "".join(x.get("text") or (x.get("emoji", {}).get("shortcuts") or [""])[0] for x in runs)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _textos(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _textos(v)


class LeitorChat(threading.Thread):
    def __init__(self, url, detector, parar_evt):
        super().__init__(daemon=True, name="chat")
        self.url = url
        self.detector = detector
        self.parar_evt = parar_evt
        self.total = 0
        self.metodo = "nenhum"
        self.ultima_msg = 0.0

    def _recebeu(self, texto):
        self.total += 1
        self.ultima_msg = time.time()
        self.detector.mensagem(texto or "")

    # ----- 1ª opção: chat-downloader -----
    def _chat_downloader(self):
        from chat_downloader import ChatDownloader

        from .live import arquivo_cookies

        chat = ChatDownloader(cookies=arquivo_cookies()).get_chat(self.url, message_types=["text_message", "paid_message"])
        self.metodo = "chat-downloader"
        log.info("lendo o chat (chat-downloader)")
        for msg in chat:
            if self.parar_evt.is_set():
                return
            self._recebeu(msg.get("message"))
        raise RuntimeError("chat-downloader parou de receber")

    # ----- 2ª opção: yt-dlp grava o chat num arquivo e a gente vai lendo -----
    def _ytdlp(self):
        from .live import arquivo_cookies

        pasta = os.path.join(config.DADOS, "chat")
        os.makedirs(pasta, exist_ok=True)
        base = os.path.join(pasta, f"chat_{int(time.time())}")
        cookies = arquivo_cookies()
        cmd = ["yt-dlp", "-q", "--no-warnings", "--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", base, self.url]
        if cookies:
            cmd[1:1] = ["--cookies", cookies]
        log.info("lendo o chat (yt-dlp)")
        self.metodo = "yt-dlp"
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        arquivo, pos, comeco = None, 0, time.time()
        try:
            while not self.parar_evt.is_set():
                # durante a live o yt-dlp escreve em "<nome>.live_chat.json.part"; no fim renomeia sem o ".part"
                candidatos = [p for p in glob.glob(base + "*") if "live_chat" in p]
                if candidatos and (arquivo is None or not os.path.exists(arquivo)):
                    novo = max(candidatos, key=os.path.getsize)
                    if arquivo is None:
                        log.info("chat chegando em %s", os.path.basename(novo))
                    arquivo = novo
                if arquivo is None and time.time() - comeco > 90:
                    raise RuntimeError("yt-dlp não criou o arquivo do chat em 90s")
                if arquivo and os.path.exists(arquivo):
                    with open(arquivo, "rb") as f:
                        f.seek(pos)
                        for linha in f:
                            if not linha.endswith(b"\n"):
                                break  # linha ainda sendo escrita
                            pos += len(linha)
                            try:
                                for texto in _textos(json.loads(linha)):
                                    self._recebeu(texto)
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                pass
                if proc.poll() is not None:
                    erro = (proc.stderr.read() or "").strip().splitlines()
                    raise RuntimeError(f"yt-dlp do chat terminou: {erro[-1][:150] if erro else 'sem mensagem'}")
                self.parar_evt.wait(2)
        finally:
            if proc.poll() is None:
                proc.terminate()
            for p in glob.glob(base + "*"):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def run(self):
        falhas = 0
        while not self.parar_evt.is_set():
            usar_ytdlp = falhas % 2 == 0  # alterna: yt-dlp (mais atualizado), chat-downloader, yt-dlp...
            try:
                (self._ytdlp if usar_ytdlp else self._chat_downloader)()
            except Exception as e:  # o chat é um extra: se cair, tenta de novo e o resto continua
                falhas += 1
                log.warning("chat (%s) falhou: %s", "yt-dlp" if usar_ytdlp else "chat-downloader", str(e)[:150])
                self.metodo = "nenhum"
            self.parar_evt.wait(10)
