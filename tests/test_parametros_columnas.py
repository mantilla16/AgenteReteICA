"""1.2/1.3/1.4 - sinonimos de columna y error tipado ColumnaNoIdentificada."""

import pytest

from motor_reteica.ingesta._io import leer_filas
from motor_reteica.parametros.columnas import (
    ROLES_AUXILIAR, ROLES_BALANCE, ROLES_ERP,
    FIRMA_AUXILIAR, FIRMA_BALANCE, FIRMA_ERP,
    ColumnaNoIdentificada, Rol, detectar_tipo_documento, localizar_columnas)

BASE = "terlica_202607"


@pytest.fixture(scope="module")
def filas_auxiliar(base_fixtures):
    return leer_filas(base_fixtures / "auxiliar_2368.xlsx")


@pytest.fixture(scope="module")
def filas_balance(base_fixtures):
    return leer_filas(base_fixtures / "balance.xlsx", hoja="BALANCE")


@pytest.fixture(scope="module")
def filas_erp(base_fixtures):
    return leer_filas(base_fixtures / "sap_retenciones.xlsx")


def test_localiza_las_columnas_del_auxiliar_por_etiqueta(filas_auxiliar):
    indice, col = localizar_columnas(filas_auxiliar, ROLES_AUXILIAR, FIRMA_AUXILIAR)
    assert col["nit"] != col["nombre"]  # 1.3: la trampa Asignacion/Tercero
    assert set(col) == set(ROLES_AUXILIAR)


def test_localiza_las_columnas_del_balance_por_etiqueta(filas_balance):
    indice, col = localizar_columnas(filas_balance, ROLES_BALANCE, FIRMA_BALANCE)
    assert set(col) == set(ROLES_BALANCE)


def test_localiza_las_columnas_del_erp_por_etiqueta(filas_erp):
    indice, col = localizar_columnas(filas_erp, ROLES_ERP, FIRMA_ERP)
    assert set(col) == set(ROLES_ERP)


def test_rol_sin_sinonimo_presente_lanza_columna_no_identificada(filas_auxiliar):
    """1.3: el error debe nombrar el rol y explicarlo en terminos de auditoria,
    no solo lanzar un ValueError generico."""
    roles = dict(ROLES_AUXILIAR)
    roles["importe"] = Rol("importe", "el importe de la retencion",
                           ("Esta Columna No Existe",))
    with pytest.raises(ColumnaNoIdentificada) as exc:
        localizar_columnas(filas_auxiliar, roles, FIRMA_AUXILIAR)
    assert exc.value.rol == "importe"
    assert "Cuenta" in exc.value.encabezados_disponibles


def test_ningun_sinonimo_de_un_rol_se_adivina_por_parecido(filas_auxiliar):
    """1.4.c: coincidencia exacta de etiqueta, nunca 'la mas parecida'."""
    roles = {"importe": Rol("importe", "x", ("Importe en M",))}  # casi igual
    with pytest.raises(ColumnaNoIdentificada):
        localizar_columnas(filas_auxiliar, roles, FIRMA_AUXILIAR)


def test_alias_aprendido_se_reutiliza(filas_auxiliar):
    """D3: un alias nuevo, agregado como segundo sinonimo, tambien resuelve."""
    roles = {"nit": Rol("nit", "el NIT del tercero",
                        ("Un Alias Que No Existe", "Asignación"))}
    indice, col = localizar_columnas(filas_auxiliar, roles, FIRMA_AUXILIAR)
    assert "nit" in col


def test_sin_fila_que_tenga_la_firma_lanza_columna_no_identificada(filas_balance):
    with pytest.raises(ColumnaNoIdentificada) as exc:
        localizar_columnas(filas_balance, ROLES_AUXILIAR, FIRMA_AUXILIAR)
    assert exc.value.rol == "encabezado"


def test_detecta_el_tipo_de_cada_documento(filas_auxiliar, filas_balance, filas_erp):
    assert detectar_tipo_documento(filas_auxiliar) == "auxiliar"
    assert detectar_tipo_documento(filas_balance) == "balance"
    assert detectar_tipo_documento(filas_erp) == "erp"


def test_detecta_none_si_ninguna_firma_conocida_coincide():
    assert detectar_tipo_documento([("cualquier", "cosa"), (1, 2)]) is None
