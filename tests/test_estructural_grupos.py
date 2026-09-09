"""3.3 y 3.4: la unidad de cruce es el GRUPO (NIT, tarifa), no el tercero.

Julio 2026 cumple por casualidad que cada tercero tiene una sola tarifa y una
sola fila en el ERP. Con eso, dos defectos quedaban invisibles:

  3.3  {f.nit: f.retencion for f in filas_erp} DESCARTA filas: dos filas del
       mismo NIT (una al 10 por mil y otra al 7) dejaban solo la ultima.
  3.4  tarifa = del_tercero[0].tarifa aplicaba la tarifa de la primera linea
       a todo el tercero.

Un proveedor que factura compras (10 por mil) y servicios (7 por mil) es
normal. Con la unidad en el tercero, el motor daba una diferencia falsa.
"""

from datetime import date
from decimal import Decimal

import pytest

from motor_reteica.controles import c3_auxiliar_vs_erp, c5_coherencia_cuenta_codigo
from motor_reteica.ingesta.sap_retenciones import RetencionERP
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.reconstruccion import reconstruir
from motor_reteica.tipos import Estado, LineaAuxiliar

CUENTA_10 = "2368010010"
CUENTA_7 = "2368010007"
DIEZ = Decimal("0.010")
SIETE = Decimal("0.007")


def _linea(nit, cuenta, retencion, referencia="R1", concepto="COMPRA"):
    return LineaAuxiliar(
        cuenta=cuenta, nit=nit, tercero="PROVEEDOR " + nit,
        fecha_documento=date(2026, 7, 1), fecha_contabilizacion=date(2026, 7, 1),
        referencia=referencia, documento="1", concepto=concepto,
        retencion=Decimal(retencion))


# --------------------------------------------------------------------------
# 3.4 un tercero con dos tarifas
# --------------------------------------------------------------------------

@pytest.fixture
def dos_tarifas():
    """Un mismo NIT: 1.000.000 en compras al 10 y 1.000.000 en servicios al 7."""
    lineas = [
        _linea("111", CUENTA_10, "10000", "FC1", "COMPRA DE REPUESTOS"),
        _linea("111", CUENTA_7, "7000", "FS1", "SERVICIO DE ASESORIA"),
    ]
    erp = [
        RetencionERP(nit="111", codigo_ret="23", base=Decimal("1000000"),
                     retencion=Decimal("10000")),
        RetencionERP(nit="111", codigo_ret="39", base=Decimal("1000000"),
                     retencion=Decimal("7000")),
    ]
    return lineas, erp


def test_un_tercero_con_dos_tarifas_produce_dos_grupos(dos_tarifas):
    lineas, erp = dos_tarifas
    recon = reconstruir(lineas, erp, MUNICIPIO, {})
    assert len(recon.por_grupo) == 2
    assert {g.tarifa for g in recon.por_grupo.values()} == {DIEZ, SIETE}


def test_cada_grupo_recalcula_con_su_propia_tarifa(dos_tarifas):
    """Antes daba una diferencia falsa de -7.000 aplicando 10 por mil a todo."""
    lineas, erp = dos_tarifas
    recon = reconstruir(lineas, erp, MUNICIPIO, {})
    for grupo in recon.por_grupo.values():
        assert grupo.diferencia == Decimal("0"), grupo


def test_el_total_del_tercero_no_se_pierde(dos_tarifas):
    lineas, erp = dos_tarifas
    recon = reconstruir(lineas, erp, MUNICIPIO, {})
    total = sum(g.retencion_contable for g in recon.por_grupo.values())
    assert total == Decimal("17000")


# --------------------------------------------------------------------------
# 3.3 NITs repetidos en el reporte del ERP
# --------------------------------------------------------------------------

def test_c3_no_descarta_filas_del_mismo_nit(dos_tarifas):
    """Antes comparaba 17.000 del auxiliar contra 7.000 (la ultima fila)."""
    lineas, erp = dos_tarifas
    resultado = c3_auxiliar_vs_erp(lineas, erp)
    assert resultado.estado is Estado.OK, [e.descripcion
                                           for e in resultado.excepciones]


def test_c3_sigue_disparando_si_el_erp_de_verdad_no_cuadra(dos_tarifas):
    lineas, erp = dos_tarifas
    erp_malo = erp[:1] + [RetencionERP(nit="111", codigo_ret="39",
                                       base=Decimal("1000000"),
                                       retencion=Decimal("9000"))]
    resultado = c3_auxiliar_vs_erp(lineas, erp_malo)
    assert resultado.estado is Estado.FALLA
    assert any(e.impacto_pesos == Decimal("2000")
               for e in resultado.excepciones)


def test_c5_no_evalua_una_linea_contra_el_codigo_de_otra(dos_tarifas):
    """Antes {f.nit: f.codigo_ret} dejaba un solo codigo por NIT y la linea de
    compras se evaluaba contra el codigo de servicios."""
    lineas, erp = dos_tarifas
    resultado = c5_coherencia_cuenta_codigo(lineas, erp, MUNICIPIO)
    assert resultado.estado is Estado.OK, [e.descripcion
                                           for e in resultado.excepciones]


def test_c5_dispara_si_la_cuenta_no_tiene_respaldo_en_el_erp(dos_tarifas):
    """Una linea al 10 por mil cuyo NIT solo tiene codigos del 7 en el ERP."""
    lineas, _ = dos_tarifas
    solo_siete = [RetencionERP(nit="111", codigo_ret="39",
                               base=Decimal("2428571"),
                               retencion=Decimal("17000"))]
    resultado = c5_coherencia_cuenta_codigo(lineas, solo_siete, MUNICIPIO)
    assert resultado.estado is Estado.FALLA
    assert any("FC1" in e.descripcion for e in resultado.excepciones)
