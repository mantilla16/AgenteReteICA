"""
Autenticacion para Motor de Revision de ReteICA.

Login por correo @rbcol.co + codigo de 6 digitos.
Basado en el sistema de analitica-puc.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

_N, _R, _P, _LARGO = 16384, 8, 1, 32

DOMINIO = os.getenv("AUDITORIA_DOMINIO", "rbcol.co").strip().lower()

_CORREO = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

LARGO_CODIGO = 6
MINUTOS_VIGENCIA_CODIGO = 10
MAX_INTENTOS_CODIGO = 5
MAX_CODIGOS_POR_VENTANA = 3
MINUTOS_VENTANA_ENVIO = 15


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=_LARGO)
    return f"scrypt${_N}${_R}${_P}${sal.hex()}${h.hex()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        algo, n, r, p, sal_hex, hash_hex = guardado.split("$")
        if algo != "scrypt":
            return False
        h = hashlib.scrypt(clave.encode(), salt=bytes.fromhex(sal_hex),
                           n=int(n), r=int(r), p=int(p),
                           dklen=len(hash_hex) // 2)
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:
        return False


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalizar_correo(correo: str | None) -> str:
    return (correo or "").strip().lower()


def problema_con_correo(correo: str) -> str | None:
    if not correo:
        return "Escriba su correo."
    if not _CORREO.match(correo):
        return "Ese no parece un correo valido."
    if not correo.endswith("@" + DOMINIO):
        return f"Solo se puede entrar con un correo @{DOMINIO}."
    return None


def nuevo_codigo() -> str:
    return f"{secrets.randbelow(10 ** LARGO_CODIGO):0{LARGO_CODIGO}d}"


def hash_codigo(codigo: str) -> str:
    return hash_clave(codigo)


def verificar_codigo(codigo: str, guardado: str) -> bool:
    return verificar_clave(codigo, guardado)
