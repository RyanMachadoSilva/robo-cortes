"""Estado persistente (cortes pendentes, contador) em /dados/estado.json."""
import json
import os
import threading
import time

from . import config

_trava = threading.RLock()
_dados = {"seq": 1, "cortes": {}}


def carregar():
    global _dados
    try:
        with open(config.ARQUIVO_ESTADO, encoding="utf-8") as f:
            _dados = {"seq": 1, "cortes": {}, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        pass


def salvar():
    with _trava:
        os.makedirs(os.path.dirname(config.ARQUIVO_ESTADO), exist_ok=True)
        tmp = config.ARQUIVO_ESTADO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, config.ARQUIVO_ESTADO)


def novo_corte(**campos):
    with _trava:
        cid = _dados["seq"]
        _dados["seq"] += 1
        _dados["cortes"][str(cid)] = {"id": cid, "status": "pendente", "criado": time.time(), **campos}
        salvar()
        return cid


def corte(cid):
    with _trava:
        return _dados["cortes"].get(str(cid))


def atualizar(cid, **campos):
    with _trava:
        c = _dados["cortes"].get(str(cid))
        if c:
            c.update(campos)
            salvar()
        return c


def remover(cid):
    """Apaga o arquivo do corte e tira do estado."""
    with _trava:
        c = _dados["cortes"].pop(str(cid), None)
        salvar()
    if c and c.get("arquivo"):
        try:
            os.remove(c["arquivo"])
        except FileNotFoundError:
            pass
    return c


def cortes():
    with _trava:
        return sorted(_dados["cortes"].values(), key=lambda c: c["id"])


def ultimo_pendente():
    pend = [c for c in cortes() if c["status"] in ("pendente", "aprovado")]
    return pend[-1] if pend else None
