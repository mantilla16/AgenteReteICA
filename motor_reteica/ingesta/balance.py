"""Ingesta del balance de prueba, limitada a las cuentas de ReteICA.

Trampa del formato: el movimiento del periodo esta en 'Saldo Haber per.inf.'.
'Saldo acumulado' trae el arrastre de todos los periodos anteriores; tomarlo
haria fallar C2 en todos los meses.
"""

from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import FIRMA_BALANCE, ROLES_BALANCE, localizar_columnas
from motor_reteica.parametros.puc import CUENTA_RETEICA, es_cuenta_reteica


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


DEBITO = "DEBITO"
CREDITO = "CREDITO"
_ACUMULADO = "Saldo acumulado"


def leer_naturalezas(ruta: Path) -> dict:
    """M11: naturaleza de cada cuenta 2368, por el signo del saldo acumulado.

    La contrapartida de pago se delata por el signo: en el balance de Terlica
    2368010090 es la unica cuenta 2368 con saldo positivo (+34.533.438)
    mientras las demas son negativas. El motor DETECTA la candidata; quien
    decide que es cada una es el auditor (ver atestacion.py). Detectar sin
    exigir declaracion seria adivinar; exigir declaracion sin detectar seria
    una lista que alguien olvida llenar.
    """
    filas = leer_filas(ruta, hoja="BALANCE")
    inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)

    columna_acumulado = None
    for indice, celda in enumerate(filas[inicio]):
        if _texto(celda) == _ACUMULADO:
            columna_acumulado = indice
            break
    if columna_acumulado is None:
        return {}

    naturalezas = {}
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if not cuenta.startswith(CUENTA_RETEICA):
            continue
        acumulado = Decimal(str(fila[columna_acumulado] or 0))
        naturalezas[cuenta] = DEBITO if acumulado > 0 else CREDITO
    return naturalezas


def leer_balance(ruta: Path, excluidas=()) -> dict:
    filas = leer_filas(ruta, hoja="BALANCE")
    inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)

    saldos = {}
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if es_cuenta_reteica(cuenta, excluidas):
            saldos[cuenta] = Decimal(
                str(fila[col["movimiento_periodo"]] or 0)).copy_abs()
    return saldos
