from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import datetime

def sanitize_text(text: str) -> str:
    replacements = {
        "„": '"', "“": '"', "”": '"', "’": "'", "‘": "'",
        "–": "-", "—": "-", "…": "...", "•": "-",
        "™": "", "®": "", "©": "(c)"
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def create_cancellation_pdf(sender_name: str, provider_name: str, provider_address: str, letter_body: str, output_path: str):
    sender_name = sanitize_text(sender_name)
    provider_name = sanitize_text(provider_name)
    provider_address = sanitize_text(provider_address)
    letter_body = sanitize_text(letter_body)
    
    pdf = FPDF(format='A4', unit='mm')
    pdf.set_margins(left=20, top=20, right=20)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    
    # 1. SENDER HEADER (Top Left)
    pdf.set_font("Helvetica", style='B', size=11)
    pdf.cell(0, 5, text=sender_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, text="Schweiz", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    
    # 2. RECIPIENT WINDOW (Swiss Standard Right Alignment)
    pdf.set_y(40)
    pdf.set_x(110) # Offset to right
    pdf.set_font("Helvetica", style='B', size=10)
    pdf.cell(0, 5, text=provider_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    # Address lines
    pdf.set_font("Helvetica", size=10)
    for line in provider_address.split("\n"):
        pdf.set_x(110)
        pdf.cell(0, 4.5, text=line.strip(), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        
    # 3. DATE LINE (Right-aligned below recipient)
    pdf.set_y(80)
    pdf.set_font("Helvetica", size=10)
    today_str = datetime.now().strftime("%d.%m.%Y")
    pdf.cell(0, 5, text=f"Schweiz, den {today_str}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(10)
    
    # 4. LETTER BODY
    pdf.set_font("Helvetica", size=10)
    
    lines = letter_body.strip().split("\n")
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            pdf.ln(3)
            continue
            
        # Bold the subject line automatically
        if line_clean.startswith("Betreff:"):
            pdf.set_font("Helvetica", style='B', size=11)
            pdf.multi_cell(0, 6, text=line_clean)
            pdf.set_font("Helvetica", size=10)
            pdf.ln(4)
        else:
            pdf.multi_cell(0, 5, text=line_clean)
            pdf.ln(2)
            
    # 5. SIGNATURE BLOCK
    pdf.ln(8)
    pdf.cell(0, 5, text="__________________________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 5, text=f"Unterschrift ({sender_name})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.output(output_path)
    return output_path
