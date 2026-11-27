"""Build the final report on the template of the Phase 1 report, adding the Phase 2 work.

    python tools/build_final_report.py            # -> teslim/Final_Report.docx and teslim/Final_Report.pdf

Input : docs/Phase1_Report_submitted.docx (the submitted Phase 1 report; it is read, never modified),
        paper/generated/values.tex and tab_*.tex (numbers and tables written by tools/build_paper.py),
        outputs/scenario_values.json, outputs/models/scenario_bundle.joblib, figures in paper/figures and outputs/figures.
Output: teslim/Final_Report.docx (+ .pdf). The table of contents and the lists of tables and figures are extended in the
        format of the Phase 1 report; on macOS with Microsoft Word, Word fills in their page numbers (PAGEREF fields)
        and exports the PDF.

The Phase 1 text, tables and figures are kept. Sentences that referred to Phase 2 in the future tense are updated,
and the Phase 2 sections are added with the same paragraph, heading, caption and table formats. No result is typed
by hand: every number comes from the pipeline outputs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "Phase1_Report_submitted.docx"
GEN = ROOT / "paper" / "generated"
FIGS = ROOT / "paper" / "figures"
BUILD = ROOT / "build_report"
OUT_DOCX = ROOT / "teslim" / "Final_Report.docx"
OUT_PDF = ROOT / "teslim" / "Final_Report.pdf"
NS = nsdecls("w", "m")


# ----------------------------------------------------------------- numbers from the pipeline
def tex2txt(c: str) -> str:
    c = c.replace("\\xspace", "").replace("\\ensuremath{-}", "−").replace("\\ensuremath{<}", "<")
    c = c.replace("\\%", "%").replace("\\&", "&")
    for a, b in [("{\\c{S}}", "Ş"), ("{\\c{s}}", "ş"), ("{\\u{g}}", "ğ"), ('{\\"u}', "ü"), ('{\\"o}', "ö"), ("{\\i}", "ı")]:
        c = c.replace(a, b)
    c = c.replace("$\\eta^2 < 0.001$", "η² < 0.001").replace("$\\eta^2$", "η²")
    c = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", c)
    c = c.replace("$n$", "n").replace("$", "").replace("--", "–")
    return c.strip()


V = {m.group(1): tex2txt(m.group(2))
     for m in re.finditer(r"\\newcommand\{\\v([A-Za-z]+)\}\{(.*)\}\s*$", (GEN / "values.tex").read_text(), re.M)}


def tex_rows(name: str) -> list[list[str]]:
    s = (GEN / f"tab_{name}.tex").read_text()
    body = s.split("\\midrule", 1)[1].split("\\bottomrule")[0]
    rows = []
    for line in body.split("\\\\"):
        line = line.replace("\\midrule", "").strip()
        if line:
            rows.append([tex2txt(c) for c in line.split("&")])
    return rows


SV = json.loads((ROOT / "outputs" / "scenario_values.json").read_text())
try:
    import joblib
    TE = joblib.load(ROOT / "outputs" / "models" / "scenario_bundle.joblib")["test_eval"]["summary"]
except Exception:                                   # bundle missing: run python run_scenario.py first
    TE = None


def f(x, d=2, sign=False):
    s = f"{x:+.{d}f}" if sign else f"{x:.{d}f}"
    return s.replace("-", "−")


# ----------------------------------------------------------------- XML building blocks (formats of the Phase 1 report)
P_BODY = '<w:pPr><w:spacing w:before="0" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
P_BODY_GAP = '<w:pPr><w:spacing w:before="120" w:after="120" w:line="360" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
P_LEAD = '<w:pPr><w:spacing w:before="200" w:after="60" w:line="360" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
P_BULLET = ('<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="21"/></w:numPr><w:spacing w:before="0" w:after="60" '
            'w:line="336" w:lineRule="auto"/><w:ind w:left="720" w:hanging="360"/><w:jc w:val="both"/></w:pPr>')
P_H2 = '<w:pPr><w:pStyle w:val="Heading2"/><w:spacing w:before="240" w:after="120" w:line="360" w:lineRule="auto"/></w:pPr>'
R_H2 = '<w:rPr><w:caps w:val="0"/></w:rPr>'
_H3F = ('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:b/><w:i/>'
        '<w:sz w:val="24"/><w:szCs w:val="24"/>')
P_H3 = ('<w:pPr><w:pStyle w:val="Heading3"/><w:numPr><w:ilvl w:val="2"/><w:numId w:val="6"/></w:numPr>'
        f'<w:spacing w:before="200" w:after="80" w:line="360" w:lineRule="auto"/><w:rPr>{_H3F}</w:rPr></w:pPr>')
R_H3 = f"<w:rPr>{_H3F}</w:rPr>"
P_TCAP = '<w:pPr><w:pStyle w:val="TableCaption"/><w:keepNext/><w:spacing w:before="240" w:after="100"/><w:jc w:val="center"/></w:pPr>'
P_FCAP = '<w:pPr><w:pStyle w:val="FigureCaption"/><w:spacing w:before="60" w:after="240"/><w:jc w:val="center"/></w:pPr>'
P_FIG = '<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="0"/><w:jc w:val="center"/></w:pPr>'
P_NOTE = '<w:pPr><w:spacing w:before="40" w:after="200" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr>'
P_SYM = '<w:pPr><w:spacing w:before="0" w:after="40" w:line="300" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr>'
P_REF = ('<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="24"/></w:numPr><w:spacing w:before="0" w:after="100" '
         'w:line="300" w:lineRule="auto"/><w:ind w:left="567" w:hanging="567"/><w:jc w:val="left"/></w:pPr>')
P_CODE = ('<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F4F4F2"/><w:spacing w:before="0" w:after="0" '
          'w:line="240" w:lineRule="auto"/><w:ind w:left="284" w:right="284"/></w:pPr>')
P_APP = '<w:pPr><w:spacing w:before="360" w:after="60" w:line="360" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr>'
P_EQ = ('<w:pPr><w:tabs><w:tab w:val="center" w:pos="4320"/><w:tab w:val="right" w:pos="8640"/></w:tabs>'
        '<w:spacing w:before="120" w:after="160"/></w:pPr>')

TOKEN = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`|\^\{[^}]+\}|_\{[^}]+\})")


def run(text, b=False, i=False, code=False, sz=None, sup=False, sub=False):
    rpr = ""
    if code:
        rpr += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
    if b:
        rpr += "<w:b/><w:bCs/>"
    if i:
        rpr += "<w:i/><w:iCs/>"
    if sz:
        rpr += f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>'
    if sup or sub:
        rpr += f'<w:vertAlign w:val="{"superscript" if sup else "subscript"}"/>'
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def runs(markup: str, sz=None) -> str:
    """**bold**, __italic__, `code`, ^{sup}, _{sub}."""
    out = []
    for part in TOKEN.split(markup):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(run(part[2:-2], b=True, sz=sz))
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            out.append(run(part[2:-2], i=True, sz=sz))
        elif part.startswith("`") and part.endswith("`"):
            out.append(run(part[1:-1], code=True, sz=(sz - 2) if sz else 20))
        elif part.startswith("^{"):
            out.append(run(part[2:-1], sup=True, sz=sz))
        elif part.startswith("_{"):
            out.append(run(part[2:-1], sub=True, sz=sz))
        else:
            out.append(run(part, sz=sz))
    return "".join(out)


def para(ppr: str, markup: str = "", sz=None, raw_runs: str | None = None):
    return parse_xml(f"<w:p {NS}>{ppr}{raw_runs if raw_runs is not None else runs(markup, sz)}</w:p>")


def body(t):
    return para(P_BODY, t)


def bullet(t):
    return para(P_BULLET, t)


TOC_NEW = []                       # (level, number, title, bookmark) of the new headings, in document order
CAP_NEW = {"Table": [], "Figure": []}
_BM = [7000]


def bookmark(p):
    _BM[0] += 1
    i, name = _BM[0], f"_Toc{_BM[0]}"
    start = parse_xml(f'<w:bookmarkStart {NS} w:id="{i}" w:name="{name}"/>')
    ppr = p.find(qn("w:pPr"))
    if ppr is not None:
        ppr.addnext(start)
    else:
        p.insert(0, start)
    p.append(parse_xml(f'<w:bookmarkEnd {NS} w:id="{i}"/>'))
    return name


def plain(t):
    return re.sub(r"\*\*|__|`|\^\{|_\{|\}", "", t)


def h2(t, num):
    p = para(P_H2, raw_runs=f'<w:r>{R_H2}<w:t xml:space="preserve">{escape(t)}</w:t></w:r>')
    TOC_NEW.append((2, f"{num}.", t, bookmark(p)))
    return p


def h3(t, num):
    p = para(P_H3, raw_runs=f'<w:r>{R_H3}<w:t xml:space="preserve">{escape(t)}</w:t></w:r>')
    TOC_NEW.append((3, f"{num}.", t, bookmark(p)))
    return p


def caption(kind, num, text):
    ppr = P_TCAP if kind == "Table" else P_FCAP
    p = para(ppr, raw_runs=run(f"{kind} {num}: ", b=True, sz=20) + runs(text, sz=20))
    CAP_NEW[kind].append((f"{kind} {num}", f"{kind} {num}: {plain(text)}", bookmark(p)))
    return p


def note(t):
    return para(P_NOTE, t, sz=17)


def code_line(t):
    return para(P_CODE, raw_runs=run(t, code=True, sz=17))


_GRID = "7F7F7F"


def table(widths, header, rows, sz=16, aligns=None, code_cols=()):
    """Table in the format of the Phase 1 tables: grey grid, shaded bold header row repeated on new pages."""
    n = len(widths)
    aligns = aligns or (["left"] + ["center"] * (n - 1))
    borders = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="{_GRID}"/>'
                      for s in ["top", "left", "bottom", "right", "insideH", "insideV"])
    tblpr = (f'<w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/><w:jc w:val="center"/><w:tblBorders>{borders}</w:tblBorders>'
             '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="28" w:type="dxa"/><w:left w:w="70" w:type="dxa"/>'
             '<w:bottom w:w="28" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="04A0"/></w:tblPr>')
    grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"

    def cell(text, w, align, head, keep, code):
        shd = '<w:shd w:val="clear" w:color="auto" w:fill="E7ECF3"/>' if head else ""
        ps = ""
        for t in str(text).split("\n"):
            ppr = (f'<w:pPr>{"<w:keepNext/>" if keep else ""}<w:spacing w:before="0" w:after="0" w:line="240" '
                   f'w:lineRule="auto"/><w:jc w:val="{align}"/></w:pPr>')
            if not t:
                r = ""
            elif head:
                r = run(t, b=True, sz=sz)
            elif code:
                r = run(t, code=True, sz=sz - 2)
            else:
                r = runs(t, sz=sz)
            ps += f"<w:p>{ppr}{r}</w:p>"
        return f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shd}<w:vAlign w:val="center"/></w:tcPr>{ps}</w:tc>'

    xml = f"<w:tbl {NS}>{tblpr}{grid}"
    xml += ("<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>"
            + "".join(cell(h, w, "center", True, True, False) for h, w in zip(header, widths)) + "</w:tr>")
    for k, r in enumerate(rows):
        keep = k < len(rows) - 1
        xml += ("<w:tr><w:trPr><w:cantSplit/></w:trPr>"
                + "".join(cell(c, w, a, False, keep, j in code_cols) for j, (c, w, a) in enumerate(zip(r, widths, aligns)))
                + "</w:tr>")
    return parse_xml(xml + "</w:tbl>")


# ----------------------------------------------------------------- the document
doc = Document(SRC)


def par_el(prefix, style=None, nth=0):
    hits = [p._p for p in doc.paragraphs
            if p.text.strip().startswith(prefix) and (style is None or p.style.name == style)]
    if len(hits) <= nth:
        raise KeyError(f"paragraph not found: {prefix!r}")
    return hits[nth]


def next_table(p):
    e = p.getnext()
    while e is not None and e.tag != qn("w:tbl"):
        e = e.getnext()
    return e


def insert_after(anchor, items):
    cur = anchor
    for e in items:
        cur.addnext(e)
        cur = e
    return cur


def rebuild(p, markup):
    """Replace the runs of a paragraph, keep its paragraph properties."""
    ppr = p.find(qn("w:pPr"))
    for ch in list(p):
        if ch is not ppr:
            p.remove(ch)
    for r in list(parse_xml(f"<w:p {NS}>{runs(markup)}</w:p>")):
        p.append(r)


def replace_text(p, old, new):
    txt = "".join(t.text or "" for t in p.iter(qn("w:t")))
    if old not in txt:
        raise KeyError(f"text not found: {old[:60]!r}")
    rebuild(p, txt.replace(old, new))


def figure(path, width_cm, alt):
    p = doc.add_paragraph()
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    e = p._p
    for ppr in e.findall(qn("w:pPr")):
        e.remove(ppr)
    e.insert(0, parse_xml(f"<w:p {NS}>{P_FIG}</w:p>")[0])
    for d in e.iter(qn("wp:docPr")):
        d.set("descr", alt)
    e.getparent().remove(e)
    return e


def first_sz(e, default):
    for z in e.iter(qn("w:sz")):
        return int(z.get(qn("w:val")))
    return default


def set_cell(tc, markup, sz):
    sz = first_sz(tc, sz)                       # keep the font size the cell already has
    ps = tc.findall(qn("w:p"))
    for extra in ps[1:]:
        tc.remove(extra)
    p = ps[0]
    for ch in list(p):
        if ch.tag != qn("w:pPr"):
            p.remove(ch)
    for r in list(parse_xml(f"<w:p {NS}>{runs(markup, sz)}</w:p>")):
        p.append(r)


def equation(omml, number):
    return parse_xml(f'<w:p {NS}>{P_EQ}<w:r><w:tab/></w:r><m:oMath>{omml}</m:oMath>'
                     f'<w:r><w:tab/></w:r><w:r><w:t xml:space="preserve">({number})</w:t></w:r></w:p>')


def mr(t, plain=False):
    sty = '<m:rPr><m:sty m:val="p"/></m:rPr>' if plain else ""
    return f'<m:r>{sty}<m:t xml:space="preserve">{escape(t)}</m:t></m:r>'


def mtext(t):
    """Normal (non-math) text inside an equation, so that a hyphen is not read as a minus sign."""
    return f'<m:r><m:rPr><m:nor/></m:rPr><w:rPr><w:rFonts w:ascii="Cambria Math" w:hAnsi="Cambria Math"/></w:rPr><m:t xml:space="preserve">{escape(t)}</m:t></m:r>'


def msub(base, sub, plain=True):
    return f"<m:sSub><m:e>{mr(base, plain)}</m:e><m:sub>{mr(sub)}</m:sub></m:sSub>"


def mfrac(num, den):
    return f"<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>"


# ================================================================= front matter
sub = par_el("Phase 1 Report:")
sub.find(qn("w:r")).find(qn("w:t")).text = "Final Report: Data Preparation, Statistical Analysis and Predictive Modelling"
doc.core_properties.title = "The Impact of Football Matches on Local Traffic Patterns in Istanbul – Final Report"

abstract = par_el("Istanbul's three largest football stadiums")
replace_text(abstract, "This report documents Phase 1: the construction of an analysis-ready dataset and the first statistical analysis.",
             "This final report documents both phases of the project: the construction of an analysis-ready dataset with the "
             "first statistical analysis (Phase 1) and the predictive modelling (Phase 2).")
ab2 = deepcopy(abstract)
rebuild(ab2,
        f"In Phase 2, the statistical analysis was extended with multi-group tests, an opponent-group comparison and Holm's "
        f"correction for multiple testing, and day-ahead models were trained for the congestion class around the stadiums. "
        f"Only features known 24 hours in advance were used, the targets were recomputed on the training period, and the models "
        f"were selected with forward-chaining validation (train 2022-23, validate 2023-24) and evaluated once on the 2024-25 "
        f"season. Histogram-based gradient boosting reached a macro-F1 of {V['FOneHgbAll']} for the three-class congestion target, "
        f"ahead of logistic regression ({V['FOneLinAll']}), a random forest ({V['FOneRfAll']}) and two seasonal baselines "
        f"({V['FOneBZeroAll']} and {V['FOneBOneAll']}). Fixture features barely matter over all hours, but in the post-match hours "
        f"near the stadiums they reduce the speed error from {V['MaeNoEvPost']} to {V['MaeHgbPost']} km/h ({V['MaeGainPost']} %), and a "
        f"bootstrap over matches confirms the gain. The match effect survives the Holm correction and does not depend on the "
        f"opponent. Daily entries at the rail stations next to the stadiums (+{V['ExtRailMean']} % on match days) and the "
        f"announcements of the municipal traffic control centre confirm it independently and show that it continued after the "
        f"traffic data end in January 2025. A long-horizon variant of the model drives a local web panel that forecasts the "
        f"traffic around a stadium for a future fixture.")
abstract.addnext(ab2)

# symbols and abbreviations (alphabetical order of the Phase 1 list)
def sym(abbr, desc):
    return para(P_SYM, raw_runs=run(abbr, b=True) + run(f": {desc}"))


par_el("API:").addprevious(sym("ANOVA", "Analysis of variance"))
insert_after(par_el("API:"), [sym("B0, B1", "Seasonal baselines: same hour of the previous week; hour-of-week profile of the training period")])
insert_after(par_el("ERA5:"), [sym("F1, macro-F1", "Harmonic mean of precision and recall of a class; unweighted mean of the class F1 scores")])
insert_after(par_el("KO:"), [sym("MAE", "Mean absolute error")])
insert_after(par_el("NEAR:"), [sym("PR-AUC", "Area under the precision–recall curve")])
insert_after(par_el("R0, R1, R2:"), [sym("R²", "Coefficient of determination"), sym("RMSE", "Root mean squared error"),
                                       sym("RQ1–RQ3", "Research questions (Section 1.1)")])
insert_after(par_el("SD:"), [sym("T1, T2, T3", "Prediction targets: average speed, congestion class, abnormal slowdown")])
insert_after(par_el("UEFA:"), [sym("UYM", "Transport Management Centre of IBB (Ulaşım Yönetim Merkezi)")])
insert_after(par_el("Δ:"), [sym("η²", "Eta squared: share of the variance explained by a factor")])

# ================================================================= 1 INTRODUCTION
rebuild(par_el("The project is carried out in phases."),
        "The project was carried out in two phases, and this final report covers both. **Phase 1 – Data Preparation and "
        "Statistical Analysis** produced a finalised dataset that is ready to use: gathering, combining, cleaning, preprocessing "
        "and feature engineering, together with clear usage instructions, quality checks and the first statistical results. "
        "**Phase 2 – Modelling** built, tested and compared machine-learning models that predict congestion around the stadiums, "
        "reported their performance and explained what they mean; it also extended the statistical analysis and checked the "
        "findings with two further open data sources. The Phase 1 chapters are kept as submitted, apart from a few sentences "
        "that referred to Phase 2 in the future tense; the Phase 2 work is added in the same structure (Sections 3.1.7, 3.3.9–3.3.15 "
        "and 4.8–4.14, and in Chapters 5 and 6).")
insert_after(par_el("Two requirements of the brief"), [body(
    "The work answers three research questions. **RQ1:** Do matches cause statistically significant changes in speed and in "
    "the number of observed vehicles around the stadiums before, during and after the match? **RQ2:** Do the effects differ by "
    "stadium, kick-off time, derby status, opponent, competition, weekday or weather? **RQ3:** Can congestion around the "
    "stadiums be predicted one day ahead, and does fixture information improve that prediction? RQ1 and RQ2 are answered with "
    "the hypotheses H1–H4 of Section 3.3.6, and RQ3 with a fifth hypothesis, **H5:** adding fixture features does not reduce "
    "the day-ahead prediction error in match windows (Section 3.3.13).")])

lead_p1 = par_el("Phase 1 covers the following work:")
lead_p2 = deepcopy(lead_p1)
rebuild(lead_p2, "Phase 2 covers the following work:")
insert_after(par_el("a reproducible Python pipeline that rebuilds"), [
    lead_p2,
    bullet("an extended statistical analysis: tests for factors with more than two groups, an opponent-group comparison, "
           "Holm's correction for multiple testing, a sensitivity analysis without relaxed weather matching and a chi-square "
           "test of congestion class and match window;"),
    bullet("a day-ahead prediction task with leakage control: features known 24 hours before the target hour and targets "
           "recomputed on the training period;"),
    bullet("two seasonal baselines and three model families (logistic and ridge regression, random forest, histogram-based "
           "gradient boosting), tuned with forward-chaining validation and evaluated once on the 2024-25 season;"),
    bullet("an ablation and a match-level bootstrap that isolate the value of fixture information, feature-group importance, "
           "error analysis and calibration;"),
    bullet("external validation with two further open IBB data sets – rail-station entries and traffic-control announcements – "
           "that continue after January 2025;"),
    bullet("a long-horizon scenario model and a local web panel that forecasts the traffic around a stadium for a future fixture."),
])
rebuild(par_el("Out of scope for Phase 1"),
        "Out of scope are real-time prediction, road-segment level analysis (the IBB data are cell-level), hourly public-transport "
        "ridership (daily rail-station entries are used only to validate the findings), and matches at other Istanbul venues such "
        "as Başakşehir Fatih Terim Stadium or Recep Tayyip Erdoğan Stadium; the latter can be added through the configuration "
        "file without code changes.")

obj = par_el("Table 1.1 lists the Phase 1 objectives")
rebuild(obj, "Table 1.1 lists the Phase 1 objectives together with the measurable criteria used to judge them. The quality-check "
             "identifiers (QC01–QC14) refer to the automated checks reported in Table 4.7. Table 1.2 lists the objectives added "
             "in Phase 2; Chapter 5 discusses whether they were met.")
t11 = next_table(obj)
w11 = [int(g.get(qn("w:w"))) for g in t11.find(qn("w:tblGrid"))]
sz11 = first_sz(t11.findall(qn("w:tr"))[1], 17)
insert_after(t11, [
    caption("Table", "1.2", "Phase 2 objectives and measurable success criteria"),
    table(w11, ["ID", "Objective", "Measurable success criterion"], [
        ["**O7**", "Leakage-free prediction setting",
         "Only features known ≥ 24 h before the target hour; free-flow speeds and hour-of-week baselines recomputed on the "
         "training period; time-ordered split without random folds"],
        ["**O8**", "Model comparison",
         "At least three model families compared with two seasonal baselines; hyperparameters chosen on the validation season "
         "only; one evaluation on the 2024-25 test season with macro-F1 (primary), per-class F1, confusion matrix, MAE / RMSE / "
         "R², PR-AUC, Brier score and reliability curves"],
        ["**O9**", "Value of fixture information (H5)",
         "Ablation without the event features; 95 % match-level bootstrap interval of the gain in match windows excludes zero"],
        ["**O10**", "Robust statistics",
         "Holm-corrected p-values for every hypothesis family; multi-group tests with effect sizes (η²); sensitivity analysis "
         "without relaxed weather matching"],
        ["**O11**", "External validation",
         "Two further open sources analysed with the matched-control design; agreement with the traffic-based effect at match level"],
        ["**O12**", "Usable result",
         "Forecast for a future fixture through a local web panel; one-command rebuild of every number in this report"],
    ], sz=sz11, aligns=["center", "left", "left"]),
])

rebuild(par_el("Chapter 2 reviews related work."),
        "Chapter 2 reviews related work. Chapter 3 describes the data sources, tools and the proposed approach: acquisition, "
        "cleaning, the spatial and temporal design, control days, feature engineering, the statistical plan, quality assurance and "
        "the final dataset (Sections 3.1–3.3.8, Phase 1), and the extended analysis, the prediction setting, the models, the "
        "validation design, the external validation and the scenario model (Sections 3.1.7 and 3.3.9–3.3.15, Phase 2). Chapter 4 presents "
        "the results: data inventory, event dataset, traffic profiles, hypothesis tests, heterogeneity, robustness checks, quality "
        "checks and target distributions (Sections 4.1–4.7), followed by the extended statistical results, the external "
        "validation, model selection, test-season performance, feature importance and error analysis, the scenario model and a "
        "comparison with the literature (Sections 4.8–4.14). Chapter 5 discusses the results and their limitations, and Chapter 6 "
        "concludes. The appendices contain the data dictionary, the list of study cells, the repository structure and the "
        "declaration on the use of generative AI.")

# ================================================================= 2 RELATED WORK
t21 = next_table(par_el("Table 2.1:", style="Table Caption"))
last = t21.findall(qn("w:tr"))[-1]
tcs = last.findall(qn("w:tc"))
set_cell(tcs[1], "IBB speeds and vehicle counts + TFF fixtures + ERA5 weather + holidays; rail-station entries and UYM "
                 "announcements for validation", 16)
set_cell(tcs[4], "Match-level paired t-tests and Wilcoxon tests, group tests with Holm correction, correlation analysis; "
                 "day-ahead logistic / ridge regression, random forest and gradient boosting with an ablation of fixture features", 16)
replace_text(par_el("The proposed approach differs in three respects"),
             "competition and weather.",
             "competition and weather. In Phase 2, the study adds a leakage-controlled day-ahead prediction that isolates what "
             "fixture information contributes to a forecast, which none of the reviewed studies does for Istanbul, and it checks "
             "the crowd effect with two further open data sources.")

# ================================================================= 3 METHODOLOGY
rebuild(par_el("This project follows the"),
        "This project follows the __data/model-driven research__ structure of the report template. Section 3.1 describes the "
        "data, Section 3.2 the tools and Section 3.3 the proposed approach in enough detail to reproduce the study: Sections "
        "3.3.1–3.3.8 describe Phase 1 and Sections 3.3.9–3.3.15 the methods added in Phase 2. All parameter values mentioned below are set in a single configuration file of "
        "the accompanying code (Appendix C).")

insert_after(par_el("Official Turkish public holidays"), [
    h3("Additional Open Sources (Phase 2)", "3.1.7"),
    body("The IBB traffic series ends in January 2025, and no other open source provides cell-level speeds for Istanbul. To "
         "validate the findings with independent data, and to see whether they continue after that date, two further data sets "
         "of the IBB open-data portal were added in Phase 2. They are used only for the external validation (Sections 3.3.14 and "
         "4.9) and do not enter the main analysis or the models."),
    bullet(f"**Rail-station entries** [44]: daily numbers of passengers entering each rail station, {V['ExtRailFirst']} to "
           f"{V['ExtRailLast']}. The stations next to the stadiums are Seyrantepe (M2 metro, with a direct stadium exit) for Rams "
           f"Park, Söğütlüçeşme (Marmaray, about 400 m from the stadium) for Şükrü Saracoğlu Stadium and Kabataş (T1 tram and F1 "
           f"funicular) for Tüpraş Stadyumu. Station names are spelled differently between years, so they are matched with "
           f"regular expressions on the line and station name."),
    bullet(f"**Traffic announcements of the Transport Management Centre (UYM)** [45]: {V['ExtUymRows']} announcements from July "
           f"2020 to {V['ExtUymLast']} with start and end time, type (for example accident, breakdown, heavy traffic or road "
           f"closure), title and coordinates. An announcement is football-related if its title mentions a match, football or the "
           f"stadium (Turkish keywords “maç”, “müsabaka”, “futbol”, “stadyum”); distances to the stadiums are computed from the "
           f"coordinates."),
    bullet(f"**Fixtures of 2025-26 and 2026-27**, collected from tff.org and the Wikipedia season articles with the same scripts "
           f"as in Phase 1: {V['ExtFixAfter']} home matches after January 2025, used for the validation and as the list of "
           f"upcoming matches in the forecast panel."),
])

t35 = next_table(par_el("Table 3.5:", style="Table Caption"))
rows35 = t35.findall(qn("w:tr"))


def row_by_first(rows, text):
    for r in rows:
        if "".join(t.text or "" for t in r.findall(qn("w:tc"))[0].iter(qn("w:t"))).strip() == text:
            return r
    raise KeyError(text)


r_stat = row_by_first(rows35, "Statistics")
set_cell(r_stat.findall(qn("w:tc"))[2], "Descriptive statistics, Shapiro–Wilk, Levene, t-tests, Wilcoxon, Mann–Whitney U, "
                                        "correlation, t-based confidence intervals; one-way ANOVA, Kruskal–Wallis, chi-square "
                                        "and Holm correction (Phase 2)", 17)
r_ml = deepcopy(r_stat)
for tc, txt in zip(r_ml.findall(qn("w:tc")), ["Machine learning", "scikit-learn [36], joblib",
                                              "Logistic and ridge regression, random forest, histogram-based gradient boosting, "
                                              "metrics, permutation importance; storage of the trained models (Phase 2)"]):
    set_cell(tc, txt, 17)
r_stat.addnext(r_ml)
r_rep = row_by_first(rows35, "Reproducibility")
set_cell(r_rep.findall(qn("w:tc"))[1], "Git, requirements.txt, config.py, run_all.py, fill_report.py; run_phase2.py, "
                                       "run_extra.py, run_scenario.py, tools/build_final_report.py", 17)
r_panel = deepcopy(r_ml)
for tc, txt in zip(r_panel.findall(qn("w:tc")), ["Forecast panel", "Python standard library (http.server), HTML, JavaScript, SVG; "
                                                 "OpenStreetMap roads [46]",
                                                 "Local web panel for future fixtures (Section 3.3.15, Phase 2)"]):
    set_cell(tc, txt, 17)
row_by_first(rows35, "Visualisation").addnext(r_panel)

replace_text(par_el("T2 is proposed as the primary target"),
             "In Phase 2, the free-flow speeds and hour-of-week baselines will be recomputed on the training period only to avoid leakage.",
             "In Phase 2, the free-flow speeds and hour-of-week baselines were recomputed on the training period only to avoid "
             "leakage (Section 3.3.11).")
replace_text(par_el("Following the course procedure"),
             "All tests use α = 0.05 and unadjusted p-values, so results are interpreted together rather than one test at a time.",
             "All tests use α = 0.05. Phase 1 reported unadjusted p-values and interpreted the results together rather than one "
             "test at a time; Phase 2 adds Holm's correction within each hypothesis family (Section 3.3.10).")

macro_f1 = (mtext("macro-F1") + mr("=") + mfrac(mr("1"), mr("3"))
            + '<m:nary><m:naryPr><m:chr m:val="∑"/><m:limLoc m:val="undOvr"/><m:supHide m:val="1"/></m:naryPr>'
            + f"<m:sub>{mr('k')}</m:sub><m:sup/><m:e>{msub('F1', 'k')}</m:e></m:nary>"
            + mr(",     ") + msub("F1", "k") + mr("=")
            + mfrac(mr("2") + msub("P", "k", False) + msub("R", "k", False), msub("P", "k", False) + mr("+") + msub("R", "k", False)))

sec34 = [
    h3("Phase 2 Overview", "3.3.9"),
    body("Phase 2 builds on the dataset of Sections 3.3.1–3.3.8. It extends the statistical analysis (3.3.10), defines a "
         "leakage-free prediction task (3.3.11), compares baselines and three model families (3.3.12) with a time-ordered "
         "validation design (3.3.13), validates the crowd effect with two further sources (3.3.14) and adds a long-horizon "
         "scenario model for future fixtures (3.3.15). Figure 3.4 shows how these parts fit into the workflow. As in Phase 1, every number in Chapter 4 is "
         "produced by the code: `run_phase2.py`, `run_extra.py` and `run_scenario.py` rebuild the Phase 2 results."),
    figure(FIGS / "fig_workflow.png", 15.24, "Workflow of the project"),
    caption("Figure", "3.4", "Workflow of the project: statistical (Phase 1) and predictive (Phase 2) results"),

    h3("Extended Statistical Analysis", "3.3.10"),
    body("Three additions make the statistical analysis of Phase 1 more complete. First, factors with three or more groups – "
         "stadium, competition, kick-off slot and opponent group – are tested with one-way ANOVA and the Kruskal–Wallis test [31] "
         "instead of only in pairs, with η² (the share of the variance of the post-match effect explained by the factor) as the "
         "effect size. The opponent, which the brief names explicitly, is grouped into big matches (derby or Trabzonspor), other "
         "Istanbul clubs (few travelling fans), other domestic clubs and European clubs, so that every group has enough matches."),
    body("Second, because Phase 1 reported more than 50 tests, Holm's step-down procedure [30] is applied within each hypothesis "
         "family (H1, H2, and H3–H4 together). It controls the probability of at least one false rejection in a family and is "
         "uniformly more powerful than the Bonferroni correction."),
    body(f"Third, two robustness checks are added: a sensitivity analysis that repeats the post-match test of H1 without the "
         f"{V['PctRelaxed']} % of matches whose weather rule had to be relaxed (Section 3.3.4), and a chi-square test of "
         f"independence between the congestion class (T2) and the match window in the evening hours of the NEAR cells, with "
         f"Cramér's V [32] as the effect size."),

    h3("Prediction Task and Leakage Control", "3.3.11"),
    body(f"The unit of prediction is one cell-hour in the {V['Cells']} analysed cells of R0–R2 in the main seasons, and the "
         f"horizon is one day: a traffic operator wants to know today what will happen at each hour tomorrow. A feature is "
         f"therefore admissible only if it is known at least 24 hours before the target hour (Table 3.11). Same-hour traffic "
         f"values, and features derived from them such as the per-cell z-scores of Section 3.3.5, are excluded because they "
         f"contain the answer; this kind of target leakage is a common reason for over-optimistic models [33]. The quantities that "
         f"define the targets – the free-flow speed of each cell and the hour-of-week mean and standard deviation – are recomputed "
         f"on the training period only. Historical ERA5 weather stands in for a weather forecast; this is slightly optimistic, but "
         f"weather turns out to be the least important feature group (Section 4.12)."),
    caption("Table", "3.11", f"Feature groups of the day-ahead models ({V['NFeatures']} features)"),
    table([1300, 4900, 2440], ["Group", "Features", "Known a day ahead because"], [
        ["History", "Speed 24, 48 and 168 h earlier; mean of the same hour in the previous four weeks; log vehicles 24 and 168 h "
                    "earlier; the same lags as ratios to the free-flow speed; hour-of-week mean speed and ratio of the training period",
         "All values lie 24 h or more before the target hour"],
        ["Event", "Match day at this stadium; match at any of the three stadiums; hour relative to kick-off; competition; "
                  "kick-off slot; derby; big match; opponent group; capacity", "Fixtures are published weeks in advance"],
        ["Calendar", "Hour (also as sine / cosine), weekday, month, weekend, holiday, holiday eve", "Deterministic"],
        ["Weather", "Temperature, precipitation, rain, snowfall, humidity, cloud cover, wind speed and gusts, rain flags",
         "Stands in for a day-ahead forecast"],
        ["Spatial", "Stadium, ring index, free-flow speed of the cell", "Fixed per cell; free-flow speed from the training period"],
    ], sz=17, aligns=["left", "left", "left"]),
    para(P_BODY_GAP, f"The three targets of Section 3.3.5 are kept. **T2**, the primary target, is the congestion class of the speed ratio "
         f"ρ = v / v_{{ff}} (congested ρ < 0.50, moderate 0.50 ≤ ρ < 0.75, free ρ ≥ 0.75); **T1** is the average speed "
         f"(regression); and **T3** is a rare abnormal slowdown with a z-score below −2 relative to the hour-of-week mean of the "
         f"cell. With the training-period definitions the classes of T2 are imbalanced: {V['TrainFree']} % free, "
         f"{V['TrainModerate']} % moderate and {V['TrainCongested']} % congested hours in training ({V['TestFree']} %, "
         f"{V['TestModerate']} % and {V['TestCongested']} % in the test season), and T3 occurs in {V['TThreePrevTrain']} % of the "
         f"training hours ({V['TThreePrevTest']} % in the test season). The modelling set contains {V['TrainRows']} labelled "
         f"cell-hours for training (2022-24) and {V['TestRows']} for testing (2024-25), of which {V['TestMatchRows']} fall in "
         f"match windows."),

    h3("Models and Hyperparameters", "3.3.12"),
    body("Two seasonal baselines set the bar that a useful model has to clear: **B0** repeats the same hour of the previous week, "
         "and **B1** predicts the cell's hour-of-week profile of the training period. Three model families of increasing "
         "flexibility were compared (Table 3.12), all implemented with scikit-learn [36]: logistic regression for the "
         "classification targets and ridge regression for speed, a random forest [37], and histogram-based gradient boosting [38], "
         "the scikit-learn implementation of the approach popularised by LightGBM [39]. The linear model shows how far additive "
         "effects go; the two tree ensembles can represent interactions such as “match day × two hours after kick-off × this "
         "stadium” without hand-made interaction terms. To answer RQ3, the gradient-boosting model was also trained __without__ "
         "the event group; the difference between the two versions isolates the value of fixture information."),
    caption("Table", "3.12", "Models and hyperparameters"),
    table([2100, 6540], ["Model", "Settings"], [
        ["Logistic / ridge regression", "L2 penalty, C = 1 (logistic) or α = 1 (ridge); balanced class weights; one-hot encoded "
                                        "categories, median imputation with missing-value indicators, z-score scaling"],
        ["Random forest", "150 trees, maximum depth 18, at least 20 samples per leaf, √p features per split, balanced class "
                          "weights; trained on 300,000 sampled rows"],
        ["Gradient boosting", f"Learning rate 0.1, 300 iterations, native handling of categories and missing values; leaves per "
                              f"tree ∈ {{31, 63}} and class weights ∈ {{none, balanced}} chosen on the validation season (selected: "
                              f"{V['BestLeaves']} leaves, class weights: {V['BestCW']})"],
    ], sz=17, aligns=["left", "left"]),

    h3("Validation Design and Evaluation Metrics", "3.3.13"),
    body(f"Random K-fold cross-validation was not used: neighbouring hours are nearly identical, so random folds would place "
         f"almost the same observation in the training and the test set and overstate performance [34]. A forward-chaining "
         f"hold-out design was used instead [35] (Figure 3.5): the models were selected on train 2022-23 → validate 2023-24 "
         f"({V['SelTrainRows']} and {V['SelValRows']} cell-hours), then refitted on 2022-24 and evaluated once on the 2024-25 "
         f"season, which was not used for any decision."),
    figure(FIGS / "fig_split_timeline.png", 15.24, "Forward-chaining validation design"),
    caption("Figure", "3.5", "Forward-chaining validation design"),
    body("The primary metric is the macro-F1 of T2 over all hours of the validation season – the unweighted mean of the F1 scores "
         "of the three classes – which weights the rare congested class as much as the frequent free class:"),
    equation(macro_f1, "3.3"),
    body("where P_{k} and R_{k} are the precision and recall of class k. Secondary metrics are accuracy, per-class F1 and the "
         "confusion matrix for T2; the mean absolute error (MAE), root mean squared error (RMSE) and R² for T1; the area under "
         "the precision–recall curve (PR-AUC), which is more informative than the ROC-AUC for rare events [40], for T3; and, for "
         "the predicted probabilities, the Brier score [41], the log loss and reliability curves [42]. Every metric is reported "
         "for all hours, for the match windows (−3 to +4 h at the stadium of the match) and for the post-match hours in the NEAR "
         "ring, because a model can be good on average and still miss the few hours that matter here."),
    body("H5 is tested with a bootstrap [43] that resamples whole test matches (2,000 resamples), so that the correlated hours of "
         "a match stay together: if the 95 % interval of the gain in the match windows excludes zero, H5 is rejected. The "
         "importance of each feature group is measured by shuffling all of its columns together on the test season and recording "
         "the drop in macro-F1 (group permutation importance), which avoids splitting the importance among correlated lags."),

    h3("External Validation with Additional Sources", "3.3.14"),
    body("**Rail stations.** The matched-control idea of Section 3.3.4 is applied to the daily station data: for each home match "
         "with a station record, the control days are the same weekday one to four weeks before or after, with no home match of "
         "the three clubs and no holiday; the four nearest valid days are kept and at least two are required. The effect is the "
         "percentage difference between the match-day entries and the mean of the control days, one value per match, tested with "
         "the Wilcoxon signed-rank test and summarised by period (traffic study period, after January 2025, closed-doors season). "
         "For the matches that are also in the traffic analysis, the Spearman correlation between the rail effect and the "
         "post-match speed effect checks whether both sources describe the same crowd."),
    body("**Traffic announcements.** A football-related announcement is matched to a home match if it starts between 12 hours "
         "before and 6 hours after kick-off and names the stadium or lies within 2 km of it. For each match it is recorded whether "
         "the control centre announced closures or congestion, of which type and how long before kick-off. As a negative check, "
         "ordinary incident announcements (accidents, breakdowns, heavy traffic and closures not linked to the match) within 2 km "
         "of the stadium are counted from 3 hours before to 4 hours after kick-off on the match day and at the same clock times on "
         "the control days; their rate ratio is reported with a 95 % bootstrap interval over matches, because the counts are "
         "mostly zero."),

    h3("Long-Horizon Scenario Model and Forecast Panel", "3.3.15"),
    body("The day-ahead model cannot forecast a match weeks or months ahead: its strongest inputs are the traffic of the same "
         "cell 24, 48 and 168 hours earlier, which do not exist yet for a future date, and the IBB traffic data end in January "
         "2025. For the forecast panel a second, __scenario__ model was therefore trained that uses only what is known as soon as "
         "a fixture is published: the calendar and spatial groups of Table 3.11, the cell's hour-of-week profile of the training "
         "period and the event group. Weather is left out, because there is no forecast weeks ahead and weather did not change "
         "the match effect (Sections 4.5 and 4.12). The scenario model is a histogram-based gradient-boosting classifier for T2 "
         "and a regressor for T1 with the settings of Table 3.12; it is validated with the same forward-chaining design and then "
         "refitted on all three seasons with spectators for the panel."),
    body("Because the panel forecasts dates up to two years after the last traffic data, a horizon back-test measures how the "
         "error grows with the gap: the model is trained on 2022-23 (or on 2022-23 and 2023-24) only and used to forecast every "
         "later match with spectators, and the errors of the post-match speed are grouped by the number of months between the end "
         "of the training data and the match. The 10th and 90th percentiles of these errors give the 80 % ranges shown in the panel."),
    body("The **forecast panel** (`python panel.py`, Figure 4.12) is a local web application built only on the Python standard "
         "library and the project's modules; it sends nothing to the internet. A user enters the date, kick-off time, stadium, "
         "opponent and competition of a match – or clicks one of the upcoming fixtures – and the panel shows the predicted hourly "
         "speed and congestion class around the stadium from six hours before to six hours after kick-off, the same hours on a "
         "normal day without a match, when the post-match slowdown starts and ends, a map of the cells with OpenStreetMap roads "
         "[46], the observed effect of earlier comparable matches, recent road works announced by UYM and the out-of-sample "
         "results of the 2024-25 test matches. The panel can be switched between English and Turkish and exports the forecast as "
         "CSV or as a printable report."),
]
insert_after(par_el("Package contents."), sec34)

# ================================================================= 4 EXPERIMENTAL RESULTS
rebuild(par_el("This chapter reports the Phase 1 results"),
        "This chapter reports the results produced by the pipeline. Sections 4.1–4.7 contain the Phase 1 results: the data "
        "inventory and cleaning outcome (4.1), the event dataset (4.2), match-day traffic profiles (4.3), the hypothesis tests "
        "(4.4–4.6), and the quality checks and target distributions (4.7). Sections 4.8–4.14 contain the Phase 2 results: the "
        "extended statistical analysis (4.8), the external validation (4.9), model selection (4.10), the test-season performance "
        "(4.11), feature importance, error analysis and calibration (4.12), the scenario model and forecast panel (4.13) and a "
        "comparison with the literature (4.14). Complete tables are written to `outputs/tables/`.")

sel = tex_rows("selection")
models = tex_rows("models")
err = tex_rows("error")
h2rows = tex_rows("h2")

fin = SV["validation"]["final"]


def sm(key, scope, metric):
    return fin[key][scope][metric]


scen_rows = []
for key, lab in [("profile_baseline", "B1: hour-of-week profile"), ("scenario_no_event", "Scenario model, no fixture features"),
                 ("scenario", "Scenario model, all features")]:
    scen_rows.append([lab] + [f(sm(f"{key}|t2", s, "macro_f1"), 3) for s in ["all", "match", "post_near"]]
                     + [f(sm(f"{key}|t2", "post_near", "f1_congested"), 3)]
                     + [f(sm(f"{key}|t1", s, "mae"), 2) for s in ["all", "match", "post_near"]])
bins = SV["horizon"]["bins"]
hz_rows = []
for b in bins:
    hi = f"{b['max_tested']:.1f}" if b is bins[-1] else str(b["hi"])
    hz_rows.append([f"{b['lo']}–{hi}", str(b["n_matches"]), f(b["post_mae_abs"]), f(b["post_mae_eff"]),
                    f"{f(b['post_abs_q10'])} … {f(b['post_abs_q90'], sign=True)}"])
S_all, S_match, S_post = sm("scenario|t2", "all", "macro_f1"), sm("scenario|t2", "match", "macro_f1"), sm("scenario|t1", "post_near", "mae")
NE_match, NE_post = sm("scenario_no_event|t2", "match", "macro_f1"), sm("scenario_no_event|t1", "post_near", "mae")
PB_post = sm("profile_baseline|t1", "post_near", "mae")
te_txt = ""
if TE:
    te_txt = (f" Applied to the {TE['n']} test matches of 2024-25 with a model trained only on 2022-24, the predicted change of the "
              f"post-match speed relative to a normal day correlates with the observed change (r = {TE['r_delta']:.2f}; mean "
              f"absolute error {TE['mae_delta']:.2f} km/h, {TE['mae_post']:.2f} km/h for the post-match speed itself), and the "
              f"direction – a slowdown or not – is right for {100 * TE['share_slowdown_both']:.0f} % of the matches. The panel shows "
              f"these matches in its “How did it do?” tab.")

sec4 = [
    # ---------------------------------------------------------- 4.8
    h2("Extended Statistical Results", "4.8"),
    body(f"**Multiple testing (H1).** All {V['HOneSpeedSigHolm']} stadium-by-window speed effects of Table 4.3 remain significant "
         f"after Holm's correction, and {V['HOneSigHolm']} of the {V['HOneTests']} p-values of that table (paired t-test and "
         f"Wilcoxon test for speed, Wilcoxon test for vehicles) stay below 0.05. The Shapiro–Wilk test rejected normality for "
         f"{V['ShapiroShare']} % of the speed distributions, which confirms the choice of the rank-based tests as the main tests; "
         f"the post-match distribution is skewed to the left (skewness {V['PostSkew']}, median {V['PostMedian']} km/h)."),
    body(f"**Heterogeneity (H2).** Table 4.9 repeats the group comparisons with the multi-group tests and Holm-corrected p-values. "
         f"The stadium remains by far the most important factor: it explains η² = {V['StEta']} of the variance of the post-match "
         f"effect. Big matches show a somewhat larger slowdown ({V['BigMean']} vs {V['BigOther']} km/h, n = {V['BigN']}; t-test "
         f"p = {V['BigP']}, Mann–Whitney p = {V['BigPU']}), but the difference does not survive the correction (p = {V['BigPHolm']}). "
         f"Istanbul opponents, which bring few travelling fans, do not differ from other domestic opponents ({V['IstMean']} vs "
         f"{V['IstOther']} km/h, p = {V['IstP']}), and the opponent group as a whole explains almost nothing (ANOVA "
         f"p = {V['OppAnovaP']}, Kruskal–Wallis p = {V['OppKwP']}, η² = {V['OppEta']}; Figure 4.4). Domestic-cup matches are "
         f"followed by smaller slowdowns than league matches, but the competition factor as a whole is not significant after the "
         f"correction (Kruskal–Wallis, Holm p = {V['CompKwPHolm']}). Overall, {V['HTwoSigRaw']} of {V['HTwoTests']} rank-based "
         f"tests are significant before and {V['HTwoSigHolm']} after Holm's correction, and all tests that survive the "
         f"correction concern the stadium or the league–cup contrast."),
    caption("Table", "4.9", "Group comparisons of the post-match speed effect with Holm correction (H2)"),
    table([2700, 2340, 900, 900, 900, 900],
          ["Comparison", "Group means, km/h (n)\nor effect size", "Raw p\nparam.", "Raw p\nrank", "Holm p\nparam.", "Holm p\nrank"],
          h2rows),
    note("param.: t-test (two groups) or one-way ANOVA (three or more groups); rank: Mann–Whitney U or Kruskal–Wallis test. "
         "Holm's correction within the H2 family. Opponent groups: big match (derby or Trabzonspor), other Istanbul club, other "
         "domestic club, European club."),
    figure(FIGS / "fig_opponent_groups.png", 13.5, "Post-match speed effect by opponent group"),
    caption("Figure", "4.4", "Post-match speed effect in the NEAR ring by opponent group (diamond: mean)"),
    body(f"**Sensitivity and association.** Excluding the matches whose weather rule was relaxed leaves {V['SensMean']} km/h "
         f"{V['SensCI']} (n = {V['SensN']}), practically the main estimate of {V['PostDS']} km/h, so the relaxed matching does not "
         f"drive the result. The checks of H3 and H4 in Table 4.6 keep their conclusions after Holm's correction: placebo dates "
         f"and closed-doors matches remain non-significant, and the difference-in-differences and spatial-decay effects remain "
         f"significant (p < 0.001). In the evening hours of the NEAR cells the congested class is more frequent in match windows "
         f"than outside them ({V['CongWin']} % vs {V['CongOther']} %; χ² = {V['ChiSq']}, p < 0.001, n = {V['ChiN']} cell-hours), "
         f"but Cramér's V = {V['CramerV']} shows that the association is small compared with the overall variability of traffic – "
         f"a first hint that match information matters mainly inside the match windows, which Section 4.11 confirms."),

    # ---------------------------------------------------------- 4.9
    h2("External Validation with Additional Sources", "4.9"),
    body(f"**Rail stations.** Station entries on match days exceed those of the control days by {V['ExtRailMean']} % on average "
         f"(median {V['ExtRailMedian']} %, 95 % CI {V['ExtRailCI']}, n = {V['ExtRailN']} matches with spectators, Wilcoxon "
         f"p < 0.001): {V['ExtRailRams']} % at Seyrantepe, which serves little other demand, {V['ExtRailSar']} % at Söğütlüçeşme "
         f"and {V['ExtRailTup']} % at Kabataş (Figure 4.5). The increase is the same in the traffic study period "
         f"({V['ExtRailStudy']} %, n = {V['ExtRailStudyN']}) and after the traffic data end (February to December 2025: "
         f"{V['ExtRailAfter']} % {V['ExtRailAfterCI']}, n = {V['ExtRailAfterN']}), whereas closed-doors matches show no increase "
         f"(median {V['ExtRailClosedMed']} %, p = {V['ExtRailClosedP']}, n = {V['ExtRailClosedN']}; the weekend curfews of early "
         f"2021 lower the mean). The two sources agree at match level: the larger the increase in station entries, the larger the "
         f"post-match slowdown of the same match measured with the traffic data (Spearman ρ = {V['ExtLinkRho']}, "
         f"n = {V['ExtLinkN']}, p < 0.001)."),
    figure(FIGS / "fig_extra_rail.png", 15.24, "Rail-station entries on match days relative to control days"),
    caption("Figure", "4.5", "Entries at the rail stations next to the stadiums on match days relative to matched control days "
                             "(mean and 95 % CI), by period"),
    body(f"**Traffic announcements.** UYM announced road closures or congestion caused by the match for {V['ExtUymWith']} of the "
         f"{V['ExtUymMatches']} matches with spectators ({V['ExtUymShare']} %), including {V['ExtUymAfterWith']} matches after "
         f"January 2025, and for none of the {V['ExtUymClosedMatches']} closed-doors matches. Of these announcements, "
         f"{V['ExtUymClosure']} % are road closures and {V['ExtUymBefore']} % start before kick-off (median {V['ExtUymMedianH']} h "
         f"before; Figure 4.6). This supports reading the pre-match slowdown with fewer vehicles at Şükrü Saracoğlu and Tüpraş "
         f"(Table 4.3) as an effect of planned closures. Ordinary incident announcements within 2 km of the stadium do not rise "
         f"clearly in the match window (rate ratio {V['ExtIncRR']}, 95 % bootstrap CI {V['ExtIncCI']})."),
    figure(ROOT / "outputs" / "figures" / "extra" / "fig_extra_uym.png", 15.24, "Timing of football-related UYM announcements"),
    caption("Figure", "4.6", "Start of the football-related UYM announcements relative to kick-off, by type (shaded: during window)"),
    body("Together, the two sources confirm three central findings of Phase 1 with data that do not come from the traffic files: "
         "the effect is linked to spectators (station entries rise on match days, closed-doors matches show nothing), part of "
         "the pre-match slowdown is caused by planned closures, and the effect continued in 2025 and 2026, after the traffic "
         "series ends."),

    # ---------------------------------------------------------- 4.10
    h2("Model Selection", "4.10"),
    body(f"Table 4.10 shows the validation season. Gradient boosting reaches the highest macro-F1 over all hours ({sel[0][1]}), "
         f"ahead of the random forest ({sel[5][1]}), logistic regression ({sel[4][1]}) and the profile baseline ({sel[6][1]}). The "
         f"four gradient-boosting settings differ by less than 0.01; the setting with {V['BestLeaves']} leaves and no class weights "
         f"was selected because it is best on the primary metric. Balanced class weights would raise the F1 of the congested class "
         f"(up to {sel[3][3]} instead of {sel[0][3]}) at a small cost in overall macro-F1 – a trade-off discussed in Chapter 5."),
    caption("Table", "4.10", "Model selection on the validation season 2023-24 (T2)"),
    table([4440, 1400, 1400, 1400], ["Model", "macro-F1\nall hours", "macro-F1\nmatch windows", "F1 congested\nall hours"], sel),
    note("Models trained on 2022-23. The selected setting is the first row."),

    # ---------------------------------------------------------- 4.11
    h2("Test-Season Performance (RQ3, H5)", "4.11"),
    body(f"Table 4.11 and Figure 4.7 report the single evaluation on the 2024-25 season. Gradient boosting with all features is "
         f"the best model on almost every metric: a macro-F1 of {V['FOneHgbAll']} over all hours (baselines {V['FOneBZeroAll']} "
         f"and {V['FOneBOneAll']}, logistic regression {V['FOneLinAll']}, random forest {V['FOneRfAll']}) and an MAE of "
         f"{V['MaeHgbAll']} km/h with R² = {V['RTwoHgbAll']} for speed. The ranking – boosting ahead of the random forest ahead of "
         f"the linear model – shows that the relationships are strongly non-linear: a match effect is an interaction of “match "
         f"day”, “two hours after kick-off” and “this stadium”, which trees represent naturally and a linear model does not. The "
         f"only column in which another model wins is the F1 of the congested class in the post-match hours, where the logistic "
         f"regression with balanced class weights ({V['FCongLinPost']}) is slightly ahead ({V['FCongHgbPost']}); its probabilities, "
         f"however, are poorly calibrated (Section 4.12)."),
    caption("Table", "4.11", "Test-season results (2024-25); best value per column in bold"),
    table([2000] + [830] * 8,
          ["Model", "T2\nmacro-F1\nall hours", "T2\nmacro-F1\nmatch win.", "T2\nF1 cong.\npost NEAR", "T1\nMAE\nall hours",
           "T1\nMAE\nmatch win.", "T1\nMAE\npost NEAR", "T3\nPR-AUC\nall hours", "T3\nPR-AUC\nmatch win."], models, sz=15),
    note("T2: congestion class; T1: average speed, MAE in km/h; T3: abnormal slowdown. Match win.: match windows, −3 to +4 h "
         "relative to kick-off at the stadium of the match. Post NEAR: +2 to +4 h in R0 and R1. T3 decision thresholds were chosen "
         "on the validation season; –: not computed."),
    figure(FIGS / "fig_model_comparison.png", 15.24, "Macro-F1 of the models on the test season"),
    caption("Figure", "4.7", "Macro-F1 of the congestion class on the test season (all hours and match windows)"),
    body(f"The value of fixture information depends entirely on __when__ it is measured. Over all hours, removing the event "
         f"features changes macro-F1 only from {V['FOneHgbAll']} to {V['FOneNoEvAll']}, because matches affect a few per cent of "
         f"the hours. In the match windows, however, macro-F1 falls from {V['FOneHgbMatch']} to {V['FOneNoEvMatch']}, and in the "
         f"post-match hours near the stadiums the speed error grows from {V['MaeHgbPost']} to {V['MaeNoEvPost']} km/h and the F1 "
         f"of the congested class collapses from {V['FCongHgbPost']} to {V['FCongNoEvPost']}. Figure 4.8 makes the mechanism "
         f"visible: the model without fixture information predicts an ordinary evening ({V['PeakNoEv']} km/h two hours after "
         f"kick-off), while the full model follows the observed dip ({V['PeakHgb']} vs {V['PeakObs']} km/h). In the post-match "
         f"hours the congested class is observed in {V['PostCongObs']} % of the NEAR cell-hours and predicted in "
         f"{V['PostCongHgb']} % by the full model but only {V['PostCongNoEv']} % without fixture features."),
    figure(FIGS / "fig_event_study_predicted.png", 15.24, "Observed and predicted speed around the test matches"),
    caption("Figure", "4.8", "Observed and day-ahead predicted speed in the NEAR ring around the 2024-25 test matches, with and "
                             "without fixture features (shaded: during window)"),
    body(f"The bootstrap over the {V['BootMatches']} test matches with observed match windows confirms the gain: the fixture "
         f"features reduce the MAE in match windows by {V['BootMae']} km/h {V['BootMaeCI']} and raise macro-F1 by {V['BootFOne']} "
         f"{V['BootFOneCI']}; all bootstrap samples favour the full model, so **H5 is rejected**. For the rare abnormal slowdown "
         f"(T3), the full model raises PR-AUC in the match windows from {V['PrNoEvMatch']} to {V['PrHgbMatch']}."),

    # ---------------------------------------------------------- 4.12
    h2("Feature Importance, Error Analysis and Calibration", "4.12"),
    body(f"Figure 4.9 shows the drop in macro-F1 when a feature group is shuffled. Traffic history dominates everywhere "
         f"({V['ImpHistoryAll']} over all hours, {V['ImpHistoryMatch']} in match windows). The event group is almost irrelevant "
         f"over all hours ({V['ImpEventAll']}) but becomes the second most important group in the match windows "
         f"({V['ImpEventMatch']}). Weather matters least ({V['ImpWeatherAll']}), in line with the absence of weather differences "
         f"in H2; it also means that replacing reanalysis by forecast weather would change little."),
    figure(FIGS / "fig_group_importance.png", 14.0, "Group permutation importance"),
    caption("Figure", "4.9", "Group permutation importance of the gradient-boosting model (T2, test season)"),
    body("Table 4.12 breaks the speed error down by stadium and window. Fixture features never hurt: outside match windows both "
         "models have the same error, while in the post-match window the error at Rams Park falls from about 8 to under 5 km/h. "
         "The largest remaining errors occur at Rams Park, the stadium with the largest and most variable effect, and the full "
         "model still slightly underestimates the post-match slowdown there."),
    caption("Table", "4.12", "Speed MAE (km/h) by stadium and window, test season: with / without fixture features"),
    table([2040, 1650, 1650, 1650, 1650], ["Stadium", "pre", "during", "post", "no match"], err),
    note("Gradient-boosting model with all features / without the event group. Windows relative to kick-off at the stadium of "
         "the match: pre −3…−1 h, during 0…+1 h, post +2…+4 h; no match: all other hours."),
    body(f"In the match windows the confusion matrix shows that {V['CongRecall']} % of the congested hours are recognised and "
         f"{V['CongAsModerate']} % are predicted as moderate; free and moderate hours are recognised in {V['FreeRecall']} % and "
         f"{V['ModRecall']} % of the cases (Figure 4.10). Errors between neighbouring classes are therefore far more common than "
         f"confusions of free and congested traffic."),
    figure(FIGS / "fig_confusion_match.png", 8.5, "Confusion matrix in the match windows"),
    caption("Figure", "4.10", "Confusion matrix of the gradient-boosting model in the match windows of the test season "
                              "(row-normalised, %)"),
    body(f"The predicted probabilities of gradient boosting are well calibrated (Figure 4.11). For T2, the multiclass Brier score "
         f"is {V['BrierTTwo']} against {V['BrierTTwoRef']} for a constant class-frequency forecast, and the log loss is "
         f"{V['LogLossTTwo']}. For T3, the Brier score is {V['BrierHgb']} against {V['BrierRef']} for the constant prevalence "
         f"forecast; the mean predicted probability ({V['TThreeMeanPred']} %) is slightly below the observed prevalence "
         f"({V['TThreePrevTest']} %). The logistic regression with balanced class weights, in contrast, has a Brier score of "
         f"{V['BrierLin']}: balancing improves the recall of rare classes but inflates the probabilities."),
    figure(FIGS / "fig_calibration.png", 9.5, "Reliability curves"),
    caption("Figure", "4.11", "Reliability curves on the test season (deciles of the predicted probability)"),

    # ---------------------------------------------------------- 4.13
    h2("Scenario Model and Forecast Panel", "4.13"),
    body(f"Table 4.13 compares the scenario model with the profile baseline on the same 2024-25 test season. Without any traffic "
         f"history it reaches a macro-F1 of {f(S_all, 3)} over all hours and {f(S_match, 3)} in the match windows; in the "
         f"post-match hours near the stadiums its speed error is {f(S_post)} km/h against {f(PB_post)} km/h for the profile "
         f"baseline. Without fixture features the same model falls to {f(NE_match, 3)} in the match windows and "
         f"{f(NE_post)} km/h after the match, so for a future date the fixture is what carries the match information. The "
         f"day-ahead model of Table 4.11 remains better over all hours ({V['FOneHgbAll']}) because it knows yesterday's traffic, "
         f"but in the match windows the scenario model is on par with it ({f(S_match, 3)} vs {V['FOneHgbMatch']})."),
    caption("Table", "4.13", "Scenario model on the test season 2024-25 (trained on 2022-24)"),
    table([2440, 880, 880, 880, 900, 880, 880, 900],
          ["Model", "macro-F1\nall hours", "macro-F1\nmatch windows", "macro-F1\npost, NEAR", "F1 cong.\npost, NEAR",
           "MAE\nall hours", "MAE\nmatch windows", "MAE\npost, NEAR"], scen_rows),
    note("T2 macro-F1 and F1 of the congested class; T1 MAE in km/h. No traffic-history and no weather features."),
    body(f"Table 4.14 shows the horizon back-test. The post-match speed error grows only slowly with the distance between the "
         f"training data and the match: from {f(bins[0]['post_mae_abs'])} km/h for matches up to six months after the training "
         f"data to {f(bins[-1]['post_mae_abs'])} km/h for 12 to {bins[-1]['max_tested']:.0f} months, the longest gap that could be "
         f"tested. Forecasts for 2026 lie about 22 months after the last traffic data, slightly beyond the tested range; the panel "
         f"shows them with the 80 % range of the longest tested gap and a warning.{te_txt}"),
    caption("Table", "4.14", "Horizon back-test of the scenario model: post-match error by months between training data and match"),
    table([2240, 1100, 1700, 1800, 1800],
          ["Months after the\ntraining data", "Matches", "Post-match speed\nMAE (km/h)", "MAE of the change vs\na normal day (km/h)",
           "80 % range of the post-\nmatch error (km/h)"], hz_rows),
    note("Error = predicted − observed speed in the NEAR ring, +2 to +4 h after kick-off; a positive error means that the slowdown "
         "was underestimated. Models trained on 2022-23 or on 2022-24 and applied to all later matches with spectators."),
    body("Figure 4.12 shows the forecast tab of the panel for the derby Galatasaray – Fenerbahçe on 15 December 2026 at Rams Park. "
         "The cards summarise the change against a normal day with its 80 % range, the speed after the match, the hour of the "
         "largest slowdown and the time at which traffic returns to normal; the chart compares the forecast with a normal day and "
         "with the observed average of earlier matches with the same kick-off slot. Further tabs show the map of the cells and "
         "the out-of-sample check on the 2024-25 test matches."),
    figure(ROOT / "outputs" / "figures" / "fig_panel_forecast.png", 15.24, "Forecast tab of the local web panel"),
    caption("Figure", "4.12", "Forecast panel (`python panel.py`): forecast for Galatasaray – Fenerbahçe, 15 December 2026, 20:00, "
                              "Rams Park"),

    # ---------------------------------------------------------- 4.14
    h2("Comparison with the Literature", "4.14"),
    body("No published study predicts congestion classes around Istanbul stadiums, so no directly comparable score exists, and "
         "the seasonal baselines serve as the reference point. Qualitatively, the findings agree with earlier work. As at the Los "
         "Angeles Coliseum [9], a tree ensemble outperforms regression. Like Rodrigues et al. [13], this study finds that event "
         "information reduces forecasting errors specifically in event areas and periods. The local effect measured here (about "
         "15 % lower speed near the stadium after the match) is much larger than the city-wide 1.3 % increase in travel times "
         "reported for Yankee Stadium [8], which is consistent with that study's finding that the effects concentrate near the "
         "venue. The dominant role of traffic history agrees with Özdenizci Köse et al. [15], who found traffic-specific "
         "variables to be the strongest predictors of Istanbul traffic density, and with the strong daily and weekly cycles "
         "described by Şahin and Çolakoğlu [14]; unlike in their city-wide setting, weather adds little to the day-ahead model "
         "once the traffic history is known."),
]
insert_after(par_el("In the match windows the congested class"), sec4)

# ================================================================= 5 DISCUSSION
replace_text(par_el("Validity of the design."),
             "Rings beyond R2, as suggested by the two-mile radius reported for the Los Angeles Coliseum [9], will be added in Phase 2.",
             "Rings beyond R2, as suggested by the two-mile radius reported for the Los Angeles Coliseum [9], are left for future work.")
replace_text(par_el("Relaxed weather matching."),
             "but these matches are flagged and will be excluded in a sensitivity analysis.",
             f"and these matches are flagged; the Phase 2 sensitivity analysis without them gives {V['SensMean']} km/h, practically "
             f"the main estimate (Section 4.8).")
replace_text(par_el("Unadjusted p-values."),
             "consistent across stadiums, windows and both tests.",
             f"consistent across stadiums, windows and both tests. Phase 2 applies Holm's correction within each hypothesis family: "
             f"all {V['HOneSpeedSigHolm']} stadium-by-window speed effects and the stadium differences remain significant, while "
             f"the big-match difference does not (Section 4.8).")
impact = par_el("Impact and next steps.")
replace_text(impact,
             "Phase 2 will train models for the congestion category (T2) and the abnormal-slowdown event (T3) on a temporal split; "
             "because the abnormal-slowdown event is rare (Table 4.8), the class imbalance has to be taken into account.",
             "Phase 2 trained models for the congestion category (T2) and the abnormal-slowdown event (T3) on a temporal split and "
             "took the class imbalance into account; the results are discussed below.")
lim_lead = deepcopy(par_el("Sources of error."))
rebuild(lim_lead, "**Limitations of Phase 2.** The main limitations of the modelling are:")
insert_after(impact, [
    body(f"**Phase 2: what the models show.** Football matches create a short, local and highly predictable disruption, and the "
         f"models confirm that it can be forecast. A day-ahead model that knows the fixture almost halves the post-match speed "
         f"error near the stadiums ({V['MaeHgbPost']} instead of {V['MaeNoEvPost']} km/h) and recognises congested post-match "
         f"hours that a model without fixture information almost never predicts (F1 {V['FCongHgbPost']} vs {V['FCongNoEvPost']}). "
         f"Over all hours, by contrast, fixture information adds almost nothing, because matches concern only a few per cent of "
         f"the hours; an evaluation over all hours alone would have hidden the value of the fixture. Which stadium hosts the match "
         f"matters far more than who the opponent is or when the match starts. That the venue matters more than the "
         f"attractiveness of a match suggests that the access network and the travel behaviour of the spectators drive the effect; "
         f"one possible explanation for the large effect at Rams Park, which lies outside the dense centre, is a higher share of "
         f"spectators travelling by car, but testing this requires modal-split data."),
    body("**Objectives.** The Phase 1 objectives in Table 1.1 were met in Phase 1 (Tables 4.7 and 4.6). The Phase 2 objectives "
         "in Table 1.2 were met as well: the features are known 24 hours ahead and the targets are fitted on the training period "
         "(O7); three model families were compared with two baselines on a single test season (O8); the bootstrap interval of "
         "the fixture gain excludes zero (O9); every hypothesis family is Holm-corrected and the sensitivity analysis confirms "
         "the main estimate (O10); both additional sources confirm the effect at match level (O11); and the forecast panel and "
         "the one-command rebuild exist (O12)."),
    body("**Strengths of Phase 2.** The prediction study is leakage-controlled (day-ahead features, targets and baselines fitted "
         "on the training period, forward-chaining validation, a single test) and isolates the value of fixture information "
         "with an ablation and a match-level bootstrap. Metrics are reported where the matches are, not only on average. Two "
         "independent open sources, rail-station entries and control-centre announcements, confirm the crowd effect, the role of "
         "closures and the persistence of the effect after the traffic data end."),
    lim_lead,
    bullet("**Weather as a forecast.** Reanalysis weather is used instead of archived forecasts, which makes the day-ahead setting "
           "slightly optimistic; weather was the least important feature group, so the effect is small."),
    bullet(f"**Short test season.** The test season covers only six months (August 2024 – January 2025) and {V['TestMatches']} "
           f"matches; the bootstrap intervals reflect this."),
    bullet(f"**Drift.** The abnormal-slowdown target is defined relative to a historical baseline and drifts: with the 2022-23 "
           f"baseline its prevalence rose from {V['TThreePrevSelTrain']} % to {V['TThreePrevSelVal']} % in the next season. An "
           f"operational model would need rolling retraining."),
    bullet("**Selection criterion.** The model was selected for overall macro-F1, which slightly favours the frequent classes; "
           "an operator who cares mainly about congestion would choose balanced class weights at the cost of calibration."),
    bullet(f"**End of the traffic data.** The IBB traffic series ends in January 2025, so later seasons are covered only by the "
           f"two indirect sources, and the scenario model forecasts 2026 about 22 months after its last data, slightly beyond the "
           f"tested horizon of {bins[-1]['max_tested']:.0f} months."),
    bullet("**Causality.** As in Phase 1, the design is observational and cannot prove causality."),
    para(P_BODY_GAP, "**Possible improvements.** Archived weather forecasts, road-segment probe data and hourly public-transport "
                     "ridership would sharpen both parts of the study. Further venues and events (Başakşehir, concerts, basketball) "
                     "would increase the number of matches and the power of the group comparisons. Rolling retraining would address "
                     "drift, isotonic calibration could combine balanced class weights with reliable probabilities, and graph-based "
                     "models [16] could exploit the spatial propagation of congestion."),
])

# ================================================================= 6 CONCLUSIONS
insert_after(par_el("Phase 1 delivers the foundation"), [body(
    f"Phase 2 turned this foundation into predictions and tested them strictly. With features that are known a day in advance, "
    f"targets fitted on the training period and a forward-chaining design with a single test on the 2024-25 season, "
    f"histogram-based gradient boosting predicted the congestion class with a macro-F1 of {V['FOneHgbAll']}, better than two "
    f"seasonal baselines, logistic regression and a random forest. Fixture information hardly matters over all hours, but it is "
    f"what allows the model to anticipate post-match congestion: near the stadiums it reduces the post-match speed error from "
    f"{V['MaeNoEvPost']} to {V['MaeHgbPost']} km/h, and a bootstrap over matches confirms the gain (H5 rejected). The extended "
    f"statistics confirm the Phase 1 results after Holm's correction and show that the opponent does not change the effect, "
    f"while daily rail-station entries (+{V['ExtRailMean']} % on match days) and the announcements of the traffic control centre "
    f"confirm the crowd effect independently and show that it continued after January 2025. A long-horizon scenario model, "
    f"back-tested over up to {bins[-1]['max_tested']:.0f} months, makes the results usable for future fixtures through a local "
    f"forecast panel.")])
rebuild(par_el("Beyond this project, the approach shows"),
        "Beyond this project, the approach shows how open municipal data and published fixtures can be used to evaluate and "
        "forecast the traffic cost of planned events with a transparent counterfactual. It can support match-day traffic "
        "management – the timing of closures, extra public-transport services and driver information – and can be extended to "
        "other venues, event types and data sources such as archived weather forecasts or hourly public-transport ridership.")

# ================================================================= REFERENCES [30]-[46], APA style as in Phase 1
REFS = [
    "Holm, S. (1979). A simple sequentially rejective multiple test procedure. __Scandinavian Journal of Statistics, 6__(2), 65–70.",
    "Kruskal, W. H., & Wallis, W. A. (1952). Use of ranks in one-criterion variance analysis. __Journal of the American "
    "Statistical Association, 47__(260), 583–621. https://doi.org/10.1080/01621459.1952.10483441",
    "Cramér, H. (1946). __Mathematical methods of statistics__. Princeton University Press.",
    "Kaufman, S., Rosset, S., Perlich, C., & Stitelman, O. (2012). Leakage in data mining: Formulation, detection, and avoidance. "
    "__ACM Transactions on Knowledge Discovery from Data, 6__(4), 15. https://doi.org/10.1145/2382577.2382579",
    "Bergmeir, C., & Benítez, J. M. (2012). On the use of cross-validation for time series predictor evaluation. __Information "
    "Sciences, 191__, 192–213. https://doi.org/10.1016/j.ins.2011.12.028",
    "Hyndman, R. J., & Athanasopoulos, G. (2021). __Forecasting: Principles and practice__ (3rd ed.). OTexts. https://otexts.com/fpp3/",
    "Pedregosa, F., Varoquaux, G., Gramfort, A., et al. (2011). Scikit-learn: Machine learning in Python. __Journal of Machine "
    "Learning Research, 12__, 2825–2830.",
    "Breiman, L. (2001). Random forests. __Machine Learning, 45__(1), 5–32. https://doi.org/10.1023/A:1010933404324",
    "Friedman, J. H. (2001). Greedy function approximation: A gradient boosting machine. __The Annals of Statistics, 29__(5), "
    "1189–1232. https://doi.org/10.1214/aos/1013203451",
    "Ke, G., Meng, Q., Finley, T., et al. (2017). LightGBM: A highly efficient gradient boosting decision tree. In __Advances in "
    "Neural Information Processing Systems 30__ (pp. 3146–3154).",
    "Saito, T., & Rehmsmeier, M. (2015). The precision-recall plot is more informative than the ROC plot when evaluating binary "
    "classifiers on imbalanced datasets. __PLoS ONE, 10__(3), e0118432. https://doi.org/10.1371/journal.pone.0118432",
    "Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. __Monthly Weather Review, 78__(1), 1–3.",
    "Niculescu-Mizil, A., & Caruana, R. (2005). Predicting good probabilities with supervised learning. In __Proceedings of the "
    "22nd International Conference on Machine Learning__ (pp. 625–632).",
    "Efron, B., & Tibshirani, R. J. (1993). __An introduction to the bootstrap__. Chapman & Hall.",
    "Istanbul Metropolitan Municipality. (2021–2025). __Rail systems station-based passenger and journey numbers__ [Data set]. "
    "İBB Open Data Portal. https://data.ibb.gov.tr/dataset/rayli-sistemler-istasyon-bazli-yolcu-ve-yolculuk-sayilari",
    "Istanbul Metropolitan Municipality. (2020–2026). __Transport Management Centre traffic announcements__ [Data set]. İBB Open "
    "Data Portal. https://data.ibb.gov.tr/dataset/ulasim-yonetim-merkezi-trafik-duyurulari-verisi",
    "OpenStreetMap contributors. (2026). __OpenStreetMap__ [Data set, ODbL 1.0]. Retrieved November 2026, from "
    "https://www.openstreetmap.org/",
]
last_ref = par_el("Kendall, M. G. (1938)")
insert_after(last_ref, [para(P_REF, r) for r in REFS])

# ================================================================= APPENDIX C (repository) and D (generative AI)
root_line = par_el("ftraffic-phase1/")
root_line.find(qn("w:r")).find(qn("w:t")).text = "FODS_Final_Code_and_Data/ # final code package (Phase 1 files unchanged)"
insert_after(par_el("├── fill_report.py"), [code_line(t) for t in [
    "├── run_phase2.py         # Phase 2: extended statistics and day-ahead models",
    "├── run_extra.py          # Phase 2: rail-station and UYM validation",
    "├── run_scenario.py       # Phase 2: scenario model for future fixtures",
    "├── panel.py, panel/      # Phase 2: local forecast panel",
    "├── demo.py               # five-step demonstration for the presentation",
]])
qc_line = par_el("│   └── qc.py")
qc_line.find(qn("w:r")).find(qn("w:t")).text = "│   ├── qc.py             # 14 automated quality checks"
insert_after(qc_line, [code_line(t) for t in [
    "│   ├── stats_extra.py    # Phase 2: multi-group tests, opponent groups, Holm",
    "│   ├── model.py          # Phase 2: day-ahead features, models, validation",
    "│   ├── extra_sources.py  # Phase 2: rail stations, UYM announcements",
    "│   └── scenario.py       # Phase 2: scenario model and back-test",
]])
insert_after(par_el("├── tools/build_fixtures.py"), [code_line(t) for t in [
    "├── tools/build_paper.py        # numbers and result tables (paper/generated)",
    "├── tools/build_final_report.py # builds this report from the Phase 1 report",
    "├── tools/fetch_osm_roads.py    # OpenStreetMap roads for the panel map",
]])
orig_last = par_el("$ python3 fill_report.py")
mid_ppr = deepcopy(par_el("$ python3 run_all.py").find(qn("w:pPr")))
end_ppr = deepcopy(orig_last.find(qn("w:pPr")))           # the last line of the block carries the space after it
orig_last.replace(orig_last.find(qn("w:pPr")), deepcopy(mid_ppr))
last_cmd = insert_after(orig_last, [code_line(t) for t in [
    "$ python3 run_phase2.py",
    "$ python3 run_scenario.py",
    "$ python3 run_extra.py",
    "$ python3 tools/build_paper.py",
    "$ python3 tools/build_final_report.py",
    "$ python3 panel.py              # forecast panel: http://127.0.0.1:8050",
]])
last_cmd.replace(last_cmd.find(qn("w:pPr")), end_ppr)
insert_after(last_cmd, [
    para(P_APP, "**Appendix D – Use of generative AI.**"),
    body("A generative AI assistant (Claude, Anthropic) was used as a supporting tool for code development and debugging, for "
         "checking statistical procedures and for language editing of this report. All analyses were run by the authors on the "
         "data described above, every number in this report is produced by the accompanying code, and the authors verified the "
         "results and references and can explain every step."),
])

# ================================================================= table of contents, list of tables, list of figures
def entry_of(style, start):
    for p in doc.paragraphs:
        if p.style.name == style and p.text.startswith(start):
            return p._p
    raise KeyError(f"entry not found: {start!r}")


def make_entry(proto, anchor, texts):
    e = deepcopy(proto)
    e.find(qn("w:hyperlink")).set(qn("w:anchor"), anchor)
    ts = list(e.iter(qn("w:t")))
    for t, v in zip(ts, texts + ["0"]):           # page number "0" until Word updates the PAGEREF field
        t.text = v
    for it in e.iter(qn("w:instrText")):
        it.text = f" PAGEREF {anchor} \\h "
    return e


proto = {2: entry_of("toc 2", "1.2."), 3: entry_of("toc 3", "3.1.2.")}
TOC_AFTER = {"3.1.7.": "3.1.6.", "3.3.9.": "3.3.8.", "4.8.": "4.7."}
cur = None
for level, num, title, bm in TOC_NEW:
    if num in TOC_AFTER:
        cur = entry_of(f"toc {3 if TOC_AFTER[num].count('.') == 3 else 2}", TOC_AFTER[num])
    new = make_entry(proto[level], bm, [num, title])
    cur.addnext(new)
    cur = new
CAP_AFTER = {"Table 1.2": "Table 1.1:", "Table 3.11": "Table 3.10:", "Table 4.9": "Table 4.8:",
             "Figure 3.4": "Figure 3.3:", "Figure 4.4": "Figure 4.3:"}
for kind, pstart in [("Table", "Table 2.1:"), ("Figure", "Figure 3.2:")]:
    pr, cur = entry_of("table of figures", pstart), None
    for label, text, bm in CAP_NEW[kind]:
        if label in CAP_AFTER:
            cur = entry_of("table of figures", CAP_AFTER[label])
        new = make_entry(pr, bm, [text])
        cur.addnext(new)
        cur = new
print(f"contents: {len(TOC_NEW)} headings, {len(CAP_NEW['Table'])} tables, {len(CAP_NEW['Figure'])} figures added")

# ================================================================= save, then let Word update the page numbers and export the PDF
BUILD.mkdir(exist_ok=True)
OUT_DOCX.parent.mkdir(exist_ok=True)
raw = BUILD / "Final_Report_raw.docx"
doc.save(raw)
print(f"written {raw}")


def word_finalise(src: Path, docx_out: Path, pdf_out: Path) -> bool:
    if sys.platform != "darwin" or not Path("/Applications/Microsoft Word.app").exists():
        return False
    script = f'''
with timeout of 600 seconds
tell application "Microsoft Word"
    open (POSIX file "{src}")
    set d to active document
    -- only the PAGEREF fields: regenerating the TOC fields would depend on the list separator of the system locale
    set tps to field type of every field of text object of d
    repeat with i from 1 to (count of tps)
        if item i of tps is field page ref then update field (field i of text object of d)
    end repeat
    save as d file name "{docx_out}" file format format document
    save as d file name "{pdf_out}" file format format PDF
    close (every document whose name is "{docx_out.name}") saving no
end tell
end timeout'''
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        print("Word step failed:", r.stderr.strip())
        return False
    return True


if "--no-word" not in sys.argv and word_finalise(raw, BUILD / "Final_Report.docx", BUILD / "Final_Report.pdf"):
    shutil.copy2(BUILD / "Final_Report.docx", OUT_DOCX)
    shutil.copy2(BUILD / "Final_Report.pdf", OUT_PDF)
    print(f"written {OUT_DOCX} and {OUT_PDF} (page numbers updated by Word)")
else:
    shutil.copy2(raw, OUT_DOCX)
    print(f"written {OUT_DOCX}; in Word select the table of contents and the lists and press F9 to refresh the page numbers")
