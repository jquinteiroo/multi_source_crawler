from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from html import unescape
from pathlib import Path
import re
import sqlite3
import statistics
import unicodedata
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit


@dataclass(slots=True)
class PropertyListing:
    source: str
    url: str
    city: str
    state: str
    title: str | None = None
    property_type: str = "terreno"
    purpose: str = "venda"
    price: float | None = None
    area_m2: float | None = None
    price_per_m2: float | None = None
    neighborhood: str | None = None
    address: str | None = None
    condominium: float | None = None
    iptu: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    description: str | None = None
    source_listing_id: str | None = None
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)

    def finalize(self) -> "PropertyListing":
        if self.price and self.area_m2 and self.area_m2 > 0:
            self.price_per_m2 = round(self.price / self.area_m2, 2)
        return self

    @property
    def fingerprint(self) -> str:
        basis = "|".join([
            self.city.strip().lower(),
            self.state.strip().lower(),
            (self.neighborhood or "").strip().lower(),
            (self.address or "").strip().lower(),
            str(round(self.area_m2 or 0, 1)),
            str(round(self.price or 0, 2)),
        ])
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    @property
    def quality_score(self) -> int:
        return (
            (3 if self.price else 0)
            + (3 if self.area_m2 else 0)
            + (2 if self.neighborhood else 0)
            + (2 if self.address else 0)
            + (1 if self.source_listing_id else 0)
            + (1 if self.description else 0)
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    domain: str
    search_url_builder: Callable[[str, str, int], str]
    property_url_patterns: tuple[str, ...]
    enabled_by_default: bool = True

    def search_url(self, city: str, state: str, page: int = 1) -> str:
        return self.search_url_builder(city, state, page)

    def is_property_url(self, url: str) -> bool:
        return self.domain in url and any(re.search(pattern, url, re.I) for pattern in self.property_url_patterns)


@dataclass(slots=True)
class SourceRun:
    source: str
    search_urls: list[str] = field(default_factory=list)
    discovered_urls: list[str] = field(default_factory=list)
    successful: int = 0
    failed: int = 0
    skipped_by_robots: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CrawlReport:
    listings: list[PropertyListing] = field(default_factory=list)
    sources: list[SourceRun] = field(default_factory=list)


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def parse_brl(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"(?:R\$\s*)?([\d.\s]+(?:,\d{1,2})?)", value)
    if not match:
        return None
    number = match.group(1).replace(" ", "")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    else:
        parts = number.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            number = "".join(parts)
    try:
        return float(number)
    except ValueError:
        return None


def parse_area_m2(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([\d.\s]+(?:,\d{1,2})?)\s*(?:m²|m2)", value, re.I)
    if not match:
        match = re.search(r"([\d.\s]+(?:,\d{1,2})?)", value)
    if not match:
        return None
    number = match.group(1).replace(" ", "")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    else:
        parts = number.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            number = "".join(parts)
    try:
        return float(number)
    except ValueError:
        return None


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def normalize_uf(state: str) -> str:
    aliases = {
        "sao paulo": "sp", "são paulo": "sp", "minas gerais": "mg",
        "rio de janeiro": "rj", "parana": "pr", "paraná": "pr",
        "santa catarina": "sc", "rio grande do sul": "rs",
        "goias": "go", "goiás": "go", "distrito federal": "df",
    }
    value = state.strip().lower()
    return aliases.get(value, value[:2]).lower()


def _zap(city: str, state: str, page: int) -> str:
    base = f"https://www.zapimoveis.com.br/venda/terrenos-lotes-condominios/{normalize_uf(state)}+{slugify(city)}/"
    return base if page <= 1 else f"{base}?pagina={page}"


def _vivareal(city: str, state: str, page: int) -> str:
    base = f"https://www.vivareal.com.br/venda/{normalize_uf(state)}/{slugify(city)}/lote-terreno_residencial/"
    return base if page <= 1 else f"{base}?pagina={page}"


def _imovelweb(city: str, state: str, page: int) -> str:
    stem = f"terrenos-venda-{slugify(city)}-{normalize_uf(state)}"
    return f"https://www.imovelweb.com.br/{stem}.html" if page <= 1 else f"https://www.imovelweb.com.br/{stem}-pagina-{page}.html"


def _chavesnamao(city: str, state: str, page: int) -> str:
    base = f"https://www.chavesnamao.com.br/terrenos-a-venda/{normalize_uf(state)}-{slugify(city)}/"
    return base if page <= 1 else f"{base}?{urlencode({'pg': page})}"


def _olx(city: str, state: str, page: int) -> str:
    base = f"https://www.olx.com.br/imoveis/terrenos/estado-{normalize_uf(state)}/{slugify(city)}"
    return base if page <= 1 else f"{base}?{urlencode({'o': page})}"


SOURCES: dict[str, Source] = {
    "zap": Source("zap", "zapimoveis.com.br", _zap, (r"/imovel/",)),
    "vivareal": Source("vivareal", "vivareal.com.br", _vivareal, (r"/imovel/",)),
    "imovelweb": Source("imovelweb", "imovelweb.com.br", _imovelweb, (r"/propriedades/",)),
    "chavesnamao": Source("chavesnamao", "chavesnamao.com.br", _chavesnamao, (r"/imovel/",)),
    "olx": Source("olx", "olx.com.br", _olx, (r"/item/", r"/d/"), enabled_by_default=False),
}


def select_sources(names: list[str] | None) -> list[Source]:
    if not names:
        return [s for s in SOURCES.values() if s.enabled_by_default]
    unknown = [name for name in names if name not in SOURCES]
    if unknown:
        raise ValueError(f"Fontes desconhecidas: {', '.join(unknown)}. Disponíveis: {', '.join(SOURCES)}")
    return [SOURCES[name] for name in names]


PRICE_RE = re.compile(r"R\$\s*[\d.]+(?:,\d{1,2})?", re.I)
AREA_RE = re.compile(r"[\d.]+(?:,\d{1,2})?\s*(?:m²|m2)", re.I)


def _markdown_text(markdown: Any) -> str:
    raw = getattr(markdown, "raw_markdown", None)
    return str(raw if raw else markdown or "")


def discover_property_links(result: Any, source: Source) -> list[str]:
    found: list[str] = []
    links = getattr(result, "links", None) or {}
    for bucket in ("internal", "external"):
        for item in links.get(bucket, []) or []:
            href = item if isinstance(item, str) else item.get("href") or item.get("url")
            if not href:
                continue
            absolute = urljoin(getattr(result, "url", ""), href)
            if source.is_property_url(absolute):
                found.append(canonicalize_url(absolute))
    html = getattr(result, "html", None) or getattr(result, "cleaned_html", None) or ""
    for href in re.findall(r'''href=["']([^"'#]+)["']''', html, re.I):
        absolute = urljoin(getattr(result, "url", ""), unescape(href))
        if source.is_property_url(absolute):
            found.append(canonicalize_url(absolute))
    return list(dict.fromkeys(found))



SEARCH_PAGE_EXTRACTION_SOURCES = {"zap", "vivareal", "imovelweb"}


def _search_page_links(result: Any, source: Source) -> list[str]:
    return discover_property_links(result, source)


def _search_page_url(result: Any, links: list[str], index: int) -> str:
    if index < len(links):
        return links[index]
    return getattr(result, "url", "") or ""


def _extract_zap_viva_search_page(
    result: Any,
    source: Source,
    city: str,
    state: str,
) -> list[PropertyListing]:
    markdown = _markdown_text(getattr(result, "markdown", ""))
    # Remove apenas a sintaxe dos links para deixar o texto dos cards mais previsível.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    links = _search_page_links(result, source)
    escaped_city = re.escape(city)

    pattern = re.compile(
        rf"(?P<title>(?:Lote/Terreno|Terreno)[^\n]{{0,220}}?)"
        rf"\s+em\s+R\$\s*(?P<price>[\d.]+(?:,\d{{1,2}})?)"
        rf"(?P<meta>[\s\S]{{0,320}}?)"
        rf"Tamanho do imóvel\s+(?P<area>[\d.,]+)\s*m²"
        rf"(?P<neighborhood>[^,\n]{{2,80}}),\s*{escaped_city}"
        rf"(?:\s+(?P<address>[^\n]{{2,180}}?))?"
        rf"(?=Contatar|\n|$)",
        re.I,
    )

    listings: list[PropertyListing] = []
    for index, match in enumerate(pattern.finditer(text)):
        meta = match.group("meta") or ""
        address = clean_text(match.group("address"))
        if address:
            address = re.sub(r"\s*Contatar\s*$", "", address, flags=re.I).strip()
        listing = PropertyListing(
            source=source.name,
            url=_search_page_url(result, links, index),
            city=city,
            state=state.upper(),
            title=clean_text(match.group("title")),
            price=parse_brl(match.group("price")),
            area_m2=parse_area_m2(match.group("area")),
            neighborhood=clean_text(match.group("neighborhood")),
            address=address,
            condominium=_extract_optional_money(meta, "Cond."),
            iptu=_extract_optional_money(meta, "IPTU"),
            raw={"origin": "search_page", "status_code": getattr(result, "status_code", None)},
        ).finalize()
        if listing.price and listing.area_m2:
            listings.append(listing)
    return listings


def _extract_imovelweb_search_page(
    result: Any,
    source: Source,
    city: str,
    state: str,
) -> list[PropertyListing]:
    markdown = _markdown_text(getattr(result, "markdown", ""))
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    links = _search_page_links(result, source)
    price_heading = re.compile(r"^##\s*R\$\s*([\d.]+(?:,\d{1,2})?)\s*$", re.M)
    price_matches = list(price_heading.finditer(text))
    listings: list[PropertyListing] = []

    for index, price_match in enumerate(price_matches):
        end = price_matches[index + 1].start() if index + 1 < len(price_matches) else min(
            len(text), price_match.end() + 1800
        )
        block = text[price_match.end():end]
        area_match = re.search(r"###\s*([\d.,]+)\s*m²\s*tot\.", block, re.I)
        if not area_match:
            continue

        before = text[max(0, price_match.start() - 350):price_match.start()]
        lines = [line.strip() for line in before.splitlines() if line.strip()]
        title = None
        for line in reversed(lines):
            if " · " in line:
                title = line.split(" · ", 1)[1].strip()
                break
            if (
                not line.startswith("#")
                and not line.lower().startswith("image")
                and len(line) > 8
            ):
                title = line
                break

        headings = re.findall(r"^####\s*(.+?)\s*$", block, re.M)
        address = clean_text(headings[0]) if headings else None
        neighborhood = None
        for heading in headings[1:]:
            match = re.match(rf"(.+?),\s*{re.escape(city)}\b", heading, re.I)
            if match:
                neighborhood = clean_text(match.group(1))
                break

        condo_match = re.search(
            r"##\s*R\$\s*([\d.]+(?:,\d{1,2})?)\s+Condominio",
            block,
            re.I,
        )
        listing = PropertyListing(
            source=source.name,
            url=_search_page_url(result, links, index),
            city=city,
            state=state.upper(),
            title=clean_text(title),
            price=parse_brl(price_match.group(1)),
            area_m2=parse_area_m2(area_match.group(1)),
            neighborhood=neighborhood,
            address=address,
            condominium=parse_brl(condo_match.group(1)) if condo_match else None,
            raw={"origin": "search_page", "status_code": getattr(result, "status_code", None)},
        ).finalize()
        if listing.price and listing.area_m2:
            listings.append(listing)
    return listings


def extract_search_page_listings(
    result: Any,
    source: Source,
    city: str,
    state: str,
) -> list[PropertyListing]:
    if source.name in {"zap", "vivareal"}:
        return _extract_zap_viva_search_page(result, source, city, state)
    if source.name == "imovelweb":
        return _extract_imovelweb_search_page(result, source, city, state)
    return []


def _extract_jsonld(html: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    pattern = r'''<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>'''
    for payload in re.findall(pattern, html or "", flags=re.I | re.S):
        try:
            data = json.loads(unescape(payload).strip())
        except Exception:
            continue
        if isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                blocks.extend(x for x in graph if isinstance(x, dict))
            blocks.append(data)
        elif isinstance(data, list):
            blocks.extend(x for x in data if isinstance(x, dict))
    return blocks


def _jsonld_fields(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in _extract_jsonld(html):
        offers = item.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        address = item.get("address") or {}
        if not isinstance(address, dict):
            address = {}
        geo = item.get("geo") or {}
        if not isinstance(geo, dict):
            geo = {}
        if item.get("name") and "title" not in out:
            out["title"] = item.get("name")
        if item.get("description") and "description" not in out:
            out["description"] = item.get("description")
        if isinstance(offers, dict) and offers.get("price") is not None and "price" not in out:
            out["price"] = offers.get("price")
        if address.get("streetAddress") and "address" not in out:
            out["address"] = address.get("streetAddress")
        if geo.get("latitude") and "latitude" not in out:
            out["latitude"] = geo.get("latitude")
        if geo.get("longitude") and "longitude" not in out:
            out["longitude"] = geo.get("longitude")
    return out


def _extract_price(markdown: str, jsonld: dict[str, Any]) -> float | None:
    if jsonld.get("price") is not None:
        parsed = parse_brl(str(jsonld["price"]))
        if parsed:
            return parsed
    for pattern in (
        r"(?:venda|para comprar)[^\n]{0,80}(R\$\s*[\d.]+(?:,\d{1,2})?)",
        r"(R\$\s*[\d.]+(?:,\d{1,2})?)[^\n]{0,40}(?:venda|para comprar)",
    ):
        match = re.search(pattern, markdown, re.I)
        if match:
            parsed = parse_brl(match.group(1))
            if parsed:
                return parsed
    values = [parse_brl(x) for x in PRICE_RE.findall(markdown)]
    values = [x for x in values if x and x >= 1000]
    return max(values) if values else None


def _extract_area(markdown: str) -> float | None:
    for pattern in (
        r"(?:Metragem|Área total|Área útil/total)[:\s#*-]*([\d.\s]+(?:,\d{1,2})?\s*(?:m²|m2))",
        r"(?:Terreno|Lote)[^\n]{0,40}([\d.\s]+(?:,\d{1,2})?\s*(?:m²|m2))",
    ):
        match = re.search(pattern, markdown, re.I)
        if match:
            area = parse_area_m2(match.group(1))
            if area and area >= 20:
                return area
    for token in AREA_RE.findall(markdown):
        area = parse_area_m2(token)
        if area and area >= 20:
            return area
    return None


def _extract_address(markdown: str, city: str, state: str) -> str | None:
    patterns = [
        r"##\s*Localização\s+([^\n#]+)",
        rf"####\s*([^\n#]+,\s*{re.escape(city)}(?:\s*[-/]\s*{re.escape(state)})?)",
        rf"##\s*([^\n#]+,\s*{re.escape(city)}/{re.escape(state)})",
    ]
    for pattern in patterns:
        match = re.search(pattern, markdown, re.I)
        if match:
            return clean_text(match.group(1).lstrip("*- "))
    return None


def _extract_neighborhood(address: str | None, markdown: str, city: str) -> str | None:
    if address:
        before_city = re.split(rf",\s*{re.escape(city)}\b", address, flags=re.I)[0]
        if " - " in before_city:
            candidate = before_city.split(" - ")[-1]
        else:
            parts = [p.strip() for p in before_city.split(",") if p.strip()]
            candidate = parts[-1] if len(parts) >= 2 else None
        if candidate and not re.match(r"^\d+$", candidate):
            return clean_text(candidate)
    match = re.search(rf"#{{1,4}}\s*([A-ZÀ-Ý][^\n,]{{2,60}}),\s*{re.escape(city)}\b", markdown, re.I)
    return clean_text(match.group(1)) if match else None


def _extract_optional_money(markdown: str, label: str) -> float | None:
    match = re.search(rf"{re.escape(label)}[^\n]{{0,30}}(?:\n|\s)*(R\$\s*[\d.]+(?:,\d{{1,2}})?)", markdown, re.I)
    return parse_brl(match.group(1)) if match else None


def _extract_listing_id(url: str) -> str | None:
    for pattern in (r"(?:id-|/id-)(\d+)", r"-(\d{7,})\.html", r"/(\d{7,})/?$"):
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_property(result: Any, source: Source, city: str, state: str) -> PropertyListing:
    markdown = _markdown_text(getattr(result, "markdown", ""))
    html = getattr(result, "html", None) or ""
    jsonld = _jsonld_fields(html)
    url = canonicalize_url(getattr(result, "url", ""))
    title_match = re.search(r"^#\s+(.+)$", markdown, re.M)
    title = clean_text(jsonld.get("title") or (title_match.group(1) if title_match else None))
    address = clean_text(jsonld.get("address") or _extract_address(markdown, city, state))
    neighborhood = _extract_neighborhood(address, markdown, city)
    listing = PropertyListing(
        source=source.name,
        url=url,
        city=city,
        state=state.upper(),
        title=title,
        price=_extract_price(markdown, jsonld),
        area_m2=_extract_area(markdown),
        neighborhood=neighborhood,
        address=address,
        condominium=_extract_optional_money(markdown, "Condomínio"),
        iptu=_extract_optional_money(markdown, "IPTU"),
        latitude=float(jsonld["latitude"]) if jsonld.get("latitude") else None,
        longitude=float(jsonld["longitude"]) if jsonld.get("longitude") else None,
        description=clean_text(jsonld.get("description")),
        source_listing_id=_extract_listing_id(url),
        raw={"status_code": getattr(result, "status_code", None)},
    )
    return listing.finalize()


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    fingerprint TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_listing_id TEXT,
    url TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    title TEXT,
    price REAL,
    area_m2 REAL,
    price_per_m2 REAL,
    neighborhood TEXT,
    address TEXT,
    condominium REAL,
    iptu REAL,
    latitude REAL,
    longitude REAL,
    description TEXT,
    quality_score INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    raw_json TEXT NOT NULL
);
"""


def deduplicate(listings: Iterable[PropertyListing]) -> list[PropertyListing]:
    best: dict[str, PropertyListing] = {}
    for listing in listings:
        current = best.get(listing.fingerprint)
        if current is None or listing.quality_score > current.quality_score:
            best[listing.fingerprint] = listing
    return list(best.values())


def save_outputs(listings: list[PropertyListing], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    json_rows = [x.to_dict() for x in listings]
    (output / "listings.json").write_text(json.dumps(json_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_fields = [k for k in json_rows[0].keys() if k != "raw"] if json_rows else []
    with (output / "listings.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        if csv_fields:
            writer = csv.DictWriter(handle, fieldnames=csv_fields)
            writer.writeheader()
            for row in json_rows:
                writer.writerow({key: row.get(key) for key in csv_fields})
    with sqlite3.connect(output / "listings.sqlite3") as conn:
        conn.execute(SCHEMA)
        for x in listings:
            conn.execute(
                """
                INSERT INTO listings (
                    fingerprint, source, source_listing_id, url, city, state,
                    title, price, area_m2, price_per_m2, neighborhood, address,
                    condominium, iptu, latitude, longitude, description,
                    quality_score, collected_at, raw_json
                ) VALUES (
                    :fingerprint, :source, :source_listing_id, :url, :city, :state,
                    :title, :price, :area_m2, :price_per_m2, :neighborhood, :address,
                    :condominium, :iptu, :latitude, :longitude, :description,
                    :quality_score, :collected_at, :raw_json
                )
                ON CONFLICT(fingerprint) DO UPDATE SET
                    source=excluded.source, url=excluded.url, price=excluded.price,
                    area_m2=excluded.area_m2, price_per_m2=excluded.price_per_m2,
                    neighborhood=excluded.neighborhood, address=excluded.address,
                    condominium=excluded.condominium, iptu=excluded.iptu,
                    quality_score=excluded.quality_score, collected_at=excluded.collected_at,
                    raw_json=excluded.raw_json
                """,
                {**x.to_dict(), "fingerprint": x.fingerprint, "quality_score": x.quality_score, "raw_json": json.dumps(x.raw, ensure_ascii=False)},
            )
        conn.commit()


async def crawl_city(city: str, state: str, sources: list[Source], pages: int, per_source_limit: int, concurrency: int, respect_robots: bool) -> CrawlReport:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, RateLimiter
    from crawl4ai.async_dispatcher import SemaphoreDispatcher

    browser_config = BrowserConfig(headless=True, verbose=False, java_script_enabled=True)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        check_robots_txt=respect_robots,
        stream=False,
        page_timeout=60_000,
    )
    listing_dispatcher = SemaphoreDispatcher(
        max_session_permit=max(1, min(concurrency, 3)),
        rate_limiter=RateLimiter(
            base_delay=(1.0, 2.0),
            max_delay=10.0,
            max_retries=2,
            rate_limit_codes=[429, 503],
        ),
    )
    # Páginas de detalhe são mais sensíveis a rate limiting. Mantemos baixa
    # concorrência e pausas maiores para não pressionar um mesmo domínio.
    detail_dispatcher = SemaphoreDispatcher(
        max_session_permit=max(1, min(concurrency, 2)),
        rate_limiter=RateLimiter(
            base_delay=(2.0, 4.0),
            max_delay=20.0,
            max_retries=3,
            rate_limit_codes=[429, 503],
        ),
    )
    report = CrawlReport()
    async with AsyncWebCrawler(config=browser_config) as crawler:
        for source in sources:
            source_run = SourceRun(source=source.name)
            source_run.search_urls = [source.search_url(city, state, page) for page in range(1, max(1, pages) + 1)]
            report.sources.append(source_run)
            try:
                results = await crawler.arun_many(source_run.search_urls, config=run_config, dispatcher=listing_dispatcher)
            except Exception as exc:
                source_run.failed += len(source_run.search_urls)
                source_run.errors.append(f"listing pages: {exc}")
                continue
            discovered: list[str] = []
            direct_fingerprints: set[str] = set()
            for result in results:
                if not result.success:
                    source_run.failed += 1
                    message = result.error_message or f"HTTP {result.status_code}"
                    if "robots.txt" in message.lower():
                        source_run.skipped_by_robots += 1
                    source_run.errors.append(f"{result.url}: {message}")
                    continue

                discovered.extend(discover_property_links(result, source))

                # ZAP, Viva Real e Imovelweb já expõem preço/área/localização
                # nos cards da página de busca. Preferimos esses dados e só
                # abrimos páginas individuais para completar o que faltar.
                if (
                    source.name in SEARCH_PAGE_EXTRACTION_SOURCES
                    and source_run.successful < per_source_limit
                ):
                    try:
                        page_listings = extract_search_page_listings(
                            result, source, city, state
                        )
                    except Exception as exc:
                        source_run.errors.append(
                            f"{result.url}: search-page extraction: {exc}"
                        )
                        page_listings = []

                    for listing in page_listings:
                        if source_run.successful >= per_source_limit:
                            break
                        if listing.fingerprint in direct_fingerprints:
                            continue
                        direct_fingerprints.add(listing.fingerprint)
                        report.listings.append(listing)
                        source_run.successful += 1

            source_run.discovered_urls = list(dict.fromkeys(discovered))[: max(1, per_source_limit)]
            if (
                source.name in SEARCH_PAGE_EXTRACTION_SOURCES
                and source_run.successful == 0
            ):
                source_run.errors.append(
                    "search page loaded, but no structured cards were extracted"
                )

        # Processa anúncios em pequenos lotes e alterna as fontes. Isso evita
        # disparar 20–30 páginas seguidas contra o mesmo portal.
        batch_size = min(5, max(1, per_source_limit))
        detail_urls_by_source: dict[str, list[str]] = {}
        for source_run in report.sources:
            remaining = max(0, per_source_limit - source_run.successful)
            detail_urls_by_source[source_run.source] = source_run.discovered_urls[:remaining]

        max_batches = max(
            (
                (len(urls) + batch_size - 1) // batch_size
                for urls in detail_urls_by_source.values()
            ),
            default=0,
        )

        for batch_index in range(max_batches):
            for source, source_run in zip(sources, report.sources):
                start = batch_index * batch_size
                detail_urls = detail_urls_by_source[source.name]
                batch = detail_urls[start:start + batch_size]
                if not batch:
                    continue
                try:
                    results = await crawler.arun_many(
                        batch,
                        config=run_config,
                        dispatcher=detail_dispatcher,
                    )
                except Exception as exc:
                    source_run.failed += len(batch)
                    source_run.errors.append(f"property pages batch {batch_index + 1}: {exc}")
                    await asyncio.sleep(1.5)
                    continue

                for result in results:
                    if not result.success:
                        source_run.failed += 1
                        message = result.error_message or f"HTTP {result.status_code}"
                        if "robots.txt" in message.lower():
                            source_run.skipped_by_robots += 1
                        source_run.errors.append(f"{result.url}: {message}")
                        continue
                    try:
                        listing = extract_property(result, source, city, state)
                    except Exception as exc:
                        source_run.failed += 1
                        source_run.errors.append(f"{result.url}: extraction: {exc}")
                        continue
                    if not listing.price or not listing.area_m2:
                        source_run.failed += 1
                        missing = []
                        if not listing.price:
                            missing.append("preço")
                        if not listing.area_m2:
                            missing.append("área")
                        source_run.errors.append(
                            f"{result.url}: missing critical {'/'.join(missing)}"
                        )
                        continue
                    source_run.successful += 1
                    report.listings.append(listing)

                # Pequena pausa entre lotes para reduzir a chance de bloqueio.
                await asyncio.sleep(1.5)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawler multi-fonte de terrenos usando Crawl4AI.")
    parser.add_argument("--city", required=True, help="Cidade, ex.: Vinhedo")
    parser.add_argument("--state", required=True, help="UF, ex.: SP")
    parser.add_argument("--sources", default="", help=f"Separadas por vírgula. Disponíveis: {', '.join(SOURCES)}")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output", default="data")
    parser.add_argument("--ignore-robots", action="store_true", help="Desativa robots.txt (não recomendado).")
    return parser


async def run_cli(args: argparse.Namespace) -> int:
    names = [x.strip().lower() for x in args.sources.split(",") if x.strip()] or None
    sources = select_sources(names)
    print(f"Coletando terrenos em {args.city}/{args.state.upper()} de {', '.join(s.name for s in sources)}...")
    report = await crawl_city(
        city=args.city,
        state=args.state,
        sources=sources,
        pages=args.pages,
        per_source_limit=args.limit,
        concurrency=args.concurrency,
        respect_robots=not args.ignore_robots,
    )
    listings = deduplicate(report.listings)
    save_outputs(listings, Path(args.output))
    print("\nResumo por fonte")
    print("-" * 72)
    for src in report.sources:
        print(f"{src.source:14} descobertos={len(src.discovered_urls):3} ok={src.successful:3} falhas={src.failed:3} robots={src.skipped_by_robots:3}")
        for error in src.errors[:3]:
            print(f"  - {error}")
    print("-" * 72)
    print(f"Brutos válidos: {len(report.listings)}")
    print(f"Após deduplicação: {len(listings)}")
    ppm2 = [x.price_per_m2 for x in listings if x.price_per_m2]
    if ppm2:
        print(f"Mediana de preço/m²: R$ {statistics.median(ppm2):,.2f}")
    print(f"Saída: {Path(args.output).resolve()}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run_cli(args))
    except KeyboardInterrupt:
        return 130
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
