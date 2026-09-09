"""3.5: mutacion ESTRUCTURAL, no solo de valores.

La prueba de mutacion del spec altera cifras sobre la misma forma de datos:
5 terceros, 5 renglones, una tarifa por tercero, 12 lineas. Julio 2026 cumple
esa forma por casualidad. Un motor probado solo contra ella no esta probado.

Aqui se cambia la FORMA: muchos terceros en el mismo renglon, muchas lineas
por tercero, y las dos clases de tarifa mezcladas.
"""

from datetime import date
from decimal import Decimal

import pytest

from motor_reteica.controles import (c3_auxiliar_vs_erp, c4_recalculo,
                                     c9_reconstruccion_vs_borrador)
from motor_reteica.ingesta.borrador_pdf import ActividadDeclarada
from motor_reteica.ingesta.sap_retenciones import RetencionERP
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import mapa_actividad
from motor_reteica.reconstruccion import SIN_CLASIFICAR, reconstruir
from motor_reteica.tipos import Estado, LineaAuxiliar, Severidad

CUENTA = {Decimal("0.010"): "2368010010", Decimal("0.007"): "2368010007"}
CODIGO = {Decimal("0.010"): "23", Decimal("0.007"): "39"}


class _Borrador:
    def __init__(self, actividades):
        self.actividades = actividades


@pytest.fixture(scope="module")
def mes_grande():
    """40 lineas, 20 terceros, dos clases de tarifa, dos renglones.

    Cada tercero tiene DOS lineas -- el caso que rompia la unidad "una linea
    por tercero" -- y diez terceros comparten cada renglon.
    """
    lineas, filas_erp = [], []
    total = {Decimal("0.010"): Decimal("0"), Decimal("0.007"): Decimal("0")}

    for indice in range(20):
        tarifa = Decimal("0.010") if indice % 2 == 0 else Decimal("0.007")
        nit = "9%08d" % indice
        base_total = Decimal("1000000") + Decimal(indice) * Decimal("100000")
        retencion_total = (base_total * tarifa).quantize(Decimal("1"))
        mitad = retencion_total / 2

        for parte in (1, 2):
            lineas.append(LineaAuxiliar(
                cuenta=CUENTA[tarifa], nit=nit, tercero="P%s" % nit,
                fecha_documento=date(2026, 7, parte),
                fecha_contabilizacion=date(2026, 7, parte),
                referencia="F%s-%d" % (nit, parte), documento=str(parte),
                concepto="COMPRA DE INSUMOS",
                retencion=(mitad if parte == 1
                           else retencion_total - mitad).quantize(Decimal("1"))))

        filas_erp.append(RetencionERP(nit=nit, codigo_ret=CODIGO[tarifa],
                                      base=base_total,
                                      retencion=retencion_total))
        total[tarifa] += base_total

    borrador = _Borrador([
        ActividadDeclarada(codigo="4669", descripcion="COMERCIO",
                           tarifa=Decimal("0.010"), base=total[Decimal("0.010")],
                           impuesto=(total[Decimal("0.010")] * Decimal("0.010")
                                     ).quantize(Decimal("1"))),
        ActividadDeclarada(codigo="7490", descripcion="PROFESIONALES",
                           tarifa=Decimal("0.007"), base=total[Decimal("0.007")],
                           impuesto=(total[Decimal("0.007")] * Decimal("0.007")
                                     ).quantize(Decimal("1"))),
    ])
    return lineas, filas_erp, borrador


def test_cuarenta_lineas_veinte_grupos(mes_grande):
    lineas, erp, borrador = mes_grande
    recon = reconstruir(lineas, erp, MUNICIPIO,
                        mapa_actividad(borrador, erp, lineas, MUNICIPIO))
    assert len(lineas) == 40
    assert len(recon.por_grupo) == 20


def test_diez_grupos_por_renglon_se_reparten_sin_inventar(mes_grande):
    lineas, erp, borrador = mes_grande
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    assert len(mapa) == 20
    assert sorted(set(mapa.values())) == ["4669", "7490"]


def test_no_queda_nada_sin_clasificar(mes_grande):
    lineas, erp, borrador = mes_grande
    recon = reconstruir(lineas, erp, MUNICIPIO,
                        mapa_actividad(borrador, erp, lineas, MUNICIPIO))
    assert SIN_CLASIFICAR not in recon.por_actividad


def test_c3_c4_y_c9_cuadran_a_escala(mes_grande):
    lineas, erp, borrador = mes_grande
    recon = reconstruir(lineas, erp, MUNICIPIO,
                        mapa_actividad(borrador, erp, lineas, MUNICIPIO))
    assert c3_auxiliar_vs_erp(lineas, erp).estado is Estado.OK
    assert c4_recalculo(recon).estado is Estado.OK
    resultado = c9_reconstruccion_vs_borrador(recon, borrador)
    graves = [e for e in resultado.excepciones
              if e.severidad is Severidad.HALLAZGO]
    assert graves == [], [e.descripcion for e in graves]


def test_a_escala_una_retencion_alterada_si_dispara(mes_grande):
    """La forma grande no puede volver ciego al motor."""
    from dataclasses import replace
    lineas, erp, borrador = mes_grande
    torcidas = [replace(lineas[0], retencion=lineas[0].retencion + Decimal("5000"))]
    torcidas += lineas[1:]
    assert c3_auxiliar_vs_erp(torcidas, erp).estado is Estado.FALLA
