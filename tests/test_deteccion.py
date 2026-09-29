"""El detector de formato reconoce los tres ERP vistos en produccion.

No usa las fixtures reales de clientes (viven fuera del repo): arma filas
sinteticas que reproducen EXACTAMENTE los encabezados y la estructura de cada
formato, para que la prueba corra en CI sin los archivos del cliente.
"""

from motor_reteica.ingesta.deteccion import detectar


# Encabezados reales, verificados contra los archivos de cada cliente.
_ENC_SAP_GRC_AUX = ["St", "Cuenta", "Texto breve", "Asignación", "Tercero",
                    "Fecha doc.", "Fe.contab.", "Referencia", "II",
                    "Importe en ML", "Período", "Cla", "Nº doc.", "Texto",
                    "Importe valorado ML2", "Soc."]

_ENC_SAP_GRC_BAL = ["Soc.", "Cta.mayor", "Texto breve", "Mon.",
                    "Arrastre de saldos", "Saldo per.anteriores",
                    "Período de informe debe", "Saldo Haber per.inf.",
                    "Saldo acumulado"]

_ENC_SBO = ["Cuenta contable", "Nombre cuenta contable", "Código SN",
            "Nombre SN", "NIT", "Nombre proyecto", "Nombre dimensión",
            "Dimensión", "Serie", "No. Transacción (Asiento)",
            "No. Línea (Asiento)", "No. Origen (Doc. Marketing)",
            "Tipo Origen (Documento)", "Referencia 1", "Referencia 2",
            "Saldo Inicial (Moneda Local)", "Débito Moneda Local",
            "Crédito Moneda Local", "Saldo Final (Moneda Local)",
            "Referencia 3", "Comentarios (Lineas)"]


def test_sap_grc_auxiliar():
    filas = [_ENC_SAP_GRC_AUX,
             ["", "2368010005", "Impuest ICA Reten 5%", "1082845843",
              "PARDO VILLA", "29.07.2026", "30.07.2026", "DE250", "",
              -1850, 7, "KR", 1900002410, "SERV", -0.58, "DA47"],
             ["", "2368010007", "Impuest ICA Reten 7%", "8698821",
              "DELGADO OROZCO", "29.07.2026", "30.07.2026", "DE248", "",
              -22260, 7, "RE", 5100003099, "HONORARIOS", -6.94, "DA47"]]
    d = detectar(filas, tipo_esperado="auxiliar")
    assert d.etiquetas[d.columnas["cuenta"]] == "Cuenta"
    assert d.etiquetas[d.columnas["nit"]] == "Asignación"
    assert d.etiquetas[d.columnas["nombre"]] == "Tercero"
    assert d.etiquetas[d.columnas["importe"]] == "Importe en ML"
    assert d.convencion_signo == "columna_unica"
    assert d.cuenta_raiz == "2368"
    assert d.filtro_transaccion is None


def test_sap_grc_balance():
    filas = [_ENC_SAP_GRC_BAL,
             ["DA47", "2368010005", "Impuest ICA Reten 5%", "COP",
              "-1.028.425", "-235.406", "0", "22.676", "-1.286.507"],
             ["DA47", "2368010090", "Ret. Ffe ICA a pagar", "COP",
              "4.223.151", "931.181", "126.375", "0", "5.280.707"]]
    d = detectar(filas, tipo_esperado="balance")
    assert d.etiquetas[d.columnas["cuenta"]] == "Cta.mayor"
    assert d.etiquetas[d.columnas["credito"]] == "Saldo Haber per.inf."
    # En un balance NO se debe inventar un NIT (no existe la columna).
    assert "nit" not in d.columnas
    assert d.cuenta_raiz == "2368"


def test_sap_business_one_con_jerarquia():
    filas = [_ENC_SBO,
             ["2368050301", "IMPUESTO...5x1000", "PN891780009", "ALCALDIA",
              "891780009-4", "", "", "", "AstCont", 474102, 1, "386747",
              "Registro", "", "", 0, 0, 1270907.06, 0, "", "CIERRE"],
             ["2368050301", "IMPUESTO...5x1000", "PN45491406", "ARRIETA",
              "45491406-6", "", "", "", "AstCont", 467606, 2, "41819",
              "Factura", "41819", "FA968", 0, 0, 2190, 0, "", "Fact."]]
    d = detectar(filas, tipo_esperado="auxiliar")
    assert d.etiquetas[d.columnas["cuenta"]] == "Cuenta contable"
    assert d.etiquetas[d.columnas["nit"]] == "NIT"
    assert d.etiquetas[d.columnas["nombre"]] == "Nombre SN"
    assert d.etiquetas[d.columnas["credito"]] == "Crédito Moneda Local"
    assert d.etiquetas[d.columnas["debito"]] == "Débito Moneda Local"
    assert d.convencion_signo == "columnas_separadas"
    # La jerarquia se detecta sola: Serie='AstCont' marca las transacciones.
    assert d.filtro_transaccion is not None
    col, marca = d.filtro_transaccion
    assert d.etiquetas[col] == "Serie"
    assert marca == "AstCont"


def test_encabezado_no_en_primera_fila():
    """SAP mete titulos y metadata antes del encabezado real."""
    filas = [["Zona Franca Tayrona S.A.S", "", "Saldos de cuentas de mayor"],
             ["Santa Marta - Colombia", "Ledger OL", ""],
             ["Períodos de arrastre 01-07"],
             _ENC_SAP_GRC_BAL,
             ["DA47", "2368010005", "Impuest ICA Reten 5%", "COP",
              "-1.028.425", "-235.406", "0", "22.676", "-1.286.507"]]
    d = detectar(filas, tipo_esperado="balance")
    assert d.fila_encabezado == 3
    assert d.etiquetas[d.columnas["cuenta"]] == "Cta.mayor"
