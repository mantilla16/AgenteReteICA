"""2.1: C11 verifica la BASE y la RETENCION, no solo NIT y fecha.

Es el unico control que va del documento fuente al registro contable sin pasar
por el ERP ni por el borrador. La tarifa sale de la cuenta contable, que esta
en el auxiliar, no del borrador: el amarre es independiente del objeto de
prueba.

    base_del_PDF x tarifa_de_la_cuenta == retencion_del_auxiliar

Medido sobre las tres facturas reales de julio 2026:
    250530    1.829.605 x 10 por mil = 18.296 vs 18.296
    FE10      5.000.000 x  7 por mil = 35.000 vs 35.000
    FE338057  1.196.993 x 10 por mil = 11.970 vs 11.970

FE338057 sale REQUIERE_REVISION porque su NIT no esta en la capa de texto del
PDF, pero SU BASE SI. Antes de 2.1, C11 la descartaba entera por eso y la base
recuperada en 2.0 no se usaba nunca. Ahora cada campo se verifica por separado
y el control declara cual pudo y cual no.
"""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from motor_reteica.controles import c11_cotejo_facturas
from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.facturas_pdf import leer_factura
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.tipos import Estado, Severidad

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


@pytest.fixture(scope="module")
def lineas():
    return leer_auxiliar(BASE / "auxiliar_2368.xlsx")


@pytest.fixture(scope="module")
def facturas():
    return [leer_factura(p, nit_cliente="819002433")
            for p in sorted((BASE / "facturas").glob("*.pdf"))]


def _de(facturas, numero):
    return next(f for f in facturas if f.numero == numero)


def _excepciones_de(resultado, numero):
    return [e for e in resultado.excepciones if numero in e.descripcion]


# --------------------------------------------------------------------------
# Lo que debe pasar con los datos correctos
# --------------------------------------------------------------------------

def test_las_tres_bases_cuadran_contra_el_auxiliar(lineas, facturas):
    """El ancla de 2.1: ninguna de las tres levanta excepcion por base."""
    resultado = c11_cotejo_facturas(lineas, facturas, MUNICIPIO)
    por_base = [e for e in resultado.excepciones if "base" in e.descripcion]
    assert por_base == [], [e.descripcion for e in por_base]


def test_fe338057_se_verifica_en_base_aunque_no_tenga_nit(lineas, facturas):
    """Antes se descartaba entera. Ahora la base si se coteja."""
    resultado = c11_cotejo_facturas(lineas, facturas, MUNICIPIO)
    suyas = _excepciones_de(resultado, "FE338057")
    assert suyas, "FE338057 debe seguir avisando algo: su NIT no es legible"
    assert all(e.severidad is Severidad.AVISO for e in suyas)
    assert any("NIT" in e.descripcion for e in suyas)
    assert not any("base" in e.descripcion for e in suyas)


def test_el_detalle_no_sobreafirma_el_alcance(lineas, facturas):
    """M8: no puede decir '3 facturas cotejadas' a secas."""
    detalle = c11_cotejo_facturas(lineas, facturas, MUNICIPIO).detalle
    assert "3" in detalle
    assert "base" in detalle.lower()


# --------------------------------------------------------------------------
# Mutaciones: cada una debe hacer disparar C11
# --------------------------------------------------------------------------

def test_mutacion_base_alterada_dispara_hallazgo_con_impacto(lineas, facturas):
    """Si el PDF dijera otra base, la retencion contabilizada no cuadraria.

    Se muta el objeto leido, NO la fixture: el PDF real no se toca.
    """
    mutadas = [replace(f, base=Decimal("2000000")) if f.numero == "250530" else f
               for f in facturas]
    resultado = c11_cotejo_facturas(lineas, mutadas, MUNICIPIO)

    assert resultado.estado is Estado.FALLA
    suyas = [e for e in _excepciones_de(resultado, "250530")
             if e.severidad is Severidad.HALLAZGO]
    assert len(suyas) == 1
    # 2.000.000 x 10 por mil = 20.000 contra 18.296 contabilizados
    assert suyas[0].impacto_pesos == Decimal("1704")


def test_mutacion_de_un_peso_tambien_dispara(lineas, facturas):
    """La tolerancia absorbe el redondeo del ERP, no una diferencia real."""
    mutadas = [replace(f, base=Decimal("1830000")) if f.numero == "250530" else f
               for f in facturas]
    resultado = c11_cotejo_facturas(lineas, mutadas, MUNICIPIO)
    assert resultado.estado is Estado.FALLA


def test_una_diferencia_dentro_de_tolerancia_no_dispara(lineas, facturas):
    """1.829.650 x 10 por mil = 18.297 contra 18.296: un peso, del redondeo."""
    mutadas = [replace(f, base=Decimal("1829650")) if f.numero == "250530" else f
               for f in facturas]
    resultado = c11_cotejo_facturas(lineas, mutadas, MUNICIPIO)
    assert not [e for e in _excepciones_de(resultado, "250530")
                if e.severidad is Severidad.HALLAZGO]


def test_la_tarifa_sale_de_la_cuenta_no_del_borrador(lineas, facturas):
    """Si la tarifa viniera del borrador, C11 dejaria de ser independiente.

    Se cambia la tabla del municipio: la esperada cambia y el control
    dispara. Prueba que la tarifa se lee de tarifa_por_cuenta.
    """
    from dataclasses import replace as reemplazar
    otro = reemplazar(MUNICIPIO, tarifa_por_cuenta={
        **MUNICIPIO.tarifa_por_cuenta, "2368010010": Decimal("0.020")})
    resultado = c11_cotejo_facturas(lineas, facturas, otro)
    assert resultado.estado is Estado.FALLA


# --------------------------------------------------------------------------
# Lo que ya hacia y no puede perder
# --------------------------------------------------------------------------

def test_sigue_detectando_el_desfase_de_fecha_de_fe10(lineas, facturas):
    resultado = c11_cotejo_facturas(lineas, facturas, MUNICIPIO)
    fechas = [e for e in _excepciones_de(resultado, "FE10")
              if "fecha" in e.descripcion]
    assert len(fechas) == 1
    assert fechas[0].severidad is Severidad.OBSERVACION


def test_sin_facturas_sigue_siendo_no_ejecutado(lineas):
    assert c11_cotejo_facturas(lineas, [], MUNICIPIO).estado is Estado.NO_EJECUTADO


def test_factura_que_no_esta_en_el_auxiliar_sigue_siendo_hallazgo(lineas, facturas):
    huerfana = replace(_de(facturas, "FE10"), numero="FE99999")
    resultado = c11_cotejo_facturas(lineas, [huerfana], MUNICIPIO)
    assert resultado.estado is Estado.FALLA
    assert any(e.severidad is Severidad.HALLAZGO
               for e in _excepciones_de(resultado, "FE99999"))
