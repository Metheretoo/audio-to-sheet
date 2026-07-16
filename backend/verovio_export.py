"""
verovio_export.py — Export MusicXML -> SVG / PDF, 100% local et gratuit.

Dépendances (offline, via pip) :
    pip install verovio          # rendu partition -> SVG
    pip install cairosvg pypdf   # (optionnel) SVG -> PDF multipage

Verovio ne sort pas de PDF directement : on rend chaque page en SVG,
puis on convertit/fusionne en PDF avec cairosvg + pypdf.
"""
from __future__ import annotations
import os
from typing import List, Optional

try:
    import verovio
except ImportError as e:
    raise ImportError("Installe verovio : pip install verovio") from e

_DEFAULT_OPTIONS = {
    "pageWidth": 2100,
    "pageHeight": 2970,
    "scale": 40,
    "adjustPageHeight": False,
    "footer": "none",
    "header": "none",
    "breaks": "auto",
}

def _make_toolkit(options: Optional[dict] = None):
    tk = verovio.toolkit()
    opts = dict(_DEFAULT_OPTIONS)
    if options:
        opts.update(options)
    tk.setOptions(opts)
    return tk

def musicxml_to_svgs(musicxml_path: str, out_dir: str,
                     basename: str = "score",
                     options: Optional[dict] = None) -> List[str]:
    """Rend un MusicXML en SVG (un fichier par page). Renvoie les chemins."""
    tk = _make_toolkit(options)
    if not tk.loadFile(musicxml_path):
        raise RuntimeError(f"Verovio n'a pas pu charger : {musicxml_path}")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for p in range(1, tk.getPageCount() + 1):
        path = os.path.join(out_dir, f"{basename}_p{p:02d}.svg")
        tk.renderToSVGFile(path, p)   # API stable toutes versions
        paths.append(path)
    return paths

def musicxml_to_pdf(musicxml_path: str, pdf_path: str,
                    options: Optional[dict] = None) -> str:
    """Rend un MusicXML en PDF multipage, 100% local. Requiert cairosvg + pypdf."""
    try:
        import io, cairosvg
        from pypdf import PdfWriter, PdfReader
    except ImportError as e:
        raise ImportError("PDF requiert : pip install cairosvg pypdf") from e

    tk = _make_toolkit(options)
    if not tk.loadFile(musicxml_path):
        raise RuntimeError(f"Verovio n'a pas pu charger : {musicxml_path}")

    writer = PdfWriter()
    for p in range(1, tk.getPageCount() + 1):
        svg = tk.renderToSVG(p)
        pdf_bytes = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
            writer.add_page(page)

    os.makedirs(os.path.dirname(os.path.abspath(pdf_path)) or ".", exist_ok=True)
    with open(pdf_path, "wb") as f:
        writer.write(f)
    return pdf_path