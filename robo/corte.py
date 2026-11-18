"""Monta o corte: junta os pedaços gravados, recorta, deixa vertical, põe legenda e o gancho no topo."""
import logging
import os
import re
import subprocess
import textwrap

from . import config
from .live import segmentos_entre

log = logging.getLogger("corte")

FONTE = os.environ.get("FONTE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def preparar_janela(ini, fim, pasta, pasta_segmentos):
    """Cria a lista de pedaços que cobre [ini, fim]. Retorna (lista_txt, deslocamento_s, duracao_s) ou None."""
    segs = segmentos_entre(ini, fim, pasta_segmentos)
    if not segs:
        return None
    os.makedirs(pasta, exist_ok=True)
    lista = os.path.join(pasta, "lista.txt")
    with open(lista, "w") as f:
        for _, p in segs:
            f.write(f"file '{p}'\n")
    comeco = max(ini, segs[0][0])
    final = min(fim, segs[-1][0] + config.SEGMENTO_S)
    return lista, comeco - segs[0][0], max(0.0, final - comeco), comeco


def extrair_audio(lista, deslocamento, duracao):
    """Áudio mono leve (mp3) da janela, para mandar para a IA."""
    cmd = [
        "nice", "-n", "10", "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", lista, "-ss", f"{deslocamento:.2f}", "-t", f"{duracao:.2f}",
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "mp3", "pipe:1",
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg (áudio): " + r.stderr.decode(errors="ignore").strip()[-300:])
    return r.stdout


def respiros(audio_mp3):
    """Momentos (em s, relativos ao áudio) em que o volume cai SILENCIO_DB abaixo da média por SILENCIO_MIN_S."""
    def ffmpeg(filtro):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", "pipe:0", "-af", filtro, "-f", "null", "-"],
                           input=audio_mp3, capture_output=True, timeout=60)
        return r.stderr.decode(errors="ignore")

    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", ffmpeg("volumedetect"))
    if not m:
        return []
    limite = float(m.group(1)) - config.SILENCIO_DB
    saida = ffmpeg(f"silencedetect=noise={limite:.1f}dB:d={config.SILENCIO_MIN_S}")
    return [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", saida)]


def escolher_fim(audio_mp3, pico, ini, dur, fim_ia=None):
    """Fim do corte: primeiro respiro do streamer pelo menos MIN_DEPOIS_PICO_S depois do pico."""
    minimo = pico + config.MIN_DEPOIS_PICO_S
    maximo = min(dur, ini + config.DURACAO_MAX_S)
    for t in respiros(audio_mp3):
        if minimo <= t <= maximo:
            return t + 0.3, "respiro"
    if fim_ia and minimo <= fim_ia <= maximo:
        return fim_ia, "IA"
    return min(maximo, pico + config.DEPOIS_S - 5), "limite"


def _tempo_srt(s):
    s = max(0.0, s)
    h, resto = divmod(int(s * 1000), 3_600_000)
    m, resto = divmod(resto, 60_000)
    seg, ms = divmod(resto, 1000)
    return f"{h:02d}:{m:02d}:{seg:02d},{ms:03d}"


def escrever_srt(legendas, caminho):
    """legendas: [{'inicio','fim','texto'}] já relativas ao começo do corte."""
    n = 0
    with open(caminho, "w", encoding="utf-8") as f:
        for leg in legendas:
            try:
                ini, fim, texto = float(leg["inicio"]), float(leg["fim"]), str(leg["texto"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not texto or fim <= ini:
                continue
            n += 1
            f.write(f"{n}\n{_tempo_srt(ini)} --> {_tempo_srt(fim)}\n{texto.upper()}\n")
            extra = str(leg.get("texto_extra") or "").strip()
            if extra:  # segunda linha (ex.: inglês no modo "junto"), menor e amarela
                f.write(f'<font color="#FFE14D" size="13">{extra.upper()}</font>\n')
            f.write("\n")
    return n


def extrair_quadro(lista, deslocamento):
    """Foto (JPEG, 640px) de um instante do trecho, para a IA achar a webcam."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(deslocamento, 0):.2f}", "-f", "concat",
           "-safe", "0", "-i", lista, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", "-f", "image2", "pipe:1"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    return r.stdout if r.returncode == 0 and r.stdout else None


def dimensoes(lista):
    """(largura, altura) do vídeo gravado."""
    primeiro = open(lista).readline().split("'")[1]
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", primeiro], capture_output=True, text=True, timeout=30)
    try:
        w, h = r.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return 1280, 720


def caixa_camera(caixa, iw, ih):
    """Converte a caixa da IA ([ymin, xmin, ymax, xmax] de 0 a 1000) em pixels (x, y, w, h), ou None se não fizer sentido."""
    try:
        y0, x0, y1, x1 = [float(v) for v in caixa]
    except (TypeError, ValueError):
        return None
    if max(y0, x0, y1, x1) <= 1.0:  # veio em fração 0-1
        y0, x0, y1, x1 = y0 * 1000, x0 * 1000, y1 * 1000, x1 * 1000
    y0, y1 = sorted((max(0, min(1000, y0)), max(0, min(1000, y1))))
    x0, x1 = sorted((max(0, min(1000, x0)), max(0, min(1000, x1))))
    bw, bh = (x1 - x0) / 1000, (y1 - y0) / 1000
    if not (0.08 <= bw <= 0.7 and 0.08 <= bh <= 0.7):  # pequena demais ou é a tela toda
        return None
    # entra 2% para dentro, tirando a borda/moldura da webcam
    mx, my = bw * 0.02, bh * 0.02
    x, y = (x0 / 1000 + mx) * iw, (y0 / 1000 + my) * ih
    w, h = (bw - 2 * mx) * iw, (bh - 2 * my) * ih
    aspecto = w / h
    if not (0.5 <= aspecto <= 2.5):
        return None
    par = lambda v: max(2, int(v) // 2 * 2)
    return par(x), par(y), par(w), par(h)


def renderizar(lista, deslocamento, duracao, legendas, gancho, saida, pasta, camera=None):
    """Gera o vídeo vertical final (LARGURA x ALTURA).

    camera=(x, y, w, h) em pixels: tela dividida (webcam em cima, gameplay embaixo).
    Sem camera: o vídeo inteiro no meio, com o fundo desfocado (nada é cortado).
    """
    W, H = config.LARGURA, config.ALTURA
    if camera:
        cx, cy, cw, ch = camera
        cam_h = int(W * ch / cw) // 2 * 2
        cam_h = max(int(H * 0.28) // 2 * 2, min(cam_h, int(H * 0.45) // 2 * 2))
        jogo_h = H - cam_h
        filtros = [
            "[0:v]setpts=PTS-STARTPTS,split=2[a][b]",
            # webcam: recorta e preenche a faixa de cima (corta um pouco se o formato não bater)
            f"[a]crop={cw}:{ch}:{cx}:{cy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h}[cam]",
            # gameplay: o centro da tela, preenchendo a faixa de baixo
            f"[b]scale=-2:{jogo_h},crop={W}:{jogo_h}[jogo]",
            "[cam][jogo]vstack[v0]",
        ]
        topo_texto = cam_h          # o gancho fica logo abaixo da câmera, no começo do jogo
        base_livre = 0.16 * H       # legenda perto do rodapé
    else:
        fg_h = int(W * 9 / 16) // 2 * 2
        fg_y = (H - fg_h) // 2
        filtros = [
            "[0:v]setpts=PTS-STARTPTS,split=2[a][b]",
            f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:4,eq=brightness=-0.15[bg]",
            f"[b]scale={W}:{fg_h}[fg]",
            f"[bg][fg]overlay=0:{fg_y}[v0]",
        ]
        topo_texto = None
        base_livre = H - (fg_y + fg_h) - H * 0.10
    atual = "v0"

    srt = os.path.join(pasta, "legenda.srt")
    if legendas and escrever_srt(legendas, srt):
        # Estilo em unidades do libass (altura de referência 288): texto grande, branco com contorno preto
        margem = int(base_livre / H * 288)
        estilo = (
            "FontName=DejaVu Sans,Bold=1,FontSize=17,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"BorderStyle=1,Outline=2.5,Shadow=0,Alignment=2,MarginV={max(margem, 10)}"
        )
        filtros.append(f"[{atual}]subtitles={srt}:force_style='{estilo}'[v1]")
        atual = "v1"

    gancho = (gancho or "").strip()
    if gancho:
        txt = os.path.join(pasta, "gancho.txt")
        with open(txt, "w", encoding="utf-8") as f:
            f.write("\n".join(textwrap.wrap(gancho.upper(), 18)[:2]))
        tam = int(W * 0.075)
        y_texto = str(topo_texto + int(H * 0.02)) if topo_texto else str(int(H * 0.08))  # nunca em cima do rosto
        filtros.append(
            f"[{atual}]drawtext=fontfile={FONTE}:textfile={txt}:fontsize={tam}:fontcolor=white:"
            f"borderw=4:bordercolor=black:line_spacing=8:x=(w-text_w)/2:y={y_texto}[v2]"
        )
        atual = "v2"

    cmd = [
        "nice", "-n", "15", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{deslocamento:.2f}", "-f", "concat", "-safe", "0", "-i", lista, "-t", f"{duracao:.2f}",
        "-filter_complex", ";".join(filtros), "-map", f"[{atual}]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(config.CRF), "-threads", "1",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida,
    ]
    r = subprocess.run(cmd, timeout=900, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg (vídeo): " + r.stderr.decode(errors="ignore").strip()[-300:])
    return saida
