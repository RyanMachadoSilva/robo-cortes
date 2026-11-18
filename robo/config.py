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


# Canais a vigiar, com o idioma de cada um: CANAIS=@gameplayrj:pt,@ishowspeed:en+pt
# "en+pt" = corte principal em inglês + uma versão extra com legenda em português.
# (aceita @nome ou o link do canal; sem ":idioma" vale pt)
def _canal(c):
    c = c.strip().rstrip("/")
    return c if c.startswith("http") else "https://www.youtube.com/" + (c if c.startswith("@") else "@" + c)


VERSAO_EN = os.environ.get("VERSAO_EN", "nao").strip().lower()  # só vale para canais ":pt" sem "+en"

CANAIS, IDIOMAS, EXTRAS = [], {}, {}
for _item in (os.environ.get("CANAIS") or os.environ.get("CANAL_URL") or "@gameplayrj").split(","):
    _item = _item.strip()
    if not _item:
        continue
    _fim = _item.rsplit(":", 1)[-1].lower()
    if all(p in ("pt", "en") for p in _fim.split("+")):
        _nome, _idiomas = _item.rsplit(":", 1)[0], _fim.split("+")
    else:
        _nome, _idiomas = _item, ["pt"]
    _url = _canal(_nome)
    CANAIS.append(_url)
    IDIOMAS[_url] = _idiomas[0]
    _extra = _idiomas[1] if len(_idiomas) > 1 and _idiomas[1] != _idiomas[0] else None
    if _extra is None and _idiomas[0] == "pt" and VERSAO_EN in ("separado", "junto"):
        _extra = "en"
    EXTRAS[_url] = _extra

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
ANTES_S = _int("ANTES_S", 40)             # segundos antes do pico que a IA ouve (contexto)
DEPOIS_S = _int("DEPOIS_S", 35)           # segundos depois do pico gravados para achar o fim
ATRASO_CHAT_S = _int("ATRASO_CHAT_S", 8)  # (só para o modo sem chat: o volume chega antes do chat)
INICIO_ANTES_PICO_S = _float("INICIO_ANTES_PICO_S", 5)  # o corte começa X s antes do pico do chat
MIN_DEPOIS_PICO_S = _float("MIN_DEPOIS_PICO_S", 6)      # o fim só pode vir X s depois do pico
SILENCIO_DB = _float("SILENCIO_DB", 10)                 # "respiro" = X dB abaixo do volume médio do trecho
SILENCIO_MIN_S = _float("SILENCIO_MIN_S", 0.5)          # duração mínima do respiro
DURACAO_MAX_S = _float("DURACAO_MAX_S", 58)
MIN_ENTRE_CORTES_S = _int("MIN_ENTRE_CORTES_S", 600)  # no máximo 1 corte a cada 10 min
MAX_CORTES_POR_LIVE = _int("MAX_CORTES_POR_LIVE", 60)
NOTA_MINIMA = _int("NOTA_MINIMA", 6)      # nota (0-10) mínima dada pela IA para te mandar o corte
LARGURA = _int("LARGURA", 720)            # vídeo final vertical: LARGURA x ALTURA
ALTURA = _int("ALTURA", 1280)
CRF = _int("CRF", 23)
LEGENDA_TAMANHO = _float("LEGENDA_TAMANHO", 14)  # tamanho da legenda (era 17)
MOLDURA_ALTURA = _float("MOLDURA_ALTURA", 0.065)  # barra do topo (fração da altura; 0 = sem moldura)
ZOOM_OUT_JOGO = _float("ZOOM_OUT_JOGO", 0.15)     # quanto o jogo encolhe na tela dividida (0.15 = 15%)
LEGENDA_ALTURA = _float("LEGENDA_ALTURA", 0.11)  # distância da legenda até o rodapé (fração da altura)
APAGAR_PENDENTES_H = _int("APAGAR_PENDENTES_H", 24)

# Detector de picos
CHAT_MULTIPLICADOR = _float("CHAT_MULTIPLICADOR", 3.0)  # chat X vezes mais rápido que o normal
CHAT_MIN_MSGS = _int("CHAT_MIN_MSGS", 10)               # mínimo de mensagens em 10s para contar
AUDIO_PICO_DB = _float("AUDIO_PICO_DB", 10.0)           # volume X dB acima do normal
PALAVRAS_MIN = _int("PALAVRAS_MIN", 5)                  # mensagens com "kkkk", "clipa"... em 10s

# Versão em inglês: "separado" (um vídeo PT e outro EN), "junto" (as duas legendas no mesmo vídeo) ou "nao"

# IA (Gemini)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODELO = os.environ.get("MODELO", "gemini-3.5-flash-lite")
MODELO_RESERVA = os.environ.get("MODELO_RESERVA", "gemini-3.5-flash-lite")

# Integração com o assistente do WhatsApp
ASSISTENTE_URL = os.environ.get("ASSISTENTE_URL", "http://assistente:3100").rstrip("/")
TOKEN_ROBO = os.environ.get("TOKEN_ROBO", "")
DESTINO = os.environ.get("DESTINO", "Ryan")  # nome (em USUARIOS do assistente) que recebe os cortes
PORTA_API = _int("PORTA_API", 8000)
