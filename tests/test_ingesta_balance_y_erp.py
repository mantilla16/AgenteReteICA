from decimal import Decimal
from pathlib import Path

from motor_reteica.ingesta.balance import leer_balance
from motor_reteica.ingesta.sap_retenciones import leer_sap_retenciones

BASE = Path(__file__).parent / "fixtures" / "terlica_202607"


def test_balance_toma_el_movimiento_del_periodo_no_el_acumulado():
    saldos = leer_balance(BASE / "balance.xlsx")
    assert saldos["2368010007"] == Decimal("36318")
    assert saldos["2368010010"] == Decimal("438243")


def test_balance_excluye_la_cuenta_de_pago():
    """2368010090 es contrapartida de pago con saldo debito de 38 millones."""
    assert "2368010090" not in leer_balance(BASE / "balance.xlsx")


def test_balance_incluye_cuentas_sin_movimiento():
    assert leer_balance(BASE / "balance.xlsx")["2368010002"] == Decimal("0")


def test_balance_suma_el_ancla():
    assert sum(leer_balance(BASE / "balance.xlsx").values()) == Decimal("474561")


def test_balance_no_toma_el_saldo_acumulado():
    """El acumulado de 2368010010 es 32.652.162; tomarlo romperia C2 siempre."""
    assert leer_balance(BASE / "balance.xlsx")["2368010010"] != Decimal("32652162")


def test_erp_lee_cinco_terceros():
    assert len(leer_sap_retenciones(BASE / "sap_retenciones.xlsx")) == 5


def test_erp_totales_son_las_anclas():
    filas = leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
    assert sum(f.base for f in filas) == Decimal("49012569")
    assert sum(f.retencion for f in filas) == Decimal("474561")


def test_erp_descarta_la_fila_de_total():
    filas = leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
    assert all(f.nit and f.codigo_ret for f in filas)


def test_erp_conserva_el_codigo_de_retencion():
    filas = {f.nit: f.codigo_ret for f in leer_sap_retenciones(BASE / "sap_retenciones.xlsx")}
    assert filas["800193573"] == "37"
    assert filas["811033997"] == "23"
    assert filas["901670478"] == "39"


def test_erp_usa_la_base_sujeta_no_el_importe_bruto():
    """CDEM: bruto 4.454.161 con IVA, base sujeta 3.742.993."""
    cdem = next(f for f in leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
                if f.nit == "811033997")
    assert cdem.base == Decimal("3742993")


def test_erp_importes_son_decimal():
    filas = leer_sap_retenciones(BASE / "sap_retenciones.xlsx")
    assert all(isinstance(f.base, Decimal) and isinstance(f.retencion, Decimal)
               for f in filas)
