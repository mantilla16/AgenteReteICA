"""Registro de perfiles de municipio.

Antes el motor tenia un solo MUNICIPIO -- Santa Marta -- con tarifas y
renglones cableados. Cada municipio nuevo con formato distinto obligaba a
tocar codigo. Ahora hay dos niveles:

  - PERFIL RICO: municipio cuya estructura conocemos completa (tarifas,
    renglones, actividades). Habilita todos los controles y el papel
    con REVISION ICA de detalle. Solo Santa Marta lo tiene hoy.

  - PERFIL MINIMO: se usa para cualquier municipio del que solo sabemos que
    existe. El motor NO afirma renglones ni tarifas; corre solo lo que sea
    independiente de la estructura del borrador --el cruce universal
    declarado vs auxiliar-- y el papel sale corto pero valido.

La deteccion es por nombre extraido del PDF; el registro es case-insensitive
y tolera acentos, porque cada municipio los escribe distinto en su formulario.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .santa_marta import MUNICIPIO as _SANTA_MARTA


def _normalizar(nombre: str) -> str:
    """'San Alberto' == 'san_alberto' == 'SAN ALBERTO' == 'Sán Álberto'."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", nombre or "")
                          if unicodedata.category(c) != "Mn")
    return sin_acentos.lower().replace(" ", "_").replace("-", "_").strip("_")


@dataclass(frozen=True)
class PerfilMinimo:
    """Perfil para un municipio sin conocimiento fino.

    Reproduce la interfaz del Municipio rico -- lo suficiente para que el
    pipeline no explote -- con datos vacios. El papel que sale de aqui trae
    el cruce universal y las hojas de evidencia, pero NO REVISION ICA con
    renglones inventados: D9 no permite firmar cifras que nadie verifico.
    """

    nombre: str
    tarifa_por_cuenta: dict = field(default_factory=dict)
    tarifa_por_codigo_ret: dict = field(default_factory=dict)
    tarifas_actividad: dict = field(default_factory=dict)
    estado_tarifas: str = "no verificadas"
    renglones: dict = field(default_factory=dict)
    vencimientos: dict = field(default_factory=dict)
    exige_discriminar_compras_servicios: bool = False

    # Marca para que el codigo pueda ramificar entre rico y minimo sin
    # inventar un flag booleano dentro del Municipio rico.
    perfil: str = "minimo"

    def vencimiento(self, periodo: str):
        return None


# Registro. La llave es el nombre normalizado; el valor es un objeto que
# EXPONE la interfaz del Municipio (sea el rico de Santa Marta o el minimo).
_PERFILES: dict = {
    _normalizar(_SANTA_MARTA.nombre): _SANTA_MARTA,
}


def perfil_para(nombre: str):
    """Devuelve el perfil del municipio, o uno minimo si no esta registrado.

    Nunca lanza. La razon: recibir un municipio que el motor no conoce NO es
    error del auditor -- es el caso normal cuando llega uno nuevo. La
    revision corre igual con el cruce universal y el papel lo dice.
    """
    if not nombre:
        return PerfilMinimo(nombre="(no detectado)")
    p = _PERFILES.get(_normalizar(nombre))
    if p is not None:
        return p
    return PerfilMinimo(nombre=nombre)


def es_perfil_rico(perfil) -> bool:
    """Un perfil que trae tarifas y renglones habilita el cruce por renglon.

    Se usa aparte de la deteccion por nombre porque hay codigo del pipeline
    --controles de tarifa, reconstruccion-- que necesita saber si tiene con
    que trabajar antes de correr, y llegar a la mitad y romper seria peor.
    """
    return getattr(perfil, "perfil", "rico") != "minimo"
