from datetime import date
from decimal import Decimal

import pytest

from motor_reteica.controles import (c6_clasificacion_por_linea, c8_corte,
                                     c11_cotejo_facturas, c12_continuidad,
                                     c13_formales, c14_compras_vs_servicios)
from motor_reteica.ingesta.facturas_pdf import leer_factura, REQUIERE_REVISION
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.tipos import Estado, Severidad

MAPA = {"800193573": "5224", "811033997": "4669", "830028245": "9903",
        "900392924": "9609", "901670478": "7490"}


@pytest.fixture(scope="module")
def facturas(base_fixtures):
    return [leer_factura(base_fixtures / "facturas" / n)
            for n in ("FE10.pdf", "250530.pdf", "FE338057.pdf")]


def test_lee_la_actividad_que_el_proveedor_declara(base_fixtures):
    f = leer_factura(base_fixtures / "facturas" / "FE10.pdf")
    assert f.nit == "901670478"
    assert f.base == Decimal("5000000")
    assert f.actividad_declarada == "7112"
    assert f.fecha == date(2026, 6, 26)


def test_la_fecha_no_es_la_autorizacion_de_la_dian(base_fixtures):
    """250530 se autorizo en 2025-08-06 y se emitio en 2026-07-27."""
    assert leer_factura(base_fixtures / "facturas" / "250530.pdf").fecha == date(2026, 7, 27)


def test_factura_ilegible_se_marca_para_revision(base_fixtures):
    f = leer_factura(base_fixtures / "facturas" / "FE338057.pdf")
    assert f.confianza == REQUIERE_REVISION


def test_c6_marca_observacion_la_actividad_discrepante_sin_impacto(recon, facturas):
    """FE10: el proveedor declara 7112 y el borrador clasifica 7490, ambas al 7 por mil."""
    r = c6_clasificacion_por_linea(recon, facturas, MAPA, MUNICIPIO)
    exc = next(e for e in r.excepciones if "7112" in e.descripcion)
    assert exc.severidad is Severidad.OBSERVACION
    assert exc.impacto_pesos == Decimal("0")


def test_c6_detecta_el_servicio_clasificado_como_comercio(recon, facturas):
    """CDEM: reparacion de manguera dentro del renglon 4669 comercio al por mayor."""
    r = c6_clasificacion_por_linea(recon, facturas, MAPA, MUNICIPIO)
    exc = next(e for e in r.excepciones if "FE338043" in e.descripcion)
    assert exc.severidad is Severidad.OBSERVACION
    assert exc.renglon == "4669"


def test_c8_no_dispara_porque_el_auxiliar_esta_todo_en_julio(lineas):
    r = c8_corte(lineas, "2026-07")
    assert r.estado is Estado.OK
    assert r.excepciones == ()


def test_c11_coteja_las_facturas_legibles(lineas, facturas):
    r = c11_cotejo_facturas(lineas, facturas, MUNICIPIO)
    assert any("FE338057" in e.descripcion for e in r.excepciones)


def test_c11_detecta_el_desfase_documental_de_fe10(lineas, facturas):
    """Factura del 26/06 registrada con fecha de documento 01/07."""
    r = c11_cotejo_facturas(lineas, facturas, MUNICIPIO)
    assert any("FE10" in e.descripcion and "fecha" in e.descripcion.lower()
               for e in r.excepciones)


def test_c11_sin_facturas_es_no_ejecutado(lineas):
    assert c11_cotejo_facturas(lineas, [], MUNICIPIO).estado is Estado.NO_EJECUTADO


def test_c12_sin_pago_anterior_es_no_ejecutado():
    assert c12_continuidad(None, None).estado is Estado.NO_EJECUTADO


def test_c12_detecta_pago_distinto_del_saldo():
    r = c12_continuidad(Decimal("500000"), Decimal("400000"))
    assert r.estado is Estado.FALLA


def test_c13_detecta_insumos_no_obtenidos(borrador):
    r = c13_formales(borrador, MUNICIPIO, {"borrador", "auxiliar"})
    assert r.estado is Estado.FALLA
    assert any("no obtenido" in e.descripcion.lower() for e in r.excepciones)


def test_c13_pasa_con_todos_los_insumos(borrador):
    completos = {"borrador", "auxiliar", "balance", "erp", "facturas", "pago_anterior"}
    assert c13_formales(borrador, MUNICIPIO, completos).estado is Estado.OK


def test_c14_no_aplica_en_santa_marta(recon):
    assert c14_compras_vs_servicios(recon, MUNICIPIO).estado is Estado.NO_EJECUTADO
