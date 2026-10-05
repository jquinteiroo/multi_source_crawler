# Multi Source Crawler

Crawler multi-fonte para alimentar o **AnalisaImóvel** com anúncios públicos de terrenos/lotes.

## MVP atual

Você informa apenas uma cidade e UF. O crawler:

1. gera as páginas de busca das fontes;
2. usa Crawl4AI para abrir as listagens;
3. descobre os links de anúncios;
4. abre os anúncios em paralelo, com rate limiting;
5. extrai preço, área, bairro, endereço, condomínio e IPTU;
6. calcula preço/m²;
7. deduplica;
8. grava SQLite, JSON e CSV.

### Fontes padrão da v0.1

- ZAP Imóveis
- Viva Real
- Imovelweb
- Chaves na Mão

### Experimental

- OLX (\`--sources olx\`)

A OLX fica desativada por padrão nesta etapa porque a rota pública varia por região.

## Instalação no Windows

\`\`\`powershell
git clone https://github.com/jquinteiroo/multi_source_crawler.git
cd multi_source_crawler
git checkout feature/multi-source-crawler-v1

py -3.11 -m venv .venv

.\\.venv\\Scripts\\python.exe -m pip install -U pip
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt

.\\.venv\\Scripts\\crawl4ai-setup.exe
.\\.venv\\Scripts\\crawl4ai-doctor.exe
\`\`\`

Você não precisa ativar o \`Activate.ps1\`.

## Primeiro teste recomendado

\`\`\`powershell
.\\.venv\\Scripts\\python.exe crawler.py --city Vinhedo --state SP --limit 5
\`\`\`

Isso tenta no máximo 5 anúncios de cada fonte.

Quando terminar:

\`\`\`text
data/
├── listings.sqlite3
├── listings.json
└── listings.csv
\`\`\`

## Teste maior

\`\`\`powershell
.\\.venv\\Scripts\\python.exe crawler.py --city Vinhedo --state SP --pages 2 --limit 30
\`\`\`

## Testar só uma fonte

\`\`\`powershell
.\\.venv\\Scripts\\python.exe crawler.py --city Vinhedo --state SP --sources imovelweb --limit 10
\`\`\`

## Testes unitários

\`\`\`powershell
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
\`\`\`

## Comportamento responsável

Por padrão o crawler:

- respeita \`robots.txt\`;
- usa concorrência limitada;
- faz backoff em \`429\` e \`503\`;
- não tenta quebrar CAPTCHA;
- não tenta contornar login ou controles de acesso.

## Limitações da v0.1

A arquitetura já é multi-source, mas sites podem mudar HTML, paginação ou proteções. A próxima etapa é usar a saída real do seu teste para criar adaptadores específicos onde o extrator genérico falhar.
