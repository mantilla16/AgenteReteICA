"""Ingesta del balance de prueba, limitada a las cuentas de ReteICA.

Trampa del formato: el movimiento del periodo esta en 'Saldo Haber per.inf.'.
'Saldo acumulado' trae el arrastre de todos los periodos anteriores; tomarlo
haria fallar C2 en todos los meses.
"""

from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import (
    ColumnaNoIdentificada, FIRMA_BALANCE, ROLES_BALANCE, localizar_columnas)
from motor_reteica.parametros.puc import CUENTA_RETEICA, es_cuenta_reteica


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


DEBITO = "DEBITO"
CREDITO = "CREDITO"
_ACUMULADO = "Saldo acumulado"


def _columna_acumulado(filas, inicio):
    for indice, celda in enumerate(filas[inicio]):
        if _texto(celda) == _ACUMULADO:
            return indice
    return None


def leer_acumulados(ruta: Path) -> dict:
    """El saldo acumulado de cada cuenta 2368, tal como viene del export.

    NO entra en ningun cruce -- arrastra todos los periodos anteriores y
    usarlo haria fallar C2 siempre. Se lee para que el papel pueda MOSTRARLO:
    es la cifra por la que el motor senala una cuenta como contrapartida de
    pago (M11), y sin ella el papel afirma una exclusion que el lector no
    puede verificar.
    """
    filas = leer_filas(ruta, hoja="BALANCE")
    try:
        inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)
    except ColumnaNoIdentificada:
        # Formato de ERP no reconocido por firma (SAP B1 y otros): en esos
        # exports el saldo acumulado por cuenta vive en filas resumen, no en las
        # de transaccion, y derivarlo bien exige logica propia del formato. Se
        # degrada a vacio: M11 (contrapartida automatica) queda sin auto-deteccion
        # y el auditor la declara por atestacion. Es la verdad del papel -- no
        # detectamos la naturaleza -- no una afirmacion falsa.
        return {}
    columna = _columna_acumulado(filas, inicio)
    if columna is None:
        return {}

    acumulados = {}
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if cuenta.startswith(CUENTA_RETEICA):
            acumulados[cuenta] = Decimal(str(fila[columna] or 0))
    return acumulados


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
    try:
        inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)
    except ColumnaNoIdentificada:
        return {}   # ver nota en leer_acumulados: se degrada, no se revienta

    columna_acumulado = _columna_acumulado(filas, inicio)
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


def _deteccion_dinamica(filas):
    """Deteccion por contenido para balances de ERP no vistos (SAP B1, etc.).

    Devuelve la Deteccion solo si trae cuenta y una columna de movimiento; si
    no, None, para que el llamador decida (no reventar el pipeline por un
    balance de formato ajeno).
    """
    from motor_reteica.ingesta.deteccion import detectar
    d = detectar(filas, tipo_esperado="balance")
    tiene_mov = "credito" in d.columnas or "importe" in d.columnas
    return d if ("cuenta" in d.columnas and tiene_mov) else None


def leer_balance(ruta: Path, excluidas=()) -> dict:
    filas = leer_filas(ruta, hoja="BALANCE")
    try:
        inicio, col = localizar_columnas(filas, ROLES_BALANCE, FIRMA_BALANCE)
    except ColumnaNoIdentificada:
        d = _deteccion_dinamica(filas)
        if d is None:
            raise
        from motor_reteica.ingesta.adaptador import leer_saldos
        return leer_saldos(filas, d, excluidas)

    saldos = {}
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if es_cuenta_reteica(cuenta, excluidas):
            saldos[cuenta] = Decimal(
                str(fila[col["movimiento_periodo"]] or 0)).copy_abs()
    return saldos
