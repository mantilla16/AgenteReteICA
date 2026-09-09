import ast
import pathlib
from datetime import date
from decimal import Decimal

from motor_reteica.parametros import puc
from motor_reteica.parametros.municipios.santa_marta import MUNICIPIO


def test_puc_es_constante():
    assert puc.CUENTAS_RETENCION["2365"] == "Retencion en la fuente"
    assert puc.CUENTAS_RETENCION["2367"] == "Retencion de IVA"
    assert puc.CUENTAS_RETENCION["2368"] == "Retencion de ICA"
    assert puc.CUENTA_RETEICA == "2368"


def test_puc_no_trae_cuentas_de_ningun_cliente(): 
    """M11: 2368010090 es la subcuenta de contrapartida de TERLICA en SAP, no
    una constante del PUC. En otro cliente tendria otro numero y pasaria como
    retencion practicada, inflando todos los cruces.

    La exclusion ahora se determina por la NATURALEZA del saldo en el balance
    (ver ingesta/balance.leer_naturalezas) y la declara el auditor.
    """
    assert puc.CUENTAS_EXCLUIDAS == frozenset()
    assert puc.es_cuenta_reteica("2368010090")           # ya no se excluye aqui
    assert not puc.es_cuenta_reteica("2368010090", {"2368010090"})
    assert puc.es_cuenta_reteica("2368010010")
    assert not puc.es_cuenta_reteica("2365050100")


def test_tarifa_por_cuenta_cubre_las_cinco_subcuentas_con_tarifa():
    esperado = {
        "2368010002": Decimal("0.002"), "2368010005": Decimal("0.005"),
        "2368010007": Decimal("0.007"), "2368010008": Decimal("0.008"),
        "2368010010": Decimal("0.010"),
    }
    assert MUNICIPIO.tarifa_por_cuenta == esperado


def test_tarifa_por_codigo_de_retencion_del_erp():
    assert MUNICIPIO.tarifa_por_codigo_ret["23"] == Decimal("0.010")
    assert MUNICIPIO.tarifa_por_codigo_ret["37"] == Decimal("0.010")
    assert MUNICIPIO.tarifa_por_codigo_ret["39"] == Decimal("0.007")


def test_tarifas_de_actividad_estan_sin_validar_contra_el_acuerdo():
    assert MUNICIPIO.estado_tarifas == "PENDIENTE_VALIDACION_ESTATUTO"


def test_santa_marta_no_exige_discriminar_compras_y_servicios():
    assert MUNICIPIO.exige_discriminar_compras_servicios is False


def test_vencimiento_de_julio_2026():
    assert MUNICIPIO.vencimiento("2026-07") == date(2026, 8, 14)


def _modulos_importados(archivo: pathlib.Path):
    """Nombres de modulo que aparecen en sentencias import del archivo."""
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                yield alias.name
        elif isinstance(nodo, ast.ImportFrom):
            base = nodo.module or ""
            yield base
            # "from motor_reteica import ingesta" deja el nombre en los alias,
            # no en nodo.module: sin esto el guard tiene un hueco.
            for alias in nodo.names:
                yield "%s.%s" % (base, alias.name) if base else alias.name


def test_parametros_no_importan_la_ingesta():
    """Garantia mecanica de no circularidad: el spec lo exige.

    Se verifica sobre las sentencias import, no sobre el texto: la palabra
    'borrador' aparece legitimamente en los comentarios que explican por que
    no debe importarse.
    """
    raiz = pathlib.Path(__file__).parent.parent / "motor_reteica" / "parametros"
    for archivo in raiz.rglob("*.py"):
        for modulo in _modulos_importados(archivo):
            assert "ingesta" not in modulo, "%s importa %s" % (archivo.name, modulo)
            assert "borrador" not in modulo, "%s importa %s" % (archivo.name, modulo)
