"""Extractor MINIMO de un borrador de ReteICA, agnostico del formato.

Extrae los cuatro datos que TODO borrador de ICA tiene por ley, cualquiera sea
el municipio: NIT del declarante, municipio, periodo, total retenciones. Con
eso alcanza para el cruce basico -- lo declarado contra el auxiliar -- que es
lo que Robinson revisa a mano y lo que sirve para cualquier municipio nuevo
sin escribir un extractor especifico.

Este modulo NO afirma nada: entrega candidatos con confianza baja/media/alta
para que el auditor confirme antes de que ninguna cifra llegue al papel. Un
falso positivo silencioso en el TOTAL declarado seria peor que no extraer
nada, porque el papel diria que cuadra sobre una cifra inventada.

D9 sigue: el motor propone, el auditor confirma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class Extraccion:
    """Los cuatro datos con la confianza con que se leyeron."""

    nit: str | None = None
    nit_confianza: str = "vacio"

    municipio: str | None = None
    municipio_confianza: str = "vacio"

    periodo: str | None = None
    periodo_confianza: str = "vacio"

    total_declarado: Decimal | None = None
    total_confianza: str = "vacio"

    # Todos los numeros que aparecen etiquetados con algo que suena a
    # "retencion" o "total". Se muestran al auditor para que elija si el que
    # propuso el motor no fuera el correcto.
    candidatos_total: tuple = field(default_factory=tuple)

    def como_dict(self) -> dict:
        return {
            "nit": self.nit,
            "nit_confianza": self.nit_confianza,
            "municipio": self.municipio,
            "municipio_confianza": self.municipio_confianza,
            "periodo": self.periodo,
            "periodo_confianza": self.periodo_confianza,
            "total_declarado": (float(self.total_declarado)
                                if self.total_declarado is not None else None),
            "total_confianza": self.total_confianza,
            "candidatos_total": [float(c) for c in self.candidatos_total],
        }


def leer_borrador_universal(ruta: Path) -> Extraccion:
    """Extrae los cuatro datos del borrador. Nunca lanza."""
    try:
        with pdfplumber.open(ruta) as pdf:
            texto = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception:
        return Extraccion()

    return Extraccion(
        **_extraer_nit(texto),
        **_extraer_municipio(texto),
        **_extraer_periodo(texto),
        **_extraer_total(texto),
    )


# --------------------------------------------------------------------------
# NIT
# --------------------------------------------------------------------------

_RE_NIT_SUELTO = re.compile(r"\b(\d{9,10})\b")

# Marca la region del formulario donde vive el NIT DEL DECLARANTE, para
# distinguirlo del NIT del municipio que suele estar en el encabezado. Todos
# los borradores traen una de estas.
_RE_ANCLA_DECLARANTE = re.compile(
    r"AGENTE\s+RETENEDOR|RAZ[ÓO]N\s+SOCIAL|"
    r"N[ÚU]MERO\s+DE\s+IDENTIFICACI[ÓO]N|IDENTIFICACI[ÓO]N\s+TRIBUTARIA",
    re.IGNORECASE)


def _limpiar_digitos(cadena: str) -> str:
    return re.sub(r"[.\s-]", "", cadena)


def _extraer_nit(texto: str) -> dict:
    """Prefiere el NIT que aparece DESPUES de un ancla del declarante.

    El primer numero de 9-10 digitos del borrador es tipicamente el NIT del
    MUNICIPIO (aparece en el encabezado con la alcaldia). Antes tomabamos ese
    y firmabamos el papel con el NIT del ente publico como declarante -- el
    error de auditoria mas grave posible en un formulario. Ahora se busca
    despues del ancla y el suelto queda como ultimo recurso.
    """
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if _RE_ANCLA_DECLARANTE.search(linea):
            # Buscar en las 8 lineas siguientes, saltando la 6 de DV que viene
            # entre el encabezado y el NIT en algunos formatos.
            for j in range(i + 1, min(i + 9, len(lineas))):
                m = _RE_NIT_SUELTO.search(lineas[j])
                if m:
                    return {"nit": m.group(1), "nit_confianza": "alta"}

    # Sin ancla: caemos al primer suelto, con confianza baja. Que sea baja
    # obliga al auditor a mirar antes de correr, que es lo que queremos si el
    # extractor no supo distinguir.
    for linea in lineas[:30]:
        m = _RE_NIT_SUELTO.search(linea)
        if m:
            return {"nit": m.group(1), "nit_confianza": "baja"}
    return {}


# --------------------------------------------------------------------------
# Municipio
# --------------------------------------------------------------------------

# Patrones ordenados por especificidad, la que golpee primero gana. Se prueban
# solo contra las 8 primeras lineas: mas abajo empieza el cuerpo del
# formulario y "DECLARACION DE CORRECCION" (que trae "DE X") o "DIRECCION DE
# NOTIFICACION" secuestran el nombre.
_PATRONES_MUNICIPIO = (
    re.compile(r"MUNICIPIO\s+DE\s+([A-ZÁÉÍÓÚÑ\s]+)", re.IGNORECASE),
    re.compile(r"DISTRITO\s+DE\s+([A-ZÁÉÍÓÚÑ\s]+)", re.IGNORECASE),
    re.compile(r"DISTRITO\s+\w+\s+(?:Y\s+)?\w*\s*DE\s+([A-ZÁÉÍÓÚÑ\s]+)",
               re.IGNORECASE),
    re.compile(r"ALCALD[IÍ]A\s+(?:MUNICIPAL\s+)?DE\s+([A-ZÁÉÍÓÚÑ\s]+)",
               re.IGNORECASE),
)

_PARADAS_MUNICIPIO = re.compile(
    r"\s+(ALCALD|SECRETARIA|SECRETARÍA|REPUBLICA|REPÚBLICA|"
    r"DEPARTAMENTO|HACIENDA|MUNICIPAL|FORMULARIO|DECLARACI|"
    r"DIRECCION|DIRECCIÓN|N[UÚ]MERO|A[ÑN]O|PERIODO|NIT)",
    re.IGNORECASE)


def _extraer_municipio(texto: str) -> dict:
    lineas = texto.splitlines()[:8]
    encabezado = "\n".join(lineas)

    for patron in _PATRONES_MUNICIPIO:
        m = patron.search(encabezado)
        if m:
            crudo = m.group(1)
            # Corta al primer terminador que suene a otra seccion.
            parada = _PARADAS_MUNICIPIO.search(crudo)
            if parada:
                crudo = crudo[:parada.start()]
            # Corta letras sueltas al final (columnas paralelas en pdfplumber).
            crudo = re.sub(r"\s+[A-ZÁÉÍÓÚÑ]\s*$", "", crudo.strip())
            nombre = re.sub(r"\s+", " ", crudo).strip().title()
            if nombre and len(nombre) >= 3:
                return {"municipio": nombre, "municipio_confianza": "alta"}
    return {}


# --------------------------------------------------------------------------
# Periodo
# --------------------------------------------------------------------------

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_RE_ANIO = re.compile(
    r"A[ÑN]O\s*(?:DECLARADO|GRAVABLE|FISCAL)?\s*[:\s]*(\d{4})",
    re.IGNORECASE)
_RE_MES_TEXTO = re.compile(
    r"\b(Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|"
    r"Setiembre|Octubre|Noviembre|Diciembre)\b", re.IGNORECASE)
_RE_MES_NUM = re.compile(r"PER[IÍ]ODO\s*[:\s]*(\d{1,2})\b", re.IGNORECASE)

# Abreviaturas de mes en el formulario de Santa Marta: "ENE FEB MAR ABR MAY
# JUN JUL" con casillas debajo. Se detecta que un mes esta marcado por la
# presencia de un cuadrito lleno.
_ABREV_MES = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL",
              "AGO", "SEP", "OCT", "NOV", "DIC")
_CAJA_MARCADA = "☒"
_CAJA_VACIA = "☐"


def _mes_por_checkbox(lineas: list) -> int | None:
    """Detecta un mes marcado con casilla llena en el formulario tipo Santa Marta.

    El texto queda como dos lineas: una con los nombres de mes, la siguiente
    con las casillas alineadas por posicion. La cantidad de casillas antes
    del cuadrito lleno da el mes; si hay dos, se toma el primero.
    """
    for i, linea in enumerate(lineas[:20]):
        if _CAJA_MARCADA not in linea:
            continue
        # Es una linea de casillas si tiene mayoria de simbolos.
        cuadros = linea.count(_CAJA_MARCADA) + linea.count(_CAJA_VACIA)
        if cuadros < 3:
            continue
        # La linea de arriba debe traer los meses.
        if i == 0:
            continue
        arriba = lineas[i - 1].upper()
        meses = [m for m in _ABREV_MES if m in arriba]
        if not meses:
            continue
        # Posicion de la casilla marcada entre las casillas.
        secuencia = [c for c in linea if c in (_CAJA_MARCADA, _CAJA_VACIA)]
        try:
            pos = secuencia.index(_CAJA_MARCADA)
        except ValueError:
            continue
        if pos < len(meses):
            return _MESES[_nombre_completo(meses[pos])]
    return None


def _nombre_completo(abrev: str) -> str:
    for m in _MESES:
        if m.upper().startswith(abrev.upper()):
            return m
    return abrev


def _extraer_periodo(texto: str) -> dict:
    anio_m = _RE_ANIO.search(texto)
    if not anio_m:
        return {}
    anio = int(anio_m.group(1))
    lineas = texto.splitlines()

    # Casilla marcada -- lo mas confiable en formularios con checkboxes.
    mes = _mes_por_checkbox(lineas)
    if mes:
        return {"periodo": "%d-%02d" % (anio, mes),
                "periodo_confianza": "alta"}

    # "PERIODO 7" literal: numero de mes junto al label.
    num = _RE_MES_NUM.search(texto)
    if num:
        mes = int(num.group(1))
        if 1 <= mes <= 12:
            return {"periodo": "%d-%02d" % (anio, mes),
                    "periodo_confianza": "alta"}

    # Meses escritos: "Julio - Agosto" es bimestral, se toma el primero.
    meses_hallados = []
    for linea in lineas[:20]:
        for m in _RE_MES_TEXTO.finditer(linea):
            n = _MESES[m.group(1).lower()]
            if not meses_hallados or meses_hallados[-1] != n:
                meses_hallados.append(n)
    if meses_hallados:
        return {"periodo": "%d-%02d" % (anio, meses_hallados[0]),
                "periodo_confianza": ("media" if len(meses_hallados) > 1
                                      else "alta")}
    return {"periodo": str(anio), "periodo_confianza": "baja"}


# --------------------------------------------------------------------------
# Total retenciones
# --------------------------------------------------------------------------

# Etiquetas que aparecen junto al total, ordenadas por especificidad: la
# primera que golpea gana.
_ETIQUETAS_TOTAL = (
    ("TOTAL RETENCIONES M[ÁA]S SANCIONES M[ÁA]S INTERESES", "alta"),
    ("TOTAL A PAGAR ANTES DE DESCUENTOS", "alta"),
    ("TOTAL RETENCIONES PRACTICADAS", "alta"),
    ("TOTAL A PAGAR", "alta"),
    ("SALDO A PAGAR", "media"),
    ("TOTAL RETENCIONES", "media"),
)

# Cifra colombiana: 2.880.000 o 2.880.000,0 o $ 2.880.000. Se admite coma
# decimal seguida de uno o dos digitos, o punto decimal. Los decimales no
# suman en ICA -- las cifras son enteros por norma -- pero el borrador puede
# escribirlas con ,0 al final.
_RE_CIFRA = re.compile(
    r"\$?\s*(\d{1,3}(?:[.\s]\d{3})+|\d{4,})(?:[.,](\d{1,2}))?")

_ETIQUETAS_CANDIDATO = re.compile(
    r"TOTAL|RETENCI[ÓO]N|SANCI[ÓO]N|IMPUESTO", re.IGNORECASE)


def _cifra_a_decimal(entera: str, decimales: str | None) -> Decimal | None:
    try:
        limpio = _limpiar_digitos(entera)
        base = Decimal(limpio)
        if decimales:
            # Los ,0 al final son ruido de formato, no un valor menor a un
            # peso: se ignoran.
            return base
        return base
    except (InvalidOperation, ValueError):
        return None


def _extraer_total(texto: str) -> dict:
    lineas = texto.splitlines()

    # Etiqueta preferente en la misma linea o la siguiente.
    for etiqueta, confianza in _ETIQUETAS_TOTAL:
        re_et = re.compile(etiqueta, re.IGNORECASE)
        for i, linea in enumerate(lineas):
            if re_et.search(linea):
                # Buscar cifra en la misma linea y en la siguiente.
                for j in (i, i + 1):
                    if j >= len(lineas):
                        continue
                    m = _RE_CIFRA.search(lineas[j])
                    if m:
                        valor = _cifra_a_decimal(m.group(1), m.group(2))
                        if valor and valor > 0:
                            candidatos = _todos_los_candidatos(texto)
                            return {"total_declarado": valor,
                                    "total_confianza": confianza,
                                    "candidatos_total": candidatos}

    # Sin etiqueta clara: se ofrecen todos los numeros grandes junto a
    # etiquetas parecidas, y confianza baja para que el auditor elija.
    candidatos = _todos_los_candidatos(texto)
    if candidatos:
        return {"total_declarado": candidatos[0],
                "total_confianza": "baja",
                "candidatos_total": candidatos}
    return {}


def _todos_los_candidatos(texto: str) -> tuple:
    """Los numeros grandes que aparecen junto a etiquetas de total/retencion.

    Se ordenan por valor descendente: el TOTAL final suele ser el mayor.
    Se descartan duplicados y ceros.
    """
    vistos = set()
    encontrados = []
    for linea in texto.splitlines():
        if not _ETIQUETAS_CANDIDATO.search(linea):
            continue
        for m in _RE_CIFRA.finditer(linea):
            valor = _cifra_a_decimal(m.group(1), m.group(2))
            if valor and valor > 0 and valor not in vistos:
                vistos.add(valor)
                encontrados.append(valor)
    encontrados.sort(reverse=True)
    return tuple(encontrados[:8])
