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

RENDER = threading.Lock()  # monta um corte por vez, mesmo com 2 lives (a VPS tem 1 vCPU)


class Editor(threading.Thread):
    """Fila de momentos detectados -> cortes prontos (um de cada vez, para não pesar a VPS)."""

    def __init__(self, live, detector_ref):
        super().__init__(daemon=True, name=f"editor-{live['nome']}")
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
        log.info("⚡ [%s] momento detectado: %s", self.live["nome"], motivo)
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
        pasta = os.path.join(config.PASTA_TMP, f"{self.live['nome']}_{int(momento)}")
        try:
            janela = corte.preparar_janela(momento - config.ANTES_S, momento + config.DEPOIS_S, pasta, self.live["pasta"])
            if not janela or janela[2] < 10:
                log.info("trecho não está mais gravado; pulando")
                return
            lista, desl, dur = janela
            audio = corte.extrair_audio(lista, desl, dur)
            chat = self.detector_ref().textos(momento - 30, momento + config.ATRASO_CHAT_S + 10)
            idioma = self.live.get("idioma", "pt")
            r = ia.analisar(audio, dur, self.live["titulo"], motivo, chat, self.live["nome"], idioma)

            titulo_en = gancho_en = ""
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
                        legendas.append({"inicio": max(a, 0), "fim": min(b, fim - ini),
                                         "texto": leg.get("texto", ""), "texto_en": leg.get("texto_en", "")})
                titulo = (r.get("titulo") or self.live["titulo"])[:100]
                gancho, sobre = r.get("gancho") or "", r.get("motivo") or motivo
                titulo_en, gancho_en = (r.get("titulo_en") or "")[:100], r.get("gancho_en") or ""

            os.makedirs(config.PASTA_CORTES, exist_ok=True)
            saida = os.path.join(config.PASTA_CORTES, f"corte_{self.live['nome']}_{int(momento)}.mp4")
            tem_en = idioma == "pt" and any(l.get("texto_en") for l in legendas)
            leg_pt = [{**l, "texto_extra": l.get("texto_en") if config.VERSAO_EN == "junto" else ""} for l in legendas]
            saida_en = None
            with RENDER:
                inicio_render = time.time()
                corte.renderizar(lista, desl + ini, fim - ini, leg_pt, gancho, saida, pasta)
                log.info("corte renderizado em %.0fs (%.0fs de vídeo)", time.time() - inicio_render, fim - ini)
                if config.VERSAO_EN == "separado" and tem_en:
                    saida_en = saida.replace(".mp4", "_en.mp4")
                    leg_en = [{**l, "texto": l.get("texto_en") or ""} for l in legendas]
                    corte.renderizar(lista, desl + ini, fim - ini, leg_en, gancho_en or gancho, saida_en, pasta)
                    log.info("versão em inglês pronta")

            nome_canal = self.live["nome"]
            cid = estado.novo_corte(
                arquivo=saida, titulo=titulo, nota=nota, live=self.live["url"],
                descricao=(f"{titulo}\n\nClip from {nome_canal}'s live stream: {self.live['url']}\n#gta6 #shorts #{nome_canal.lower()}"
                           if idioma == "en" else
                           f"{titulo}\n\nCorte da live do {nome_canal}: {self.live['url']}\n#gta6 #shorts #{nome_canal.lower()}"),
                arquivo_en=saida_en, titulo_en=titulo_en if (saida_en or tem_en) else "",
                descricao_en=(f"{titulo_en}\n\nClip from {nome_canal}'s live stream: {self.live['url']}\n#gta6 #shorts #gaming"
                              if titulo_en and (saida_en or tem_en) else ""),
            )
            self.feitos += 1
            if nome_canal in api.status_lives:
                api.status_lives[nome_canal]["cortes"] = self.feitos
            legenda = (
                f"🎬 *Corte #{cid}* · {nome_canal}{' 🇺🇸' if idioma == 'en' else ''}{f' (nota {nota}/10)' if nota is not None else ''}\n{titulo}\n_{sobre}_\n\n"
                f"Responde *ok {cid}*, *não {cid}* ou *postei {cid}*"
            )
            if not assistente.video(saida, legenda, cid):
                assistente.texto(f"Corte #{cid} pronto, mas não consegui mandar o vídeo pelo WhatsApp.")
            if saida_en:
                assistente.video(saida_en, f"🇺🇸 *Corte #{cid}, versão em inglês*\n{titulo_en}", cid)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


def limpar_pendentes_antigos():
    limite = time.time() - config.APAGAR_PENDENTES_H * 3600
    for c in estado.cortes():
        if c["criado"] < limite:
            log.info("apagando corte #%s sem resposta há mais de %sh", c["id"], config.APAGAR_PENDENTES_H)
            estado.remover(c["id"])


def sessao(live):
    nome = live["nome"]
    log.info("🔴 [%s] live aberta: %s", nome, live["titulo"])
    assistente.texto(f"🔴 *{nome}* abriu live: {live['titulo']}\nVou gravando e te mando os melhores momentos.")
    api.status_lives[nome] = {"titulo": live["titulo"], "cortes": 0, "desde": time.time()}

    parar = threading.Event()
    detector_box = {}
    editor = Editor(live, lambda: detector_box["d"])
    detector = Detector(editor.enfileirar)
    detector_box["d"] = detector
    editor.start()
    chat = LeitorChat(live["url"], detector, parar)
    chat.start()
    Ouvinte(detector, parar, live["pasta"]).start()

    gravador = Gravador(live["url"], live["pasta"])
    gravador.iniciar()
    ultima_limpeza = 0.0
    st = api.status_lives[nome]
    try:
        while True:
            detector.checar()
            if time.time() - ultima_limpeza > 30:
                limpar_segmentos(live["pasta"])
                ultima_limpeza = time.time()
            if not gravador.ativo():
                log.info("[%s] gravação parou; conferindo se a live acabou", nome)
                time.sleep(15)
                try:
                    ainda = checar_live(live["canal"])
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
        limpar_segmentos(live["pasta"], tudo=True)
        api.status_lives.pop(nome, None)

    duracao = (time.time() - st["desde"]) / 3600
    assistente.texto(
        f"⏹️ Live do *{nome}* acabou ({duracao:.1f}h). Cortes enviados: {editor.feitos}. "
        f"Descartados pela IA: {editor.descartados}. Mensagens de chat lidas: {chat.total}."
    )


def _rodar_sessao(live, ativas):
    try:
        sessao(live)
    except Exception:
        log.exception("[%s] erro na sessão", live["nome"])
    finally:
        ativas.pop(live["canal"], None)


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
    log.info("vigiando %s a cada %ss (até %s lives ao mesmo tempo)", ", ".join(config.CANAIS), config.INTERVALO_CHECAGEM_S, config.MAX_LIVES)

    ativas = {}  # canal -> thread da sessão
    ignoradas = set()  # lives fora do filtro SO_TITULO_COM (para não logar toda hora)
    ultimo_aviso_bloqueio = 0.0
    while True:
        limpar_pendentes_antigos()
        for canal in config.CANAIS:
            if canal in ativas:
                continue
            if len(ativas) >= config.MAX_LIVES:
                break
            try:
                live = checar_live(canal)
            except Bloqueado:
                log.error("YouTube bloqueou: pediu login (cookies vencidos ou ausentes)")
                if time.time() - ultimo_aviso_bloqueio > 6 * 3600:
                    assistente.texto("⚠️ O YouTube bloqueou o robô de cortes (pediu login). Exporta o cookies.txt de novo e manda pra VPS.")
                    ultimo_aviso_bloqueio = time.time()
                break
            except Exception:
                log.exception("erro ao checar %s", canal)
                continue
            if live and config.SO_TITULO_COM and not any(p in live["titulo"].lower() for p in config.SO_TITULO_COM):
                if live["id"] not in ignoradas:
                    ignoradas.add(live["id"])
                    log.info("[%s] live sem %s no título, ignorando: %s", live["nome"], "/".join(config.SO_TITULO_COM), live["titulo"])
                continue
            if live:
                t = threading.Thread(target=_rodar_sessao, args=(live, ativas), daemon=True, name=f"sessao-{live['nome']}")
                ativas[canal] = t
                t.start()
        time.sleep(config.INTERVALO_CHECAGEM_S)

if __name__ == "__main__":
    main()
