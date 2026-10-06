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

    def test_zap_search_page_extraction(self):
        class Md:
            raw_markdown = """# 3.692 Terrenos, Lotes e Condomínios para venda em Vinhedo - SP
Lote/Terreno para comprar com 199 m² em R$ 1.390.000 Cond. R$ 1.620 • IPTU R$ 471 Tamanho do imóvel 199 m²São Joaquim, Vinhedo Rua dos Servidores Públicos Contatar
Lote/Terreno para comprar com 1690 m² em R$ 1.180.000 Cond. isento • IPTU R$ 350 Tamanho do imóvel 1690 m²Vista Alegre, Vinhedo Rua Arnaldo Roque Brisque Contatar
"""

        class Result:
            markdown = Md()
            html = ""
            url = "https://www.zapimoveis.com.br/venda/terrenos-lotes-condominios/sp%2Bvinhedo/"
            status_code = 200
            links = {"internal": [], "external": []}

        items = crawler.extract_search_page_listings(
            Result(), crawler.SOURCES["zap"], "Vinhedo", "SP"
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].price, 1390000.0)
        self.assertEqual(items[0].area_m2, 199.0)
        self.assertEqual(items[0].neighborhood, "São Joaquim")
        self.assertEqual(items[1].price_per_m2, round(1180000 / 1690, 2))

    def test_imovelweb_search_page_extraction(self):
        class Md:
            raw_markdown = """Image: abc123 · Terreno à venda no Condomínio Campos de Toscana - Vinhedo/SP

## R$ 980.000

## R$ 1.631 Condominio

### 850 m² tot.

#### Rua Abrahão Kalil Aun 1400

#### Vinhedo, São Paulo

Image: def456 · Terreno à venda no Condomínio Marambaia Vinhedo/SP

## R$ 1.299.000

## R$ 1.056 Condominio

### 800 m² tot.

#### Rua Cafelândia 112

#### Marambaia, Vinhedo
"""

        class Result:
            markdown = Md()
            html = ""
            url = "https://www.imovelweb.com.br/terrenos-venda-vinhedo-sp.html"
            status_code = 200
            links = {"internal": [], "external": []}

        items = crawler.extract_search_page_listings(
            Result(), crawler.SOURCES["imovelweb"], "Vinhedo", "SP"
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].price, 980000.0)
        self.assertEqual(items[0].area_m2, 850.0)
        self.assertEqual(items[1].neighborhood, "Marambaia")

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
