"""Ingesta del libro auxiliar de la cuenta 2368.

Hay dos formatos vivos en produccion, ambos exportados desde SAP con
transacciones distintas:

  - FORMATO RICO (FBL3N): trae 'Cuenta' y 'Importe en ML' por linea, con
    fecha del documento, fecha de contabilizacion, tercero y todo lo que
    los cruces por renglon necesitan. Es el de TERLICA.

  - FORMATO AGREGADO (FAGLL03H): trae 'Asignacion' e 'Importe en moneda
    local' por linea, pero la CUENTA no viene en la fila: aparece como
    subtotal ('Cuenta 2368010005') al final de cada bloque de esa cuenta.
    Es el de Agroingenium. Con este solo se puede alimentar el cruce
    universal (total declarado vs total auxiliar); los cruces por renglon
    quedaran NO_EJECUTADO porque falta informacion.

El motor decide cual usar viendo cual firma coincide primero. Se prefiere
el rico -- da mas cruces -- y se cae al agregado si es el unico que golpea.

Trampas del formato rico: la columna 'Asignacion' trae el NIT y 'Tercero'
el nombre, no al reves. Los importes vienen negativos (naturaleza credito)
y se normalizan a positivo. Las filas de totales ('*' y '**') no traen
cuenta y se descartan.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import (
    FIRMA_AUXILIAR, FIRMAS_ALTERNATIVAS, ROLES_AUXILIAR,
    _fila_a_etiquetas, localizar_columnas,
)
from motor_reteica.parametros.puc import es_cuenta_reteica
from motor_reteica.tipos import LineaAuxiliar


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if valor is None or valor == "":
        return date(1900, 1, 1)         # sin fecha; el cruce por corte se salta
    s = str(valor).strip()
    for formato in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.split(" ")[0], formato.split(" ")[0]).date()
        except ValueError:
            pass
    return date(1900, 1, 1)


def _texto(valor) -> str:
    return str(valor).strip() if valor is not None else ""


def leer_auxiliar(ruta: Path) -> list:
    """Devuelve las lineas del auxiliar en cualquiera de los formatos vivos.

    Se prueba el formato RICO primero; si no golpea ninguna fila con esa
    firma, cae al AGREGADO. Un archivo que no encaje en ninguno lanza
    ColumnaNoIdentificada -- la misma excepcion que antes -- para que el
    pipeline muestre el error al auditor y no siga silenciosamente.
    """
    filas = leer_filas(ruta)

    # Formato rico: si golpea, es el mejor. Los cruces por renglon corren.
    if _tiene_firma(filas, FIRMA_AUXILIAR):
        return _leer_rico(filas)

    # Cualquier firma alternativa del auxiliar habilita el modo agregado.
    for firma in FIRMAS_ALTERNATIVAS["auxiliar"][1:]:
        if _tiene_firma(filas, firma):
            return _leer_agregado(filas, firma)

    # Ninguna firma: el reader de siempre lanza ColumnaNoIdentificada con
    # las etiquetas disponibles para que el auditor sepa que corregir.
    return _leer_rico(filas)


def _tiene_firma(filas, firma) -> bool:
    for fila in filas:
        etiquetas = _fila_a_etiquetas(fila)
        if all(marca in etiquetas for marca in firma):
            return True
    return False


def _leer_rico(filas: list) -> list:
    inicio, col = localizar_columnas(filas, ROLES_AUXILIAR, FIRMA_AUXILIAR)
    lineas = []
    for fila in filas[inicio + 1:]:
        cuenta = _texto(fila[col["cuenta"]])
        if not es_cuenta_reteica(cuenta):
            continue
        lineas.append(LineaAuxiliar(
            cuenta=cuenta,
            nit=_texto(fila[col["nit"]]),
            tercero=_texto(fila[col["nombre"]]),
            fecha_documento=_a_fecha(fila[col["fecha_documento"]]),
            fecha_contabilizacion=_a_fecha(fila[col["fecha_contabilizacion"]]),
            referencia=_texto(fila[col["referencia"]]),
            documento=_texto(fila[col["documento"]]),
            concepto=_texto(fila[col["concepto"]]),
            retencion=Decimal(str(fila[col["importe"]])).copy_abs(),
        ))
    return lineas


def _leer_agregado(filas: list, firma) -> list:
    """Formato Agroingenium: la cuenta esta en filas de subtotal.

    Estructura del bloque:
        detalle_1               <- filas con NIT, importe, concepto
        detalle_-1              <- contra-abono (misma linea reversada)
        ...
        Icono part.abiertas...  <- basura de SAP
        Cuenta 2368010005       <- subtotal NETO reportado por SAP

    Se emite UNA SOLA LineaAuxiliar por cuenta con la retencion neta que
    SAP reporta en el subtotal -- es lo mas fiel: el auxiliar del cliente
    trae contra-abonos legitimos y sumar los detalles a mano los duplicaria.

    El detalle por linea (NIT, tercero, factura) se pierde: este formato no
    permite los cruces por renglon ni el mapeo tercero-por-tercero contra el
    ERP. Los cruces que necesiten eso quedaran NO_EJECUTADO. Es la
    contrapartida de aceptar un export agregado.
    """
    encabezado, col = _localizar_encabezado_agregado(filas, firma)
    if encabezado is None:
        return []

    lineas: list = []
    for fila in filas[encabezado + 1:]:
        cuenta = _detectar_subtotal(fila)
        if not cuenta or not es_cuenta_reteica(cuenta):
            continue
        subtotal = _importe_de(fila, col["importe"])
        if subtotal is None:
            continue
        lineas.append(LineaAuxiliar(
            cuenta=cuenta,
            nit="",                       # el subtotal no lo trae
            tercero="",
            fecha_documento=date(1900, 1, 1),
            fecha_contabilizacion=date(1900, 1, 1),
            referencia="",
            documento="",
            concepto="(subtotal agregado de SAP)",
            retencion=Decimal(str(subtotal)).copy_abs(),
        ))
    return lineas


def _importe_de(fila, columna):
    if columna is None or columna >= len(fila):
        return None
    valor = fila[columna]
    return valor if isinstance(valor, (int, float)) else None


def _localizar_encabezado_agregado(filas, firma):
    for indice, fila in enumerate(filas):
        etiquetas = _fila_a_etiquetas(fila)
        if all(m in etiquetas for m in firma):
            resueltas = {
                "nit":      etiquetas.get("Asignación",
                                          etiquetas.get("Asignacion")),
                "importe":  etiquetas["Importe en moneda local"],
                "documento": etiquetas.get("N° documento",
                                           etiquetas.get("Nº documento")),
                "fecha_documento": etiquetas.get("Fecha de documento",
                                                 etiquetas.get("Fecha doc.")),
                "concepto": etiquetas.get("Texto"),
                "referencia": etiquetas.get("Referencia"),
            }
            return indice, resueltas
    return None, {}


def _detectar_subtotal(fila) -> str | None:
    """Devuelve la cuenta (p.ej. '2368010005') si la fila es un subtotal."""
    for celda in fila:
        if isinstance(celda, str) and celda.strip().startswith("Cuenta 2368"):
            partes = celda.strip().split()
            if len(partes) >= 2 and partes[1].isdigit():
                return partes[1]
    return None
