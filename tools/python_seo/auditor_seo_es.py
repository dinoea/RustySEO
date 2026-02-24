#!/usr/bin/env python3
"""Auditor SEO en español.

Rastrea un sitio, exporta HTML por URL y genera un CSV con señales para:
- Agente de auditoría SEO técnica
- Agente de revisión comercial (impacto en ventas)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

USER_AGENT = "RustySEO-Python-Auditor/1.0 (+https://github.com/mascanho/RustySEO)"
REQUEST_TIMEOUT = 15

BLOG_URL_HINTS = (
    "/blog",
    "/articulo",
    "/artículos",
    "/post",
    "/noticia",
    "/news",
)

BLOG_CLASS_HINTS = (
    "post",
    "article",
    "blog",
    "entry",
    "single-post",
)

DATE_META_CANDIDATES = (
    "article:published_time",
    "article:modified_time",
    "publish_date",
    "pubdate",
    "date",
    "dc.date",
    "dc.date.issued",
    "lastmod",
)

AUTHOR_META_CANDIDATES = (
    "author",
    "article:author",
    "parsely-author",
)


@dataclass
class ResultadoPagina:
    url: str
    status_code: int
    content_type: str
    is_html: bool
    es_blog: bool
    fecha_publicacion: str
    fecha_ultima_actualizacion: str
    autor: str
    cantidad_h1: int
    cantidad_h2: int
    cantidad_h3: int
    cantidad_h4: int
    cantidad_h5: int
    cantidad_h6: int
    links_navbar_total: int
    links_footer_total: int
    links_resto_total: int
    clases_navbar_detectadas: str
    clases_footer_detectadas: str
    html_guardado_path: str
    observaciones: str
    prioridad_seo: str
    impacto_comercial_estimado: str


def normalizar_url(base: str, link: str) -> Optional[str]:
    if not link:
        return None
    link = link.strip()
    if link.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    full = urljoin(base, link)
    full, _ = urldefrag(full)
    parsed = urlparse(full)
    if parsed.scheme not in ("http", "https"):
        return None
    clean = parsed._replace(query="", fragment="").geturl().rstrip("/")
    return clean


def es_url_interna(url: str, dominio_base: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return netloc == dominio_base or netloc.endswith("." + dominio_base)


def slug_para_archivo(url: str) -> str:
    digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "home"
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", path)[:80]
    return f"{safe}_{digest}.html"


def obtener_clases_y_id(tag) -> List[str]:
    vals: List[str] = []
    cls = tag.get("class") or []
    vals.extend(str(c) for c in cls)
    tag_id = tag.get("id")
    if tag_id:
        vals.append(str(tag_id))
    return vals


def detectar_bloque_con_hints(soup: BeautifulSoup, hints: Iterable[str], tags: Iterable[str]):
    hints_lower = tuple(h.lower() for h in hints)

    for tag_name in tags:
        tag = soup.find(tag_name)
        if tag:
            return tag

    for tag in soup.find_all(True):
        tokens = " ".join(obtener_clases_y_id(tag)).lower()
        if any(h in tokens for h in hints_lower):
            return tag

    return None


def extraer_links_por_bloque(soup: BeautifulSoup) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    nav_tag = detectar_bloque_con_hints(
        soup,
        hints=("nav", "navbar", "menu", "header-menu", "main-menu"),
        tags=("nav",),
    )
    footer_tag = detectar_bloque_con_hints(
        soup,
        hints=("footer", "site-footer", "footer-menu"),
        tags=("footer",),
    )

    nav_links: Set[str] = set()
    footer_links: Set[str] = set()
    nav_classes: Set[str] = set()
    footer_classes: Set[str] = set()

    if nav_tag:
        nav_classes.update(obtener_clases_y_id(nav_tag))
        for a in nav_tag.find_all("a", href=True):
            nav_links.add(a["href"].strip())

    if footer_tag:
        footer_classes.update(obtener_clases_y_id(footer_tag))
        for a in footer_tag.find_all("a", href=True):
            footer_links.add(a["href"].strip())

    return nav_links, footer_links, nav_classes, footer_classes


def extraer_json_ld(soup: BeautifulSoup) -> List[Dict]:
    items: List[Dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for elem in data:
                    if isinstance(elem, dict):
                        items.append(elem)
            elif isinstance(data, dict):
                items.append(data)
        except json.JSONDecodeError:
            continue
    return items


def buscar_meta(soup: BeautifulSoup, candidatos: Iterable[str]) -> str:
    lower_cands = {c.lower() for c in candidatos}
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower().strip()
        if name in lower_cands:
            content = (meta.get("content") or "").strip()
            if content:
                return content
    return ""


def parsear_fecha(valor: str) -> str:
    if not valor:
        return ""
    valor = valor.strip()
    formatos = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%Y/%m/%d",
    ]
    for fmt in formatos:
        try:
            dt = datetime.strptime(valor, fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return valor


def detectar_datos_blog(url: str, soup: BeautifulSoup) -> Tuple[bool, str, str, str]:
    url_low = url.lower()
    es_blog = any(h in url_low for h in BLOG_URL_HINTS)

    root_classes = " ".join(
        c.lower() for t in soup.find_all(True) for c in obtener_clases_y_id(t)
    )
    if any(h in root_classes for h in BLOG_CLASS_HINTS):
        es_blog = True

    fecha_publicacion = ""
    fecha_ultima_actualizacion = ""
    autor = ""

    json_ld = extraer_json_ld(soup)
    for item in json_ld:
        t = str(item.get("@type", "")).lower()
        if "blogposting" in t or "article" in t or "newsarticle" in t:
            es_blog = True
            fecha_publicacion = fecha_publicacion or str(item.get("datePublished", "")).strip()
            fecha_ultima_actualizacion = fecha_ultima_actualizacion or str(item.get("dateModified", "")).strip()
            if isinstance(item.get("author"), dict):
                autor = autor or str(item["author"].get("name", "")).strip()
            elif isinstance(item.get("author"), list):
                nombres = []
                for a in item["author"]:
                    if isinstance(a, dict) and a.get("name"):
                        nombres.append(str(a["name"]).strip())
                if nombres:
                    autor = autor or ", ".join(nombres)
            elif item.get("author"):
                autor = autor or str(item.get("author")).strip()

    fecha_publicacion = fecha_publicacion or buscar_meta(soup, DATE_META_CANDIDATES)
    fecha_ultima_actualizacion = fecha_ultima_actualizacion or buscar_meta(
        soup, ("article:modified_time", "lastmod", "dc.date.modified")
    )
    autor = autor or buscar_meta(soup, AUTHOR_META_CANDIDATES)

    for selector in ("time[datetime]", "meta[itemprop='datePublished']", "meta[itemprop='dateModified']"):
        if not fecha_publicacion:
            node = soup.select_one(selector)
            if node:
                fecha_publicacion = (node.get("datetime") or node.get("content") or "").strip()

    if not autor:
        autor_node = soup.select_one("[rel='author'], .author, [itemprop='author']")
        if autor_node:
            autor = autor_node.get_text(" ", strip=True) or (autor_node.get("content") or "")

    return es_blog, parsear_fecha(fecha_publicacion), parsear_fecha(fecha_ultima_actualizacion), autor


def prioridad_y_impacto(row: ResultadoPagina) -> Tuple[str, str]:
    if row.status_code >= 400:
        return "alta", "Riesgo directo de pérdida de tráfico y conversiones por páginas no accesibles."
    if row.cantidad_h1 == 0:
        return "media", "Disminuye claridad semántica; puede afectar rankings y descubrimiento de producto."
    if row.es_blog and (not row.fecha_publicacion or not row.autor):
        return "media", "Reduce señales E-E-A-T y confianza, impactando captación orgánica en TOFU/MOFU."
    return "baja", "Sin impacto comercial crítico inmediato; optimización incremental."


def analizar_pagina(url: str, output_html_dir: Path, session: requests.Session) -> Tuple[ResultadoPagina, Set[str]]:
    nuevos_links: Set[str] = set()
    status_code = 0
    content_type = ""
    observaciones = ""

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status_code = resp.status_code
        content_type = resp.headers.get("content-type", "")
    except requests.RequestException as exc:
        res = ResultadoPagina(
            url=url,
            status_code=0,
            content_type="",
            is_html=False,
            es_blog=False,
            fecha_publicacion="",
            fecha_ultima_actualizacion="",
            autor="",
            cantidad_h1=0,
            cantidad_h2=0,
            cantidad_h3=0,
            cantidad_h4=0,
            cantidad_h5=0,
            cantidad_h6=0,
            links_navbar_total=0,
            links_footer_total=0,
            links_resto_total=0,
            clases_navbar_detectadas="",
            clases_footer_detectadas="",
            html_guardado_path="",
            observaciones=f"Error al descargar: {exc}",
            prioridad_seo="alta",
            impacto_comercial_estimado="Riesgo alto: URL no disponible para usuarios ni buscadores.",
        )
        return res, nuevos_links

    is_html = "text/html" in content_type.lower()
    html_path = ""
    es_blog = False
    fecha_pub = ""
    fecha_mod = ""
    autor = ""

    h1 = h2 = h3 = h4 = h5 = h6 = 0
    nav_total = footer_total = resto_total = 0
    nav_classes: Set[str] = set()
    footer_classes: Set[str] = set()

    if is_html:
        html = resp.text
        filename = slug_para_archivo(url)
        filepath = output_html_dir / filename
        filepath.write_text(html, encoding="utf-8", errors="ignore")
        html_path = str(filepath)

        soup = BeautifulSoup(html, "html.parser")

        h1 = len(soup.find_all("h1"))
        h2 = len(soup.find_all("h2"))
        h3 = len(soup.find_all("h3"))
        h4 = len(soup.find_all("h4"))
        h5 = len(soup.find_all("h5"))
        h6 = len(soup.find_all("h6"))

        nav_links_raw, footer_links_raw, nav_classes, footer_classes = extraer_links_por_bloque(soup)
        nav_links = {normalizar_url(url, l) for l in nav_links_raw}
        footer_links = {normalizar_url(url, l) for l in footer_links_raw}
        nav_links.discard(None)
        footer_links.discard(None)

        all_links = set()
        for a in soup.find_all("a", href=True):
            nu = normalizar_url(url, a["href"])
            if nu:
                all_links.add(nu)

        nav_total = len(nav_links)
        footer_total = len(footer_links)
        resto_total = len(all_links - nav_links - footer_links)

        nuevos_links = all_links

        es_blog, fecha_pub, fecha_mod, autor = detectar_datos_blog(url, soup)

    else:
        observaciones = "Contenido no HTML, omitido para análisis on-page."

    row = ResultadoPagina(
        url=url,
        status_code=status_code,
        content_type=content_type,
        is_html=is_html,
        es_blog=es_blog,
        fecha_publicacion=fecha_pub,
        fecha_ultima_actualizacion=fecha_mod,
        autor=autor,
        cantidad_h1=h1,
        cantidad_h2=h2,
        cantidad_h3=h3,
        cantidad_h4=h4,
        cantidad_h5=h5,
        cantidad_h6=h6,
        links_navbar_total=nav_total,
        links_footer_total=footer_total,
        links_resto_total=resto_total,
        clases_navbar_detectadas="|".join(sorted(nav_classes)),
        clases_footer_detectadas="|".join(sorted(footer_classes)),
        html_guardado_path=html_path,
        observaciones=observaciones,
        prioridad_seo="",
        impacto_comercial_estimado="",
    )

    prioridad, impacto = prioridad_y_impacto(row)
    row.prioridad_seo = prioridad
    row.impacto_comercial_estimado = impacto
    return row, nuevos_links


def crawl(dominio_inicial: str, max_paginas: int, delay_s: float, output_dir: Path) -> List[ResultadoPagina]:
    parsed = urlparse(dominio_inicial)
    if not parsed.scheme:
        dominio_inicial = f"https://{dominio_inicial}"
        parsed = urlparse(dominio_inicial)

    dominio_base = parsed.netloc.lower()
    visitadas: Set[str] = set()
    cola = deque([dominio_inicial.rstrip("/")])

    output_html_dir = output_dir / "html_exportado"
    output_html_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    resultados: List[ResultadoPagina] = []

    while cola and len(visitadas) < max_paginas:
        actual = cola.popleft()
        if actual in visitadas:
            continue
        visitadas.add(actual)

        resultado, links = analizar_pagina(actual, output_html_dir, session)
        resultados.append(resultado)

        for link in links:
            if link and es_url_interna(link, dominio_base) and link not in visitadas:
                cola.append(link)

        if delay_s > 0:
            time.sleep(delay_s)

    return resultados


def exportar_csv(resultados: List[ResultadoPagina], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    campos = [
        "url",
        "status_code",
        "content_type",
        "is_html",
        "es_blog",
        "fecha_publicacion",
        "fecha_ultima_actualizacion",
        "autor",
        "cantidad_h1",
        "cantidad_h2",
        "cantidad_h3",
        "cantidad_h4",
        "cantidad_h5",
        "cantidad_h6",
        "links_navbar_total",
        "links_footer_total",
        "links_resto_total",
        "clases_navbar_detectadas",
        "clases_footer_detectadas",
        "html_guardado_path",
        "observaciones",
        "prioridad_seo",
        "impacto_comercial_estimado",
    ]

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for r in resultados:
            writer.writerow(r.__dict__)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawler SEO en español con exportación de HTML + CSV para auditoría técnica y comercial."
    )
    parser.add_argument("dominio", nargs="?", help="Dominio inicial, ej: https://example.com")
    parser.add_argument("--max-paginas", type=int, default=50, help="Máximo de páginas internas a rastrear")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay entre requests (segundos)")
    parser.add_argument(
        "--output-dir",
        default="salida_auditoria",
        help="Carpeta de salida para CSV y HTML exportado",
    )
    parser.add_argument(
        "--csv",
        default="auditoria_seo.csv",
        help="Nombre del archivo CSV final",
    )
    args = parser.parse_args(argv)
    if not args.dominio:
        parser.error("Debes indicar un dominio. Ejemplo: https://example.com")
    return args


def ejecutar_auditoria(
    dominio: str,
    max_paginas: int = 50,
    delay: float = 0.3,
    output_dir: str = "salida_auditoria",
    csv_name: str = "auditoria_seo.csv",
) -> Tuple[List[ResultadoPagina], Path]:
    out_dir = Path(output_dir)

    resultados = crawl(
        dominio_inicial=dominio,
        max_paginas=max_paginas,
        delay_s=delay,
        output_dir=out_dir,
    )

    output_csv = out_dir / csv_name
    exportar_csv(resultados, output_csv)
    return resultados, output_csv


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    resultados, output_csv = ejecutar_auditoria(
        dominio=args.dominio,
        max_paginas=args.max_paginas,
        delay=args.delay,
        output_dir=args.output_dir,
        csv_name=args.csv,
    )

    print("✅ Auditoría finalizada")
    print(f"- URLs analizadas: {len(resultados)}")
    print(f"- CSV generado: {output_csv}")
    print(f"- HTML exportado: {Path(args.output_dir) / 'html_exportado'}")


if __name__ == "__main__":
    main()
