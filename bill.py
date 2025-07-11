# app.py
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
import fitz  # PyMuPDF
import pandas as pd
import re
import sqlite3
import tempfile
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Initialize SQLite database
DB_PATH = 'bill.db'
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute('''
    CREATE TABLE IF NOT EXISTS invoices (
        bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        pdf_name TEXT,
        invoice_no TEXT
    )
''')
c.execute('''
    CREATE TABLE IF NOT EXISTS invoice_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER,
        meta_key TEXT,
        meta_value TEXT,
        FOREIGN KEY (bill_id) REFERENCES invoices (bill_id)
    )
''')
conn.commit()

def extract_all_invoices(text):
    entries = re.split(r'(?=Customer Address)', text)
    return [entry.strip() for entry in entries if len(entry.strip()) > 50]

def extract_field(text, pattern, group=1):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(group).strip() if match else "NA"

def extract_data_from_invoice(text):
    return {
        "Customer Name": extract_field(text, r'Customer Address\s*\n(.+?)\n'),
        "Courier Partner": extract_field(text, r'(Delhivery|Ekart|XpressBees|BlueDart|EcomExpress|Shadowfax)'),
        "AWB Number": extract_field(text, r'\b(\d{15,})\b'),
        "Payment Type": extract_field(text, r'(COD|Prepaid: Do not collect cash)'),
        "Order ID": extract_field(text, r'Purchase Order No\.\s*(\S+)'),
        "Invoice No": extract_field(text, r'Invoice No\.\s*(\S+)'),
        "Order Date": extract_field(text, r'Order Date\s*(\d{2}[./-]\d{2}[./-]\d{4})'),
        "Invoice Date": extract_field(text, r'Invoice Date\s*(\d{2}[./-]\d{2}[./-]\d{4})'),
        "Product Description": extract_field(text, r'Description.*?\n(.*?)\n', group=1),
        "Size": extract_field(text, r'\b(\d{2,3}cm|XS|S|M|L|XL|XXL|3XL|4XL|5XL)\b'),
        "Qty": extract_field(text, r'\bQty\b.*?(\d+)'),
        "SKU": extract_field(text, r'SKU\s+Size\s+Qty.*?\n(\w+)'),
        "HSN Code": extract_field(text, r'HSN\s*(\d+)'),
        "Gross Amount": extract_field(text, r'Gross Amount\s+(Rs\.\d+\.\d{2})'),
        "Discount": extract_field(text, r'Discount\s+(Rs\.\d+\.\d{2})'),
        "Taxable Value": extract_field(text, r'Taxable Value\s+(Rs\.\d+\.\d{2})'),
        "Taxes": extract_field(text, r'Taxes.*?\n.*?(Rs\.\d+\.\d{2})'),
        "Other Charges": extract_field(text, r'Other Charges.*?\n.*?(Rs\.\d+\.\d{2})'),
        "Total Amount": extract_field(text, r'Total\s+(Rs\.\d+\.\d{2})'),
        "State": extract_field(text, r',\s*([A-Za-z ]+),\s*\d{6}')
    }

def extract_data_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    invoices = extract_all_invoices(full_text)
    return [extract_data_from_invoice(inv) for inv in invoices]

@app.route('/')
def index():
    return render_template('bills.html')

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('pdfs')
    extracted_data = []

    for file in files:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        rows = extract_data_from_pdf(filepath)
        extracted_data.extend(rows)

        for row in rows:
            invoice_no = row.get("Invoice No", "")
            c.execute("INSERT INTO invoices (pdf_name, invoice_no) VALUES (?, ?)",
                      (filename, invoice_no))
            bill_id = c.lastrowid
            for key, value in row.items():
                if key not in ["Invoice No"]:
                    c.execute("INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)",
                              (bill_id, key, value))
    conn.commit()

    df = pd.DataFrame(extracted_data)
    excel_path = "extracted.xlsx"
    df.to_excel(excel_path, index=False)

    return jsonify({
        "data": extracted_data,
        "excel_path": excel_path,
        "uploaded_files": [file.filename for file in files]
    })

@app.route('/resize/<filename>')
def resize_pdf(filename):
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    width_cm = float(request.args.get('width', 10))
    height_cm = float(request.args.get('height', 15))
    is_preview = request.args.get('preview', 'true') == 'true'

    output_path = os.path.join(tempfile.gettempdir(), f"{filename}_preview.pdf") if is_preview else os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}_output.pdf")

    doc = fitz.open(input_path)
    output = fitz.open()
    a4_width, a4_height = 595, 842
    target_width = width_cm * 28.35
    target_height = height_cm * 28.35

    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        new_page = output.new_page(width=a4_width, height=a4_height)
        x0 = (a4_width - target_width) / 2
        y0 = 0
        x1 = x0 + target_width
        y1 = y0 + target_height
        new_page.insert_image([x0, y0, x1, y1], pixmap=pix)

    output.save(output_path)
    return redirect(f'/open_preview?path={output_path}')

@app.route('/open_preview')
def open_preview():
    path = request.args.get('path')
    return send_file(path, as_attachment=False)

@app.route('/save_selected', methods=['POST'])
def save_selected():
    rows = request.json.get('rows', [])
    for row in rows:
        invoice_no = row.get("Invoice No", "")
        pdf_name = row.get("AWB Number", "UNKNOWN_PDF")
        c.execute("INSERT INTO invoices (pdf_name, invoice_no) VALUES (?, ?)", (pdf_name, invoice_no))
        bill_id = c.lastrowid
        for key, value in row.items():
            if key not in ["Invoice No"]:
                c.execute("INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)",
                          (bill_id, key, value))
    conn.commit()
    return jsonify({"message": f"{len(rows)} row(s) saved to bill.db ✅"})

@app.route('/download')
def download_excel():
    return send_file("extracted.xlsx", as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)