"""Tipos base del motor. Todo importe monetario es Decimal, nunca float."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class Estado(Enum):
    """Cuatro estados. La ausencia de un insumo no es un OK.

    ATESTADO (X1) es el cuarto: cuando el auditor pone su nombre respaldando
    un dato que el motor no pudo verificar contra una fuente externa. No es OK
    -- nadie recalculo contra el estatuto -- ni NO_EJECUTADO -- si hubo
    procedimiento. El papel debe decir cual de los cuatro fue.
    """

    OK = "OK"
    FALLA = "FALLA"
    NO_EJECUTADO = "NO EJECUTADO"
    ATESTADO = "ATESTADO"


class Severidad(Enum):
    HALLAZGO = "HALLAZGO"
    OBSERVACION = "OBSERVACION"
    AVISO = "AVISO"


# M13: Excepcion.renglon esta sobrecargado -- distintos controles meten ahi
# una cuenta contable (C2/C5/C8/C11/C13), un NIT (C3/C4/C9) o un renglon real
# del formulario (C6/C7/C9). Renombrar `renglon` tocaria cada llamada, cada
# prueba que lo lee y el encabezado de la hoja Excepciones/Notas del papel,
# por una ganancia mayormente cosmetica. En vez de eso, `tipo_referencia`
# etiqueta que tipo de dato es, de forma aditiva: no cambia el significado de
# `renglon` para quien ya lo consume, solo lo hace explicito para quien
# necesite ordenar o mostrar por tipo (la hoja Notas de 5.4, por ejemplo).
REF_CUENTA = "cuenta"
REF_NIT = "nit"
REF_RENGLON = "renglon"
REF_SIN_TIPO = ""


@dataclass(frozen=True)
class LineaAuxiliar:
    """Unidad atomica del motor: una linea del auxiliar, no un tercero."""

    cuenta: str
    nit: str
    tercero: str
    fecha_documento: date
    fecha_contabilizacion: date
    referencia: str
    documento: str
    concepto: str
    retencion: Decimal

    def __post_init__(self):
        if not isinstance(self.retencion, Decimal):
            raise TypeError(
                "retencion debe ser Decimal, no %s" % type(self.retencion).__name__
            )


@dataclass(frozen=True)
class Excepcion:
    severidad: Severidad
    control: str
    descripcion: str
    renglon: str = ""
    impacto_pesos: Decimal = Decimal("0")
    # M13: que TIPO de dato trae `renglon` en esta excepcion puntual. Ver
    # nota junto a REF_CUENTA/REF_NIT/REF_RENGLON mas arriba.
    tipo_referencia: str = REF_SIN_TIPO


@dataclass(frozen=True)
class ResultadoControl:
    codigo: str
    nombre: str
    estado: Estado
    detalle: str
    excepciones: tuple = field(default_factory=tuple)
    # Un control que el municipio no exige NO es un control sin ejecutar:
    # confundirlos degrada la conclusion del papel.
    aplica: bool = True

    @property
    def paso(self) -> bool:
        return self.estado is Estado.OK
