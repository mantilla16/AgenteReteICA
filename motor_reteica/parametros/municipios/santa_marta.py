"""Paquete de parametros del Distrito de Santa Marta.

Nada de este modulo puede provenir del borrador del cliente: el borrador es
objeto de prueba, no fuente de parametros.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Municipio:
    nombre: str
    tarifa_por_cuenta: dict
    tarifa_por_codigo_ret: dict
    tarifas_actividad: dict
    estado_tarifas: str
    renglones: dict
    vencimientos: dict
    exige_discriminar_compras_servicios: bool

    def vencimiento(self, periodo: str) -> date:
        return self.vencimientos[periodo]


MUNICIPIO = Municipio(
    nombre="Santa Marta",
    # La subcuenta codifica la tarifa: 2368010007 -> 7 por mil.
    tarifa_por_cuenta={
        "2368010002": Decimal("0.002"),
        "2368010005": Decimal("0.005"),
        "2368010007": Decimal("0.007"),
        "2368010008": Decimal("0.008"),
        "2368010010": Decimal("0.010"),
    },
    tarifa_por_codigo_ret={
        "23": Decimal("0.010"),
        "37": Decimal("0.010"),
        "39": Decimal("0.007"),
    },
    # PROVISIONAL: tomadas del borrador del cliente por falta del Acuerdo
    # municipal. Mientras estado_tarifas sea PENDIENTE_VALIDACION_ESTATUTO,
    # el control C7 reporta NO_EJECUTADO y nunca OK.
    tarifas_actividad={
        "4669": Decimal("0.010"),
        "5224": Decimal("0.010"),
        "9903": Decimal("0.010"),
        "7490": Decimal("0.007"),
        "9609": Decimal("0.007"),
    },
    estado_tarifas="PENDIENTE_VALIDACION_ESTATUTO",
    renglones={
        "total_pagos": "23",
        "total_retenciones": "24",
        "retenciones_en_exceso": "25",
        "sanciones": "26",
        "saldo_a_cargo": "27",
        "valor_a_pagar_impuesto": "28",
        "valor_a_pagar_sanciones": "29",
        "intereses_mora": "30",
        "total_a_pagar": "31",
        "valor_en_bancos": "32",
    },
    vencimientos={"2026-07": date(2026, 8, 14)},
    exige_discriminar_compras_servicios=False,
)
