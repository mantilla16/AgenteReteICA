"""El registro de perfiles resuelve un municipio a partir del texto del PDF."""

from motor_reteica.parametros.municipios.perfiles import (
    PerfilMinimo, es_perfil_rico, perfil_para,
)


def test_santa_marta_devuelve_el_perfil_rico():
    """La firma tiene sus renglones cargados. Debe seguir enrutandose ahi."""
    p = perfil_para("Santa Marta")
    assert p.nombre == "Santa Marta"
    assert es_perfil_rico(p)
    assert p.tarifa_por_cuenta, "sin tarifas el perfil no sirve para el cruce fino"


def test_reconoce_pese_a_acentos_y_mayusculas():
    """Cada formulario escribe el municipio como quiere. La deteccion no
    puede depender de la forma exacta."""
    for variante in ("SANTA MARTA", "santa marta", "Sánta Marta"):
        assert perfil_para(variante).nombre == "Santa Marta", variante


def test_municipio_desconocido_cae_al_perfil_minimo():
    """San Alberto no tiene renglones cargados. En vez de fallar, se
    devuelve un perfil vacio para que la revision corra con solo el cruce
    universal."""
    p = perfil_para("San Alberto")
    assert isinstance(p, PerfilMinimo)
    assert p.nombre == "San Alberto"
    assert not es_perfil_rico(p)


def test_sin_nombre_no_lanza():
    """La extraccion puede fallar en detectar municipio. El motor tiene que
    seguir corriendo con el cruce universal aunque no sepa quien es."""
    p = perfil_para("")
    assert isinstance(p, PerfilMinimo)
    assert not es_perfil_rico(p)


def test_el_perfil_minimo_expone_la_misma_interfaz():
    """El pipeline usa municipio.tarifa_por_cuenta y demas -- si el perfil
    minimo no los tuviera, un municipio nuevo haria explotar el motor."""
    p = perfil_para("Barranquilla")   # otro que aun no tenemos cargado
    assert p.tarifa_por_cuenta == {}
    assert p.tarifas_actividad == {}
    assert p.renglones == {}
    assert p.vencimiento("2026-07") is None
