import os
from fpdf import FPDF

class SwissLegalPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 5, "Digital Estate Manager - Formelle Kündigung", ln=True, align="R")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Seite {self.page_no()}/{{nb}}", align="C")

def create_cancellation_pdf(sender_name: str, provider_name: str, provider_address: str, letter_body: str, output_path: str) -> str:
    pdf = SwissLegalPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Sender / Header Info
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"Absender: {sender_name}", ln=True)
    pdf.ln(5)

    # Recipient Info
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, f"An: {provider_name}", ln=True)
    pdf.multi_cell(0, 5, provider_address)
    pdf.ln(10)

    # Subject / Letter Body
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, letter_body)
    pdf.ln(10)

    # Signature Placeholder
    pdf.cell(0, 5, "Freundliche Grüsse,", ln=True)
    pdf.ln(12)
    pdf.cell(0, 5, "___________________________", ln=True)
    pdf.cell(0, 5, sender_name, ln=True)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
    pdf.output(output_path)
    return output_path
