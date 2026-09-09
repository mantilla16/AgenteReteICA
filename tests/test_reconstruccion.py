from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta.auxiliar import leer_auxiliar
from motor_reteica.ingesta.sap_retenciones import leer_sap_retenciones
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO
from motor_reteica.reconstruccion import reconstruir, redondear_al_mil

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"
LINEAS = leer_auxiliar(BASE / "auxiliar_2368.xlsx")
ERP = leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
MAPA = {"800193573": "5224", "811033997": "4669", "830028245": "9903",
        "900392924": "9609", "901670478": "7490"}


def _recon(erp=ERP):
    return reconstruir(LINEAS, erp, MUNICIPIO, MAPA)


def test_redondeo_al_mil_mas_cercano():
    assert redondear_al_mil(Decimal("389657")) == Decimal("390000")
    assert redondear_al_mil(Decimal("37430")) == Decimal("37000")
    assert redondear_al_mil(Decimal("1318")) == Decimal("1000")
    assert redondear_al_mil(Decimal("11156")) == Decimal("11000")
    assert redondear_al_mil(Decimal("500")) == Decimal("1000")


def test_valora_las_doce_lineas():
    assert len(_recon().lineas_valoradas) == 12


def test_tarifa_sale_de_la_cuenta_contable():
    fe10 = next(v for v in _recon().lineas_valoradas if v.linea.referencia == "FE10")
    assert fe10.tarifa == Decimal("0.007")


def test_la_base_viene_del_erp_no_de_la_retencion():
    """Derivarla daria 49.012.586; la real es 49.012.569."""
    r = _recon()
    assert r.total_base == Decimal("49012569")
    assert r.base_es_derivada is False


def test_totales_reproducen_las_anclas():
    r = _recon()
    assert r.total_impuesto_contable == Decimal("474561")
    assert r.total_impuesto_declarable == Decimal("474000")


def test_detalle_por_actividad_reproduce_el_spec():
    esperado = {
        "9609": (Decimal("188341"), Decimal("1318")),
        "7490": (Decimal("5000000"), Decimal("35000")),
        "4669": (Decimal("3742993"), Decimal("37430")),
        "5224": (Decimal("38965609"), Decimal("389657")),
        "9903": (Decimal("1115626"), Decimal("11156")),
    }
    por_actividad = _recon().por_actividad
    assert len(por_actividad) == 5
    for codigo, (base, impuesto) in esperado.items():
        assert por_actividad[codigo].base_contable == base
        assert por_actividad[codigo].impuesto_contable == impuesto


def test_declarables_coinciden_con_el_borrador():
    r = _recon().por_actividad
    assert r["5224"].base_declarable == Decimal("38966000")
    assert r["5224"].impuesto_declarable == Decimal("390000")
    assert r["4669"].impuesto_declarable == Decimal("37000")


def test_recalculo_por_tercero_expone_el_peso_de_superportuaria():
    """El ERP redondea por factura: 38.965.609 x 10 por mil = 389.656 vs 389.657."""
    portuaria = _recon().por_tercero["800193573"]
    assert portuaria.retencion_recalculada == Decimal("389656")
    assert portuaria.retencion_contable == Decimal("389657")
    assert portuaria.diferencia == Decimal("-1")


def test_el_recalculo_no_es_circular():
    """Si la base se derivara de la retencion, toda diferencia seria cero."""
    diferencias = {t.nit: t.diferencia for t in _recon().por_tercero.values()}
    assert any(d != 0 for d in diferencias.values())


def test_sin_erp_la_base_se_marca_derivada():
    r = _recon(erp=None)
    assert r.base_es_derivada is True
    assert r.total_base == Decimal("49012586")


def test_las_dos_lineas_de_cdem_siguen_separadas():
    valoradas = [v for v in _recon().lineas_valoradas if v.linea.nit == "811033997"]
    assert len(valoradas) == 2
