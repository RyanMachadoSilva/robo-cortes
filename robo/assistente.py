"""Fala com o assistente do WhatsApp (porta interna http://assistente:3100)."""
import base64
import json
import logging
import os
import urllib.request

from . import config

log = logging.getLogger("assistente")


def _post(corpo, espera=120):
    req = urllib.request.Request(
        config.ASSISTENTE_URL + "/enviar",
        data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json", "X-Token": config.TOKEN_ROBO},
    )
    try:
        with urllib.request.urlopen(req, timeout=espera) as r:
            return json.load(r)
    except Exception as e:
        log.warning("não consegui falar com o assistente: %s", e)
        return None


def texto(msg):
    log.info("whatsapp: %s", msg.replace("\n", " ")[:120])
    return _post({"para": config.DESTINO, "tipo": "texto", "texto": msg})


def video(caminho, legenda, corte_id):
    with open(caminho, "rb") as f:
        dados = base64.b64encode(f.read()).decode()
    return _post({
        "para": config.DESTINO, "tipo": "video", "legenda": legenda, "corte_id": corte_id,
        "nome": os.path.basename(caminho), "arquivo_base64": dados,
    }, espera=300)
