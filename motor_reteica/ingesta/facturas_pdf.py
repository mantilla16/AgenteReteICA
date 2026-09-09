"""Ingesta de facturas electronicas para el cotejo documental (C11).

Cada proveedor emite en un formato distinto, asi que la extraccion es
best-effort y declara su nivel de confianza. Una factura de la que no se
puede extraer la base con seguridad se marca REQUIERE_REVISION: el papel debe
decir que no se pudo cotejar, no fingir que cuadro.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

ALTA = "ALTA"
REQUIERE_REVISION = "REQUIERE_REVISION"

_RE_NIT = re.compile(r"(?:NIT|Nit)[\s:.]*([\d][\d.\s]{7,14}\d)")
_RE_ACTIVIDAD = re.compile(r"Actividad\s+Econ[oó]mica\s+(\d{4})", re.IGNORECASE)
_RE_FECHA_DMY = re.compile(r"\b(\d{2})/(\d{2})/(20\d{2})\b")
_RE_FECHA_YMD = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_ETIQUETAS_BASE = ("Total Bruto", "Subtotal", "SUBTOTAL", "Base gravable")


@dataclass(frozen=True)
class FacturaFuente:
    numero: str
    nit: str
    base: Decimal
    fecha: date
    actividad_declarada: str
    confianza: str


def _normalizar_nit(bruto: str) -> str:
    return re.sub(r"\D", "", bruto)[:9]


def _a_decimal(bruto: str):
    limpio = bruto.strip()
    if "," in limpio and "." in limpio:
        # 1.829.605,00 -> punto de miles; 5,000,000.00 -> coma de miles
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        limpio = limpio.replace(",", "")
    try:
        return Decimal(limpio).quantize(Decimal("1"))
    except Exception:
        return None


_ANCLAS_EMISION = ("GENERACI", "Generaci", "Fec.Gener", "FECHA DE EMISI")


def _primera_fecha(texto: str):
    encontrada = _RE_FECHA_DMY.search(texto)
    if encontrada:
        dia, mes, anio = encontrada.groups()
        return date(int(anio), int(mes), int(dia))
    encontrada = _RE_FECHA_YMD.search(texto)
    if encontrada:
        anio, mes, dia = encontrada.groups()
        return date(int(anio), int(mes), int(dia))
    return None


def _fecha_de_emision(texto: str, lineas: list):
    """La primera fecha del texto suele ser la autorizacion de la DIAN.

    En 250530 la autorizacion es del 2025-08-06 y la factura del 2026-07-27:
    tomar la primera daria un desfase de casi un anio y haria que C11
    reportara un falso hallazgo de corte. Se ancla en la fecha de generacion.
    """
    for linea in lineas:
        if any(ancla in linea for ancla in _ANCLAS_EMISION):
            fecha = _primera_fecha(linea)
            if fecha is not None:
                return fecha
    return _primera_fecha(texto)


def leer_factura(ruta: Path, nit_cliente: str = "819002433") -> FacturaFuente:
    with pdfplumber.open(ruta) as pdf:
        texto = pdf.pages[0].extract_text()
    lineas = [l.strip() for l in texto.split("\n")]

    nit = ""
    for bruto in _RE_NIT.findall(texto):
        candidato = _normalizar_nit(bruto)
        if len(candidato) == 9 and candidato != nit_cliente:
            nit = candidato
            break

    base = None
    for indice, linea in enumerate(lineas):
        for etiqueta in _ETIQUETAS_BASE:
            if etiqueta in linea:
                numeros = re.findall(r"[\d][\d.,]*[\d]", linea.split(etiqueta)[-1])
                if not numeros and indice + 1 < len(lineas):
                    # Encabezado tabular: la etiqueta va en una fila y los
                    # valores en la fila siguiente (ver FE338057).
                    numeros = re.findall(r"[\d][\d.,]*[\d]", lineas[indice + 1])
                if numeros:
                    base = _a_decimal(numeros[0])
                    break
        if base is not None:
            break

    fecha = _fecha_de_emision(texto, lineas)

    actividad = _RE_ACTIVIDAD.search(texto)

    confianza = ALTA if (nit and base is not None) else REQUIERE_REVISION
    return FacturaFuente(
        numero=Path(ruta).stem,
        nit=nit,
        base=base,
        fecha=fecha,
        actividad_declarada=actividad.group(1) if actividad else None,
        confianza=confianza,
    )
