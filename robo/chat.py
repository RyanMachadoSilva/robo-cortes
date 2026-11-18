"""Lê o chat da live do YouTube em tempo real e passa as mensagens para o detector."""
import logging
import os
import threading

from . import config

log = logging.getLogger("chat")


class LeitorChat(threading.Thread):
    def __init__(self, url, detector, parar_evt):
        super().__init__(daemon=True, name="chat")
        self.url = url
        self.detector = detector
        self.parar_evt = parar_evt
        self.total = 0

    def run(self):
        while not self.parar_evt.is_set():
            try:
                from chat_downloader import ChatDownloader

                cookies = config.COOKIES if os.path.exists(config.COOKIES) else None
                chat = ChatDownloader(cookies=cookies).get_chat(self.url, message_types=["text_message", "paid_message"])
                log.info("lendo o chat")
                for msg in chat:
                    if self.parar_evt.is_set():
                        return
                    self.total += 1
                    self.detector.mensagem(msg.get("message") or "")
            except Exception as e:  # o chat é um extra: se cair, tenta de novo e o resto continua
                log.warning("chat caiu (%s); tentando de novo em 30s", str(e)[:150])
            self.parar_evt.wait(30)
