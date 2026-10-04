import unittest

import crawler


class CrawlerTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(crawler.slugify("São José"), "sao-jose")

    def test_brl(self):
        self.assertEqual(crawler.parse_brl("R$ 1.300.000,00"), 1300000.0)

    def test_area(self):
        self.assertEqual(crawler.parse_area_m2("1.250m²"), 1250.0)
        self.assertEqual(crawler.parse_area_m2("862,62 m²"), 862.62)

    def test_source_urls(self):
        self.assertEqual(
            crawler.SOURCES["imovelweb"].search_url("Vinhedo", "SP", 2),
            "https://www.imovelweb.com.br/terrenos-venda-vinhedo-sp-pagina-2.html",
        )
        self.assertEqual(
            crawler.SOURCES["chavesnamao"].search_url("Vinhedo", "SP", 2),
            "https://www.chavesnamao.com.br/terrenos-a-venda/sp-vinhedo/?pg=2",
        )

    def test_zap_like_extraction(self):
        class Md:
            raw_markdown = """# Terreno / Lote / Condomínio à venda, 800m² - Condomínio Campo de Toscana
Metragem
800 m²
## Localização
Rua Abrahão Kalil Aun, 1400 - Condomínio Campo de Toscana, Vinhedo - SP
## Valores
Venda
R$ 859.000
Condomínio
R$ 1.700/mês
IPTU
R$ 300
"""

        class Result:
            markdown = Md()
            html = ""
            url = "https://www.zapimoveis.com.br/imovel/x-id-2860670790/"
            status_code = 200

        item = crawler.extract_property(Result(), crawler.SOURCES["zap"], "Vinhedo", "SP")
        self.assertEqual(item.price, 859000.0)
        self.assertEqual(item.area_m2, 800.0)
        self.assertEqual(item.price_per_m2, 1073.75)
        self.assertEqual(item.neighborhood, "Condomínio Campo de Toscana")


if __name__ == "__main__":
    unittest.main()
