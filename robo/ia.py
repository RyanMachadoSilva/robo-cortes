"""Gemini: ouve o trecho, decide se vale corte, escolhe início/fim, escreve título, gancho e legendas."""
import base64
import json
import logging
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("ia")

_pausado_ate = 0.0  # se o modelo principal congestionar, usa a reserva por 10 min

PROMPT = """Você é editor de cortes de live para YouTube Shorts e TikTok, em português do Brasil.
Live: "{titulo}" (canal {canal}).
O áudio anexado tem {duracao:.0f} segundos e foi gravado ao redor de um momento em que o chat explodiu ({motivo}).
Mensagens do chat nesse momento: {chat}

Analise e responda SÓ com JSON neste formato:
{{
  "vale_corte": true/false,
  "nota": 0-10 (quanto isso viraliza como Short),
  "motivo": "frase curta do que acontece",
  "inicio": segundo do áudio onde o corte deve começar (comece um pouco antes da ação),
  "fim": segundo onde deve terminar (logo depois da reação; corte entre 15 e 58 segundos),
  "titulo": "título chamativo para o Short, até 70 caracteres, sem aspas",
  "gancho": "texto curto para aparecer no topo do vídeo, até 30 caracteres",
  "legendas": [{{"inicio": s, "fim": s, "texto": "fala"{extra_leg}}}]{extra}
}}
Legendas: transcreva as falas entre "inicio" e "fim" em blocos de até 6 palavras, com tempos em segundos do áudio.{extra_regra}
Se for só silêncio, conversa morna ou menu, "vale_corte": false."""


def _chamar(modelo, corpo, espera):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_API_KEY},
    )
    with urllib.request.urlopen(req, timeout=espera) as r:
        return json.load(r)


def _campos_ingles():
    if config.VERSAO_EN not in ("separado", "junto"):
        return {"extra_leg": "", "extra": "", "extra_regra": ""}
    return {
        "extra_leg": ', "texto_en": "a mesma fala traduzida para o inglês"',
        "extra": (',\n  "titulo_en": "o título em inglês, chamativo para público gringo, até 70 caracteres",'
                  '\n  "gancho_en": "o gancho em inglês, até 30 caracteres"'),
        "extra_regra": " Em \"texto_en\", traduza de forma natural (gírias equivalentes em inglês), mantendo nomes próprios.",
    }


def analisar(audio_mp3, duracao, titulo_live, motivo, amostra_chat, canal=""):
    """Retorna o dicionário da IA, ou None se não deu para analisar (sem chave, sem cota...)."""
    global _pausado_ate
    if not config.GEMINI_API_KEY:
        return None
    texto = PROMPT.format(
        titulo=titulo_live, canal=canal or config.CANAL_URL.split("/")[-1], duracao=duracao, motivo=motivo,
        chat=" | ".join(amostra_chat[-40:]) or "(chat indisponível)",
        **_campos_ingles(),
    )
    corpo = {
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "audio/mpeg", "data": base64.b64encode(audio_mp3).decode()}},
            {"text": texto},
        ]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 4000},
    }
    modelos = [config.MODELO]
    if config.MODELO_RESERVA and config.MODELO_RESERVA != config.MODELO:
        modelos = [config.MODELO_RESERVA] if time.time() < _pausado_ate else [config.MODELO, config.MODELO_RESERVA]
    for i, modelo in enumerate(modelos):
        try:
            resp = _chamar(modelo, corpo, 40 if i < len(modelos) - 1 else 90)
            partes = resp.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            bruto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
            bruto = bruto.strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(bruto)
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode(errors="ignore")[:200]
            log.warning("Gemini %s em %s: %s", e.code, modelo, detalhe)
            if e.code in (429, 500, 503) and i < len(modelos) - 1:
                _pausado_ate = time.time() + 600
                continue
            return None
        except (TimeoutError, urllib.error.URLError) as e:
            log.warning("Gemini sem resposta em %s: %s", modelo, e)
            if i < len(modelos) - 1:
                _pausado_ate = time.time() + 600
                continue
            return None
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning("resposta da IA ilegível: %s", e)
            return None
    return None
