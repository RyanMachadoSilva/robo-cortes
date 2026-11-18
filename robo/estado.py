"""Estado persistente (cortes pendentes, contador) em /dados/estado.json."""
import json
import os
import threading
import time

from . import config

_trava = threading.RLock()
_dados = {"seq": 1, "cortes": {}, "cameras": {}}


def carregar():
    global _dados
    try:
        with open(config.ARQUIVO_ESTADO, encoding="utf-8") as f:
            _dados = {"seq": 1, "cortes": {}, "cameras": {}, **json.load(f)}
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
    for chave in ("arquivo", "arquivo_en", "arquivo_extra"):
        if c and c.get(chave):
            try:
                os.remove(c[chave])
            except FileNotFoundError:
                pass
    return c


def cortes():
    with _trava:
        return sorted(_dados["cortes"].values(), key=lambda c: c["id"])


def limpar_tudo():
    """Apaga todos os cortes (arquivos e registros), inclusive arquivos soltos, e zera o contador."""
    import glob

    with _trava:
        arquivos = set()
        for c in _dados["cortes"].values():
            arquivos.update(c.get(k) for k in ("arquivo", "arquivo_en", "arquivo_extra") if c.get(k))
        arquivos.update(glob.glob(os.path.join(config.PASTA_CORTES, "*.mp4")))
        n_cortes = len(_dados["cortes"])
        _dados["cortes"] = {}
        _dados["seq"] = 1  # a posição das webcams (cameras) é mantida
        salvar()
    apagados, bytes_ = 0, 0
    for a in arquivos:
        try:
            bytes_ += os.path.getsize(a)
            os.remove(a)
            apagados += 1
        except OSError:
            pass
    return n_cortes, apagados, bytes_


def camera(nome):
    """Última posição conhecida da webcam do canal (ou a padrão do config)."""
    with _trava:
        return _dados.get("cameras", {}).get(nome.lower()) or config.CAMERAS_PADRAO.get(nome.lower())


def salvar_camera(nome, caixa):
    with _trava:
        _dados.setdefault("cameras", {})[nome.lower()] = [round(float(v)) for v in caixa]
        salvar()


def ultimo_pendente():
    pend = [c for c in cortes() if c["status"] in ("pendente", "aprovado")]
    return pend[-1] if pend else None
