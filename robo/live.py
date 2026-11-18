"""Detecta se o canal está ao vivo e grava a live em pedaços de poucos segundos."""
import glob
import logging
import os
import re
import shlex
import subprocess
import threading
import time

from . import config

log = logging.getLogger("live")


class Bloqueado(Exception):
    """O YouTube pediu login ("confirme que você não é um robô")."""


def _opcoes_ytdlp():
    op = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    if os.path.exists(config.COOKIES):
        op["cookiefile"] = config.COOKIES
    return op


def checar_live():
    """Retorna {'id','titulo','url'} se o canal está ao vivo agora, senão None."""
    import yt_dlp

    url = config.CANAL_URL + "/live"
    try:
        with yt_dlp.YoutubeDL(_opcoes_ytdlp()) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if re.search(r"confirm you.?re not a bot|Sign in to confirm", msg, re.I):
            raise Bloqueado(msg) from e
        if not re.search(r"not currently live|will begin|Premieres in|is offline|does not exist", msg, re.I):
            log.warning("yt-dlp: %s", msg.splitlines()[0][:200])
        return None
    if not info or info.get("_type") == "playlist":
        return None
    if info.get("is_live") or info.get("live_status") == "is_live":
        return {"id": info["id"], "titulo": info.get("title") or "", "url": info.get("webpage_url") or url}
    return None


class Gravador:
    """yt-dlp | ffmpeg -> /dados/segmentos/<horario-unix>.ts (um arquivo a cada SEGMENTO_S)."""

    def __init__(self, url):
        self.url = url
        self.proc = None

    def iniciar(self):
        os.makedirs(config.PASTA_SEGMENTOS, exist_ok=True)
        cookies = f"--cookies {shlex.quote(config.COOKIES)}" if os.path.exists(config.COOKIES) else ""
        saida = shlex.quote(os.path.join(config.PASTA_SEGMENTOS, "%s.ts"))
        cmd = (
            f"set -o pipefail; "
            f"nice -n 5 yt-dlp -q --no-warnings --no-part {cookies} -f {shlex.quote(config.QUALIDADE)} "
            f"-o - {shlex.quote(self.url)} | "
            f"nice -n 5 ffmpeg -hide_banner -loglevel error -i pipe:0 -map 0:v:0 -map 0:a:0? -c copy "
            f"-f segment -segment_time {config.SEGMENTO_S} -reset_timestamps 1 -strftime 1 {saida}"
        )
        log.info("gravando %s", self.url)
        self.proc = subprocess.Popen(["bash", "-c", cmd])

    def ativo(self):
        return self.proc is not None and self.proc.poll() is None

    def parar(self):
        if self.ativo():
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------- Pedaços gravados ----------
def segmentos():
    """Lista [(inicio_unix, caminho)] dos pedaços já fechados (o último, ainda sendo gravado, fica de fora)."""
    itens = []
    for p in glob.glob(os.path.join(config.PASTA_SEGMENTOS, "*.ts")):
        nome = os.path.basename(p)[:-3]
        if nome.isdigit():
            itens.append((int(nome), p))
    itens.sort()
    return itens[:-1]


def segmentos_entre(ini, fim):
    """Pedaços que cobrem o intervalo [ini, fim] (horário unix)."""
    return [(t, p) for t, p in segmentos() if t + config.SEGMENTO_S > ini and t < fim]


def limpar_segmentos(tudo=False):
    limite = time.time() - config.BUFFER_MIN * 60
    for p in glob.glob(os.path.join(config.PASTA_SEGMENTOS, "*.ts")):
        nome = os.path.basename(p)[:-3]
        if tudo or (nome.isdigit() and int(nome) < limite):
            try:
                os.remove(p)
            except FileNotFoundError:
                pass


# ---------- Volume do áudio (1 valor por segundo) ----------
_RE_RMS = re.compile(r"pts_time:([\d.]+).*?RMS_level=(-?[\d.]+|-inf)", re.S)


def volume_por_segundo(caminho):
    """Retorna [(segundo_relativo, rms_db)] de um pedaço gravado."""
    cmd = [
        "nice", "-n", "10", "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", caminho, "-vn",
        "-af", "aresample=8000,asetnsamples=8000,astats=metadata=1:reset=1,"
        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        return []
    valores = []
    for bloco in out.split("frame:")[1:]:
        m = _RE_RMS.search(bloco)
        if m and m.group(2) != "-inf":
            valores.append((float(m.group(1)), float(m.group(2))))
    return valores


class Ouvinte(threading.Thread):
    """Mede o volume de cada pedaço novo e entrega ao detector."""

    def __init__(self, detector, parar_evt):
        super().__init__(daemon=True, name="ouvinte")
        self.detector = detector
        self.parar_evt = parar_evt
        self.vistos = set()

    def run(self):
        while not self.parar_evt.is_set():
            for t, p in segmentos()[-3:]:
                if t in self.vistos:
                    continue
                self.vistos.add(t)
                for seg, db in volume_por_segundo(p):
                    self.detector.audio(t + seg, db)
            if len(self.vistos) > 500:
                self.vistos = set(sorted(self.vistos)[-100:])
            self.parar_evt.wait(3)
