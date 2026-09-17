"""Lo que sale hacia el navegador cuando se lista el historial.

Las filas de Postgres traen datetime, Decimal y uuid, y nada de eso es JSON.
Ademas llevan el usuario_id, que es de adentro: la pantalla no lo necesita y
publicarlo solo sirve para que alguien lo use como parametro.

La visibilidad en si (que cada auditor vea lo suyo) no se decide aqui sino en
el WHERE de las consultas, que es donde tiene que estar.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from motor_reteica.api.servidor import _fila_json


def _fila():
    return {
        "corrida": "fe44a79fdda6",
        "usuario_id": uuid.uuid4(),
        "nit": "819002433",
        "razon_social": "TERLICA SAS",
        "periodo": "2026-07",
        "creado_en": datetime(2026, 9, 17, 4, 15, tzinfo=timezone.utc),
        "impacto_total": Decimal("474561"),
        "puede_concluir_limpio": False,
        "semaforo": "AMARILLO",
    }


def test_el_usuario_id_no_sale_hacia_afuera():
    assert "usuario_id" not in _fila_json(_fila())


def test_las_fechas_salen_en_iso():
    assert _fila_json(_fila())["creado_en"] == "2026-09-17T04:15:00+00:00"


def test_los_decimales_salen_como_numero():
    impacto = _fila_json(_fila())["impacto_total"]
    assert impacto == 474561
    assert isinstance(impacto, float)


def test_lo_demas_pasa_tal_cual():
    salida = _fila_json(_fila())
    assert salida["nit"] == "819002433"
    assert salida["razon_social"] == "TERLICA SAS"
    assert salida["puede_concluir_limpio"] is False


def test_el_resultado_es_serializable():
    """La prueba de fuego: que json.dumps no se queje."""
    import json
    json.dumps(_fila_json(_fila()))
