"""Robô de cortes: espera a live abrir, grava, detecta os melhores momentos e manda os cortes pro WhatsApp."""
import logging
import os
import queue
import shutil
import threading
import time

from . import api, assistente, config, corte, estado, ia
from .chat import LeitorChat
from .detector import Detector
from .live import Bloqueado, Gravador, Ouvinte, checar_live, limpar_segmentos

log = logging.getLogger("robo")


class Editor(threading.Thread):
    """Fila de momentos detectados -> cortes prontos (um de cada vez, para não pesar a VPS)."""

    def __init__(self, live, detector_ref):
        super().__init__(daemon=True, name="editor")
        self.live = live
        self.detector_ref = detector_ref
        self.fila = queue.Queue()
        self.feitos = 0
        self.descartados = 0

    def enfileirar(self, momento, motivo):
        if self.fila.qsize() >= 3:
            log.info("fila cheia, ignorando momento (%s)", motivo)
            return
        if self.feitos >= config.MAX_CORTES_POR_LIVE:
            return
        log.info("⚡ momento detectado: %s", motivo)
        self.fila.put((momento, motivo))

    def run(self):
        while True:
            item = self.fila.get()
            if item is None:
                return
            momento, motivo = item
            # espera os pedaços depois do momento terminarem de gravar
            espera = momento + config.DEPOIS_S + config.SEGMENTO_S + 5 - time.time()
            if espera > 0:
                time.sleep(espera)
            try:
                self.processar(momento, motivo)
            except Exception:
                log.exception("erro ao montar corte")

    def processar(self, momento, motivo):
        pasta = os.path.join(config.PASTA_TMP, str(int(momento)))
        try:
            janela = corte.preparar_janela(momento - config.ANTES_S, momento + config.DEPOIS_S, pasta)
            if not janela or janela[2] < 10:
                log.info("trecho não está mais gravado; pulando")
                return
            lista, desl, dur = janela
            audio = corte.extrair_audio(lista, desl, dur)
            chat = self.detector_ref().textos(momento - 30, momento + config.ATRASO_CHAT_S + 10)
            r = ia.analisar(audio, dur, self.live["titulo"], motivo, chat)

            if r is None:  # IA indisponível: manda o trecho inteiro, sem legenda
                ini, fim, legendas, nota = 0.0, dur, [], None
                titulo, gancho, sobre = f"Momento da live: {self.live['titulo']}"[:70], "", f"(sem IA) {motivo}"
            else:
                nota = int(r.get("nota") or 0)
                if not r.get("vale_corte") or nota < config.NOTA_MINIMA:
                    self.descartados += 1
                    log.info("descartado pela IA (nota %s): %s", nota, r.get("motivo", ""))
                    return
                ini = min(max(float(r.get("inicio") or 0), 0.0), max(dur - 10, 0.0))
                fim = min(max(float(r.get("fim") or dur), ini + 10), dur, ini + 58)
                legendas = []
                for leg in r.get("legendas") or []:
                    try:
                        a, b = float(leg["inicio"]) - ini, float(leg["fim"]) - ini
                    except (KeyError, TypeError, ValueError):
                        continue
                    if b > 0 and a < fim - ini:
                        legendas.append({"inicio": max(a, 0), "fim": min(b, fim - ini), "texto": leg.get("texto", "")})
                titulo = (r.get("titulo") or self.live["titulo"])[:100]
                gancho, sobre = r.get("gancho") or "", r.get("motivo") or motivo

            os.makedirs(config.PASTA_CORTES, exist_ok=True)
            saida = os.path.join(config.PASTA_CORTES, f"corte_{int(momento)}.mp4")
            inicio_render = time.time()
            corte.renderizar(lista, desl + ini, fim - ini, legendas, gancho, saida, pasta)
            log.info("corte renderizado em %.0fs (%.0fs de vídeo)", time.time() - inicio_render, fim - ini)

            canal = config.CANAL_URL.split("/")[-1]
            cid = estado.novo_corte(
                arquivo=saida, titulo=titulo, nota=nota, live=self.live["url"],
                descricao=f"{titulo}\n\nCorte da live do {canal.lstrip('@')}: {self.live['url']}\n#gta6 #shorts #{canal.lstrip('@').lower()}",
            )
            self.feitos += 1
            api.status_live["cortes_na_live"] = self.feitos
            legenda = (
                f"🎬 *Corte #{cid}*{f' (nota {nota}/10)' if nota is not None else ''}\n{titulo}\n_{sobre}_\n\n"
                f"Responde *ok {cid}*, *não {cid}* ou *postei {cid}*"
            )
            if not assistente.video(saida, legenda, cid):
                assistente.texto(f"Corte #{cid} pronto, mas não consegui mandar o vídeo pelo WhatsApp.")
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


def limpar_pendentes_antigos():
    limite = time.time() - config.APAGAR_PENDENTES_H * 3600
    for c in estado.cortes():
        if c["criado"] < limite:
            log.info("apagando corte #%s sem resposta há mais de %sh", c["id"], config.APAGAR_PENDENTES_H)
            estado.remover(c["id"])


def sessao(live):
    log.info("🔴 live aberta: %s", live["titulo"])
    assistente.texto(f"🔴 Live começou: *{live['titulo']}*\nVou gravando e te mando os melhores momentos.")
    api.status_live.update(ao_vivo=True, titulo=live["titulo"], cortes_na_live=0, desde=time.time())

    parar = threading.Event()
    detector_box = {}
    editor = Editor(live, lambda: detector_box["d"])
    detector = Detector(editor.enfileirar)
    detector_box["d"] = detector
    editor.start()
    chat = LeitorChat(live["url"], detector, parar)
    chat.start()
    Ouvinte(detector, parar).start()

    gravador = Gravador(live["url"])
    gravador.iniciar()
    ultima_limpeza = 0.0
    try:
        while True:
            detector.checar()
            if time.time() - ultima_limpeza > 30:
                limpar_segmentos()
                ultima_limpeza = time.time()
            if not gravador.ativo():
                log.info("gravação parou; conferindo se a live acabou")
                time.sleep(15)
                try:
                    ainda = checar_live()
                except Bloqueado:
                    ainda = None
                if ainda and ainda["id"] == live["id"]:
                    gravador.iniciar()
                    continue
                break
            time.sleep(2)
    finally:
        gravador.parar()
        parar.set()
        editor.fila.put(None)
        editor.join(timeout=900)  # termina os cortes que já estavam na fila
        limpar_segmentos(tudo=True)
        api.status_live.update(ao_vivo=False)

    duracao = (time.time() - api.status_live["desde"]) / 3600
    assistente.texto(
        f"⏹️ Live acabou ({duracao:.1f}h). Cortes enviados: {editor.feitos}. "
        f"Descartados pela IA: {editor.descartados}. Mensagens de chat lidas: {chat.total}."
    )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%d/%m %H:%M:%S")
    for pasta in (config.PASTA_SEGMENTOS, config.PASTA_CORTES, config.PASTA_TMP):
        os.makedirs(pasta, exist_ok=True)
    estado.carregar()
    limpar_segmentos(tudo=True)
    shutil.rmtree(config.PASTA_TMP, ignore_errors=True)
    api.iniciar()
    if not os.path.exists(config.COOKIES):
        log.warning("sem cookies em %s: o YouTube pode bloquear o IP da VPS", config.COOKIES)
    if not config.GEMINI_API_KEY:
        log.warning("sem GEMINI_API_KEY: os cortes vão sem legenda e sem filtro da IA")
    log.info("vigiando %s a cada %ss", config.CANAL_URL, config.INTERVALO_CHECAGEM_S)

    ultimo_aviso_bloqueio = 0.0
    while True:
        limpar_pendentes_antigos()
        try:
            live = checar_live()
        except Bloqueado:
            log.error("YouTube bloqueou: pediu login (cookies vencidos ou ausentes)")
            if time.time() - ultimo_aviso_bloqueio > 6 * 3600:
                assistente.texto("⚠️ O YouTube bloqueou o robô de cortes (pediu login). Exporta o cookies.txt de novo e manda pra VPS.")
                ultimo_aviso_bloqueio = time.time()
            live = None
        except Exception:
            log.exception("erro ao checar a live")
            live = None
        if live:
            sessao(live)
        else:
            time.sleep(config.INTERVALO_CHECAGEM_S)


if __name__ == "__main__":
    main()
