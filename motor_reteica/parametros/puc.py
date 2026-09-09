"""Plan de cuentas de retenciones. Constante del PUC, no configuracion por cliente."""

CUENTAS_RETENCION = {
    "2365": "Retencion en la fuente",
    "2367": "Retencion de IVA",
    "2368": "Retencion de ICA",
}

CUENTA_RETEICA = "2368"

# 2368010090 "Ret. Ffe ICA a pagar" es la contrapartida de pago (saldo debito),
# no una retencion practicada. Incluirla infla todos los cruces.
CUENTAS_EXCLUIDAS = {"2368010090"}


def es_cuenta_reteica(cuenta: str) -> bool:
    return cuenta.startswith(CUENTA_RETEICA) and cuenta not in CUENTAS_EXCLUIDAS
