"""Monta o corte: junta os pedaços gravados, recorta, deixa vertical, põe legenda e o gancho no topo."""
import logging
import os
import subprocess
import textwrap

from . import config
from .live import segmentos_entre

log = logging.getLogger("corte")

FONTE = os.environ.get("FONTE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def preparar_janela(ini, fim, pasta):
    """Cria a lista de pedaços que cobre [ini, fim]. Retorna (lista_txt, deslocamento_s, duracao_s) ou None."""
    segs = segmentos_entre(ini, fim)
    if not segs:
        return None
    os.makedirs(pasta, exist_ok=True)
    lista = os.path.join(pasta, "lista.txt")
    with open(lista, "w") as f:
        for _, p in segs:
            f.write(f"file '{p}'\n")
    comeco = max(ini, segs[0][0])
    final = min(fim, segs[-1][0] + config.SEGMENTO_S)
    return lista, comeco - segs[0][0], max(0.0, final - comeco)


def extrair_audio(lista, deslocamento, duracao):
    """Áudio mono leve (mp3) da janela, para mandar para a IA."""
    cmd = [
        "nice", "-n", "10", "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", lista, "-ss", f"{deslocamento:.2f}", "-t", f"{duracao:.2f}",
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "mp3", "pipe:1",
    ]
    return subprocess.run(cmd, capture_output=True, timeout=120, check=True).stdout


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
            f.write(f"{n}\n{_tempo_srt(ini)} --> {_tempo_srt(fim)}\n{texto.upper()}\n\n")
    return n


def renderizar(lista, deslocamento, duracao, legendas, gancho, saida, pasta):
    """Gera o vídeo vertical final (LARGURA x ALTURA)."""
    W, H = config.LARGURA, config.ALTURA
    fg_h = int(W * 3 / 4)              # gameplay em 4:3 (corta um pouco das laterais, fica maior na tela)
    fg_y = int(H * 0.22)               # posição do gameplay
    filtros = [
        "[0:v]setpts=PTS-STARTPTS,split=2[a][b]",
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:4,eq=brightness=-0.15[bg]",
        f"[b]crop=ih*4/3:ih,scale={W}:{fg_h}[fg]",
        f"[bg][fg]overlay=0:{fg_y}[v0]",
    ]
    atual = "v0"

    srt = os.path.join(pasta, "legenda.srt")
    if legendas and escrever_srt(legendas, srt):
        # Estilo em unidades do libass (altura de referência 288): texto grande, branco com contorno preto
        margem = int((H - (fg_y + fg_h) - H * 0.08) / H * 288)
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
        filtros.append(
            f"[{atual}]drawtext=fontfile={FONTE}:textfile={txt}:fontsize={tam}:fontcolor=white:"
            f"borderw=4:bordercolor=black:line_spacing=8:x=(w-text_w)/2:y={int(H * 0.08)}[v2]"
        )
        atual = "v2"

    cmd = [
        "nice", "-n", "15", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{deslocamento:.2f}", "-f", "concat", "-safe", "0", "-i", lista, "-t", f"{duracao:.2f}",
        "-filter_complex", ";".join(filtros), "-map", f"[{atual}]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(config.CRF), "-threads", "1",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida,
    ]
    subprocess.run(cmd, check=True, timeout=900, capture_output=True)
    return saida
