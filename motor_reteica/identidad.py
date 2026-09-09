"""C0: identidad de las fuentes.

Si el borrador, el auxiliar y el periodo esperado no hablan de la misma
entidad y el mismo mes, todo control posterior seria un cruce sobre datos
distintos. Por eso este control no reporta FALLA: detiene el proceso.

1.5: con el manifiesto libre (ver manifiesto.py) aparece un riesgo nuevo
que el nombre de archivo literal evitaba por accidente: si el auditor
declara el balance en el rol del auxiliar, el motor lo cargaria igual y
reventaria mas adelante con un traceback dificil de leer. C0 verifica
ahora una tercera pata ademas de NIT y periodo: la NATURALEZA del
documento, comparando la firma de columnas real contra el rol declarado.
"""

import hashlib
from pathlib import Path

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import detectar_tipo_documento
from motor_reteica.tipos import Estado, ResultadoControl

_ROLES_CON_FIRMA = ("auxiliar", "balance", "erp")


class IdentidadIncompatible(Exception):
    """Las fuentes no pertenecen a la misma entidad y periodo."""


def huella(ruta: Path) -> str:
    return hashlib.sha256(Path(ruta).read_bytes()).hexdigest()


def verificar_tipo_documento(rol: str, ruta: Path) -> None:
    """1.5: confirma que el archivo declarado en `rol` tiene la estructura
    de ese tipo de documento contable, antes de intentar leerlo en serio.

    El borrador (PDF) y las facturas no tienen esta firma tabular: se
    saltan. Para los tres roles contables (auxiliar/balance/erp) se busca
    la firma de cada tipo conocido y se exige que coincida con el rol
    declarado.
    """
    if rol not in _ROLES_CON_FIRMA:
        return

    hoja = "BALANCE" if rol == "balance" else None
    filas = leer_filas(ruta, hoja=hoja)
    detectado = detectar_tipo_documento(filas)
    if detectado != rol:
        raise IdentidadIncompatible(
            "el manifiesto declara '%s' en el rol '%s', pero la estructura "
            "de ese archivo corresponde a %s, no a %s"
            % (Path(ruta).name, rol,
               "'%s'" % detectado if detectado else "un tipo de documento no reconocido",
               rol))


def verificar_identidad(borrador, lineas, nit_esperado: str,
                        periodo_esperado: str) -> ResultadoControl:
    if borrador.nit != nit_esperado:
        raise IdentidadIncompatible(
            "el borrador es del NIT %s y se esperaba %s"
            % (borrador.nit, nit_esperado))

    if borrador.periodo != periodo_esperado:
        raise IdentidadIncompatible(
            "el borrador es del periodo %s y se esperaba %s"
            % (borrador.periodo, periodo_esperado))

    anio, mes = (int(parte) for parte in periodo_esperado.split("-"))
    fuera = [l for l in lineas
             if (l.fecha_contabilizacion.year,
                 l.fecha_contabilizacion.month) != (anio, mes)]
    if fuera:
        raise IdentidadIncompatible(
            "%d linea(s) del auxiliar estan contabilizadas fuera de %s: %s"
            % (len(fuera), periodo_esperado,
               ", ".join(sorted({l.referencia for l in fuera}))))

    return ResultadoControl(
        codigo="C0",
        nombre="Identidad de las fuentes",
        estado=Estado.OK,
        detalle="NIT %s, periodo %s, municipio %s, %d linea(s) de auxiliar"
                % (borrador.nit, borrador.periodo, borrador.municipio, len(lineas)),
    )
