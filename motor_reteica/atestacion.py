"""Atestacion del auditor: lo que el motor no puede decidir solo.

Tres decisiones distintas del diseno llegaron a la misma forma, y comparten
este mecanismo en vez de tener tres implementaciones:

  columnas del balance que el motor no reconoce   (1.4)
  tarifas sin Acuerdo municipal cargado           (X1)
  cuentas candidatas a contrapartida de pago      (M11)

La forma es siempre la misma: EL MOTOR SENALA LO QUE NO PUEDE DECIDIR SOLO,
LA PERSONA DECIDE, Y QUEDA IMPRESO EN EL PAPEL. No declarar NUNCA produce un
OK: produce NO EJECUTADO y el motor no avanza.

Dos reglas duras:

  - La atestacion lleva VALORES (una tarifa), asi que NO puede vivir en el
    manifiesto: el manifiesto declara identidad de archivos y nada mas (D1).
    Si el manifiesto aceptara cifras, el borrador volveria a ser fuente de
    parametros por la puerta de atras.
  - Toda atestacion EXIGE PROCEDENCIA: quien atesta, cuando, y contra que
    documento. Sin procedencia no es testimonio, es repetir el borrador con
    otra letra.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

NOMBRE_ARCHIVO = "atestacion.json"

CONTRAPARTIDA = "contrapartida"
RETENCION_PRACTICADA = "retencion_practicada"
_NATURALEZAS = (CONTRAPARTIDA, RETENCION_PRACTICADA)


class AtestacionInvalida(Exception):
    """La atestacion existe pero no sirve como evidencia."""


@dataclass(frozen=True)
class TarifaAtestada:
    municipio: str
    actividad: str
    tarifa: Decimal
    vigencia_desde: str
    acuerdo: str
    articulo: str

    def descripcion(self) -> str:
        return ("actividad %s al %s, segun %s articulo %s, vigente desde %s"
                % (self.actividad, self.tarifa, self.acuerdo, self.articulo,
                   self.vigencia_desde))


@dataclass(frozen=True)
class CuentaAtestada:
    cuenta: str
    naturaleza: str
    motivo: str


@dataclass(frozen=True)
class Atestacion:
    declarada_por: str
    fecha: str
    tarifas: dict = field(default_factory=dict)
    cuentas: dict = field(default_factory=dict)

    @property
    def hay_tarifas(self) -> bool:
        return bool(self.tarifas)

    def cuentas_excluidas(self) -> set:
        return {c.cuenta for c in self.cuentas.values()
                if c.naturaleza == CONTRAPARTIDA}

    def firma(self) -> str:
        return "%s el %s" % (self.declarada_por, self.fecha)


def _exigir(bloque, campo, contexto):
    valor = bloque.get(campo)
    if valor in (None, "", []):
        raise AtestacionInvalida(
            "%s: falta '%s'. Sin procedencia la atestacion no es testimonio, "
            "es repetir el borrador con otra letra." % (contexto, campo))
    return valor


def _en_blanco(entrada, campos) -> bool:
    """Una fila de la plantilla que nadie lleno.

    La plantilla se entrega con marcadores vacios. Una fila intacta significa
    "todavia no lo he declarado" -- y entonces el control que dependa de ella
    queda NO EJECUTADO, que es lo correcto -- no "el archivo es invalido".
    Rechazar el archivo entero por una fila sin llenar bloquearia la corrida
    por algo que el auditor deliberadamente dejo pendiente.

    Una fila a MEDIO llenar si es un error y se sigue rechazando.
    """
    return all(str(entrada.get(campo, "")).strip() == "" for campo in campos)


# Solo los campos que llena LA PERSONA. La plantilla trae ya puestos los que
# el motor conoce (el codigo de actividad, el numero de cuenta), asi que
# mirarlos haria que ninguna fila pareciera nunca intacta.
_CAMPOS_TARIFA = ("tarifa", "vigencia_desde", "acuerdo", "articulo")
_CAMPOS_CUENTA = ("naturaleza", "motivo")


def _leer_tarifas(crudo) -> dict:
    tarifas = {}
    for entrada in crudo:
        if _en_blanco(entrada, _CAMPOS_TARIFA):
            continue
        contexto = "tarifa de la actividad %r" % entrada.get("actividad", "?")
        atestada = TarifaAtestada(
            municipio=_exigir(entrada, "municipio", contexto),
            actividad=str(_exigir(entrada, "actividad", contexto)),
            tarifa=Decimal(str(_exigir(entrada, "tarifa", contexto))),
            vigencia_desde=str(_exigir(entrada, "vigencia_desde", contexto)),
            acuerdo=_exigir(entrada, "acuerdo", contexto),
            articulo=str(_exigir(entrada, "articulo", contexto)),
        )
        tarifas[atestada.actividad] = atestada
    return tarifas


def _leer_cuentas(crudo) -> dict:
    cuentas = {}
    for entrada in crudo:
        if _en_blanco(entrada, _CAMPOS_CUENTA):
            continue
        contexto = "cuenta %r" % entrada.get("cuenta", "?")
        naturaleza = _exigir(entrada, "naturaleza", contexto)
        if naturaleza not in _NATURALEZAS:
            raise AtestacionInvalida(
                "%s: naturaleza %r desconocida; debe ser una de %s"
                % (contexto, naturaleza, ", ".join(_NATURALEZAS)))
        atestada = CuentaAtestada(
            cuenta=str(_exigir(entrada, "cuenta", contexto)),
            naturaleza=naturaleza,
            motivo=_exigir(entrada, "motivo", contexto),
        )
        cuentas[atestada.cuenta] = atestada
    return cuentas


def leer_atestacion(carpeta) -> Atestacion:
    """Devuelve una Atestacion vacia si la carpeta no trae el archivo.

    Vacia NO significa 'todo bien': significa que nadie atesto nada, y los
    controles que dependen de una atestacion saldran NO EJECUTADO.
    """
    ruta = Path(carpeta) / NOMBRE_ARCHIVO
    if not ruta.exists():
        return Atestacion(declarada_por="", fecha="")

    crudo = json.loads(ruta.read_text(encoding="utf-8"))
    return Atestacion(
        declarada_por=_exigir(crudo, "declarada_por", "la atestacion"),
        fecha=str(_exigir(crudo, "fecha", "la atestacion")),
        tarifas=_leer_tarifas(crudo.get("tarifas", [])),
        cuentas=_leer_cuentas(crudo.get("cuentas", [])),
    )


NOMBRE_PLANTILLA = "atestacion.plantilla.json"


def escribir_plantilla(carpeta, municipio: str, actividades,
                       cuentas_candidatas) -> Path:
    """Deja lista la plantilla para que el auditor la complete (D2).

    Sin esto habia que redactar atestacion.json a mano, y por eso nadie
    atesto nunca: X1 quedaba como mecanismo sin usar y C7 en NO EJECUTADO
    mes tras mes.

    NO sobreescribe una atestacion real ya hecha, y se escribe aparte
    (atestacion.plantilla.json) para que completarla sea un paso deliberado:
    renombrarla es la firma.
    """
    ruta = Path(carpeta) / NOMBRE_PLANTILLA
    ruta.write_text(
        json.dumps(plantilla(municipio, actividades, cuentas_candidatas),
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return ruta


def plantilla(municipio: str, actividades, cuentas_candidatas) -> dict:
    """Esqueleto para que el auditor lo complete. D2: nada interactivo."""
    return {
        "declarada_por": "",
        "fecha": date.today().isoformat(),
        "tarifas": [
            {"municipio": municipio, "actividad": codigo, "tarifa": "",
             "vigencia_desde": "", "acuerdo": "", "articulo": ""}
            for codigo in sorted(actividades)
        ],
        "cuentas": [
            {"cuenta": cuenta, "naturaleza": "", "motivo": ""}
            for cuenta in sorted(cuentas_candidatas)
        ],
    }
