"""Reconstruccion independiente de la declaracion.

De donde sale cada cifra:
  - tarifa    -> de la cuenta contable (2368010007 = 7 por mil)
  - retencion -> del libro auxiliar
  - base      -> del reporte del ERP

La base NO se deriva de la retencion. El auxiliar guarda la retencion ya
redondeada, asi que derivarla da 49.012.586 frente a los 49.012.569 reales, y
recalcular base_derivada x tarifa devuelve la retencion por construccion: un
control que pasa siempre. Cuando falta el reporte del ERP se deriva igual, pero
se marca base_es_derivada y C4 debe reportarse NO_EJECUTADO.

El mapa de actividades se toma del borrador SOLO para agrupar en renglones,
nunca para tarifar ni para valorar.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

MIL = Decimal("1000")
SIN_CLASIFICAR = "SIN_CLASIFICAR"
_UNIDAD = Decimal("1")


def redondear_al_mil(valor: Decimal) -> Decimal:
    return (valor / MIL).quantize(_UNIDAD, rounding=ROUND_HALF_UP) * MIL


def _a_peso(valor: Decimal) -> Decimal:
    return valor.quantize(_UNIDAD, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LineaValorada:
    linea: object
    tarifa: Decimal
    base_derivada: Decimal


@dataclass(frozen=True)
class TerceroReconstruido:
    nit: str
    tarifa: Decimal
    base: Decimal
    retencion_contable: Decimal
    retencion_recalculada: Decimal

    @property
    def diferencia(self) -> Decimal:
        return self.retencion_recalculada - self.retencion_contable


@dataclass(frozen=True)
class RenglonReconstruido:
    actividad: str
    tarifa: Decimal
    base_contable: Decimal
    impuesto_contable: Decimal

    @property
    def base_declarable(self) -> Decimal:
        return redondear_al_mil(self.base_contable)

    @property
    def impuesto_declarable(self) -> Decimal:
        return redondear_al_mil(self.impuesto_contable)


@dataclass(frozen=True)
class Reconstruccion:
    lineas_valoradas: list
    por_tercero: dict
    por_actividad: dict
    total_base: Decimal
    total_impuesto_contable: Decimal
    total_impuesto_declarable: Decimal
    base_es_derivada: bool


def reconstruir(lineas, filas_erp, municipio, mapa_actividad) -> Reconstruccion:
    base_es_derivada = filas_erp is None
    base_erp = {} if base_es_derivada else {f.nit: f.base for f in filas_erp}

    valoradas = [
        LineaValorada(
            linea=linea,
            tarifa=municipio.tarifa_por_cuenta[linea.cuenta],
            base_derivada=_a_peso(
                linea.retencion / municipio.tarifa_por_cuenta[linea.cuenta]),
        )
        for linea in lineas
    ]

    por_tercero = {}
    for nit in sorted({v.linea.nit for v in valoradas}):
        del_tercero = [v for v in valoradas if v.linea.nit == nit]
        tarifa = del_tercero[0].tarifa
        contable = sum((v.linea.retencion for v in del_tercero), Decimal("0"))
        base = base_erp.get(
            nit, sum((v.base_derivada for v in del_tercero), Decimal("0")))
        por_tercero[nit] = TerceroReconstruido(
            nit=nit, tarifa=tarifa, base=base,
            retencion_contable=contable,
            retencion_recalculada=_a_peso(base * tarifa),
        )

    acumulado = {}
    for tercero in por_tercero.values():
        codigo = mapa_actividad.get(tercero.nit, SIN_CLASIFICAR)
        base, impuesto, _ = acumulado.get(
            codigo, (Decimal("0"), Decimal("0"), tercero.tarifa))
        acumulado[codigo] = (base + tercero.base,
                             impuesto + tercero.retencion_contable,
                             tercero.tarifa)

    por_actividad = {
        codigo: RenglonReconstruido(actividad=codigo, tarifa=tarifa,
                                    base_contable=base, impuesto_contable=impuesto)
        for codigo, (base, impuesto, tarifa) in acumulado.items()
    }

    return Reconstruccion(
        lineas_valoradas=valoradas,
        por_tercero=por_tercero,
        por_actividad=por_actividad,
        total_base=sum((r.base_contable for r in por_actividad.values()), Decimal("0")),
        total_impuesto_contable=sum(
            (r.impuesto_contable for r in por_actividad.values()), Decimal("0")),
        total_impuesto_declarable=sum(
            (r.impuesto_declarable for r in por_actividad.values()), Decimal("0")),
        base_es_derivada=base_es_derivada,
    )
