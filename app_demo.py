
from flask import Flask, render_template, request, jsonify, send_file
import os
import webbrowser
from PyPDF2 import PdfMerger
import fitz  # PyMuPDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import cm
import re
import csv
from datetime import datetime
import pytz
import sqlite3
import random
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Constants
PAGE_WIDTH, PAGE_HEIGHT = A4
BLOCK_WIDTH = 7 * cm
BLOCK_HEIGHT = 2.5 * cm
NUM_BLOCKS = 36
short_messages = [
    "Feel good every day", "Comfort that empowers you", "Made to love yourself",
    "Softness meets strength", "Wear confidence daily", "Graceful, bold, beautiful you",
    "Power in every layer", "Comfort is self-love", "Love your shape always",
    "You deserve the best", "Unmatched softness, perfect fit", "Shine from within",
    "Beauty with comfort inside", "Feel relaxed, feel amazing", "Strong. Soft. You.",
    "Glow with inner peace", "Be bold. Be comfy.", "Confidence underneath everything",
    "Carefully crafted for you", "Support that hugs gently", "Celebrate your curves today",
    "Your comfort is our joy", "Confidence starts from inside", "Your style, your comfort",
    "Designed for every woman", "Beautiful inside and out", "Feel the loving softness",
    "Start your day with grace", "Pamper your beautiful self", "Elegance under every outfit",
    "Every layer loves you", "Every woman deserves this", "Wrap yourself in love",
    "Step into daily comfort", "You're always worth comfort", "Let your beauty shine"
]
SIZE_SETS = {
    "Panty": {"XS": "XS  | 75 cm | 28", "S": "S   | 80 cm | 30", "M": "M   | 85 cm | 32", "L": "L   | 90 cm | 34", "XL": "XL  | 95 cm | 36", "XXL": "XXL  | 100 cm | 38"},
    "Leggins": {"XS": "XS  | 75 cm | 28", "S": "S   | 80 cm | 30", "M": "M   | 85 cm | 32", "L": "L   | 90 cm | 34", "XL": "XL  | 95 cm | 36", "XXL": "XXL  | 100 cm | 38"},
    "Camisole": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34", "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"},
    "Bra": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34", "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"}
}
defaults = {"brand_text": "Collect Now", "website": "collectnow.in", "whatsapp": "7872427219", "border": "No"}

def init_db():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            product_type TEXT,
            size TEXT,
            color TEXT,
            sku TEXT,
            platform TEXT,
            quantity INTEGER,
            price REAL DEFAULT 21,
            datetime TEXT
        )
    ''')
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/merge')
def merge():
    return render_template('merge.html')

@app.route('/resize')
def resize():
    return render_template('resize.html')

@app.route('/extract')
def extract():
    return render_template('extract.html')

@app.route('/size_card')
def size_card():
    return render_template('size_card.html')

@app.route('/tape')
def tape():
    return render_template('tape.html')

@app.route('/inventory')
def inventory():
    return render_template('inventory.html')

@app.route('/api/merge_pdfs', methods=['POST'])
def merge_pdfs():
    if 'files' not in request.files:
        return jsonify({'error': 'No files provided'}), 400
    files = request.files.getlist('files')
    merger = PdfMerger()
    for file in files:
        if file and file.filename.endswith('.pdf'):
            merger.append(file)
    output_name = f"uploads/Merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    merger.write(output_name)
    merger.close()
    return jsonify({'file': output_name})

@app.route('/api/resize_pdf', methods=['POST'])
def resize_pdf():
    if 'file' not in request.files or not request.form.get('width') or not request.form.get('height'):
        return jsonify({'error': 'Missing file or dimensions'}), 400
    file = request.files['file']
    width_cm = float(request.form['width'])
    height_cm = float(request.form['height'])
    is_preview = request.form.get('preview') == 'true'
    if not file.filename.endswith('.pdf'):
        return jsonify({'error': 'Invalid file type'}), 400
    filename = secure_filename(file.filename)
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(input_path)
    base_name = os.path.splitext(filename)[0]
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_name}_{'preview' if is_preview else 'output'}.pdf")
    a4_width, a4_height = 595, 842
    target_width_pt = width_cm * 28.35
    target_height_pt = height_cm * 28.35
    doc = fitz.open(input_path)
    output = fitz.open()
    for page in doc:
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        new_page = output.new_page(width=a4_width, height=a4_height)
        x0 = (a4_width - target_width_pt) / 2
        y0 = 0
        x1 = x0 + target_width_pt
        y1 = y0 + target_height_pt
        new_page.insert_image([x0, y0, x1, y1], pixmap=pix)
    output.save(output_path)
    output.close()
    doc.close()
    return jsonify({'file': output_path})

@app.route('/api/extract_info', methods=['POST'])
def extract_info():
    if 'folder' not in request.form:
        return jsonify({'error': 'No folder provided'}), 400
    folder_path = request.form['folder']
    if not os.path.isdir(folder_path):
        return jsonify({'error': 'Invalid folder'}), 400
    india_time = datetime.now(pytz.timezone('Asia/Kolkata')).strftime("%Y%m%d_%H%M%S")
    output_csv = os.path.join(folder_path, f"output_{india_time}.csv")
    all_data = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            if filename.lower().endswith(".pdf"):
                pdf_path = os.path.join(root, filename)
                doc = fitz.open(pdf_path)
                for page_number, page in enumerate(doc, start=1):
                    text = page.get_text()
                    barcode_match = re.search(r'\b\d{15,}\b', text)
                    suborder_match = re.search(r'Purchase Order No\.\s*(\S+)', text)
                    courier_match = re.search(r'(Delhivery|Ekart|XpressBees|BlueDart|EcomExpress|Shadowfax)', text)
                    size_match = re.search(r'\b(\d{2,3}cm|XS|S|M|L|XL|XXL|3XL|4XL|5XL)\b', text)
                    qty_match = re.search(r'\bQty\b.*?(\d+)', text)
                    product_match = re.search(r'Description.*?\n(.*?)\n', text, re.DOTALL)
                    name_match = re.search(r'Customer Address\s*\n(.+?)\n', text, re.DOTALL)
                    state_match = re.search(r',\s*([A-Za-z ]+),\s*\d{6}', text)
                    barcode = "AWB " + barcode_match.group(0) if barcode_match else "NA"
                    suborder = "ORDER " + suborder_match.group(1) if suborder_match else "NA"
                    courier = courier_match.group(1) if courier_match else "NA"
                    size = size_match.group(1) if size_match else "NA"
                    qty = qty_match.group(1) if qty_match else "NA"
                    product = product_match.group(1).strip() if product_match else "NA"
                    name = name_match.group(1).strip() if name_match else "NA"
                    state = state_match.group(1).strip() if state_match else "NA"
                    all_data.append([f"{filename} (Page {page_number})", barcode, suborder, courier, size, qty, product, name, state])
    if not all_data:
        return jsonify({'error': 'No PDFs found'}), 400
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['File/Page', 'Barcode Number', 'Suborder ID', 'Courier Partner', 'Size', 'Quantity', 'Product', 'Customer Name', 'Customer State'])
        writer.writerows(all_data)
    return jsonify({'file': output_csv})

@app.route('/api/size_card', methods=['POST'])
def generate_size_card():
    data = request.form
    total = sum(int(data.get(f'size_{s}', 0)) for s in ['XS', 'S', 'M', 'L', 'XL', 'XXL'])
    if total != NUM_BLOCKS:
        return jsonify({'error': f"Total must be {NUM_BLOCKS}. You entered {total}."}), 400
    filename = f"Uploads/size_cards_{data['category'].lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    sizes = (
        [SIZE_SETS[data['category']]["XS"]] * int(data.get('size_XS', 0)) +
        [SIZE_SETS[data['category']]["S"]] * int(data.get('size_S', 0)) +
        [SIZE_SETS[data['category']]["M"]] * int(data.get('size_M', 0)) +
        [SIZE_SETS[data['category']]["L"]] * int(data.get('size_L', 0)) +
        [SIZE_SETS[data['category']]["XL"]] * int(data.get('size_XL', 0)) +
        [SIZE_SETS[data['category']]["XXL"]] * int(data.get('size_XXL', 0))
    )
    random.shuffle(sizes)
    c = canvas.Canvas(filename, pagesize=A4)
    width, height = A4
    cols, rows = 4, 9
    block_width = width / cols
    block_height = height / rows
    for i in range(NUM_BLOCKS):
        x = (i % cols) * block_width
        y = height - ((i // cols + 1) * block_height)
        center_x = x + block_width / 2
        top_y = y + block_height
        c.setStrokeColor(colors.lightpink)
        c.setLineWidth(1)
        c.rect(x + 4, y + 4, block_width - 8, block_height - 8, stroke=1, fill=0)
        for key in ['brand', 'category', 'size', 'message', 'thanks', 'url']:
            c.setFont(data[f'{key}_font'], int(data[f'{key}_size']))
            c.setFillColor(colors.HexColor(data[f'{key}_color']))
            text = data[f'{key}_text'] if key != 'category' else data['category']
            text = data[f'{key}_text'] or SIZE_SETS[data['category']]['S'] if key == 'size' else text
            if key == 'message':
                text = short_messages[i]
            y_offset = {'brand': top_y - 20, 'category': top_y - 35, 'size': top_y - 45, 'message': top_y - 60, 'thanks': y + 20, 'url': y + 8}
            c.drawCentredString(center_x, y_offset[key], text)
    c.save()
    return jsonify({'file': filename})

@app.route('/api/tape', methods=['POST'])
def generate_tape():
    data = request.form
    filename = f"Uploads/tape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    c = canvas.Canvas(filename, pagesize=A4)
    show_border = data['border_text'] == "Yes"
    block_count = 0
    while block_count < 36:
        cols = int(PAGE_WIDTH // BLOCK_WIDTH)
        rows = int(PAGE_HEIGHT // BLOCK_HEIGHT)
        for row in range(rows):
            for col in range(cols):
                if block_count >= 36:
                    break
                x = col * BLOCK_WIDTH
                y = PAGE_HEIGHT - (row + 1) * BLOCK_HEIGHT
                if show_border:
                    c.setStrokeColor(colors.HexColor(data['border_color']))
                    c.rect(x, y, BLOCK_WIDTH, BLOCK_HEIGHT)
                center_y = y + BLOCK_HEIGHT / 2 + 5
                for label in ["Brand Name", "Website", "Whatsapp"]:
                    c.setFont(data[f'{label}_font'], int(data[f'{label}_size']))
                    c.setFillColor(colors.HexColor(data[f'{label}_color']))
                    c.drawCentredString(x + BLOCK_WIDTH / 2, center_y + 8 if label == "Brand Name" else center_y - 4 if label == "Website" else center_y - 16, data[f'{label}_text'])
                block_count += 1
        if block_count < 36:
            c.showPage()
    c.save()
    return jsonify({'file': filename})

@app.route('/api/inventory', methods=['GET', 'POST', 'DELETE'])
def manage_inventory():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    if request.method == 'GET':
        c.execute("SELECT * FROM products")
        rows = c.fetchall()
        conn.close()
        return jsonify({'products': [{'id': r[0], 'name': r[1], 'type': r[2], 'size': r[3], 'color': r[4], 'sku': r[5], 'platform': r[6], 'quantity': r[7], 'price': r[8], 'datetime': r[9]} for r in rows]})
    elif request.method == 'POST':
        data = request.form
        name = data['name'].strip().lower()
        product_type = data['type'].strip()
        size = data['size'].strip().lower()
        color = data['color'].strip().lower() or "Multicolor"
        sku = data['sku'].strip()
        platform = data['platform'].strip()
        quantity = int(data['quantity'] or 0)
        price = float(data['price'] or 21)
        name = f"{name} - {size} - {color}"
        dt = datetime.now().isoformat()
        c.execute("SELECT id, quantity FROM products WHERE lower(name) = ? AND lower(size) = ? AND lower(color) = ?", (name, size, color))
        result = c.fetchone()
        if platform.lower() == 'supplier':
            if result:
                product_id, existing_qty = result
                new_qty = existing_qty + quantity
                c.execute("UPDATE products SET quantity = ?, price = ?, datetime = ?, sku = ?, platform = ?, product_type = ? WHERE id = ?",
                          (new_qty, price, dt, sku, platform, product_type, product_id))
            else:
                c.execute("INSERT INTO products (name, product_type, size, color, sku, platform, quantity, price, datetime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (name, product_type, size, color, sku, platform, quantity, price, dt))
        else:
            if result:
                product_id, existing_qty = result
                new_qty = max(existing_qty - quantity, 0)
                c.execute("UPDATE products SET quantity = ?, price = ?, datetime = ?, sku = ?, platform = ?, product_type = ? WHERE id = ?",
                          (new_qty, price, dt, sku, platform, product_type, product_id))
            else:
                c.execute("INSERT INTO products (name, product_type, size, color, sku, platform, quantity, price, datetime) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (name, product_type, size, color, sku, platform, -quantity, price, dt))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Product added/updated successfully'})
    elif request.method == 'DELETE':
        product_id = request.args.get('id')
        c.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Product deleted successfully'})

@app.route('/api/export_inventory', methods=['GET'])
def export_inventory():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute("SELECT * FROM products")
    rows = c.fetchall()
    conn.close()
    filename = f"Uploads/inventory_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(['ID', 'Name', 'Type', 'Size', 'Color', 'SKU', 'Platform', 'Quantity', 'Price', 'Datetime'])
        writer.writerows(rows)
    return jsonify({'file': filename})

@app.route('/uploads/<path:filename>')
def serve_file(filename):
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], filename))

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    init_db()
    #app.run(debug=True, port=8000)
    app.run(host='0.0.0.0', port=8000, debug=True)
