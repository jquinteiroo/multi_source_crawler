# Multi Source Crawler

Crawler multi-fonte para coletar e normalizar anúncios públicos de terrenos/lotes para o AnalisaImóvel.

> Status: em desenvolvimento. A implementação principal está sendo feita em branch de feature antes de entrar no `main`.

## Objetivo

Receber uma cidade/UF e coletar anúncios de várias fontes, normalizando campos como preço, área, bairro, endereço, condomínio, IPTU e URL de origem.

## Princípios

- Crawl4AI self-hosted
- extração determinística sempre que possível
- fontes isoladas por adaptadores
- rate limiting e sem bypass de CAPTCHA/controles de acesso
- deduplicação e persistência local
