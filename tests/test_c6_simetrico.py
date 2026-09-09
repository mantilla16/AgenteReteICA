"""C6 simetrico (tarea que sale de 3.1.bis).

Hoy C6 solo dispara cuando un SERVICIO esta en un renglon de COMERCIO. Al
reves no mira: una compra sentada en el renglon 5224 de manipulacion de carga
es invisible. Un control asimetrico deja media poblacion sin cubrir y no lo
dice.
"""

from datetime import date
from decimal import Decimal

import pytest

from motor_reteica.controles import c6_clasificacion_por_linea
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.reconstruccion import reconstruir
from motor_reteica.tipos import Estado, LineaAuxiliar, Severidad

CUENTA_10 = "2368010010"


def _linea(concepto, referencia="F1", nit="111"):
    return LineaAuxiliar(
        cuenta=CUENTA_10, nit=nit, tercero="P" + nit,
        fecha_documento=date(2026, 7, 1), fecha_contabilizacion=date(2026, 7, 1),
        referencia=referencia, documento="1", concepto=concepto,
        retencion=Decimal("10000"))


def _corre(lineas, codigo):
    recon = reconstruir(lineas, None, MUNICIPIO, {})
    mapa = {(l.nit, Decimal("0.010")): codigo for l in lineas}
    return c6_clasificacion_por_linea(recon, [], mapa, MUNICIPIO)


def test_servicio_en_renglon_de_comercio_sigue_disparando():
    """Lo que ya hacia. Es el caso CDEM."""
    resultado = _corre([_linea("REPARACION MANGUERA DE 6\"")], "4669")
    assert resultado.estado is Estado.FALLA
    assert any("servicio" in e.descripcion.lower()
               for e in resultado.excepciones)


def test_compra_en_renglon_de_servicios_ahora_tambien_dispara():
    """El lado que faltaba: una COMPRA en 5224 manipulacion de carga."""
    resultado = _corre([_linea("COMPRA DE ESCUALIZADOR SURTIDOR")], "5224")
    assert resultado.estado is Estado.FALLA
    excepciones = [e for e in resultado.excepciones
                   if "comercio" in e.descripcion.lower()
                   or "compra" in e.descripcion.lower()]
    assert excepciones, [e.descripcion for e in resultado.excepciones]
    assert excepciones[0].severidad is Severidad.OBSERVACION


def test_una_compra_en_renglon_de_comercio_no_dispara():
    assert _corre([_linea("COMPRA DE INSUMOS")], "4669").estado is Estado.OK


def test_un_servicio_en_renglon_de_servicios_no_dispara():
    assert _corre([_linea("SERVICIOS DE OPERACION PORTUARIA")], "5224").estado \
        is Estado.OK


def test_un_concepto_que_no_se_puede_clasificar_avisa_en_vez_de_callar():
    """Antes devolvia None y la linea se saltaba en silencio."""
    resultado = _corre([_linea("XYZ 123")], "4669")
    assert any(e.severidad is Severidad.AVISO for e in resultado.excepciones)


def test_un_concepto_ambiguo_avisa_en_vez_de_elegir_por_orden():
    """'SUMINISTRO E INSTALACION' golpea las dos listas.

    Antes ganaba SERVICIO solo porque se chequeaba primero. Eso no es juicio,
    es orden de lineas de codigo.
    """
    resultado = _corre([_linea("SUMINISTRO E INSTALACION DE VALVULA")], "4669")
    avisos = [e for e in resultado.excepciones if e.severidad is Severidad.AVISO]
    assert avisos, [e.descripcion for e in resultado.excepciones]
    assert any("ambig" in e.descripcion.lower() for e in avisos)
