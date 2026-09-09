"""Plan de cuentas de retenciones. Constante del PUC, no configuracion por cliente."""

CUENTAS_RETENCION = {
    "2365": "Retencion en la fuente",
    "2367": "Retencion de IVA",
    "2368": "Retencion de ICA",
}

CUENTA_RETEICA = "2368"

# M11: aqui NO va ninguna cuenta concreta. "2368010090" es la subcuenta de
# contrapartida de TERLICA en SAP, no una constante del PUC: en otro cliente
# tendria otro numero, pasaria como retencion practicada e inflaria todos los
# cruces. La exclusion la declara el auditor (ver atestacion.py) sobre las
# candidatas que el motor detecta por la naturaleza del saldo.
CUENTAS_EXCLUIDAS = frozenset()


def es_cuenta_reteica(cuenta: str, excluidas=()) -> bool:
    return cuenta.startswith(CUENTA_RETEICA) and cuenta not in set(excluidas)
