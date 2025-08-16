from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import sqlite3
from datetime import datetime
import uuid


import os
import fitz  # PyMuPDF
import pandas as pd
import re
import tempfile
from werkzeug.utils import secure_filename
import json

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from datetime import datetime
import random

from fpdf import FPDF
import qrcode
import tempfile
import io
import re

import webbrowser
import webview

from io import BytesIO

# Load config
with open('config.json') as f:
    config = json.load(f)

app = Flask(__name__)

# Use configs from JSON
UPLOAD_FOLDER = config.get("UPLOAD_FOLDER", "uploads")
DB_PATH = config.get("DB_PATH", "inventoryV4.db")

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.executescript('''
            CREATE TABLE IF NOT EXISTS categories (id TEXT PRIMARY KEY, name TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS types (id TEXT PRIMARY KEY, name TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS sizes (id TEXT PRIMARY KEY, name TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS suppliers (id TEXT PRIMARY KEY, name TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS purchases (
                id TEXT PRIMARY KEY, category_id TEXT, type_id TEXT, size_id TEXT, supplier_id TEXT,
                quantity INTEGER, price REAL, tax REAL, carry_cost REAL, extra_cost REAL, date TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (type_id) REFERENCES types(id),
                FOREIGN KEY (size_id) REFERENCES sizes(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            );
            CREATE TABLE IF NOT EXISTS ready_to_sale (
                id TEXT PRIMARY KEY, purchase_id TEXT, quantity INTEGER, date TEXT,
                FOREIGN KEY (purchase_id) REFERENCES purchases(id)
            );
            CREATE TABLE IF NOT EXISTS sales (
                id TEXT PRIMARY KEY, ready_to_sale_id TEXT, quantity INTEGER, date TEXT,
                FOREIGN KEY (ready_to_sale_id) REFERENCES ready_to_sale(id)
            );
            CREATE TABLE IF NOT EXISTS returns (
                id TEXT PRIMARY KEY, category_id TEXT, type_id TEXT, size_id TEXT, supplier_id TEXT,
                return_type TEXT, quantity INTEGER, add_to_stock INTEGER, loss_amount REAL, date TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (type_id) REFERENCES types(id),
                FOREIGN KEY (size_id) REFERENCES sizes(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            );
            CREATE TABLE IF NOT EXISTS invoices (
                bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_name TEXT,
                awb_number TEXT,
                invoice_no TEXT,
                order_id TEXT
            );
            CREATE TABLE IF NOT EXISTS invoice_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER,
                meta_key TEXT,
                meta_value TEXT,
                FOREIGN KEY (bill_id) REFERENCES invoices (bill_id)
            );
            CREATE TABLE IF NOT EXISTS sku_mappings (
                sku_id TEXT PRIMARY KEY,
                category_id TEXT,
                type_id TEXT,
                size_id TEXT,
                supplier_id TEXT,
                sku_name TEXT NOT NULL,
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (type_id) REFERENCES types(id),
                FOREIGN KEY (size_id) REFERENCES sizes(id),
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            );
            CREATE TABLE IF NOT EXISTS sales_log (
                sale_id TEXT PRIMARY KEY,
                awb_number TEXT,
                order_id TEXT,
                created_at TEXT,
                UNIQUE(awb_number, order_id)
            );
            CREATE TABLE IF NOT EXISTS order_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_order_no TEXT UNIQUE,
    order_date TEXT,
    dispatch_date TEXT,
    product_name TEXT,
    supplier_sku TEXT,
    order_status TEXT,
    product_gst_pct REAL,
    listing_price REAL,
    quantity INTEGER,
    transaction_id TEXT,
    payment_date TEXT,
    final_settlement_amount REAL,
    price_type TEXT,
    total_sale_amount REAL,
    total_sale_return_amount REAL,
    fixed_fee REAL,
    warehousing_fee REAL,
    return_premium REAL,
    return_premium_of_return REAL,
    meesho_commission_pct REAL,
    meesho_commission REAL,
    meesho_gold_platform_fee REAL,
    meesho_mall_platform_fee REAL,
    fixed_fee_1 REAL,
    warehousing_fee_1 REAL,
    return_shipping_charge REAL,
    gst_compensation REAL,
    shipping_charge REAL,
    other_support_service_charges REAL,
    waivers REAL,
    net_other_support_service_charges REAL,
    gst_on_net_other_support_service_charges REAL,
    tcs REAL,
    tds_rate_pct REAL,
    tds REAL,
    compensation REAL,
    claims REAL,
    recovery REAL,
    compensation_reason TEXT,
    claims_reason TEXT,
    recovery_reason TEXT
);

            CREATE TABLE IF NOT EXISTS order_payment_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER,
                meta_key TEXT,
                meta_value TEXT,
                FOREIGN KEY (payment_id) REFERENCES order_payments (id)
            );
        ''')
        default_data = {
            'categories': ['Bra', 'Panty', 'Camisole', 'Nighty'],
            'types': ['Bad', 'Average', 'Good', 'Premium'],
            'sizes': ['XS | 75 cm | 30', 'S | 80 cm | 32', 'M | 85 cm | 34', 'L | 90 cm | 36', 
                     'XL | 95 cm | 38', 'XXL | 100 cm | 40'],
            'suppliers': ['Bhola', 'JTM', 'JMD', 'SUMON', 'SUVRO']
        }
        for table, names in default_data.items():
            for name in names:
                c.execute(f"INSERT OR IGNORE INTO {table} (id, name) VALUES (?, ?)", 
                         (str(uuid.uuid4()), name))
        conn.commit()


def extract_all_invoices(text):
    entries = re.split(r'(?=Customer Address)', text)
    return [entry.strip() for entry in entries if len(entry.strip()) > 50]

def extract_field(text, pattern, group=1):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(group).strip() if match else "NA"

def extract_product_name(text):
    lines = text.splitlines()
    print("Lines =====================>" ,lines)
    # Define keyword groups and normalized values
    keyword_map = {
        'camisole': ['camisole', 'camisoles', 'Camisole', 'camisoles'],
        'panty': ['panty', 'briefs', 'Panty'],
        'nighty': ['nighty', 'Nighty'],
    }

    for i, line in enumerate(lines):
        # if re.search(r'Description\s+HSN\s+Qty', line, re.IGNORECASE):
            if i + 1 < len(lines):
                name_line = lines[i + 1].strip().lower()

                for normalized, variants in keyword_map.items():
                    for keyword in variants:
                        if keyword.lower() in name_line:
                            return normalized
    return "NA"



def extract_qty(text):
    match = re.search(r'HSN\s+\d+\s+(\d+)', text)
    return match.group(1) if match else "NA"



def extract_data_from_invoice(text):
    return {
        "Product Name": extract_product_name(text),
        "Pack Of": extract_field(text, r'Pack of\s*(\d+)'),
        "Customer Name": extract_field(text, r'Customer Address\s*\n(.+?)\n'),
        "Courier Partner": extract_field(text, r'(Delhivery|Ekart|XpressBees|BlueDart|EcomExpress|Shadowfax|Valmo)'),
        "AWB Number": extract_field(text, r'\b(\d{15,})\b'),
        "Payment Type": extract_field(text, r'(COD|Prepaid: Do not collect cash)'),
        "Order ID": extract_field(text, r'Purchase Order No\.\s*(\S+)'),
        "Invoice No": extract_field(text, r'Invoice No\.\s*(\S+)'),
        "Order Date": extract_field(text, r'Order Date\s*(\d{2}[./-]\d{2}[./-]\d{4})'),
        "Invoice Date": extract_field(text, r'Invoice Date\s*(\d{2}[./-]\d{2}[./-]\d{4})'),
        "Product Description": extract_field(text, r'Description.*?\n(.*?)\n', group=1),
        "Size": extract_field(text, r'\b(\d{2,3}cm|XS|S|M|L|XL|XXL|3XL|4XL|5XL)\b'),
        "Qty": extract_qty(text),
        "SKU": extract_field(text, r'SKU\s+Size\s+Qty.*?\n(\w+)'),
        "HSN Code": extract_field(text, r'HSN\s*(\d+)'),
        "Gross Amount": extract_field(text, r'Gross Amount\s+(Rs\.\d+\.\d{2})'),
        "Discount": extract_field(text, r'Discount\s+(Rs\.\d+\.\d{2})'),
        "Taxable Value": extract_field(text, r'Taxable Value\s+(Rs\.\d+\.\d{2})'),
        "Taxes": extract_field(text, r'Taxes.*?\n.*?(Rs\.\d+\.\d{2})'),
        "Other Charges": extract_field(text, r'Other Charges.*?\n.*?(Rs\.\d+\.\d{2})'),
        "Total Amount": extract_field(text, r'Total\s+(Rs\.\d+\.\d{2})'),
        "State": extract_field(text, r',\s*([A-Za-z ]+),\s*\d{6}'),
        
    }

def extract_data_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    full_text = "\n".join([page.get_text() for page in doc])
    invoices = extract_all_invoices(full_text)
    return [extract_data_from_invoice(inv) for inv in invoices]

@app.route('/InvoicePayment')
def InvoicePayment():
    return render_template('invoices.html')

@app.route('/Payment')
def Payment():
    return render_template('payment.html')

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/raw_sql', methods=['POST'])
def execute_raw_sql():
    data = request.json
    query = data.get('query')
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(query)
            conn.commit()
            return jsonify({'message': 'Query executed'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400



@app.route('/api/<table>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_table(table):
    print("------------------------------------1")
    if table not in ['categories', 'types', 'sizes', 'suppliers']:
        return jsonify({'error': 'Invalid table'}), 400
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute(f'SELECT id, name FROM {table}')
            return jsonify([{'id': row[0], 'name': row[1]} for row in c.fetchall()])
        
        if request.method == 'POST':
            data = request.json
            c.execute(f'SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?)', (data['name'],))
            if c.fetchone():
                return jsonify({'error': f'{table[:-1]} exists'}), 400
            c.execute(f'INSERT INTO {table} (id, name) VALUES (?, ?)', 
                     (str(uuid.uuid4()), data['name']))
            conn.commit()
            return jsonify({'message': f'{table[:-1]} added'})

        if request.method == 'PUT':
            data = request.json
            c.execute(f'SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?) AND id != ?', 
                     (data['name'], data['id']))
            if c.fetchone():
                return jsonify({'error': f'{table[:-1]} exists'}), 400
            c.execute(f'UPDATE {table} SET name = ? WHERE id = ?', 
                     (data['name'], data['id']))
            conn.commit()
            return jsonify({'message': f'{table[:-1]} updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute(f'SELECT 1 FROM purchases WHERE {table[:-1]}_id = ?', (data['id'],))
            c.execute(f'SELECT 1 FROM returns WHERE {table[:-1]}_id = ?', (data['id'],))
            if c.fetchone():
                return jsonify({'error': f'Cannot delete {table[:-1]} in use'}), 400
            c.execute(f'DELETE FROM {table} WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': f'{table[:-1]} deleted'})
        
@app.route('/api/categories', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_categories():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        if request.method == 'GET':
            c.execute('SELECT id, name FROM categories')  # Fixed
            return jsonify([{
                'id': row[0], 'name': row[1]
            } for row in c.fetchall()])

        if request.method == 'POST':
            data = request.json
            c.execute('INSERT INTO categories (id, name, active) VALUES (?, ?, ?)',
                      (str(uuid.uuid4()), data['name'], 1))
            conn.commit()
            return jsonify({'message': 'Category added'})

        if request.method == 'PUT':
            data = request.json
            c.execute('UPDATE categories SET active = ? WHERE id = ?', (data['active'], data['id']))
            conn.commit()
            return jsonify({'message': 'Category status updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('SELECT 1 FROM purchases WHERE category_id = ?', (data['id'],))
            if c.fetchone():
                return jsonify({'error': 'Category is in use and cannot be deleted'}), 400

            c.execute('DELETE FROM categories WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': 'Category deleted'})


@app.route('/api/<table>/merge', methods=['POST'])
def merge_table(table):
    print("------------------------------------2")
    
    if table not in ['categories', 'types', 'sizes', 'suppliers']:
        return jsonify({'error': 'Invalid table'}), 400
    data = request.json
    keep_id, merge_id = data['keep_id'], data['merge_id']
    if keep_id == merge_id:
        return jsonify({'error': 'Cannot merge same item'}), 400
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(f'SELECT 1 FROM {table} WHERE id = ?', (keep_id,))
        if not c.fetchone():
            return jsonify({'error': f'Keep {table[:-1]} not found'}), 400
        c.execute(f'SELECT 1 FROM {table} WHERE id = ?', (merge_id,))
        if not c.fetchone():
            return jsonify({'error': f'Merge {table[:-1]} not found'}), 400
        c.execute(f'UPDATE purchases SET {table[:-1]}_id = ? WHERE {table[:-1]}_id = ?', 
                 (keep_id, merge_id))
        c.execute(f'UPDATE returns SET {table[:-1]}_id = ? WHERE {table[:-1]}_id = ?', 
                 (keep_id, merge_id))
        c.execute(f'DELETE FROM {table} WHERE id = ?', (merge_id,))
        conn.commit()
        return jsonify({'message': f'{table[:-1]} merged'})

@app.route('/api/purchases', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_purchases():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute('''
                SELECT 
                    p.id, c.name, t.name, s.name, su.name, 
                    p.quantity, p.price, p.tax, p.carry_cost, p.extra_cost, p.date,
                    COALESCE(rts.total_ready, 0) AS ready_quantity,
                    COALESCE(s.total_sold, 0) AS sold_quantity
                FROM purchases p
                JOIN categories c ON p.category_id = c.id
                JOIN types t ON p.type_id = t.id
                JOIN sizes s ON p.size_id = s.id
                JOIN suppliers su ON p.supplier_id = su.id
                LEFT JOIN (
                    SELECT purchase_id, SUM(quantity) AS total_ready
                    FROM ready_to_sale
                    GROUP BY purchase_id
                ) rts ON p.id = rts.purchase_id
                LEFT JOIN (
                    SELECT r.purchase_id, SUM(s.quantity) AS total_sold
                    FROM sales s
                    JOIN ready_to_sale r ON s.ready_to_sale_id = r.id
                    GROUP BY r.purchase_id
                ) s ON p.id = s.purchase_id
            ''')
            return jsonify([dict(zip([
                'id', 'category', 'type', 'size', 'supplier', 'quantity', 
                'price', 'tax', 'carry_cost', 'extra_cost', 'date',
                'ready_quantity', 'sold_quantity'
            ], row)) for row in c.fetchall()])

        
        if request.method == 'POST':
            data = request.json
            c.execute('''
                INSERT INTO purchases (id, category_id, type_id, size_id, supplier_id, 
                    quantity, price, tax, carry_cost, extra_cost, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(uuid.uuid4()), data['category_id'], data['type_id'], data['size_id'], 
                  data['supplier_id'], data['quantity'], data.get('price', 0), 
                  data.get('tax', 0), data.get('carry_cost', 0), data.get('extra_cost', 0), 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            return jsonify({'message': 'Purchase added'})

        if request.method == 'PUT':
            data = request.json
            c.execute('SELECT COALESCE(SUM(r.quantity), 0) FROM ready_to_sale r WHERE purchase_id = ?', 
                     (data['id'],))
            ready_qty = c.fetchone()[0]
            if data['quantity'] < ready_qty:
                return jsonify({'error': 'Quantity below ready to sale'}), 400
            c.execute('''
                UPDATE purchases SET category_id = ?, type_id = ?, size_id = ?, supplier_id = ?, 
                    quantity = ?, price = ?, tax = ?, carry_cost = ?, extra_cost = ?, date = ?
                WHERE id = ?
            ''', (data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], 
                  data['quantity'], data.get('price', 0), data.get('tax', 0), 
                  data.get('carry_cost', 0), data.get('extra_cost', 0), 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
            conn.commit()
            return jsonify({'message': 'Purchase updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('SELECT 1 FROM ready_to_sale WHERE purchase_id = ?', (data['id'],))
            if c.fetchone():
                return jsonify({'error': 'Purchase in use'}), 400
            c.execute('DELETE FROM purchases WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': 'Purchase deleted'})





@app.route('/api/returns', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_returns():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute('''
                SELECT r.id, c.name, t.name, s.name, su.name, r.return_type, r.quantity, 
                       r.add_to_stock, r.loss_amount, r.date
                FROM returns r
                JOIN categories c ON r.category_id = c.id
                JOIN types t ON r.type_id = t.id
                JOIN sizes s ON r.size_id = s.id
                JOIN suppliers su ON r.supplier_id = su.id
            ''')
            return jsonify([dict(zip(['id', 'category', 'type', 'size', 'supplier', 'return_type', 
                                    'quantity', 'add_to_stock', 'loss_amount', 'date'], row)) 
                           for row in c.fetchall()])
        
        if request.method == 'POST':
            data = request.json
            c.execute('''
                INSERT INTO returns (id, category_id, type_id, size_id, supplier_id, 
                    return_type, quantity, add_to_stock, loss_amount, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (str(uuid.uuid4()), data['category_id'], data['type_id'], data['size_id'], 
                  data['supplier_id'], data['return_type'], data['quantity'], 
                  data.get('add_to_stock', 1), data.get('loss_amount', 0), 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            return jsonify({'message': 'Return added'})

        if request.method == 'PUT':
            data = request.json
            c.execute('''
                UPDATE returns SET category_id = ?, type_id = ?, size_id = ?, supplier_id = ?, 
                    return_type = ?, quantity = ?, add_to_stock = ?, loss_amount = ?, date = ?
                WHERE id = ?
            ''', (data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], 
                  data['return_type'], data['quantity'], data.get('add_to_stock', 1), 
                  data.get('loss_amount', 0), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                  data['id']))
            conn.commit()
            return jsonify({'message': 'Return updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('DELETE FROM returns WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': 'Return deleted'})
        
        
@app.route('/api/ready_to_sale', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_ready_to_sale():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        if request.method == 'GET':
            c.execute('''
                SELECT 
                    r.id, 
                    p.id, 
                    c.name, 
                    t.name, 
                    s.name, 
                    su.name, 
                    r.quantity, 
                    COALESCE((
                        SELECT SUM(sa.quantity)
                        FROM sales sa
                        WHERE sa.ready_to_sale_id = r.id
                    ), 0) as sold,
                    r.date
                FROM ready_to_sale r
                JOIN purchases p ON r.purchase_id = p.id
                JOIN categories c ON p.category_id = c.id
                JOIN types t ON p.type_id = t.id
                JOIN sizes s ON p.size_id = s.id
                JOIN suppliers su ON p.supplier_id = su.id
                WHERE r.quantity > COALESCE((
                        SELECT SUM(sa.quantity)
                        FROM sales sa
                        WHERE sa.ready_to_sale_id = r.id
                    ), 0)
            ''')
            return jsonify([{
                'id': row[0],
                'purchase_id': row[1],
                'category': row[2],
                'type': row[3],
                'size': row[4],
                'supplier': row[5],
                'quantity': row[6],
                'sold': row[7],
                'date': row[8]
            } for row in c.fetchall()])

        if request.method == 'POST':
            data = request.json
            c.execute('''
                SELECT p.quantity, COALESCE(SUM(r.quantity), 0), 
                       COALESCE(SUM(CASE WHEN ret.add_to_stock = 1 THEN ret.quantity ELSE 0 END), 0)
                FROM purchases p
                LEFT JOIN ready_to_sale r ON r.purchase_id = p.id
                LEFT JOIN returns ret ON ret.category_id = p.category_id 
                    AND ret.type_id = p.type_id 
                    AND ret.size_id = p.size_id 
                    AND ret.supplier_id = p.supplier_id
                WHERE p.id = ?
                GROUP BY p.id
            ''', (data['purchase_id'],))
            purchase = c.fetchone()
            print("purchase=========>",purchase)
            if not purchase:
                return jsonify({'error': 'Invalid purchase_id'}), 400
            available = purchase[0]  #+ purchase[2] - purchase[1]
            print("available================>",available)
            if data['quantity'] > available:
                return jsonify({'error': 'Quantity exceeds available'}), 400
            c.execute('''
                INSERT INTO ready_to_sale (id, purchase_id, quantity, date)
                VALUES (?, ?, ?, ?)
            ''', (str(uuid.uuid4()), data['purchase_id'], data['quantity'], 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            return jsonify({'message': 'Added to ready to sale'})

        if request.method == 'PUT':
            data = request.json
            c.execute('''
                SELECT p.quantity, COALESCE(SUM(r.quantity), 0), COALESCE(SUM(s.quantity), 0),
                       COALESCE(SUM(CASE WHEN ret.add_to_stock = 1 THEN ret.quantity ELSE 0 END), 0)
                FROM ready_to_sale r
                JOIN purchases p ON r.purchase_id = p.id
                LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                LEFT JOIN returns ret ON ret.category_id = p.category_id 
                    AND ret.type_id = p.type_id 
                    AND ret.size_id = p.size_id 
                    AND ret.supplier_id = p.supplier_id
                WHERE r.id = ?
                GROUP BY p.id
            ''', (data['id'],))
            result = c.fetchone()
            if not result:
                return jsonify({'error': 'Invalid ready_to_sale_id'}), 400
            available = result[0] + result[3] - result[1]
            if data['quantity'] > available:
                return jsonify({'error': 'Quantity exceeds available'}), 400
            if data['quantity'] < result[2]:
                return jsonify({'error': 'Quantity below sold'}), 400
            c.execute('''
                UPDATE ready_to_sale SET quantity = ?, date = ? WHERE id = ?
            ''', (data['quantity'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
            conn.commit()
            return jsonify({'message': 'Ready to sale updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('SELECT 1 FROM sales WHERE ready_to_sale_id = ?', (data['id'],))
            if c.fetchone():
                return jsonify({'error': 'Ready to sale in use'}), 400
            c.execute('DELETE FROM ready_to_sale WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': 'Ready to sale deleted'})

@app.route('/api/ready_to_sale_summary', methods=['GET'])
def ready_to_sale_summary():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute('''
            SELECT 
                rts.id,
                rts.purchase_id,
                c.name AS category,
                t.name AS type,
                sz.name AS size,
                su.name AS supplier,
                rts.quantity AS ready_quantity,
                COALESCE((
                    SELECT SUM(s.quantity) 
                    FROM sales s 
                    WHERE s.ready_to_sale_id = rts.id
                ), 0) AS already_sold,
                rts.date
            FROM ready_to_sale rts
            JOIN purchases p ON rts.purchase_id = p.id
            JOIN categories c ON p.category_id = c.id
            JOIN types t ON p.type_id = t.id
            JOIN sizes sz ON p.size_id = sz.id
            JOIN suppliers su ON p.supplier_id = su.id
        ''')

        result = []
        for row in c.fetchall():
            ready_quantity = row[6]
            already_sold = row[7]
            remain_to_be_sold = ready_quantity - already_sold

            result.append({
                'id': row[0],
                'purchase_id': row[1],
                'category': row[2],
                'type': row[3],
                'size': row[4],
                'supplier': row[5],
                'ready_quantity': ready_quantity,
                'already_sold': already_sold,
                'remain_to_be_sold': remain_to_be_sold,
                'date': row[8]
            })

        return jsonify(result)



@app.route('/api/sales', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_sales():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute('''
                SELECT sa.id, r.id, p.id, c.name, t.name, s.name, su.name, sa.quantity, sa.date
                FROM sales sa
                JOIN ready_to_sale r ON sa.ready_to_sale_id = r.id
                JOIN purchases p ON r.purchase_id = p.id
                JOIN categories c ON p.category_id = c.id
                JOIN types t ON p.type_id = t.id
                JOIN sizes s ON p.size_id = s.id
                JOIN suppliers su ON p.supplier_id = su.id
            ''')

            return jsonify([dict(zip([
                'id', 'ready_id', 'purchase_id', 'category', 'type', 'size', 'supplier', 'quantity', 'date'
            ], row)) for row in c.fetchall()])

        if request.method == 'POST':
            data = request.json
            c.execute('''
                SELECT r.quantity, COALESCE(SUM(s.quantity), 0)
                FROM ready_to_sale r
                LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                WHERE r.id = ?
                GROUP BY r.id
            ''', (data['ready_to_sale_id'],))
            ready = c.fetchone()
            if not ready:
                return jsonify({'error': 'Invalid ready_to_sale_id'}), 400
            if data['quantity'] > ready[0] - ready[1]:
                return jsonify({'error': 'Quantity exceeds available'}), 400
            c.execute('''
                INSERT INTO sales (id, ready_to_sale_id, quantity, date)
                VALUES (?, ?, ?, ?)
            ''', (str(uuid.uuid4()), data['ready_to_sale_id'], data['quantity'], 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            return jsonify({'message': 'Sale recorded'})

        if request.method == 'PUT':
            data = request.json
            c.execute('''
                SELECT r.quantity, COALESCE(SUM(s.quantity), 0)
                FROM ready_to_sale r
                LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                WHERE r.id = (SELECT ready_to_sale_id FROM sales WHERE id = ?)
                GROUP BY r.id
            ''', (data['id'],))
            ready = c.fetchone()
            if not ready:
                return jsonify({'error': 'Invalid sale_id'}), 400
            if data['quantity'] > ready[0] - ready[1]:
                return jsonify({'error': 'Quantity exceeds available'}), 400
            c.execute('''
                UPDATE sales SET quantity = ?, date = ? WHERE id = ?
            ''', (data['quantity'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
            conn.commit()
            return jsonify({'message': 'Sale updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('DELETE FROM sales WHERE id = ?', (data['id'],))
            conn.commit()
            return jsonify({'message': 'Sale deleted'})


@app.route('/api/sales_sku_summary', methods=['GET'])
def sales_sku_summary():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                c.name AS category,
                t.name AS type,
                s.name AS size,
                su.name AS supplier,
                SUM(sa.quantity) AS total_sold
            FROM sales sa
            JOIN ready_to_sale rts ON sa.ready_to_sale_id = rts.id
            JOIN purchases p ON rts.purchase_id = p.id
            JOIN categories c ON p.category_id = c.id
            JOIN types t ON p.type_id = t.id
            JOIN sizes s ON p.size_id = s.id
            JOIN suppliers su ON p.supplier_id = su.id
            GROUP BY c.id, t.id, s.id, su.id
        ''')
        return jsonify([
            dict(zip(['category', 'type', 'size', 'supplier', 'total_sold'], row))
            for row in c.fetchall()
        ])


@app.route('/api/inventory_summary', methods=['GET'])
def inventory_summary():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                c.name, t.name, sz.name, su.name,
                COALESCE(SUM(p.quantity), 0),
                COALESCE(SUM(CASE WHEN r.add_to_stock = 1 THEN r.quantity ELSE 0 END), 0),
                COALESCE(SUM(rts.quantity), 0),
                COALESCE(SUM(s.quantity), 0)
            FROM categories c
            CROSS JOIN types t
            CROSS JOIN sizes sz
            CROSS JOIN suppliers su
            LEFT JOIN purchases p 
                ON p.category_id = c.id AND p.type_id = t.id 
                AND p.size_id = sz.id AND p.supplier_id = su.id
            LEFT JOIN returns r 
                ON r.category_id = c.id AND r.type_id = t.id 
                AND r.size_id = sz.id AND r.supplier_id = su.id
            LEFT JOIN ready_to_sale rts 
                ON rts.purchase_id IN (SELECT id FROM purchases 
                                      WHERE category_id = c.id AND type_id = t.id 
                                      AND size_id = sz.id AND supplier_id = su.id)
            LEFT JOIN sales s ON s.ready_to_sale_id = rts.id
            GROUP BY c.name, t.name, sz.name, su.name
            HAVING COALESCE(SUM(p.quantity), 0) > 0 
                OR COALESCE(SUM(r.quantity), 0) > 0 
                OR COALESCE(SUM(rts.quantity), 0) > 0 
                OR COALESCE(SUM(s.quantity), 0) > 0
        ''')
        return jsonify([{
            'category': row[0], 'type': row[1], 'size': row[2], 'supplier': row[3],
            'purchase_qty': row[4], 'return_qty': row[5], 'ready_to_sale_stock': row[6],
            'sale_qty': row[7], 'added_stock': row[4] + row[5],
            'actual_inventory': row[4] + row[5] - row[7],
            'temporary_inventory': row[6] - row[7],
            'warehouse_stock': row[4] + row[5] - row[6]
        } for row in c.fetchall()])

@app.route('/api/report', methods=['GET'])
def get_report():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                sku.category,
                sku.type,
                sku.size,
                sku.supplier,
                COALESCE(p.total_purchase, 0),
                COALESCE(r.total_return, 0),
                COALESCE(rts.total_ready, 0),
                COALESCE(s.total_sale, 0)
            FROM (
                SELECT 
                    c.id AS category_id, c.name AS category,
                    t.id AS type_id, t.name AS type,
                    sz.id AS size_id, sz.name AS size,
                    su.id AS supplier_id, su.name AS supplier
                FROM purchases p
                JOIN categories c ON p.category_id = c.id
                JOIN types t ON p.type_id = t.id
                JOIN sizes sz ON p.size_id = sz.id
                JOIN suppliers su ON p.supplier_id = su.id
                GROUP BY c.id, t.id, sz.id, su.id
            ) sku
            LEFT JOIN (
                SELECT category_id, type_id, size_id, supplier_id, SUM(quantity) AS total_purchase
                FROM purchases
                GROUP BY category_id, type_id, size_id, supplier_id
            ) p ON p.category_id = sku.category_id AND p.type_id = sku.type_id AND p.size_id = sku.size_id AND p.supplier_id = sku.supplier_id

            LEFT JOIN (
                SELECT category_id, type_id, size_id, supplier_id, SUM(quantity) AS total_return
                FROM returns
                WHERE add_to_stock = 1
                GROUP BY category_id, type_id, size_id, supplier_id
            ) r ON r.category_id = sku.category_id AND r.type_id = sku.type_id AND r.size_id = sku.size_id AND r.supplier_id = sku.supplier_id

            LEFT JOIN (
                SELECT p.category_id, p.type_id, p.size_id, p.supplier_id, SUM(rts.quantity) AS total_ready
                FROM ready_to_sale rts
                JOIN purchases p ON rts.purchase_id = p.id
                GROUP BY p.category_id, p.type_id, p.size_id, p.supplier_id
            ) rts ON rts.category_id = sku.category_id AND rts.type_id = sku.type_id AND rts.size_id = sku.size_id AND rts.supplier_id = sku.supplier_id

            LEFT JOIN (
                SELECT p.category_id, p.type_id, p.size_id, p.supplier_id, SUM(s.quantity) AS total_sale
                FROM sales s
                JOIN ready_to_sale rts ON s.ready_to_sale_id = rts.id
                JOIN purchases p ON rts.purchase_id = p.id
                GROUP BY p.category_id, p.type_id, p.size_id, p.supplier_id
            ) s ON s.category_id = sku.category_id AND s.type_id = sku.type_id AND s.size_id = sku.size_id AND s.supplier_id = sku.supplier_id


        ''')
        return jsonify([{
            'category': row[0], 'type': row[1], 'size': row[2], 'supplier': row[3],
            'total_purchase': row[4], 'total_return': row[5], 'total_ready': row[6],
            'total_sale': row[7], 'added_stock': row[4] + row[5],
            'actual_inventory': row[4] + row[5] - row[7],
            'temporary_inventory': row[6] - row[7],
            'warehouse_stock': row[4] + row[5] - row[6]
        } for row in c.fetchall()])


@app.route('/debug/purchases')
def debug_purchases():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, category_id, type_id, size_id, supplier_id, quantity, date FROM purchases")
        return jsonify(c.fetchall())
    
@app.route('/debug/ready_to_sale', methods=['GET'])
def debug_ready_to_sale():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                r.id AS ready_id,
                p.id AS purchase_id,
                c.name AS category,
                t.name AS type,
                s.name AS size,
                su.name AS supplier,
                r.quantity AS ready_qty,
                r.date AS ready_date
            FROM ready_to_sale r
            JOIN purchases p ON r.purchase_id = p.id
            JOIN categories c ON p.category_id = c.id
            JOIN types t ON p.type_id = t.id
            JOIN sizes s ON p.size_id = s.id
            JOIN suppliers su ON p.supplier_id = su.id
            ORDER BY r.date DESC
        ''')
        results = c.fetchall()
        return jsonify([
            {
                'ready_to_sale_id': row[0],
                'purchase_id': row[1],
                'category': row[2],
                'type': row[3],
                'size': row[4],
                'supplier': row[5],
                'ready_quantity': row[6],
                'ready_date': row[7]
            }
            for row in results
        ])


#################################### RETURN MANAGE START
@app.route('/api/returns_to_ready_to_sale', methods=['POST'])
def returns_to_ready_to_sale():
    data = request.json
    return_id = data.get('return_id')
    quantity = data.get('quantity')
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT r.quantity, r.category_id, r.type_id, r.size_id, r.supplier_id
            FROM returns r
            WHERE r.id = ? AND r.add_to_stock = 1
        ''', (return_id,))
        return_data = c.fetchone()
        
        if not return_data:
            return jsonify({'error': 'Invalid return_id or not marked for stock'}), 400
            
        return_qty, category_id, type_id, size_id, supplier_id = return_data
        
        if quantity > return_qty:
            return jsonify({'error': 'Quantity exceeds available return'}), 400
            
        c.execute('''
            SELECT id, quantity, COALESCE(SUM(rts.quantity), 0) as ready_qty
            FROM purchases p
            LEFT JOIN ready_to_sale rts ON rts.purchase_id = p.id
            WHERE p.category_id = ? AND p.type_id = ? AND p.size_id = ? AND p.supplier_id = ?
            GROUP BY p.id
            HAVING p.quantity + ? - ready_qty >= ?
        ''', (category_id, type_id, size_id, supplier_id, return_qty, quantity))
        purchase = c.fetchone()
        
        if not purchase:
            return jsonify({'error': 'No matching purchase found or insufficient stock'}), 400
            
        purchase_id, purchase_qty, ready_qty = purchase
        available = purchase_qty + return_qty - ready_qty
        
        if quantity > available:
            return jsonify({'error': 'Quantity exceeds available stock'}), 400
            
        ready_id = str(uuid.uuid4())  # Fixed: uuid4() to uuid.uuid4()
        c.execute('''
            INSERT INTO ready_to_sale (id, purchase_id, quantity, date)
            VALUES (?, ?, ?, ?)
        ''', (ready_id, purchase_id, quantity, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        c.execute('UPDATE returns SET quantity = quantity - ? WHERE id = ?', 
                 (quantity, return_id))
        
        conn.commit()
        return jsonify({'message': 'Added to ready to sale from return', 'ready_to_sale_id': ready_id})

@app.route('/api/returns_to_sale', methods=['POST'])
def returns_to_sale():
    data = request.json
    return_id = data.get('return_id')
    quantity = data.get('quantity')
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT r.quantity, r.category_id, r.type_id, r.size_id, r.supplier_id
            FROM returns r
            WHERE r.id = ? AND r.add_to_stock = 1
        ''', (return_id,))
        return_data = c.fetchone()
        
        if not return_data:
            return jsonify({'error': 'Invalid return_id or not marked for stock'}), 400
            
        return_qty, category_id, type_id, size_id, supplier_id = return_data
        
        if quantity > return_qty:
            return jsonify({'error': 'Quantity exceeds available return'}), 400
            
        c.execute('''
            SELECT p.id, p.quantity, COALESCE(SUM(rts.quantity), 0) as ready_qty
            FROM purchases p
            LEFT JOIN ready_to_sale rts ON rts.purchase_id = p.id
            WHERE p.category_id = ? AND p.type_id = ? AND p.size_id = ? AND p.supplier_id = ?
            GROUP BY p.id
            HAVING p.quantity + ? - ready_qty >= ?
        ''', (category_id, type_id, size_id, supplier_id, return_qty, quantity))
        purchase = c.fetchone()
        
        if not purchase:
            return jsonify({'error': 'No matching purchase found or insufficient stock'}), 400
            
        purchase_id, purchase_qty, ready_qty = purchase
        available = purchase_qty + return_qty - ready_qty
        
        if quantity > available:
            return jsonify({'error': 'Quantity exceeds available stock'}), 400
            
        ready_id = str(uuid.uuid4())  # Fixed: uuid4() to uuid.uuid4()
        c.execute('''
            INSERT INTO ready_to_sale (id, purchase_id, quantity, date)
            VALUES (?, ?, ?, ?)
        ''', (ready_id, purchase_id, quantity, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        sale_id = str(uuid.uuid4())  # Fixed: uuid4() to uuid.uuid4()
        c.execute('''
            INSERT INTO sales (id, ready_to_sale_id, quantity, date)
            VALUES (?, ?, ?, ?)
        ''', (sale_id, ready_id, quantity, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        c.execute('UPDATE returns SET quantity = quantity - ? WHERE id = ?', 
                 (quantity, return_id))
        
        conn.commit()
        return jsonify({'message': 'Sale recorded from return', 'sale_id': sale_id})

@app.route('/api/returns_report', methods=['GET'])
def returns_report():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                c.name AS category,
                t.name AS type,
                sz.name AS size,
                su.name AS supplier,
                r.return_type,
                r.quantity AS return_quantity,
                r.add_to_stock,
                r.loss_amount,
                r.date
            FROM returns r
            JOIN categories c ON r.category_id = c.id
            JOIN types t ON r.type_id = t.id
            JOIN sizes sz ON r.size_id = sz.id
            JOIN suppliers su ON r.supplier_id = su.id
        ''')
        return jsonify([
            {
                'category': row[0], 'type': row[1], 'size': row[2], 'supplier': row[3],
                'return_type': row[4], 'return_quantity': row[5], 'add_to_stock': row[6],
                'loss_amount': row[7], 'date': row[8]
            } for row in c.fetchall()
        ])
        
################################## RETURN MANAGE END


@app.route('/api/truncate_database', methods=['POST'])
def truncate_database():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('PRAGMA foreign_keys = OFF')
        for table in ['sales', 'ready_to_sale', 'returns', 'purchases', 'categories', 'types', 'sizes', 'suppliers']:
            c.execute(f'DELETE FROM {table}')
        c.execute('PRAGMA foreign_keys = ON')
        init_db()
        return jsonify({'message': 'Database truncated'})


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

    #     for row in rows:
    #         invoice_no = row.get("Invoice No", "")
    #         c.execute("INSERT INTO invoices (pdf_name, invoice_no) VALUES (?, ?)",
    #                   (filename, invoice_no))
    #         bill_id = c.lastrowid
    #         for key, value in row.items():
    #             if key not in ["Invoice No"]:
    #                 c.execute("INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)",
    #                           (bill_id, key, value))
    # conn.commit()

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

@app.route('/api/save_selected/savexls', methods=['POST'])
def save_selected():
    print("-------------ready")
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")  # Allow concurrent access
        c = conn.cursor()
        # DROP TABLE IF EXISTS invoices;
        c.executescript('''
            CREATE TABLE IF NOT EXISTS invoices (
                bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_name TEXT,
                awb_number TEXT,
                invoice_no TEXT,
                order_id TEXT
            );
            CREATE TABLE IF NOT EXISTS invoice_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER,
                meta_key TEXT,
                meta_value TEXT,
                FOREIGN KEY (bill_id) REFERENCES invoices (bill_id)
            );
        ''')
        print("-------------------check -1")
        rows = request.json.get('rows', [])
        pdf_name = request.json.get("pdf_name")
        print("---request.json", request.json)
        # return None
        for row in rows:
            print("-------------------check -1",row)
            invoice_no = row.get("Invoice No", "")
            pdf_name = pdf_name #
            awb_number = row.get("AWB Number", "unknown")
            order_id = row.get("Order ID", "unknown")
            c.execute("INSERT INTO invoices (pdf_name, awb_number, invoice_no, order_id) VALUES (?, ?, ?, ?)", (pdf_name, awb_number, invoice_no,order_id))
            print("----execute")
            bill_id = c.lastrowid
            for key, value in row.items():
                if key not in ["Invoice No"]:
                    c.execute("INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)",
                            (bill_id, key, value))
        conn.commit()
    return jsonify({"message": f"{len(rows)} row(s) saved to bill.db ✅"})


@app.route('/api/invoices/list_m')
def list_saved_invoices():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT 
                i.invoice_no,
                i.pdf_name,
                i.awb_number,
                i.order_id,
                MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) AS invoice_date,
                MAX(CASE WHEN m.meta_key = 'Customer Name' THEN m.meta_value END) AS customer_name,
                MAX(CASE WHEN m.meta_key = 'State' THEN m.meta_value END) AS state,
                MAX(CASE WHEN m.meta_key = 'Payment Type' THEN m.meta_value END) AS payment_type
                MAX(CASE WHEN m.meta_key = 'Size' THEN m.meta_value END) AS size
            FROM invoices i
            LEFT JOIN invoice_metadata m ON i.bill_id = m.bill_id
            GROUP BY i.bill_id
            ORDER BY i.bill_id DESC
        ''')
        rows = c.fetchall()
        result = [
            {
                "invoice_no": row[0],
                "pdf_name": row[1],
                "awb_number": row[2],
                "order_id": row[3],
                "invoice_date": row[4],
                "customer_name": row[5],
                "state": row[6],
                "payment_type": row[7]
            }
            for row in rows
        ]
    return jsonify(result)


@app.route('/api/list/Paymentsinvoices_v4')
def invoices_payments_v4():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        print("Start executing .................")

        # Build the query dynamically so we don't miss columns from order_payments
        c.execute('PRAGMA table_info(order_payments)')
        payment_cols = [col[1] for col in c.fetchall() if col[1] != 'id']  # skip PK id

        # Select fields from invoices + metadata as pivots + all payment fields
        query = f'''
            SELECT 
                i.*,
                MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) AS invoice_date,
                MAX(CASE WHEN m.meta_key = 'Customer Name' THEN m.meta_value END) AS customer_name,
                MAX(CASE WHEN m.meta_key = 'State' THEN m.meta_value END) AS state,
                MAX(CASE WHEN m.meta_key = 'Payment Type' THEN m.meta_value END) AS payment_type,
                MAX(CASE WHEN m.meta_key = 'Size' THEN m.meta_value END) AS size,
                {', '.join([f"p.{col}" for col in payment_cols])}
            FROM invoices i
            LEFT JOIN invoice_metadata m 
                ON i.bill_id = m.bill_id
            LEFT JOIN order_payments p
                ON i.order_id = REPLACE(p.sub_order_no, '_1', '')
            GROUP BY i.bill_id
            ORDER BY i.bill_id DESC
        '''

        c.execute(query)
        rows = c.fetchall()
        results = [dict(row) for row in rows]

    return jsonify(results)


@app.route('/api/list/Paymentsinvoices')
def invoices_payments():
    start_order_date = request.args.get('start_order_date')
    end_order_date = request.args.get('end_order_date')
    start_payment_date = request.args.get('start_payment_date')
    end_payment_date = request.args.get('end_payment_date')

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute('PRAGMA table_info(order_payments)')
        payment_cols = [col[1] for col in c.fetchall() if col[1] != 'id']

        query = f'''
            SELECT 
                i.*,
                MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) AS invoice_date,
                MAX(CASE WHEN m.meta_key = 'Customer Name' THEN m.meta_value END) AS customer_name,
                MAX(CASE WHEN m.meta_key = 'State' THEN m.meta_value END) AS state,
                MAX(CASE WHEN m.meta_key = 'Payment Type' THEN m.meta_value END) AS payment_type,
                MAX(CASE WHEN m.meta_key = 'Size' THEN m.meta_value END) AS size,
                {', '.join([f"p.{col}" for col in payment_cols])}
            FROM invoices i
            LEFT JOIN invoice_metadata m 
                ON i.bill_id = m.bill_id
            LEFT JOIN order_payments p
                ON i.order_id = REPLACE(p.sub_order_no, '_1', '')
        '''

        filters = []
        params = []

        if start_order_date and end_order_date:
            filters.append("p.order_date BETWEEN ? AND ?")
            params.extend([start_order_date, end_order_date])

        if start_payment_date and end_payment_date:
            filters.append("p.payment_date BETWEEN ? AND ?")
            params.extend([start_payment_date, end_payment_date])

        if filters:
            query += " WHERE " + " AND ".join(filters)

        query += " GROUP BY i.bill_id ORDER BY i.bill_id DESC"

        c.execute(query, params)
        rows = c.fetchall()
        results = [dict(row) for row in rows]

    return jsonify(results)




@app.route('/view_pdf/<path:filename>')
def view_pdf(filename):
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=False)
    return f"PDF not found: {filename}", 404

# API to mark invoice as return and handle return details
@app.route('/api/invoices/mark_return', methods=['POST'])
def mark_invoice_return():
    data = request.json
    bill_id = data.get('bill_id')
    return_type = data.get('return_type')  # customer, supplier, or damaged
    add_to_stock = data.get('add_to_stock', 0)
    category_id = data.get('category_id')
    type_id = data.get('type_id')
    size_id = data.get('size_id')
    supplier_id = data.get('supplier_id')
    quantity = data.get('quantity', 1)
    loss_amount = data.get('loss_amount', 0)
    reason = data.get('reason', 'No reason provided')

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        
        # Verify bill_id exists
        c.execute('SELECT 1 FROM invoices WHERE bill_id = ?', (bill_id,))
        if not c.fetchone():
            return jsonify({'error': 'Invalid bill_id'}), 400

        # Validate return_type
        if return_type not in ['RTO', 'Customer', 'damaged']:
            return jsonify({'error': 'Invalid return_type'}), 400

        # Insert return record
        return_id = str(uuid.uuid4())
        c.execute('''
            INSERT INTO returns (id, category_id, type_id, size_id, supplier_id, 
                return_type, quantity, add_to_stock, loss_amount, date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (return_id, category_id, type_id, size_id, supplier_id, return_type, 
              quantity, add_to_stock, loss_amount, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Update invoice_metadata with return details
        c.execute('''
            INSERT INTO invoice_metadata (bill_id, meta_key, meta_value)
            VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)
        ''', (bill_id, 'return', 'yes', 
              bill_id, 'return_type', return_type, 
              bill_id, 'reason', reason))

        conn.commit()
        return jsonify({'message': 'Invoice marked as return', 'return_id': return_id})

# API to delete invoice
@app.route('/api/invoices/delete', methods=['POST'])
def delete_invoice():
    data = request.json
    bill_id = data.get('bill_id')
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT 1 FROM invoice_metadata WHERE bill_id = ? AND meta_key = "return" AND meta_value = "yes"', (bill_id,))
        if c.fetchone():
            return jsonify({'error': 'Cannot delete returned invoice'}), 400
            
        c.execute('DELETE FROM invoice_metadata WHERE bill_id = ?', (bill_id,))
        c.execute('DELETE FROM invoices WHERE bill_id = ?', (bill_id,))
        conn.commit()
        return jsonify({'message': 'Invoice deleted'})

# Modified saved invoices list to include return metadata
@app.route('/api/invoices/list', methods=['GET'])
def list_saved_invoices_m():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # SELECT 
        #         i.bill_id,
        #         i.invoice_no,
        #         i.pdf_name,
        #         i.awb_number,
        #         i.order_id,
        #         MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) AS invoice_date,
        #         MAX(CASE WHEN m.meta_key = 'Customer Name' THEN m.meta_value END) AS customer_name,
        #         MAX(CASE WHEN m.meta_key = 'State' THEN m.meta_value END) AS state,
        #         MAX(CASE WHEN m.meta_key = 'Payment Type' THEN m.meta_value END) AS payment_type,
        #         MAX(CASE WHEN m.meta_key = 'return' THEN m.meta_value END) AS return_status,
        #         MAX(CASE WHEN m.meta_key = 'return_type' THEN m.meta_value END) AS return_type,
        #         MAX(CASE WHEN m.meta_key = 'reason' THEN m.meta_value END) AS return_reason
        #     FROM invoices i
        #     LEFT JOIN invoice_metadata m ON i.bill_id = m.bill_id
        #     GROUP BY i.bill_id
        #     ORDER BY i.bill_id DESC
        c.execute('''
                  SELECT 
                i.bill_id,
                i.invoice_no,
                i.pdf_name,
                i.awb_number,
                i.order_id,
                MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) AS invoice_date,
                MAX(CASE WHEN m.meta_key = 'Customer Name' THEN m.meta_value END) AS customer_name,
                MAX(CASE WHEN m.meta_key = 'State' THEN m.meta_value END) AS state,
                MAX(CASE WHEN m.meta_key = 'Payment Type' THEN m.meta_value END) AS payment_type,
                MAX(CASE WHEN m.meta_key = 'return' THEN m.meta_value END) AS return_status,
                MAX(CASE WHEN m.meta_key = 'return_type' THEN m.meta_value END) AS return_type,
                MAX(CASE WHEN m.meta_key = 'reason' THEN m.meta_value END) AS return_reason,
                MAX(CASE WHEN m.meta_key = 'Size' THEN m.meta_value END) AS size,
                MAX(CASE WHEN m.meta_key =  'Courier Partner' THEN m.meta_value END ) As courier,
                MAX(CASE WHEN m.meta_key =  'Product Name' THEN m.meta_value END ) As product_name
            FROM invoices i
            LEFT JOIN invoice_metadata m ON i.bill_id = m.bill_id
            WHERE i.order_id != 'NA'
            GROUP BY i.bill_id
            ORDER BY MAX(CASE WHEN m.meta_key = 'Invoice Date' THEN m.meta_value END) DESC
            
        ''')
        rows = c.fetchall()
        result = [
            {
                'bill_id': row[0],
                'invoice_no': row[1],
                'pdf_name': row[2],
                'awb_number': row[3],
                'order_id': row[4],
                'invoice_date': row[5],
                'customer_name': row[6],
                'state': row[7],
                'payment_type': row[8],
                'return_status': row[9],
                'return_type': row[10],
                'return_reason': row[11],
                'size' : row[12],
                'courier' : row [13],
                'product_name' : row [14]
            } for row in rows
        ]
        return jsonify(result)


# API to get counts of bills, returns, actual sales, and summary
@app.route('/api/invoice_summary/data', methods=['GET'])
def invoice_summary():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM invoices')
        total_bills = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM invoice_metadata WHERE meta_key = "return" AND meta_value = "yes"')
        total_returns = c.fetchone()[0]
        actual_sales = total_bills - total_returns
        
        c.execute('''
            SELECT 
                i.bill_id,
                i.invoice_no,
                i.order_id,
                i.awb_number,
                MAX(CASE WHEN m.meta_key = 'return' THEN m.meta_value END) AS return_status,
                MAX(CASE WHEN m.meta_key = 'return_type' THEN m.meta_value END) AS return_type
            FROM invoices i
            LEFT JOIN invoice_metadata m ON i.bill_id = m.bill_id
            GROUP BY i.bill_id
        ''')
        summary = [{
            'bill_id': row[0],
            'invoice_no': row[1],
            'order_id': row[2],
            'awb_number': row[3],
            'return_status': row[4],
            'return_type': row[5]
        } for row in c.fetchall()]
        
        return jsonify({
            'total_bills': total_bills,
            'total_returns': total_returns,
            'actual_sales': actual_sales,
            'summary': summary
        })  
        
@app.route('/api/bulk_upload_folder', methods=['POST'])
def bulk_upload_folder():
    if 'folder' not in request.files:
        return jsonify({'error': 'No folder uploaded'}), 400

    files = request.files.getlist('folder')
    extracted_data = []
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        for file in files:
            if file.filename.lower().endswith('.pdf'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                file.save(filepath)

                # Check for duplicate
                c.execute('SELECT 1 FROM invoices WHERE pdf_name = ?', (filename,))
                if c.fetchone():
                    continue

                rows = extract_data_from_pdf(filepath)
                for row in rows:
                    invoice_no = row.get("Invoice No", "")
                    awb_number = row.get("AWB Number", "unknown")
                    order_id = row.get("Order ID", "unknown")

                    # Check for AWB number duplicate
                    c.execute('SELECT 1 FROM invoices WHERE awb_number = ?', (awb_number,))
                    if c.fetchone():
                        continue

                    c.execute('INSERT INTO invoices (pdf_name, awb_number, invoice_no, order_id) VALUES (?, ?, ?, ?)',
                             (filename, awb_number, invoice_no, order_id))
                    bill_id = c.lastrowid

                    for key, value in row.items():
                        if key not in ["Invoice No", "AWB Number", "Order ID"]:
                            c.execute('INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)',
                                     (bill_id, key, value))
                    extracted_data.append({**row, 'pdf_name': filename})

        conn.commit()

    df = pd.DataFrame(extracted_data)
    excel_path = "bulk_folder_extracted.xlsx"
    df.to_excel(excel_path, index=False)

    return jsonify({
        "message": f"{len(extracted_data)} invoices processed",
        "data": extracted_data,
        "excel_path": excel_path
    }) 


@app.route('/api/sku_mappings', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_sku_mappings():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if request.method == 'GET':
            c.execute('''
                SELECT sm.sku_id, c.name, t.name, sz.name, su.name, sm.sku_name
                FROM sku_mappings sm
                JOIN categories c ON sm.category_id = c.id
                JOIN types t ON sm.type_id = t.id
                JOIN sizes sz ON sm.size_id = sz.id
                JOIN suppliers su ON sm.supplier_id = su.id
            ''')
            return jsonify([{
                'sku_id': row[0],
                'category': row[1],
                'type': row[2],
                'size': row[3],
                'supplier': row[4],
                'sku_name': row[5]
            } for row in c.fetchall()])

        if request.method == 'POST':
            data = request.json
            c.execute('''
                SELECT sm.sku_id, sm.sku_name
                FROM sku_mappings sm
                WHERE sm.category_id = ? AND sm.type_id = ? AND sm.size_id = ? AND sm.supplier_id = ?
            ''', (data['category_id'], data['type_id'], data['size_id'], data['supplier_id']))
            existing = c.fetchall()
            if existing and not data.get('confirm_duplicate', False):
                return jsonify({
                    'error': 'Duplicate combination found',
                    'existing': [{'sku_id': row[0], 'sku_name': row[1]} for row in existing]
                }), 409
            sku_id = str(uuid.uuid4())
            c.execute('''
                INSERT INTO sku_mappings (sku_id, category_id, type_id, size_id, supplier_id, sku_name)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (sku_id, data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], data['sku_name']))
            conn.commit()
            return jsonify({'message': 'SKU mapping created', 'sku_id': sku_id})

        if request.method == 'PUT':
            data = request.json
            c.execute('''
                SELECT 1 FROM sku_mappings
                WHERE category_id = ? AND type_id = ? AND size_id = ? AND supplier_id = ? AND sku_id != ?
            ''', (data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], data['sku_id']))
            existing = c.fetchall()
            if existing and not data.get('confirm_duplicate', False):
                return jsonify({
                    'error': 'Duplicate combination found',
                    'existing': [{'sku_id': row[0]} for row in existing]
                }), 409
            c.execute('''
                UPDATE sku_mappings
                SET category_id = ?, type_id = ?, size_id = ?, supplier_id = ?, sku_name = ?
                WHERE sku_id = ?
            ''', (data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], data['sku_name'], data['sku_id']))
            conn.commit()
            return jsonify({'message': 'SKU mapping updated'})

        if request.method == 'DELETE':
            data = request.json
            c.execute('DELETE FROM sku_mappings WHERE sku_id = ?', (data['sku_id'],))
            conn.commit()
            return jsonify({'message': 'SKU mapping deleted'})
        
        
@app.route('/api/upload_returns_csv', methods=['POST'])
def upload_returns_csv():
    print("request=======>",  request.files)
    if 'file' not in request.files:
        return jsonify({'error': 'no file uploaded'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith('.csv'):
        return jsonify({'error': 'invalid file format, must be csv'}), 400

    try:
        # df = pd.read_csv(file)
        df = pd.read_csv(file, on_bad_lines='skip', encoding='utf-8')
        print("df---------------",df.columns.tolist())
        processed = []
        errors = []
        
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            
            # Get category, size, supplier, and type mappings (lowercase for matching)
            c.execute('SELECT id, LOWER(name) FROM categories')
            categories = {row[1]: row[0] for row in c.fetchall()}
            c.execute('SELECT id, LOWER(name) FROM sizes')
            sizes = {row[1].replace('cm', '').strip(): row[0] for row in c.fetchall()}
            c.execute('SELECT id, LOWER(name) FROM suppliers')
            suppliers = {row[1]: row[0] for row in c.fetchall()}
            c.execute('SELECT id, LOWER(name) FROM types')
            types = {row[1]: row[0] for row in c.fetchall()}

            for _, row in df.iterrows():
                order_id = str(row['Suborder Number']).replace('_1', '')
                
                # Check for duplicate based on order_id
                c.execute('''
                    SELECT 1 FROM invoice_metadata 
                    WHERE bill_id IN (SELECT bill_id FROM invoices WHERE order_id = ?) 
                    AND meta_key = 'return' AND meta_value = 'yes'
                ''', (order_id,))
                if c.fetchone():
                    errors.append(f"return already processed for order {order_id}")
                    continue

                category_name = str(row['Category']).lower()
                if 'briefs' in category_name:
                    category_name = 'panty'
                if 'camisoles' in category_name:
                    category_name = 'camisole'
                category_id = categories.get(category_name)
                if not category_id:
                    errors.append(f"category {category_name} not found for order {order_id}")
                    continue

                size_name = str(row['Variation']).lower().replace('cm', '').strip()
                size_id = next((sid for sname, sid in sizes.items() if size_name in sname), None)
                if not size_id:
                    errors.append(f"size {size_name} not found for order {order_id}")
                    continue

                company = 'jtm' if 'camisole' in category_name else 'bhola'
                supplier_id = suppliers.get(company)
                if not supplier_id:
                    errors.append(f"supplier {company} not found for order {order_id}")
                    continue

                type_name = 'good'
                type_id = types.get(type_name)
                if not type_id:
                    errors.append(f"type {type_name} not found for order {order_id}")
                    continue

                return_type = 'rto' if 'courier return' in str(row['Type of Return']).lower() else 'customer' if 'customer return' in str(row['Type of Return']).lower() else row['Type of Return'].lower()
                return_reason = f"{str(row.get('Return Reason', 'na')).lower()} - {str(row.get('Detailed Return Reason', 'na')).lower()}".strip()
                otp_verified_at = str(row.get('OTP verified at', 'na')).lower()

                c.execute('SELECT bill_id FROM invoices WHERE order_id = ?', (order_id,))
                bill = c.fetchone()
                if not bill:
                    errors.append(f"invoice not found for order {order_id}")
                    continue

                bill_id = bill[0]
                return_id = str(uuid.uuid4())
                quantity = 1  # Set quantity to 1 for all returns
                c.execute('''
                    INSERT INTO returns (id, category_id, type_id, size_id, supplier_id, return_type, quantity, add_to_stock, loss_amount, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (return_id, category_id, type_id, size_id, supplier_id, return_type, quantity, 1, 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

                c.execute('''
                    INSERT INTO invoice_metadata (bill_id, meta_key, meta_value)
                    VALUES (?, ?, ?), (?, ?, ?), (?, ?, ?)
                ''', (bill_id, 'return', 'yes', 
                      bill_id, 'return_type', return_type, 
                      bill_id, 'reason', return_reason))
                
                if otp_verified_at != 'na':
                    c.execute('INSERT INTO invoice_metadata (bill_id, meta_key, meta_value) VALUES (?, ?, ?)',
                             (bill_id, 'otp_verified_at', otp_verified_at))

                processed.append({
                    'order_id': order_id,
                    'category': category_name,
                    'size': size_name,
                    'supplier': company,
                    'type': type_name,
                    'return_type': return_type,
                    'return_reason': return_reason,
                    'otp_verified_at': otp_verified_at,
                    'quantity': quantity
                })

            conn.commit()

        return jsonify({
            'message': f'{len(processed)} returns processed',
            'processed': processed,
            'errors': errors if errors else None
        })

    except Exception as e:
        return jsonify({'error': f'error processing csv: {str(e)}'}), 400    
    

@app.route('/api/adjust_return_loss', methods=['POST'])
def adjust_return_loss():
    data = request.json
    category_id = data.get('category_id')
    size_id = data.get('size_id', None)
    loss_amount = data.get('loss_amount')
    override = data.get('override', False)
    return_type = data.get('return_type', None)

    try:
        loss_amount = float(loss_amount) if loss_amount else 0.0
        if loss_amount <= 0:
            return jsonify({'error': 'loss amount must be greater than 0'}), 400

        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()

            # Validate category_id
            c.execute('SELECT 1 FROM categories WHERE id = ?', (category_id,))
            if not c.fetchone():
                return jsonify({'error': 'invalid category_id'}), 400

            # Validate size_id if provided
            if size_id:
                c.execute('SELECT 1 FROM sizes WHERE id = ?', (size_id,))
                if not c.fetchone():
                    return jsonify({'error': 'invalid size_id'}), 400

            # Validate return_type if provided
            if return_type and return_type.lower() not in ['rto', 'customer', 'other']:
                return jsonify({'error': 'invalid return_type, must be rto, customer, or other'}), 400

            # Update returns based on conditions
            query = 'UPDATE returns SET loss_amount = ? WHERE category_id = ?'
            params = [loss_amount, category_id]

            if not override:
                query += ' AND (loss_amount IS NULL OR loss_amount = 0.0)'

            if size_id:
                query += ' AND size_id = ?'
                params.append(size_id)

            if return_type:
                query += ' AND LOWER(return_type) = ?'
                params.append(return_type.lower())

            c.execute(query, params)
            affected_rows = c.rowcount
            conn.commit()

            if affected_rows == 0:
                return jsonify({'message': 'no returns found to update'})

            return jsonify({
                'message': f'{affected_rows} return(s) updated with loss amount {loss_amount}',
                'category_id': category_id,
                'size_id': size_id,
                'return_type': return_type,
                'loss_amount': loss_amount,
                'override': override
            })

    except ValueError:
        return jsonify({'error': 'invalid loss amount format'}), 400
    except Exception as e:
        return jsonify({'error': f'error updating returns: {str(e)}'}), 400


NUM_BLOCKS = 36
SHORT_MESSAGES = [
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


@app.route('/api/generate_pdf', methods=['POST'])
def generate_pdf():
    SIZE_SETS = {
    "Panty": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34",
              "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"},
    "Leggins": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34",
                "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"},
    "Camisole": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34",
                 "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"},
    "Bra": {"XS": "XS  | 75 cm | 30", "S": "S   | 80 cm | 32", "M": "M   | 85 cm | 34",
            "L": "L   | 90 cm | 36", "XL": "XL  | 95 cm | 38", "XXL": "XXL  | 100 cm | 40"}
    }
    
    print("Headers:", request.headers)
    print("Raw data:", request.data)  # Raw body content
    print("request.get_json(force=True):", request.get_json(force=True))
    
    data = request.get_json(force=True) #request.json
    print("data============>",data)
    category ="Panty" # data.get('category', 'Panty')
    xs_count = int(data.get('xs_count', 0))
    s_count = int(data.get('s_count', 9))
    m_count = int(data.get('m_count', 9))
    l_count = int(data.get('l_count', 9))
    xl_count = int(data.get('xl_count', 9))
    xxl_count = int(data.get('xxl_count', 0))
    brand_text = data.get('brand_text', 'Collect Now')
    brand_color = data.get('brand_color', '#FF0000')
    brand_font = data.get('brand_font', 'Helvetica-Bold')
    brand_size = int(data.get('brand_size', 12))
    size_text = data.get('size_text', '')
    size_color = data.get('size_color', '#00008B')
    size_font = data.get('size_font', 'Helvetica-Bold')
    size_size = int(data.get('size_size', 10))
    message_color = data.get('message_color', '#FF00FF')
    message_font = data.get('message_font', 'Helvetica-Bold')
    message_size = int(data.get('message_size', 8))
    thanks_text = data.get('thanks_text', 'Thank you for choosing us')
    thanks_color = data.get('thanks_color', '#000000')
    thanks_font = data.get('thanks_font', 'Helvetica')
    thanks_size = int(data.get('thanks_size', 7))
    url_text = data.get('url_text', 'collectnow.in | 7872427219')
    url_color = data.get('url_color', '#0000FF')
    url_font = data.get('url_font', 'Helvetica-Bold')
    url_size = int(data.get('url_size', 8))
    emoji_text =data.get('emoji_text', '❤️').strip()

    # Clean emoji to remove unwanted codepoints like ZWJ and variation selectors
    emoji_text_raw = data.get('emoji_text', '❤️')
    emoji_text = re.sub(r'[\uFE0F\u200D]', '', emoji_text_raw).strip()

    emoji_color = data.get('emoji_color', '#FF0000')
    emoji_size = int(data.get('emoji_size', 9))

    total = xs_count + s_count + m_count + l_count + xl_count + xxl_count
    if total != NUM_BLOCKS:
        return {'error': f'Total must be exactly {NUM_BLOCKS}. You entered {total}.'}, 400

    now = datetime.now()
    filename = f"ladies_comfort_cards_{category.lower()}_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = os.path.join(os.getcwd(), filename)
    print("category ==============>", data.get('category'))
    print("SIZE_SETS[category]['XS']===========>",SIZE_SETS.get(category))
    sizes = (
        [SIZE_SETS[category]["XS"]] * xs_count +
        [SIZE_SETS[category]["S"]] * s_count +
        [SIZE_SETS[category]["M"]] * m_count +
        [SIZE_SETS[category]["L"]] * l_count +
        [SIZE_SETS[category]["XL"]] * xl_count +
        [SIZE_SETS[category]["XXL"]] * xxl_count
    )
    random.shuffle(sizes)

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    cols = 4
    rows = 9
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

        c.setFont(brand_font, brand_size)
        c.setFillColor(colors.HexColor(brand_color))
        c.drawCentredString(center_x, top_y - 20, brand_text)

        c.setFont("Helvetica", emoji_size)
        c.setFillColor(colors.HexColor(emoji_color))
        c.drawCentredString(center_x, top_y - 35, emoji_text)

        c.setFont(size_font, size_size)
        c.setFillColor(colors.HexColor(size_color))
        c.drawCentredString(center_x, top_y - 45, sizes[i])

        c.setFont(message_font, message_size)
        c.setFillColor(colors.HexColor(message_color))
        c.drawCentredString(center_x, top_y - 60, SHORT_MESSAGES[i])

        c.setFont(thanks_font, thanks_size)
        c.setFillColor(colors.HexColor(thanks_color))
        c.drawCentredString(center_x, y + 20, thanks_text)

        c.setFont(url_font, url_size)
        c.setFillColor(colors.HexColor(url_color))
        c.drawCentredString(center_x, y + 8, url_text)

    c.save()
    return send_file(filepath, as_attachment=True, download_name=filename)




@app.route('/api/generate-promo-pdf', methods=['POST'])
def generate_promo_pdf():
    #try:
        data = request.get_json(force=True)
        # request.get_json(force=True)

        promo_text = data.get("promoText", "More discount")
        shop_text = data.get("shopText", "collectnow.in")
        qr_text = data.get("qrText", "collectnow.in")
        promo_color = hex_to_rgb(data.get("promoColor", "#FF1493"))
        shop_color = hex_to_rgb(data.get("shopColor", "#0000FF"))
        code_color = hex_to_rgb(data.get("codeColor", "#8A2BE2"))

        codes = data.get("codes", [])
        counts = data.get("counts", [])

        # flatten codes to 36 items based on counts
        all_codes = []
        for code, count in zip(codes, counts):
            all_codes.extend([code] * int(count))
        all_codes = all_codes[:36]

        pdf = FPDF(orientation='P', unit='mm', format='A4')
        pdf.add_page()

        total_cards = 36
        cols, rows = 6, 6
        page_width, page_height = 210, 297
        margin, padding = 5, 2
        card_width = (page_width - 2 * margin) / cols
        card_height = (page_height - 2 * margin) / rows
        x_start, y_start = margin, margin
        qr_images = []

        for index in range(total_cards):
            code = all_codes[index] if index < len(all_codes) else "N/A"
            col = index % cols
            row = index // cols
            x = x_start + col * card_width
            y = y_start + row * card_height

            pdf.set_draw_color(200, 200, 200)
            pdf.rect(x, y, card_width, card_height)

            text_x = x + padding
            text_y = y + padding
            qr_size = card_height - 2 * padding
            qr_side = qr_size * 0.45
            text_width = card_width - 2 * padding

            pdf.set_xy(text_x, text_y)
            pdf.set_font("Arial", "B", 8)
            pdf.set_text_color(*promo_color)
            pdf.multi_cell(text_width, 3, promo_text, align='C')

            pdf.set_text_color(*shop_color)
            pdf.set_font("Arial", "", 7)
            pdf.set_xy(text_x, pdf.get_y())
            pdf.multi_cell(text_width, 3, shop_text, align='C')

            pdf.set_text_color(*code_color)
            pdf.set_font("Arial", "B", 8)
            pdf.set_xy(text_x, pdf.get_y())
            pdf.multi_cell(text_width, 3, f"Code: {code}", align='C')

            qr_img = qrcode.make(qr_text)
            img_path = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
            qr_img.save(img_path)
            qr_images.append(img_path)

            qr_x = x + (card_width - qr_side) / 2
            qr_y = pdf.get_y() + padding
            pdf.image(img_path, qr_x, qr_y, qr_side, qr_side)

        # Save PDF to BytesIO
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
            pdf.output(tmp_pdf.name)
            tmp_pdf_path = tmp_pdf.name

        return send_file(
            tmp_pdf_path,
            as_attachment=True,
            download_name="promo_cards.pdf",
            mimetype="application/pdf"
        )


    # except Exception as e:
    #     return jsonify({"error": str(e)}), 500




@app.route('/api/invoices_to_sale', methods=['POST'])
def invoices_to_sale():
    data = request.get_json(force=True)
    selected_rows = data.get('selectedRows', [])
    type_name = data.get('type', '').strip().lower()
    supplier_name = data.get('supplier', '').strip().lower()

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # Get type_id
        type_id = None
        if type_name:
            c.execute('SELECT id FROM types WHERE LOWER(name) = ?', (type_name,))
            row = c.fetchone()
            type_id = row[0] if row else None
        if not type_id:
            c.execute('SELECT id FROM types WHERE LOWER(name) = ?', ('good',))
            row = c.fetchone()
            type_id = row[0] if row else None

        processed, duplicates, errors = [], [], []

        for row in selected_rows:
            awb_number = row.get('AWB Number', '').strip()
            order_id = row.get('Order ID', '').strip()
            size = row.get('Size', '').lower().strip()
            product_name = row.get('Product Name', '').lower().strip()

            print(f"\n⏳ Processing AWB: {awb_number}")

            # Duplicate check
            c.execute('SELECT sale_id FROM sales_log WHERE awb_number = ? AND order_id = ?', (awb_number, order_id))
            if c.fetchone():
                duplicates.append({'awb_number': awb_number, 'order_id': order_id})
                print(f"⚠️ Duplicate found: {awb_number}")
                continue

            # Fetch invoice data
            c.execute('''
                SELECT i.bill_id, i.order_id, m.meta_value AS product_name, LOWER(REPLACE(m2.meta_value, 'cm', '')) AS size
                FROM invoices i
                LEFT JOIN invoice_metadata m ON i.bill_id = m.bill_id AND m.meta_key = 'Product Name'
                LEFT JOIN invoice_metadata m2 ON i.bill_id = m2.bill_id AND m2.meta_key = 'Size'
                WHERE i.awb_number = ? AND i.order_id = ?
            ''', (awb_number, order_id))
            invoice = c.fetchone()

            if not invoice:
                errors.append(f"Invoice not found for AWB {awb_number}, Order ID {order_id}")
                continue

            bill_id, order_id, db_product_name, db_size = invoice
            db_product_name = db_product_name if db_product_name != "NA" else product_name
            product_name = db_product_name.lower().strip() if db_product_name else product_name
            size = db_size.lower().strip() if db_size else size

            # Return check
            c.execute('''
                SELECT 1 FROM invoice_metadata 
                WHERE bill_id = ? AND meta_key = "return" AND meta_value = "yes"
            ''', (bill_id,))
            if c.fetchone():
                errors.append(f"Invoice {order_id} is marked as RETURN (AWB {awb_number})")
                continue

            # Category mapping
            if 'camisole' in product_name:
                c.execute('SELECT id FROM categories WHERE LOWER(name) = "camisole"')
            elif 'briefs' in product_name or 'panty' in product_name:
                c.execute('SELECT id FROM categories WHERE LOWER(name) = "panty"')
            elif 'nighty' in product_name:
                c.execute('SELECT id FROM categories WHERE LOWER(name) = "nighty"')
            elif 'bra' in product_name:
                c.execute('SELECT id FROM categories WHERE LOWER(name) = "bra"')
            else:
                c.execute('SELECT id FROM categories WHERE LOWER(name) = ?', (product_name,))
            row = c.fetchone()
            if not row:
                errors.append(f"Category not found for product '{product_name}' (AWB {awb_number})")
                continue
            category_id = row[0]

            # Size mapping
            c.execute('SELECT id, name FROM sizes')
            size_map = {}
            for sid, name in c.fetchall():
                parts = name.lower().replace('cm', '').split('|')
                parts = [p.strip() for p in parts]
                for part in parts:
                    size_map[part] = sid
            normalized_size = size.replace('cm', '').replace(' ', '')
            size_id = size_map.get(normalized_size)
            if not size_id:
                errors.append(f"Size '{size}' not found for invoice {order_id} (AWB {awb_number})")
                continue

            # Supplier mapping
            default_supplier = 'jtm' if 'camisole' in product_name else 'bhola'
            use_supplier = supplier_name or default_supplier
            c.execute('SELECT id FROM suppliers WHERE LOWER(name) = ?', (use_supplier,))
            row = c.fetchone()
            if not row:
                errors.append(f"Supplier '{use_supplier}' not found for AWB {awb_number}")
                continue
            supplier_id = row[0]

            # Purchase check
            c.execute('''
                SELECT p.id, p.quantity, COALESCE(SUM(rts.quantity), 0) as ready_qty
                FROM purchases p
                LEFT JOIN ready_to_sale rts ON rts.purchase_id = p.id
                WHERE p.category_id = ? AND p.type_id = ? AND p.size_id = ? AND p.supplier_id = ?
                GROUP BY p.id
                HAVING p.quantity - ready_qty >= 1
            ''', (category_id, type_id, size_id, supplier_id))
            purchase = c.fetchone()

            if not purchase:
                # Create new purchase
                print(f"🛒 Creating new purchase for AWB: {awb_number}")
                purchase_id = str(uuid.uuid4())
                quantity = 1
                tax, carry_cost, extra_cost = 0.0, 0.0, 0.0
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if 'camisole' in product_name:
                    price = 4 * 30
                elif 'panty' in product_name or 'briefs' in product_name:
                    price = 5 * 23
                else:
                    price = 150

                c.execute('''
                    INSERT INTO purchases (id, category_id, type_id, size_id, supplier_id, quantity, price, tax, carry_cost, extra_cost, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (purchase_id, category_id, type_id, size_id, supplier_id, quantity, price, tax, carry_cost, extra_cost, now))
            else:
                purchase_id, _, _ = purchase

            # Insert into ready_to_sale
            ready_id = str(uuid.uuid4())
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            c.execute('''
                INSERT INTO ready_to_sale (id, purchase_id, quantity, date)
                VALUES (?, ?, ?, ?)
            ''', (ready_id, purchase_id, 1, now))

            # Insert into sales
            sale_id = str(uuid.uuid4())
            c.execute('''
                INSERT INTO sales (id, ready_to_sale_id, quantity, date)
                VALUES (?, ?, ?, ?)
            ''', (sale_id, ready_id, 1, now))

            # Log sale
            c.execute('''
                INSERT INTO sales_log (sale_id, awb_number, order_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (sale_id, awb_number, order_id, now))

            # Update invoice_metadata
            c.execute('''
                INSERT INTO invoice_metadata (bill_id, meta_key, meta_value)
                VALUES (?, ?, ?)
            ''', (bill_id, 'sale_id', sale_id))

            processed.append({
                'bill_id': bill_id,
                'awb_number': awb_number,
                'order_id': order_id,
                'sale_id': sale_id,
                'category_id': category_id,
                'type_id': type_id,
                'size_id': size_id,
                'supplier_id': supplier_id
            })

            print(f"✅ AWB {awb_number} processed successfully.")

        conn.commit()

    print("\n===== FINAL REPORT =====")
    print(f"✅ Processed: {len(processed)}")
    print(f"⚠️ Duplicates: {len(duplicates)}")
    print(f"❌ Errors: {len(errors)}")
    for e in errors:
        print("Error:", e)

    return jsonify({
        'message': f'{len(processed)} invoices processed, {len(duplicates)} duplicates skipped.',
        'processed': processed,
        'duplicates': duplicates or None,
        'errors': errors or None
    })


@app.route('/api/full_inventory_report', methods=['GET'])
def full_inventory_report():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        report = {}

        # Purchases
        c.execute('''
            SELECT p.*, ca.name AS category_name, ty.name AS type_name,
                   sz.name AS size_name, sp.name AS supplier_name
            FROM purchases p
            LEFT JOIN categories ca ON p.category_id = ca.id
            LEFT JOIN types ty ON p.type_id = ty.id
            LEFT JOIN sizes sz ON p.size_id = sz.id
            LEFT JOIN suppliers sp ON p.supplier_id = sp.id
        ''')
        report['purchases'] = [dict(row) for row in c.fetchall()]

        # Ready to Sale
        c.execute('''
            SELECT rts.*, p.id AS purchase_id
            FROM ready_to_sale rts
            LEFT JOIN purchases p ON rts.purchase_id = p.id
        ''')
        report['ready_to_sale'] = [dict(row) for row in c.fetchall()]

        # Sales with customer data
        c.execute('''
            SELECT s.*, sl.awb_number, sl.order_id, sl.created_at AS log_time
            FROM sales s
            LEFT JOIN sales_log sl ON s.id = sl.sale_id
        ''')
        report['sales'] = [dict(row) for row in c.fetchall()]

        # Returns
        c.execute('''
            SELECT r.*, ca.name AS category_name, ty.name AS type_name,
                   sz.name AS size_name, sp.name AS supplier_name
            FROM returns r
            LEFT JOIN categories ca ON r.category_id = ca.id
            LEFT JOIN types ty ON r.type_id = ty.id
            LEFT JOIN sizes sz ON r.size_id = sz.id
            LEFT JOIN suppliers sp ON r.supplier_id = sp.id
        ''')
        report['returns'] = [dict(row) for row in c.fetchall()]

        # Stock Calculation
        c.execute('''
            SELECT ca.name AS category, ty.name AS type, sz.name AS size,
                   sp.name AS supplier, p.quantity, 
                   COALESCE(SUM(rts.quantity), 0) AS used,
                   (p.quantity - COALESCE(SUM(rts.quantity), 0)) AS available
            FROM purchases p
            LEFT JOIN ready_to_sale rts ON rts.purchase_id = p.id
            LEFT JOIN categories ca ON p.category_id = ca.id
            LEFT JOIN types ty ON p.type_id = ty.id
            LEFT JOIN sizes sz ON p.size_id = sz.id
            LEFT JOIN suppliers sp ON p.supplier_id = sp.id
            GROUP BY p.id
        ''')
        report['stocks'] = [dict(row) for row in c.fetchall()]

        # Invoice to Sale
        c.execute('''
            SELECT im.bill_id, i.awb_number, i.order_id, im.meta_value AS sale_id
            FROM invoice_metadata im
            JOIN invoices i ON i.bill_id = im.bill_id
            WHERE im.meta_key = 'sale_id'
        ''')
        report['invoice_to_sale'] = [dict(row) for row in c.fetchall()]

        # Invoice to Return
        c.execute('''
            SELECT DISTINCT i.bill_id, i.awb_number, i.order_id
            FROM invoices i
            JOIN invoice_metadata im ON im.bill_id = i.bill_id
            WHERE im.meta_key = 'return' AND LOWER(im.meta_value) = 'yes'
        ''')
        report['invoice_to_return'] = [dict(row) for row in c.fetchall()]

        return jsonify(report)

# init_order_payments_table()

# ---- Import API ----
@app.route("/api/action/import_order_payments", methods=["POST"])
def import_order_payments():
    # with sqlite3.connect(DB_PATH) as conn:
    #     cursor = conn.cursor()
    #     cursor.execute("DELETE FROM order_payments;")
    #     conn.commit()
    #     cursor.execute("VACUUM;")  # Optional, reclaims space
    # return ""
    # with sqlite3.connect(DB_PATH) as conn:
    #     cursor = conn.cursor()
    #     cursor.execute("DROP TABLE IF EXISTS order_payments;")
    #     conn.commit()
    #     return ""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    try:
        df = pd.read_excel(BytesIO(file.read()), sheet_name="Order Payments")
        df = df.rename(columns=lambda x: str(x).strip())

        df = df.dropna(subset=["Sub Order No"])

        inserted_count = 0
        duplicate_count = 0

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                sub_order_no = str(row["Sub Order No"]).strip()

                # Check for duplicates
                cursor.execute("SELECT id FROM order_payments WHERE sub_order_no = ?", (sub_order_no,))
                if cursor.fetchone():
                    duplicate_count += 1
                    continue

                cursor.execute("""
    INSERT INTO order_payments (
        sub_order_no, order_date, dispatch_date, product_name, supplier_sku, order_status,
        product_gst_pct, listing_price, quantity, transaction_id, payment_date,
        final_settlement_amount, price_type, total_sale_amount, total_sale_return_amount,
        fixed_fee, warehousing_fee, return_premium, return_premium_of_return,
        meesho_commission_pct, meesho_commission, meesho_gold_platform_fee,
        meesho_mall_platform_fee, fixed_fee_1, warehousing_fee_1, return_shipping_charge,
        gst_compensation, shipping_charge, other_support_service_charges, waivers,
        net_other_support_service_charges, gst_on_net_other_support_service_charges,
        tcs, tds_rate_pct, tds, compensation, claims, recovery,
        compensation_reason, claims_reason, recovery_reason
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
""", (
    row.get("Sub Order No"),
    row.get("Order Date"),
    row.get("Dispatch Date"),
    row.get("Product Name"),
    row.get("Supplier SKU"),
    row.get("Live Order Status"),
    row.get("Product GST %"),
    row.get("Listing Price (Incl. taxes)"),
    row.get("Quantity"),
    row.get("Transaction ID"),
    row.get("Payment Date"),
    row.get("Final Settlement Amount"),
    row.get("Price Type"),
    row.get("Total Sale Amount (Incl. Shipping & GST)"),
    row.get("Total Sale Return Amount (Incl. Shipping & GST)"),
    row.get("Fixed Fee (Incl. GST)"),
    row.get("Warehousing fee (inc Gst)"),
    row.get("Return premium (incl GST)"),
    row.get("Return premium (incl GST) of Return"),
    row.get("Meesho Commission Percentage"),
    row.get("Meesho Commission (Incl. GST)"),
    row.get("Meesho gold platform fee (Incl. GST)"),
    row.get("Meesho mall platform fee (Incl. GST)"),
    row.get("Fixed Fee (Incl. GST).1"),
    row.get("Warehousing fee (Incl. GST)"),
    row.get("Return Shipping Charge (Incl. GST)"),
    row.get("GST Compensation (PRP Shipping)"),
    row.get("Shipping Charge (Incl. GST)"),
    row.get("Other Support Service Charges (Excl. GST)"),
    row.get("Waivers (Excl. GST)"),
    row.get("Net Other Support Service Charges (Excl. GST)"),
    row.get("GST on Net Other Support Service Charges"),
    row.get("TCS"),
    row.get("TDS Rate %"),
    row.get("TDS"),
    row.get("Compensation"),
    row.get("Claims"),
    row.get("Recovery"),
    row.get("Compensation Reason"),
    row.get("Claims Reason"),
    row.get("Recovery Reason")
))



                inserted_count += 1

            conn.commit()

        skipped_count = len(df) - inserted_count - duplicate_count

        return jsonify({
            "status": "success",
            "rows_inserted": inserted_count,
            "duplicates_skipped": duplicate_count,
            "rows_skipped": skipped_count
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
    
# ---- Get Data API ----
@app.route("/api/order_payments", methods=["GET"])
def get_order_payments():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM order_payments ORDER BY order_date DESC")
        rows = cursor.fetchall()
        return jsonify([dict(row) for row in rows])



def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


      
@app.route('/download')
def download_excel():
    return send_file("extracted.xlsx", as_attachment=True)

import threading
import time
# import webview
# from your_flask_app import app, init_db  # adjust import as needed


def run_flask():
    app.run(host='0.0.0.0', port=8000, debug=False, use_reloader=False)


if __name__ == '__main__':
    init_db()
    url = 'http://127.0.0.1:8000' #
    app.run(host='127.0.0.1', port=8000, debug=True)
    # Start Flask in a new thread
    # flask_thread = threading.Thread(target=run_flask)
    # flask_thread.daemon = True
    # flask_thread.start()

    # Optional delay to allow Flask to start
    # time.sleep(2)

    try:
        url = '' #http://127.0.0.1:8000
        # webview.create_window("My App", url)
        # webview.start()
    except Exception as e:
        print(f"Failed to open embedded webview: {e}")
