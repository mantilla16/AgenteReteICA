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
class GrupoReconstruido:
    """Unidad de cruce: un NIT a UNA tarifa.

    3.4: antes la unidad era el tercero y se le aplicaba
    `del_tercero[0].tarifa` a todas sus lineas. Un proveedor que factura
    compras (10 por mil) y servicios (7 por mil) -- que es lo normal -- daba
    una diferencia falsa. Julio 2026 no lo mostraba porque cada tercero tenia
    una sola tarifa.
    """

    nit: str
    tarifa: Decimal
    base: Decimal
    retencion_contable: Decimal
    retencion_recalculada: Decimal

    @property
    def clave(self) -> tuple:
        return (self.nit, self.tarifa)

    @property
    def diferencia(self) -> Decimal:
        return self.retencion_recalculada - self.retencion_contable


# Nombre anterior, conservado para no romper importaciones existentes.
TerceroReconstruido = GrupoReconstruido


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
    por_grupo: dict
    por_actividad: dict
    total_base: Decimal
    total_impuesto_contable: Decimal
    total_impuesto_declarable: Decimal
    base_es_derivada: bool

    @property
    def por_tercero(self) -> dict:
        """Alias historico. La unidad real es el grupo (NIT, tarifa); cuando
        cada tercero tiene una sola tarifa -- el caso de julio 2026 -- ambos
        coinciden en cantidad."""
        return self.por_grupo


def reconstruir(lineas, filas_erp, municipio, mapa_actividad) -> Reconstruccion:
    base_es_derivada = filas_erp is None
    # 3.3: el ERP se agrega por (NIT, tarifa), NO por NIT. Antes
    # `{f.nit: f.base for f in filas_erp}` descartaba filas: dos filas del
    # mismo NIT con codigos de retencion distintos dejaban solo la ultima.
    base_erp = {}
    if not base_es_derivada:
        for fila in filas_erp:
            tarifa = municipio.tarifa_por_codigo_ret.get(fila.codigo_ret)
            if tarifa is None:
                continue
            clave = (fila.nit, tarifa)
            base_erp[clave] = base_erp.get(clave, Decimal("0")) + fila.base

    valoradas = [
        LineaValorada(
            linea=linea,
            tarifa=municipio.tarifa_por_cuenta[linea.cuenta],
            base_derivada=_a_peso(
                linea.retencion / municipio.tarifa_por_cuenta[linea.cuenta]),
        )
        for linea in lineas
    ]

    por_grupo = {}
    for clave in sorted({(v.linea.nit, v.tarifa) for v in valoradas}):
        nit, tarifa = clave
        del_grupo = [v for v in valoradas
                     if v.linea.nit == nit and v.tarifa == tarifa]
        contable = sum((v.linea.retencion for v in del_grupo), Decimal("0"))
        base = base_erp.get(
            clave, sum((v.base_derivada for v in del_grupo), Decimal("0")))
        por_grupo[clave] = GrupoReconstruido(
            nit=nit, tarifa=tarifa, base=base,
            retencion_contable=contable,
            retencion_recalculada=_a_peso(base * tarifa),
        )

    acumulado = {}
    for grupo in por_grupo.values():
        codigo = mapa_actividad.get(grupo.clave,
                                    mapa_actividad.get(grupo.nit, SIN_CLASIFICAR))
        base, impuesto, _ = acumulado.get(
            codigo, (Decimal("0"), Decimal("0"), grupo.tarifa))
        acumulado[codigo] = (base + grupo.base,
                             impuesto + grupo.retencion_contable,
                             grupo.tarifa)

    por_actividad = {
        codigo: RenglonReconstruido(actividad=codigo, tarifa=tarifa,
                                    base_contable=base, impuesto_contable=impuesto)
        for codigo, (base, impuesto, tarifa) in acumulado.items()
    }

    return Reconstruccion(
        lineas_valoradas=valoradas,
        por_grupo=por_grupo,
        por_actividad=por_actividad,
        total_base=sum((r.base_contable for r in por_actividad.values()), Decimal("0")),
        total_impuesto_contable=sum(
            (r.impuesto_contable for r in por_actividad.values()), Decimal("0")),
        total_impuesto_declarable=sum(
            (r.impuesto_declarable for r in por_actividad.values()), Decimal("0")),
        base_es_derivada=base_es_derivada,
    )
