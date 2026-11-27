"""Insert the pipeline results into the Phase-1 report.

    python3 fill_report.py            (uses report_template/Phase1_Report_template.docx)

Each yellow "[…]" placeholder in the report is preceded by a hidden key
(e.g. «POOLED_POST_DS»). This script replaces the placeholder with the value
from outputs/report_values.json, removes the highlight and the hidden key,
and swaps the three results-figure placeholders for outputs/figures/*.png.
Output: Phase1_Report_filled.docx in this folder (the template is not modified). Placeholders
without a value stay yellow so they are easy to find.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "outputs" / "report_values.json"
TEMPLATE = ROOT / "report_template" / "Phase1_Report_template.docx"
FIGURES = {
    "word/media/fig_4_1_placeholder.png": ROOT / "outputs" / "figures" / "fig_4_1_profiles.png",
    "word/media/fig_4_2_placeholder.png": ROOT / "outputs" / "figures" / "fig_4_2_event_study.png",
    "word/media/fig_4_3_placeholder.png": ROOT / "outputs" / "figures" / "fig_4_3_heterogeneity.png",
}
TOKEN = re.compile(
    r'<w:r><w:rPr><w:vanish/></w:rPr><w:t xml:space="preserve">«([A-Za-z0-9_]+)»</w:t></w:r>'
    r'<w:r><w:rPr>((?:(?!</w:rPr>).)*?)<w:highlight w:val="yellow"/></w:rPr>'
    r'<w:t xml:space="preserve">\[…\]</w:t></w:r>')


def main(src: str):
    src = Path(src)
    dst = ROOT / "Phase1_Report_filled.docx"
    values = json.loads(VALUES.read_text(encoding="utf-8"))
    missing, n = set(), [0]

    def rep(m):
        key, rpr = m.group(1), m.group(2)
        if key not in values:
            missing.add(key)
            return m.group(0)
        n[0] += 1
        rp = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
        return f'<w:r>{rp}<w:t xml:space="preserve">{escape(str(values[key]))}</w:t></w:r>'

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = TOKEN.sub(rep, data.decode("utf-8")).encode("utf-8")
            elif item.filename in FIGURES and FIGURES[item.filename].exists():
                data = FIGURES[item.filename].read_bytes()
            zout.writestr(item, data)
    print(f"written {dst}: {n[0]} values inserted")
    if missing:
        print(f"{len(missing)} placeholders had no value and stay yellow: {sorted(missing)}")
    print("Open the file in Word and update the table of contents (right-click > Update Field).")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(TEMPLATE))
