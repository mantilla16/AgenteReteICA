"""1.1 - Manifiesto de fuentes.

Antes, pipeline.py exigia nombres de archivo literales (borrador.pdf,
auxiliar_2368.xlsx, ...). La carpeta real del cliente nunca trae esos
nombres: hay que renombrar 4 archivos a mano solo para poder correr. El
manifiesto declara rol -> nombre real del archivo, y se conserva el
nombre original del cliente (dice cosas utiles: que el auxiliar es la
version "DEF", por ejemplo).

D1 -- LIMITE DURO: el manifiesto declara IDENTIDAD DE ARCHIVOS, nunca
valores contables. Si aceptara cifras, el borrador volveria a ser fuente
de parametros por la puerta de atras. Este modulo es standalone: no
importa nada de parametros/ ni de ingesta/borrador_pdf.py, y nada en
parametros/ lo importa a el.

D2 -- NADA INTERACTIVO. Si falta el manifiesto o esta incompleto, se
escribe (o se deja) una plantilla con los roles pendientes marcados y el
motor se detiene con un mensaje util. El auditor la completa a mano y
reejecuta. Nunca se le pregunta nada por teclado.

Un insumo que el cliente no entrego se declara con `null` EXPLICITO en el
JSON (una afirmacion: "no lo entrego"), nunca por ausencia de la llave
(1.4.c, extendido de columnas a archivos): la ausencia de la llave es
"todavia no lo decidi" (PENDIENTE_DE_DECLARAR), y eso tambien bloquea.
"""

import json
from dataclasses import dataclass
from pathlib import Path

ROLES_OBLIGATORIOS = ("borrador", "auxiliar")
ROLES_OPCIONALES = ("balance", "erp", "facturas", "pago_anterior")
ROLES = ROLES_OBLIGATORIOS + ROLES_OPCIONALES

PENDIENTE = "PENDIENTE_DE_DECLARAR"
NOMBRE_ARCHIVO = "manifiesto.json"


class ManifiestoIncompleto(Exception):
    """El manifiesto no existe, o le falta declarar algun campo o rol."""


@dataclass(frozen=True)
class Manifiesto:
    nit: str
    periodo: str
    municipio: str
    declarado_por: str
    fecha: str
    archivos: dict  # rol -> nombre de archivo, o None si el cliente no lo entrego


def _plantilla() -> dict:
    return {
        "nit": None,
        "periodo": None,
        "municipio": None,
        "declarado_por": None,
        "fecha": None,
        "archivos": {rol: PENDIENTE for rol in ROLES},
    }


def _escribir_plantilla(ruta: Path) -> None:
    ruta.write_text(
        json.dumps(_plantilla(), indent=2, ensure_ascii=False, sort_keys=False),
        encoding="utf-8")


def leer_manifiesto(carpeta: Path) -> Manifiesto:
    carpeta = Path(carpeta)
    ruta = carpeta / NOMBRE_ARCHIVO

    if not ruta.exists():
        _escribir_plantilla(ruta)
        raise ManifiestoIncompleto(
            "no existe %s en %s; se escribio una plantilla. Complete "
            "rol->nombre de archivo real para cada rol (o null explicito "
            "si el cliente no lo entrego), mas nit/periodo/municipio/"
            "declarado_por/fecha, y reejecute" % (NOMBRE_ARCHIVO, carpeta))

    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ManifiestoIncompleto(
            "%s no es JSON valido: %s" % (NOMBRE_ARCHIVO, error)) from error

    archivos = datos.get("archivos", {})
    pendientes = [rol for rol in ROLES
                 if rol not in archivos or archivos[rol] == PENDIENTE]
    if pendientes:
        raise ManifiestoIncompleto(
            "%s no declara el rol de: %s (use el nombre real del archivo, "
            "o null explicito si el cliente no lo entrego)"
            % (NOMBRE_ARCHIVO, ", ".join(pendientes)))

    faltantes_obligatorios = [rol for rol in ROLES_OBLIGATORIOS
                              if archivos.get(rol) is None]
    if faltantes_obligatorios:
        raise ManifiestoIncompleto(
            "%s declara null en un rol obligatorio: %s. Sin ese archivo no "
            "hay revision posible" % (NOMBRE_ARCHIVO, ", ".join(faltantes_obligatorios)))

    campos_identidad = ("nit", "periodo", "municipio", "declarado_por", "fecha")
    faltantes_identidad = [campo for campo in campos_identidad if not datos.get(campo)]
    if faltantes_identidad:
        raise ManifiestoIncompleto(
            "%s no declara: %s" % (NOMBRE_ARCHIVO, ", ".join(faltantes_identidad)))

    return Manifiesto(
        nit=datos["nit"], periodo=datos["periodo"], municipio=datos["municipio"],
        declarado_por=datos["declarado_por"], fecha=datos["fecha"],
        archivos=archivos,
    )
