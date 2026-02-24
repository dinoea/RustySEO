# Auditor SEO en Python (español)

Este módulo añade un crawler SEO en Python que:

- rastrea páginas internas de un dominio,
- exporta el HTML de cada URL,
- separa enlaces detectados en `navbar`, `footer` y resto,
- cuenta encabezados `h1` a `h6`,
- marca si una URL parece artículo de blog (`es_blog`),
- extrae `fecha_publicacion`, `autor`, `fecha_ultima_actualizacion` cuando es posible,
- genera un CSV pensado para consumo por:
  - un agente técnico SEO,
  - y un agente comercial orientado a impacto en ventas/gerencia.

## Requisitos

```bash
pip install -r tools/python_seo/requirements.txt
```

## Uso por CLI

```bash
python tools/python_seo/auditor_seo_es.py https://example.com --max-paginas 30 --output-dir salida_auditoria
```

Parámetros principales:

- `dominio`: URL inicial.
- `--max-paginas`: límite de URLs internas.
- `--delay`: pausa entre requests para no sobrecargar.
- `--output-dir`: carpeta donde se guarda CSV + HTML.
- `--csv`: nombre del archivo CSV de salida.

## Uso desde código (ideal para Colab)

```python
from tools.python_seo.auditor_seo_es import ejecutar_auditoria

resultados, csv_path = ejecutar_auditoria(
    dominio="https://example.com",
    max_paginas=30,
    delay=0.2,
    output_dir="/content/salida_auditoria",
    csv_name="auditoria_seo.csv",
)
```

## Google Colab

Se incluye un notebook listo para ejecutar:

- `tools/python_seo/Auditor_SEO_Colab.ipynb`

Pasos rápidos:

1. Abre el notebook en Colab.
2. Ajusta la ruta `RUTA_SCRIPT` a donde tengas el repo.
3. Configura `DOMINIO`, `MAX_PAGINAS` y `OUT_DIR`.
4. Ejecuta las celdas para generar y descargar CSV + ZIP de HTML.

## Formato de salida

El CSV incluye campos como:

- `es_blog` (booleano),
- `cantidad_h1..cantidad_h6`,
- `clases_navbar_detectadas`, `clases_footer_detectadas`,
- `links_navbar_total`, `links_footer_total`, `links_resto_total`,
- `fecha_publicacion`, `autor`, `fecha_ultima_actualizacion`,
- `prioridad_seo`, `impacto_comercial_estimado`.

Esto permite que otro agente aplique criterios de especialista SEO y otro haga una lectura comercial para C-level.
