from fpdf import FPDF
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
    """Generates a formal Swiss-style cancellation letter in PDF format."""
    
    # Sanitize inputs to prevent FPDF character encoding errors
    sender_name = sanitize_text(sender_name)
    provider_name = sanitize_text(provider_name)
    provider_address = sanitize_text(provider_address)
    letter_body = sanitize_text(letter_body)
    
    pdf = FPDF(format='A4', unit='mm')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    # Font setup
    pdf.set_font("Helvetica", size=11)
    
    # Header: Sender Details
    pdf.set_font("Helvetica", style='B', size=11)
    pdf.cell(0, 6, txt=sender_name, ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, txt="Schweiz", ln=True)
    pdf.ln(10)
    
    # Recipient Info
    pdf.set_font("Helvetica", style='B', size=11)
    pdf.cell(0, 6, txt=f"An: {provider_name}", ln=True)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 5, txt=provider_address)
    pdf.ln(15)
    
    # Date line
    pdf.cell(0, 6, txt="Datum: [Aktuelles Datum]", ln=True)
    pdf.ln(10)
    
    # Letter Body
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, txt=letter_body)
    pdf.ln(15)
    
    # Signature line
    pdf.cell(0, 6, txt="Mit freundlichen Grüssen,", ln=True)
    pdf.ln(12)
    pdf.cell(0, 6, txt=f"_________________________", ln=True)
    pdf.cell(0, 6, txt=sender_name, ln=True)
    
    # Save PDF
    pdf.output(output_path)
    return output_path
