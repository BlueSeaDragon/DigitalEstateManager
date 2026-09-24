from datetime import date
from typing import Optional

from fpdf import FPDF

# Layout per Swiss business letter standard (SN 010130), A4 with right-hand address window
MARGIN_LEFT = 25  # mm
MARGIN_RIGHT = 20  # mm
ADDRESS_WINDOW_X = 118  # mm from left edge (C5/C6 window envelope, window right)
ADDRESS_WINDOW_Y = 52  # mm from top edge
FONT = "Helvetica"

GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

# Built-in PDF fonts only cover Latin-1; map common LLM typography to safe equivalents
_CHAR_REPLACEMENTS = {
    "ß": "ss",  # Swiss German does not use ß
    "‘": "'", "’": "'", "‚": ",",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "…": "...",
    " ": " ", "•": "-",
}


def _sanitize(text: str) -> str:
    for char, replacement in _CHAR_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _format_swiss_date(d: date) -> str:
    return f"{d.day}. {GERMAN_MONTHS[d.month - 1]} {d.year}"


def _address_lines(address: str) -> list[str]:
    """Split a comma- or newline-separated address into individual lines."""
    parts = address.replace("\n", ",").split(",")
    return [part.strip() for part in parts if part.strip()]


def create_cancellation_pdf(
    sender_name: str,
    provider_name: str,
    provider_address: str,
    letter_body: str,
    output_path: str,
    sender_address: Optional[str] = None,
    place: Optional[str] = None,
    subject: str = "Kündigung des Vertrags",
    letter_date: Optional[date] = None,
) -> str:
    """
    Generate a formal German cancellation letter as an A4 PDF in Swiss layout.

    Returns the path of the written PDF.
    """
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN_LEFT, 20, MARGIN_RIGHT)
    pdf.set_auto_page_break(auto=True, margin=25)
    pdf.set_title(_sanitize(f"{subject} - {provider_name}"))
    pdf.set_author(_sanitize(sender_name))
    pdf.add_page()

    # Sender block (top left)
    pdf.set_font(FONT, size=10)
    pdf.set_xy(MARGIN_LEFT, 20)
    for line in [sender_name, *_address_lines(sender_address or "")]:
        pdf.cell(0, 5, _sanitize(line), new_x="LMARGIN", new_y="NEXT")

    # Recipient block in the right-hand address window
    recipient_lines = _address_lines(provider_address)
    if not recipient_lines or recipient_lines[0] != provider_name:
        recipient_lines.insert(0, provider_name)
    pdf.set_font(FONT, size=11)
    pdf.set_y(ADDRESS_WINDOW_Y)
    for line in recipient_lines:
        pdf.set_x(ADDRESS_WINDOW_X)
        pdf.cell(0, 5, _sanitize(line), new_x="LMARGIN", new_y="NEXT")

    # Place and date
    date_line = _format_swiss_date(letter_date or date.today())
    if place:
        date_line = f"{place}, {date_line}"
    pdf.set_y(max(pdf.get_y(), ADDRESS_WINDOW_Y + 35) + 10)
    pdf.cell(0, 5, _sanitize(date_line), new_x="LMARGIN", new_y="NEXT")

    # Subject line (bold, no "Betreff:" prefix per Swiss convention)
    pdf.ln(10)
    pdf.set_font(FONT, style="B", size=11)
    pdf.multi_cell(0, 6, _sanitize(subject), new_x="LMARGIN", new_y="NEXT")

    # Body
    pdf.ln(6)
    pdf.set_font(FONT, size=11)
    pdf.multi_cell(0, 5.5, _sanitize(letter_body.strip()), align="L", new_x="LMARGIN", new_y="NEXT")

    # Closing and signature line, unless the body already contains a closing
    if "grüsse" not in letter_body.lower() and "grüße" not in letter_body.lower():
        pdf.ln(8)
        pdf.cell(0, 5, "Freundliche Grüsse", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)
    pdf.cell(70, 0, "", border="T", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.cell(0, 5, _sanitize(sender_name), new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)
    return output_path
