"""Configurações lidas do .env (todas com valor padrão razoável)."""
import os


def _int(nome, padrao):
    try:
        return int(os.environ.get(nome, padrao))
    except ValueError:
        return padrao


def _float(nome, padrao):
    try:
        return float(os.environ.get(nome, padrao))
    except ValueError:
        return padrao


# Canais a vigiar, com o idioma de cada um: CANAIS=@gameplayrj:pt,@ishowspeed:en
# (aceita @nome ou o link do canal; sem ":idioma" vale pt)
def _canal(c):
    c = c.strip().rstrip("/")
    return c if c.startswith("http") else "https://www.youtube.com/" + (c if c.startswith("@") else "@" + c)


CANAIS, IDIOMAS = [], {}
for _item in (os.environ.get("CANAIS") or os.environ.get("CANAL_URL") or "@gameplayrj").split(","):
    if not _item.strip():
        continue
    _nome, _, _idioma = _item.strip().rpartition(":") if _item.strip().rsplit(":", 1)[-1].lower() in ("pt", "en") else (_item, "", "pt")
    _url = _canal(_nome)
    CANAIS.append(_url)
    IDIOMAS[_url] = (_idioma or "pt").lower()

# Só grava lives cujo título tenha uma destas palavras (vazio = grava qualquer live). Ex.: SO_TITULO_COM=gta
SO_TITULO_COM = [p.strip().lower() for p in os.environ.get("SO_TITULO_COM", "").split(",") if p.strip()]
CANAL_URL = CANAIS[0]  # compatibilidade
MAX_LIVES = _int("MAX_LIVES", 2)  # quantas lives gravar ao mesmo tempo
COOKIES = os.environ.get("COOKIES", "/dados/cookies.txt")
QUALIDADE = os.environ.get("QUALIDADE", "best[height<=720]/best")
INTERVALO_CHECAGEM_S = _int("INTERVALO_CHECAGEM_S", 90)  # de quanto em quanto tempo checa se abriu live

# Pastas
DADOS = os.environ.get("DADOS", "/dados")
PASTA_SEGMENTOS = os.path.join(DADOS, "segmentos")
PASTA_CORTES = os.path.join(DADOS, "cortes")
PASTA_TMP = os.path.join(DADOS, "tmp")
ARQUIVO_ESTADO = os.path.join(DADOS, "estado.json")

# Gravação
SEGMENTO_S = _int("SEGMENTO_S", 10)       # tamanho de cada pedaço gravado
BUFFER_MIN = _int("BUFFER_MIN", 15)       # minutos de live guardados no disco (o resto é apagado)

# Corte
ANTES_S = _int("ANTES_S", 45)             # segundos antes do pico que entram na janela analisada
DEPOIS_S = _int("DEPOIS_S", 20)           # segundos depois do pico
ATRASO_CHAT_S = _int("ATRASO_CHAT_S", 8)  # o chat reage alguns segundos depois do momento
MIN_ENTRE_CORTES_S = _int("MIN_ENTRE_CORTES_S", 600)  # no máximo 1 corte a cada 10 min
MAX_CORTES_POR_LIVE = _int("MAX_CORTES_POR_LIVE", 60)
NOTA_MINIMA = _int("NOTA_MINIMA", 6)      # nota (0-10) mínima dada pela IA para te mandar o corte
LARGURA = _int("LARGURA", 720)            # vídeo final vertical: LARGURA x ALTURA
ALTURA = _int("ALTURA", 1280)
CRF = _int("CRF", 23)
APAGAR_PENDENTES_H = _int("APAGAR_PENDENTES_H", 24)

# Detector de picos
CHAT_MULTIPLICADOR = _float("CHAT_MULTIPLICADOR", 3.0)  # chat X vezes mais rápido que o normal
CHAT_MIN_MSGS = _int("CHAT_MIN_MSGS", 10)               # mínimo de mensagens em 10s para contar
AUDIO_PICO_DB = _float("AUDIO_PICO_DB", 10.0)           # volume X dB acima do normal
PALAVRAS_MIN = _int("PALAVRAS_MIN", 5)                  # mensagens com "kkkk", "clipa"... em 10s

# Versão em inglês: "separado" (um vídeo PT e outro EN), "junto" (as duas legendas no mesmo vídeo) ou "nao"
VERSAO_EN = os.environ.get("VERSAO_EN", "nao").strip().lower()  # só vale para canais em português

# IA (Gemini)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODELO = os.environ.get("MODELO", "gemini-3.5-flash-lite")
MODELO_RESERVA = os.environ.get("MODELO_RESERVA", "gemini-3.5-flash-lite")

# Integração com o assistente do WhatsApp
ASSISTENTE_URL = os.environ.get("ASSISTENTE_URL", "http://assistente:3100").rstrip("/")
TOKEN_ROBO = os.environ.get("TOKEN_ROBO", "")
DESTINO = os.environ.get("DESTINO", "Ryan")  # nome (em USUARIOS do assistente) que recebe os cortes
PORTA_API = _int("PORTA_API", 8000)
