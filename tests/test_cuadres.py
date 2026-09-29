"""La bateria de cuadres valida un mapeo sin intervencion humana.

Filas sinteticas que reproducen la estructura de cada ERP (mismos encabezados
y jerarquia que los archivos reales), para correr en CI sin datos del cliente.
"""

from decimal import Decimal

from motor_reteica.ingesta.deteccion import detectar
from motor_reteica.ingesta.cuadres import (
    validar_deteccion, es_confiable, cuadre_auxiliar_vs_balance,
    movimiento_periodo_balance, cuadre_totalizador,
)

_ENC_SBO = ["Cuenta contable", "Nombre cuenta contable", "Código SN",
            "Nombre SN", "NIT", "Nombre proyecto", "Nombre dimensión",
            "Dimensión", "Serie", "No. Transacción (Asiento)",
            "No. Línea (Asiento)", "No. Origen (Doc. Marketing)",
            "Tipo Origen (Documento)", "Referencia 1", "Referencia 2",
            "Saldo Inicial (Moneda Local)", "Débito Moneda Local",
            "Crédito Moneda Local", "Saldo Final (Moneda Local)",
            "Referencia 3", "Comentarios (Lineas)"]


def _fila_sbo(cuenta, nit, serie, debito, credito):
    f = [""] * 21
    f[0], f[4], f[8], f[16], f[17] = cuenta, nit, serie, debito, credito
    return f


def test_sbo_auxiliar_cuadra_totalizador_y_partida_doble():
    filas = [_ENC_SBO,
             # fila padre (totalizador): Db == Cr, sin Serie
             _fila_sbo("23680503", "", "", 3320, 3320),
             # detalle: tres transacciones que suman 3320 en credito
             _fila_sbo("2368050301", "891780009-4", "AstCont", 0, 2190),
             _fila_sbo("2368050301", "45491406-6", "AstCont", 0, 730),
             _fila_sbo("2368050302", "802003363-1", "AstCont", 0, 400),
             # debito del cierre (contrapartida), para que Db padre == 3320
             _fila_sbo("2368050301", "891780009-4", "AstCont", 3320, 0)]
    d = detectar(filas, tipo_esperado="auxiliar")
    cuadres = validar_deteccion(filas, d)
    assert es_confiable(cuadres), [(c.nombre, c.detalle) for c in cuadres]


def test_mapeo_equivocado_no_cuadra():
    """Si la deteccion apuntara a la columna equivocada, el cuadre lo rechaza.

    Se fuerza credito -> columna de debito: la suma del detalle deja de
    coincidir con el totalizador de credito y el cuadre FALLA. Es justo la red
    que impide producir un papel sobre columnas mal mapeadas.
    """
    filas = [_ENC_SBO,
             _fila_sbo("23680503", "", "", 999999, 3320),
             _fila_sbo("2368050301", "891780009-4", "AstCont", 0, 2190),
             _fila_sbo("2368050301", "45491406-6", "AstCont", 0, 1130)]
    d = detectar(filas, tipo_esperado="auxiliar")
    # Mapeo saboteado a mano: la retencion apunta al debito (todo en cero).
    from dataclasses import replace
    cols = dict(d.columnas)
    cols["credito"] = cols["debito"]
    d_malo = replace(d, columnas=cols)
    c = cuadre_totalizador(filas, d_malo)
    assert not c.cuadra


def test_cruce_auxiliar_vs_balance():
    total_auxiliar = Decimal("1632338.63")
    movimiento_balance = Decimal("1632338.63")
    c = cuadre_auxiliar_vs_balance(total_auxiliar, movimiento_balance)
    assert c.cuadra
    # Un balance de otro mes (no cuadra) se rechaza.
    c2 = cuadre_auxiliar_vs_balance(total_auxiliar, Decimal("44936"))
    assert not c2.cuadra


def test_balance_solo_suma_cuentas_2368():
    """El balance abarca toda la empresa; el movimiento del periodo es solo 2368."""
    enc = ["Soc.", "Cta.mayor", "Texto breve", "Mon.", "Arrastre de saldos",
           "Saldo per.anteriores", "Período de informe debe",
           "Saldo Haber per.inf.", "Saldo acumulado"]
    filas = [enc,
             ["DA47", "1110063600", "Banco", "COP", "10", "20", "30", "999999", "40"],
             ["DA47", "2368010005", "ICA 5%", "COP", "-1", "-2", "0", "22676", "-3"],
             ["DA47", "2368010007", "ICA 7%", "COP", "-3", "-7", "0", "22260", "-3"]]
    d = detectar(filas, tipo_esperado="balance")
    mov = movimiento_periodo_balance(filas, d)
    # Solo las dos cuentas 2368: 22676 + 22260 = 44936. La cuenta banco no entra.
    assert mov == Decimal("44936")
