"""3.2 y 3.1.bis: el reparto de grupos por renglon.

El motor NO puede reconstruir la clasificacion: el auxiliar trae el concepto,
no el codigo CIIU. El auditor acepta la clasificacion del borrador (3.1.bis).
Lo que el motor SI puede hacer son tres cosas:

  CAPA 1  exigir que el renglon asignado pertenezca a la MISMA CLASE DE TARIFA
          que implica la cuenta contable. La cuenta esta en el auxiliar: es
          independiente del borrador. Cierra el caso que mueve pesos.
  CAPA 3  declarar que el reparto se tomo del borrador y no se verifico.
          C9 deja de decir OK a secas.

Y 3.2: cuando el reparto no se puede reproducir, el motor AVISA. Antes emitia
un HALLAZGO FALSO ("se reconstruyo pero no aparece en el borrador") porque
disponibles.remove() consumia el renglon y el segundo grupo caia en
SIN_CLASIFICAR.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from motor_reteica.controles import c9_reconstruccion_vs_borrador
from motor_reteica.ingesta.borrador_pdf import ActividadDeclarada
from motor_reteica.ingesta.sap_retenciones import RetencionERP
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.pipeline import mapa_actividad
from motor_reteica.reconstruccion import SIN_CLASIFICAR, reconstruir
from motor_reteica.tipos import Estado, LineaAuxiliar, Severidad

CUENTA_10 = "2368010010"
CUENTA_7 = "2368010007"


def _linea(nit, cuenta, retencion, referencia):
    return LineaAuxiliar(
        cuenta=cuenta, nit=nit, tercero="P" + nit,
        fecha_documento=date(2026, 7, 1), fecha_contabilizacion=date(2026, 7, 1),
        referencia=referencia, documento="1", concepto="COMPRA",
        retencion=Decimal(retencion))


def _actividad(codigo, base, por_mil):
    tarifa = Decimal(por_mil) / Decimal("1000")
    return ActividadDeclarada(codigo=codigo, descripcion=codigo, tarifa=tarifa,
                              base=Decimal(base),
                              impuesto=(Decimal(base) * tarifa).quantize(
                                  Decimal("1")))


class _Borrador:
    def __init__(self, actividades):
        self.actividades = actividades


# --------------------------------------------------------------------------
# 3.2 dos grupos en la misma actividad
# --------------------------------------------------------------------------

@pytest.fixture
def dos_grupos_un_renglon():
    """1.000.000 y 2.000.000 al 10 por mil contra un unico renglon de 3.000.000."""
    lineas = [_linea("111", CUENTA_10, "10000", "F1"),
              _linea("222", CUENTA_10, "20000", "F2")]
    erp = [RetencionERP(nit="111", codigo_ret="23", base=Decimal("1000000"),
                        retencion=Decimal("10000")),
           RetencionERP(nit="222", codigo_ret="23", base=Decimal("2000000"),
                        retencion=Decimal("20000"))]
    borrador = _Borrador([_actividad("4669", "3000000", "10")])
    return lineas, erp, borrador


def test_dos_grupos_en_una_actividad_no_dejan_el_mapa_vacio(dos_grupos_un_renglon):
    """Antes devolvia {} y el segundo grupo caia en SIN_CLASIFICAR."""
    lineas, erp, borrador = dos_grupos_un_renglon
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    assert mapa[("111", Decimal("0.010"))] == "4669"
    assert mapa[("222", Decimal("0.010"))] == "4669"


def test_dos_grupos_en_una_actividad_no_producen_hallazgo_falso(dos_grupos_un_renglon):
    lineas, erp, borrador = dos_grupos_un_renglon
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    recon = reconstruir(lineas, erp, MUNICIPIO, mapa)
    assert SIN_CLASIFICAR not in recon.por_actividad
    resultado = c9_reconstruccion_vs_borrador(recon, borrador)
    assert not [e for e in resultado.excepciones
                if e.severidad is Severidad.HALLAZGO], \
        [e.descripcion for e in resultado.excepciones]


# --------------------------------------------------------------------------
# CAPA 1: coherencia cuenta contable <-> clase de tarifa del renglon
# --------------------------------------------------------------------------

def test_capa1_dispara_si_no_hay_renglon_de_la_clase_de_tarifa_de_la_cuenta():
    """El auxiliar retuvo al 10 por mil; el borrador solo declara renglones
    al 7. La cuenta contable NO sale del borrador: la contradiccion es real."""
    lineas = [_linea("111", CUENTA_10, "10000", "F1")]
    erp = [RetencionERP(nit="111", codigo_ret="23", base=Decimal("1000000"),
                        retencion=Decimal("10000"))]
    borrador = _Borrador([_actividad("7490", "1000000", "7")])

    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    recon = reconstruir(lineas, erp, MUNICIPIO, mapa)
    resultado = c9_reconstruccion_vs_borrador(recon, borrador)

    assert resultado.estado is Estado.FALLA
    capa1 = [e for e in resultado.excepciones if "tarifa" in e.descripcion]
    assert capa1, [e.descripcion for e in resultado.excepciones]
    assert capa1[0].severidad is Severidad.HALLAZGO
    assert capa1[0].impacto_pesos > 0


def test_capa1_no_dispara_cuando_las_clases_coinciden(dos_grupos_un_renglon):
    lineas, erp, borrador = dos_grupos_un_renglon
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    recon = reconstruir(lineas, erp, MUNICIPIO, mapa)
    resultado = c9_reconstruccion_vs_borrador(recon, borrador)
    assert not [e for e in resultado.excepciones if "tarifa" in e.descripcion]


def test_el_mapa_jamas_asigna_a_un_renglon_de_otra_clase_de_tarifa():
    """Un grupo al 10 por mil no puede terminar en un renglon al 7, ni siquiera
    si los montos coinciden. Ese emparejamiento por monto era el que permitia
    que el borrador dictara la clasificacion sin control."""
    lineas = [_linea("111", CUENTA_10, "10000", "F1")]
    erp = [RetencionERP(nit="111", codigo_ret="23", base=Decimal("1000000"),
                        retencion=Decimal("10000"))]
    borrador = _Borrador([_actividad("7490", "1000000", "7")])
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    assert mapa.get(("111", Decimal("0.010"))) != "7490"


# --------------------------------------------------------------------------
# CAPA 3: C9 declara el limite de su alcance
# --------------------------------------------------------------------------

def test_c9_declara_que_no_verifico_el_reparto(dos_grupos_un_renglon):
    lineas, erp, borrador = dos_grupos_un_renglon
    mapa = mapa_actividad(borrador, erp, lineas, MUNICIPIO)
    recon = reconstruir(lineas, erp, MUNICIPIO, mapa)
    detalle = c9_reconstruccion_vs_borrador(recon, borrador).detalle.lower()
    assert "reparto" in detalle
    assert "no se verific" in detalle


def test_c9_sigue_disparando_por_montos(dos_grupos_un_renglon):
    """La dimension de montos no se debilita."""
    lineas, erp, borrador = dos_grupos_un_renglon
    torcido = _Borrador([_actividad("4669", "9000000", "10")])
    mapa = mapa_actividad(torcido, erp, lineas, MUNICIPIO)
    recon = reconstruir(lineas, erp, MUNICIPIO, mapa)
    resultado = c9_reconstruccion_vs_borrador(recon, torcido)
    assert resultado.estado is Estado.FALLA
    assert any(e.severidad is Severidad.HALLAZGO
               for e in resultado.excepciones)
