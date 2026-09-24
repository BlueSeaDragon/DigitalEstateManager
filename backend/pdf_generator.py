from fpdf import FPDF
from fpdf.enums import XPos, YPos
import os

def sanitize_text(text: str) -> str:
    """Replaces Unicode characters outside standard Latin range with safe equivalents."""
    replacements = {
        "„": '"', "“": '"', "”": '"', "’": "'", "‘": "'",
        "–": "-", "—": "-", "…": "...", "•": "-",
        "™": "", "®": "", "©": "(c)"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def create_cancellation_pdf(sender_name: str, provider_name: str, provider_address: str, letter_body: str, output_path: str):
    """Generates a formal Swiss-style cancellation letter in PDF format using fpdf2 modern syntax."""
    
    sender_name = sanitize_text(sender_name)
    provider_name = sanitize_text(provider_name)
    provider_address = sanitize_text(provider_address)
    letter_body = sanitize_text(letter_body)
    
    pdf = FPDF(format='A4', unit='mm')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    pdf.set_font("Helvetica", size=11)
    
    # Header: Sender Details
    pdf.set_font("Helvetica", style='B', size=11)
    pdf.cell(0, 6, text=sender_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, text="Schweiz", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Recipient Info
    pdf.set_font("Helvetica", style='B', size=11)
    pdf.cell(0, 6, text=f"An: {provider_name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 5, text=provider_address)
    pdf.ln(15)
    
    # Date line
    pdf.cell(0, 6, text="Datum: [Aktuelles Datum]", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # Letter Body
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, text=letter_body)
    pdf.ln(15)
    
    # Signature line
    pdf.cell(0, 6, text="Mit freundlichen Grüssen,", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(12)
    pdf.cell(0, 6, text="_________________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 6, text=sender_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.output(output_path)
    return output_path
