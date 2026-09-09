from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta.borrador_pdf import leer_borrador

FIXTURE = Path(__file__).parent / "fixtures" / "terlica_202607" / "borrador.pdf"


def test_identifica_contribuyente_y_periodo():
    b = leer_borrador(FIXTURE)
    assert b.nit == "819002433"
    assert b.municipio.upper() == "SANTA MARTA"
    assert b.anio == 2026
    assert b.periodo == "2026-07"
    assert b.numero_formulario == "120260043072"


def test_lee_los_cinco_renglones_de_actividad():
    b = leer_borrador(FIXTURE)
    assert len(b.actividades) == 5
    assert {a.codigo for a in b.actividades} == {"9609", "7490", "4669", "5224", "9903"}


def test_normaliza_la_tarifa_por_mil():
    a = next(x for x in leer_borrador(FIXTURE).actividades if x.codigo == "5224")
    assert a.tarifa == Decimal("0.010")
    assert a.base == Decimal("38966000")
    assert a.impuesto == Decimal("390000")


def test_lee_los_renglones_de_liquidacion():
    r = leer_borrador(FIXTURE).renglones
    assert r["23"] == Decimal("49013000")
    assert r["24"] == Decimal("474000")
    assert r["25"] == Decimal("0")
    assert r["27"] == Decimal("474000")
    assert r["31"] == Decimal("474000")
    assert r["32"] == Decimal("474000")


def test_lee_los_doce_renglones_de_base_gravable_en_cero():
    """La autorretencion esta fuera de alcance, pero los renglones deben leerse."""
    r = leer_borrador(FIXTURE).renglones
    assert all(r["%d" % n] == Decimal("0") for n in range(11, 23))


def test_detecta_la_firma_del_revisor_fiscal():
    assert leer_borrador(FIXTURE).firma_revisor_fiscal is True


def test_solo_lee_la_primera_pagina():
    """Las 3 paginas son copias; leerlas todas triplicaria los renglones."""
    b = leer_borrador(FIXTURE)
    assert sum(a.impuesto for a in b.actividades) == Decimal("474000")


def test_la_descripcion_partida_en_dos_lineas_no_genera_actividad_fantasma():
    b = leer_borrador(FIXTURE)
    assert all(a.codigo.isdigit() and len(a.codigo) == 4 for a in b.actividades)


def test_importes_son_decimal():
    b = leer_borrador(FIXTURE)
    assert all(isinstance(a.base, Decimal) for a in b.actividades)
    assert all(isinstance(v, Decimal) for v in b.renglones.values())
