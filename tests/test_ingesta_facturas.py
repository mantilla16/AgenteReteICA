"""2.0 - parser de numeros de facturas_pdf.py.

FE338057 tiene la etiqueta SUBTOTAL en una fila de encabezado tabular; el
valor esta en la fila SIGUIENTE, no en la misma linea. El parser original
solo miraba la misma linea que la etiqueta y perdia el dato.
"""

from decimal import Decimal

from motor_reteica.ingesta.facturas_pdf import leer_factura


def test_recupera_la_base_cuando_el_valor_esta_en_la_linea_siguiente_a_la_etiqueta(
        base_fixtures):
    f = leer_factura(base_fixtures / "facturas" / "FE338057.pdf")
    assert f.base == Decimal("1196993")


def test_no_recupera_nit_de_fe338057_porque_no_esta_en_la_capa_de_texto(
        base_fixtures):
    """El NIT del proveedor solo esta en el logo (imagen) del encabezado.

    Verificado con pdfplumber: la pagina tiene 7 imagenes (una de 570x86 en
    el encabezado) y el unico NIT en el texto es el del cliente (819002433),
    que se excluye a proposito. Sin OCR esto no es recuperable, y P2 del
    backlog ya decidio no construir OCR en esta etapa: el AVISO de cotejo
    manual se queda como el techo real de C11 para esta factura.
    """
    f = leer_factura(base_fixtures / "facturas" / "FE338057.pdf")
    assert f.nit == ""
    assert f.confianza != "ALTA"


def test_las_facturas_ya_correctas_no_cambian_de_valor(base_fixtures):
    """250530 y FE10 traen el valor en la misma linea de la etiqueta: la
    busqueda en la linea siguiente no debe alterar su resultado."""
    f_250530 = leer_factura(base_fixtures / "facturas" / "250530.pdf")
    f_fe10 = leer_factura(base_fixtures / "facturas" / "FE10.pdf")
    assert f_250530.base == Decimal("1829605")
    assert f_fe10.base == Decimal("5000000")
