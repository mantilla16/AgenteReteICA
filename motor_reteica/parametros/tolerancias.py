"""Umbrales explicitos. Antes eran implicitos y nadie los escribia."""

from decimal import Decimal

TOLERANCIAS = {
    "redondeo_declaracion_pesos": Decimal("1000"),
    "diferencia_maxima_cruce_pesos": Decimal("1"),
    # El ERP redondea por factura, no por tercero: una diferencia de 1 peso
    # en el recalculo es real y esperada.
    "diferencia_maxima_recalculo_pesos": Decimal("1"),
}
