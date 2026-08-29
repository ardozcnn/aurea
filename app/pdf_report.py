"""Oyuncu dosyası PDF: Aurea markalı, Unicode Türkçe."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from app.config import WEB_DIR
from app.money import format_eur, format_pct

_INK = (26, 24, 20)
_MUTED = (92, 86, 76)
_GOLD = (184, 148, 64)
_NAVY = (18, 20, 27)
_CREAM = (247, 244, 236)
_LINE = (220, 214, 200)
_GOLD_SOFT = (245, 236, 214)


def _fonts() -> tuple[Path, Path]:
    regular = WEB_DIR / "fonts" / "NotoSans-Regular.ttf"
    semibold = WEB_DIR / "fonts" / "NotoSans-SemiBold.ttf"
    if regular.exists() and semibold.exists():
        return regular, semibold
    windows = Path(r"C:\Windows\Fonts")
    for a, b in (
        (windows / "segoeui.ttf", windows / "segoeuib.ttf"),
        (windows / "arial.ttf", windows / "arialbd.ttf"),
    ):
        if a.exists() and b.exists():
            return a, b
    linux = Path("/usr/share/fonts/truetype/dejavu")
    if (linux / "DejaVuSans.ttf").exists():
        bold = linux / "DejaVuSans-Bold.ttf"
        return linux / "DejaVuSans.ttf", bold if bold.exists() else linux / "DejaVuSans.ttf"
    raise RuntimeError("PDF için yazı tipi bulunamadı.")


def _clean(text: Any) -> str:
    return (
        str(text or "")
        .replace("\xa0", " ")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .strip()
    )


def _diamond(pdf, cx: float, cy: float, size: float = 3.4) -> None:
    pdf.set_fill_color(*_GOLD)
    pdf.polygon(
        ((cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy)),
        style="F",
    )


def _make_doc(stamp: str):
    from fpdf import FPDF

    regular, semibold = _fonts()

    class Doc(FPDF):
        def header(self) -> None:
            self.set_fill_color(*_CREAM)
            self.rect(0, 0, 210, 297, style="F")
            tall = self.page_no() == 1
            h = 36 if tall else 16
            self.set_fill_color(*_NAVY)
            self.rect(0, 0, 210, h, style="F")
            self.set_fill_color(*_GOLD)
            self.rect(0, h, 210, 0.7, style="F")
            _diamond(self, 20, 10 if tall else 8)
            self.set_text_color(*_GOLD)
            self.set_font("Aurea", "B", 14 if tall else 11)
            self.set_xy(26, 6 if tall else 4)
            self.cell(80, 8, "AUREA")
            self.set_font("Aurea", "", 8)
            self.set_text_color(212, 181, 106)
            self.set_xy(140, 6 if tall else 4)
            self.cell(54, 8, stamp, align="R")
            if tall:
                self.set_xy(26, 16)
                self.set_font("Aurea", "", 9)
                self.cell(80, 6, "Adil değer dosyası")
                self.set_xy(26, 23)
                self.set_text_color(168, 164, 156)
                self.set_font("Aurea", "", 8)
                self.cell(160, 5, "Transfermarkt etiketi modele girmez. Üretime dayalı okuma.")
            self.set_y(44 if tall else 24)

        def footer(self) -> None:
            self.set_y(-16)
            self.set_draw_color(*_LINE)
            self.line(16, self.get_y(), 194, self.get_y())
            self.set_y(-13)
            self.set_font("Aurea", "", 7)
            self.set_text_color(*_MUTED)
            self.set_x(16)
            self.cell(110, 6, "Aurea  ·  istatistiksel okuma, tavsiye değildir.")
            self.cell(68, 6, f"{self.page_no()} / {{nb}}", align="R")

    pdf = Doc(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font("Aurea", "", str(regular))
    pdf.add_font("Aurea", "B", str(semibold))
    pdf.alias_nb_pages()
    return pdf


def build_player_pdf(pack: dict[str, Any]) -> bytes:
    player = pack.get("player") or {}
    report = pack.get("report") or {}
    live = pack.get("live") or {}
    ident = report.get("identity") or {}
    name = _clean(ident.get("name") or player.get("name") or "Oyuncu")
    club = _clean(ident.get("club") or player.get("club") or "")
    pos = _clean(ident.get("position") or player.get("position") or "")
    league = _clean(ident.get("league") or player.get("league") or "")
    stamp = datetime.now().strftime("%d.%m.%Y")
    pdf = _make_doc(stamp)
    pdf.add_page()

    pdf.set_text_color(*_INK)
    pdf.set_font("Aurea", "B", 22)
    pdf.set_x(16)
    pdf.multi_cell(178, 9, name)
    pdf.set_font("Aurea", "", 11)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(16)
    meta = " · ".join(
        part
        for part in (
            pos,
            club,
            league,
            f"{player.get('age')} yaş" if player.get("age") else "",
        )
        if part
    )
    pdf.multi_cell(178, 6, meta or "—")

    pdf.ln(3)
    tm = _clean(player.get("tm_label") or format_eur(player.get("tm_value")))
    true = _clean(player.get("true_label") or format_eur(player.get("true_value")))
    gap = _clean(player.get("gap_label") or format_pct(player.get("gap_pct")))
    box_w = 86
    y0 = pdf.get_y()
    pdf.set_fill_color(255, 255, 255)
    pdf.set_draw_color(*_LINE)
    pdf.rect(16, y0, box_w, 30, style="DF")
    pdf.set_fill_color(*_GOLD_SOFT)
    pdf.set_draw_color(*_GOLD)
    pdf.rect(108, y0, box_w, 30, style="DF")
    pdf.set_xy(20, y0 + 4)
    pdf.set_font("Aurea", "", 8)
    pdf.set_text_color(*_MUTED)
    pdf.cell(78, 5, "TRANSFERMARKT")
    pdf.set_xy(20, y0 + 12)
    pdf.set_font("Aurea", "B", 16)
    pdf.set_text_color(*_INK)
    pdf.cell(78, 8, tm)
    pdf.set_xy(112, y0 + 4)
    pdf.set_font("Aurea", "", 8)
    pdf.set_text_color(*_GOLD)
    pdf.cell(78, 5, "AUREA DEĞERİ")
    pdf.set_xy(112, y0 + 12)
    pdf.set_font("Aurea", "B", 16)
    pdf.set_text_color(*_INK)
    pdf.cell(78, 8, true)
    pdf.set_xy(112, y0 + 21)
    pdf.set_font("Aurea", "", 8)
    pdf.set_text_color(*_MUTED)
    pdf.cell(78, 5, gap)
    pdf.set_y(y0 + 36)

    headline = _clean(report.get("headline"))
    summary = _clean(report.get("summary"))
    if headline:
        pdf.set_font("Aurea", "B", 13)
        pdf.set_text_color(*_INK)
        pdf.set_x(16)
        pdf.multi_cell(178, 6.2, headline)
    if summary:
        pdf.set_font("Aurea", "", 10)
        pdf.set_text_color(40, 36, 30)
        pdf.set_x(16)
        pdf.multi_cell(178, 5.5, summary)
        pdf.ln(2)

    metrics = report.get("metrics") or []
    if metrics:
        pdf.set_font("Aurea", "B", 11)
        pdf.set_text_color(*_INK)
        pdf.set_x(16)
        pdf.cell(178, 7, "Üretim")
        pdf.ln(2)
        col = 0
        row_y = pdf.get_y()
        for item in metrics:
            x = 16 + (col % 4) * 45
            if col and col % 4 == 0:
                row_y += 16
                if row_y > 262:
                    pdf.add_page()
                    row_y = pdf.get_y()
            pdf.set_fill_color(255, 255, 255)
            pdf.set_draw_color(*_LINE)
            pdf.rect(x, row_y, 43, 14, style="D")
            pdf.set_xy(x + 2, row_y + 1.5)
            pdf.set_font("Aurea", "", 7)
            pdf.set_text_color(*_MUTED)
            pdf.cell(39, 4, _clean(item.get("k")))
            pdf.set_xy(x + 2, row_y + 6.5)
            pdf.set_font("Aurea", "B", 10)
            pdf.set_text_color(*_INK)
            pdf.cell(39, 5, _clean(item.get("v")))
            col += 1
        pdf.set_y(row_y + 18)

    for section in report.get("sections") or []:
        title = _clean(section.get("title"))
        paras = section.get("paragraphs") or []
        if not paras and section.get("body"):
            paras = [section.get("body")]
        if not title or not paras:
            continue
        if pdf.get_y() > 248:
            pdf.add_page()
        pdf.set_font("Aurea", "B", 12)
        pdf.set_text_color(*_GOLD)
        pdf.set_x(16)
        pdf.cell(178, 7, title)
        pdf.ln(1)
        pdf.set_draw_color(*_GOLD)
        pdf.set_line_width(0.3)
        yline = pdf.get_y()
        pdf.line(16, yline, 52, yline)
        pdf.ln(2)
        pdf.set_font("Aurea", "", 10)
        pdf.set_text_color(40, 36, 30)
        for para in paras:
            text = _clean(para)
            if not text:
                continue
            if pdf.get_y() > 262:
                pdf.add_page()
            pdf.set_x(16)
            pdf.multi_cell(178, 5.4, text)
            pdf.ln(1.2)
        pdf.ln(1)

    fm = (live.get("fotmob") or {}) if isinstance(live, dict) else {}
    recent = fm.get("recent") or []
    if recent:
        if pdf.get_y() > 230:
            pdf.add_page()
        pdf.set_font("Aurea", "B", 12)
        pdf.set_text_color(*_GOLD)
        pdf.set_x(16)
        pdf.cell(178, 7, "Son maçlar")
        pdf.ln(1)
        pdf.set_font("Aurea", "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.set_x(16)
        pdf.cell(78, 6, "Rakip")
        pdf.cell(22, 6, "Dakika")
        pdf.cell(22, 6, "Gol")
        pdf.cell(22, 6, "Asist")
        pdf.cell(34, 6, "İlk 11")
        pdf.ln()
        pdf.set_font("Aurea", "", 8)
        pdf.set_text_color(*_INK)
        for rec in recent[:6]:
            if pdf.get_y() > 268:
                pdf.add_page()
            pdf.set_x(16)
            pdf.cell(78, 5.5, _clean(rec.get("opponent") or "—")[:36])
            pdf.cell(22, 5.5, str(rec.get("minutes") or 0))
            pdf.cell(22, 5.5, str(rec.get("goals") or 0))
            pdf.cell(22, 5.5, str(rec.get("assists") or 0))
            pdf.cell(34, 5.5, "Evet" if rec.get("started") else "Hayır")
            pdf.ln()

    table = pack.get("season_table") or []
    rows = [r for r in table if int(r.get("apps") or 0) > 0][:8]
    if rows:
        if pdf.get_y() > 230:
            pdf.add_page()
        pdf.set_font("Aurea", "B", 12)
        pdf.set_text_color(*_GOLD)
        pdf.set_x(16)
        pdf.cell(178, 7, "Sezon")
        pdf.ln(1)
        pdf.set_font("Aurea", "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.set_x(16)
        pdf.cell(78, 6, "Turnuva")
        pdf.cell(20, 6, "Maç")
        pdf.cell(20, 6, "Gol")
        pdf.cell(20, 6, "Asist")
        pdf.cell(24, 6, "Dakika")
        pdf.ln()
        pdf.set_font("Aurea", "", 8)
        pdf.set_text_color(*_INK)
        for rec in rows:
            if pdf.get_y() > 268:
                pdf.add_page()
            pdf.set_x(16)
            label = _clean(rec.get("competition") or "—")
            if rec.get("season"):
                label = f"{label} · {_clean(rec.get('season'))}"
            pdf.cell(78, 5.5, label[:42])
            pdf.cell(20, 5.5, str(rec.get("apps") or 0))
            pdf.cell(20, 5.5, str(rec.get("goals") or 0))
            pdf.cell(20, 5.5, str(rec.get("assists") or 0))
            pdf.cell(24, 5.5, str(rec.get("minutes") or 0))
            pdf.ln()

    similar = pack.get("similar") or []
    if similar:
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(2)
        pdf.set_font("Aurea", "B", 12)
        pdf.set_text_color(*_GOLD)
        pdf.set_x(16)
        pdf.cell(178, 7, "Benzer oyuncular")
        pdf.ln(1)
        pdf.set_font("Aurea", "", 9)
        pdf.set_text_color(*_INK)
        for item in similar[:6]:
            line = " · ".join(
                part
                for part in (
                    _clean(item.get("name")),
                    _clean(item.get("club")),
                    _clean(item.get("true_label") or item.get("tm_label")),
                )
                if part
            )
            pdf.set_x(16)
            pdf.cell(178, 5.4, line)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
