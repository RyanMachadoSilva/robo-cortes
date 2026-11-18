"""Gemini: ouve o trecho, decide se vale corte, escolhe início/fim, escreve título, gancho e legendas."""
import base64
import json
import logging
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("ia")


PROMPT = """Você é editor de cortes de live para YouTube Shorts e TikTok, em português do Brasil.
Live: "{titulo}" (canal {canal}).
O áudio anexado tem {duracao:.0f} segundos e foi gravado ao redor de um momento em que o chat explodiu ({motivo}).
Mensagens do chat nesse momento: {chat}

{instrucao_idioma}
Analise e responda SÓ com JSON neste formato:
{{
  "vale_corte": true/false,
  "nota": 0-10 (quanto isso viraliza como Short),
  "motivo": "frase curta do que acontece",
  "inicio": segundo do áudio onde o corte deve começar (comece um pouco antes da ação),
  "fim": segundo onde deve terminar (logo depois da reação; corte entre 15 e 58 segundos),
  "titulo": "título chamativo para o Short, até 70 caracteres, sem aspas",
  "gancho": "texto curto para aparecer no topo do vídeo, até 30 caracteres",
  "legendas": [{{"inicio": s, "fim": s, "texto": "fala"{extra_leg}}}]{extra}{campo_camera}
}}
Legendas: transcreva TODAS as falas do áudio inteiro (do segundo 0 ao fim), em blocos de até 6 palavras, com "inicio" e "fim" em segundos do áudio (número, ex.: 12.5).{extra_regra}
Se for só silêncio, conversa morna ou menu, "vale_corte": false.{regra_camera}"""

CAMPO_CAMERA = ',\n  "camera": [ymin, xmin, ymax, xmax] ou null'
REGRA_CAMERA = (
    "\nA imagem anexada é um quadro da live nesse momento. Em \"camera\", dê a caixa da WEBCAM do streamer "
    "(o retângulo com o vídeo do rosto dele sobreposto ao jogo), em coordenadas de 0 a 1000 no formato "
    "[ymin, xmin, ymax, xmax]. Pegue só o retângulo da webcam, sem o resto da tela. Use null se não houver webcam "
    "sobreposta (ex.: só jogo, ou a câmera ocupando a tela inteira)."
)


def _chamar(modelo, corpo, espera):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=espera) as r:
        return json.load(r)


NOMES = {"en": ("inglês", "público gringo", "gírias equivalentes em inglês"),
         "pt": ("português do Brasil", "público brasileiro", "gírias brasileiras equivalentes")}


def _campos_extra(extra=None):
    """Campos a mais no JSON quando o corte também sai numa versão em outro idioma."""
    if extra not in NOMES:
        return {"extra_leg": "", "extra": "", "extra_regra": ""}
    lingua, publico, girias = NOMES[extra]
    return {
        "extra_leg": f', "texto_{extra}": "a mesma fala traduzida para o {lingua}"',
        "extra": (f',\n  "titulo_{extra}": "o título em {lingua}, chamativo para {publico}, até 70 caracteres",'
                  f'\n  "gancho_{extra}": "o gancho em {lingua}, até 30 caracteres"'),
        "extra_regra": f' Em "texto_{extra}", traduza de forma natural ({girias}), mantendo nomes próprios.',
    }


IDIOMA_EN = (
    "IMPORTANTE: esta live é em INGLÊS e o corte vai para público gringo. Escreva \"titulo\", \"gancho\" e o "
    "\"texto\" das legendas EM INGLÊS (as legendas são a transcrição em inglês do que é falado)."
)


def _normalizar(dados):
    """A IA às vezes devolve [ {...} ] ou {"corte": {...}} em vez de {...}: pega o objeto certo."""
    while isinstance(dados, list):
        dicts = [d for d in dados if isinstance(d, dict)]
        if not dicts:
            return None
        dados = max(dicts, key=lambda d: d.get("nota") or 0) if len(dicts) > 1 else dicts[0]
    if isinstance(dados, dict) and "vale_corte" not in dados and len(dados) == 1:
        interno = next(iter(dados.values()))
        if isinstance(interno, (dict, list)):
            return _normalizar(interno)
    if not isinstance(dados, dict):
        return None
    if not isinstance(dados.get("legendas"), list):
        dados["legendas"] = []
    dados["legendas"] = [l for l in dados["legendas"] if isinstance(l, dict)]
    return dados


def analisar(audio_mp3, duracao, titulo_live, motivo, amostra_chat, canal="", idioma="pt", extra=None, quadro=None):
    """Retorna o dicionário da IA, ou None se não deu para analisar (sem chave, sem cota...)."""
    if not config.GEMINI_API_KEY:
        return None
    texto = PROMPT.format(
        titulo=titulo_live, canal=canal or config.CANAL_URL.split("/")[-1], duracao=duracao, motivo=motivo,
        chat=" | ".join(amostra_chat[-40:]) or "(chat indisponível)",
        instrucao_idioma=IDIOMA_EN if idioma == "en" else "",
        campo_camera=CAMPO_CAMERA if quadro else "",
        regra_camera=REGRA_CAMERA if quadro else "",
        **_campos_extra(extra),
    )
    corpo = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "audio/mpeg", "data": base64.b64encode(audio_mp3).decode()}},
            *([{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(quadro).decode()}}] if quadro else []),
            {"text": texto},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 8000},
    }
    # Modelo principal + reservas diferentes; cada um com até 3 tentativas quando está congestionado (503)
    modelos = []
    for m in [config.MODELO, *config.MODELOS_RESERVA]:
        if m and m not in modelos:
            modelos.append(m)
    for modelo in modelos:
        for tentativa in range(3):
            try:
                resp = _chamar(modelo, corpo, 90)
                partes = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                bruto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
                bruto = bruto.strip().removeprefix("```json").removesuffix("```").strip()
                dados = _normalizar(json.loads(bruto))
                if dados is not None:
                    if modelo != config.MODELO or tentativa:
                        log.info("IA respondeu com %s (tentativa %s)", modelo, tentativa + 1)
                    return dados
                log.warning("resposta da IA sem o formato esperado (%s)", modelo)
                break
            except urllib.error.HTTPError as e:
                detalhe = " ".join(e.read().decode(errors="ignore").split())[:120]
                log.warning("Gemini %s em %s (tentativa %s): %s", e.code, modelo, tentativa + 1, detalhe)
                if e.code in (500, 503) and tentativa < 2:
                    time.sleep(5 * (tentativa + 1) ** 2)  # 5s, 20s
                    continue
                break  # 429 (cota) ou outro erro: vai para o próximo modelo
            except (TimeoutError, urllib.error.URLError) as e:
                log.warning("Gemini sem resposta em %s: %s", modelo, e)
                break
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                log.warning("resposta da IA ilegível (%s): %s", modelo, e)
                break
    log.error("nenhum modelo da IA respondeu; corte vai sem legenda")
    return None
    return None
