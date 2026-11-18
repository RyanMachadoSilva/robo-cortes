"""Detecta momentos bons: pico de mensagens no chat, risadas/"clipa" no chat e pico de volume."""
import re
import statistics
import threading
import time
from collections import deque

from . import config

PALAVRAS = re.compile(
    r"k{4,}|ka{3,}|rs{3,}|hah{2,}|\bclip|\bcorta|caralh|\bmds\b|meu deus|\bnossa+\b|\blol\b|lmao|[😂🤣💀😱]|!{3,}",
    re.I,
)
JANELA_S = 10        # janela usada para medir o chat "agora"
HISTORICO_S = 600    # janela usada para saber o que é "normal" (10 min)


class Detector:
    def __init__(self, ao_detectar, agora=time.time):
        self.ao_detectar = ao_detectar  # função(momento_unix, motivo)
        self.agora = agora
        self.msgs = deque()             # (ts, tem_palavra, texto)
        self.taxas = deque()            # (ts, msgs nos últimos 10s) amostradas a cada checagem
        self.volumes = deque()          # (ts, db)
        self.ultimo_corte = 0.0
        self.trava = threading.Lock()

    # ----- entradas -----
    def mensagem(self, texto, ts=None):
        ts = ts or self.agora()
        with self.trava:
            self.msgs.append((ts, bool(PALAVRAS.search(texto or "")), (texto or "")[:120]))

    def audio(self, ts, db):
        with self.trava:
            self.volumes.append((ts, db))

    def textos(self, ini, fim, limite=60):
        """Mensagens do chat entre ini e fim (para a IA entender o contexto)."""
        with self.trava:
            return [m[2] for m in self.msgs if ini <= m[0] <= fim and m[2]][-limite:]

    # ----- avaliação (chamar a cada ~2s) -----
    def checar(self):
        agora = self.agora()
        with self.trava:
            while self.msgs and self.msgs[0][0] < agora - HISTORICO_S:
                self.msgs.popleft()
            while self.volumes and self.volumes[0][0] < agora - HISTORICO_S:
                self.volumes.popleft()
            while self.taxas and self.taxas[0][0] < agora - HISTORICO_S:
                self.taxas.popleft()

            recentes = [m for m in self.msgs if m[0] >= agora - JANELA_S]
            n = len(recentes)
            palavras = sum(1 for m in recentes if m[1])
            normal = statistics.median([t for _, t in self.taxas]) if len(self.taxas) >= 15 else None
            self.taxas.append((agora, n))

            # Volume: compara os últimos segundos com o normal (o áudio chega com ~10-20s de atraso)
            vols = [db for _, db in self.volumes]
            vol_normal = statistics.median(vols) if len(vols) >= 60 else None
            vol_recente = [db for ts, db in self.volumes if ts >= agora - 40]
            vol_pico = max(vol_recente) if vol_recente else None

        motivos = []
        mult = n / max(normal, 1.0) if normal is not None else 0
        if normal is not None and n >= config.CHAT_MIN_MSGS and mult >= config.CHAT_MULTIPLICADOR:
            motivos.append(f"chat {mult:.1f}x mais rápido")
        if palavras >= config.PALAVRAS_MIN:
            motivos.append(f"{palavras} reações no chat")
        audio_alto = vol_normal is not None and vol_pico is not None and vol_pico - vol_normal >= config.AUDIO_PICO_DB
        chat_mudo = not any(m[0] >= agora - 120 for m in list(self.msgs))  # chat não chegou nos últimos 2 min
        if audio_alto and (mult >= 1.5 or palavras >= 2 or chat_mudo):
            motivos.append(f"volume +{vol_pico - vol_normal:.0f}dB" + (" (sem chat)" if chat_mudo else ""))

        if not motivos or agora - self.ultimo_corte < config.MIN_ENTRE_CORTES_S:
            return None
        self.ultimo_corte = agora
        momento = agora - config.ATRASO_CHAT_S
        motivo = ", ".join(motivos)
        self.ao_detectar(momento, motivo)
        return motivo
