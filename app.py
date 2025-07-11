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

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def init_db():
    with sqlite3.connect('inventory.db') as conn:
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
                invoice_no TEXT
            );
            CREATE TABLE IF NOT EXISTS invoice_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bill_id INTEGER,
                meta_key TEXT,
                meta_value TEXT,
                FOREIGN KEY (bill_id) REFERENCES invoices (bill_id)
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
    for i, line in enumerate(lines):
        if re.search(r'Description\s+HSN\s+Qty', line, re.IGNORECASE):
            if i + 1 < len(lines):
                name_line = lines[i + 1].strip()
                if re.search(r'\b(panty|camisole|bra|printed panty|nighty|leggings)\b', name_line, re.IGNORECASE):
                    return name_line
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


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/raw_sql', methods=['POST'])
def execute_raw_sql():
    data = request.json
    query = data.get('query')
    try:
        with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
            if not purchase:
                return jsonify({'error': 'Invalid purchase_id'}), 400
            available = purchase[0] + purchase[2] - purchase[1]
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
        c = conn.cursor()
        c.execute("SELECT id, category_id, type_id, size_id, supplier_id, quantity, date FROM purchases")
        return jsonify(c.fetchall())
    
@app.route('/debug/ready_to_sale', methods=['GET'])
def debug_ready_to_sale():
    with sqlite3.connect('inventory.db') as conn:
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
    
    with sqlite3.connect('inventory.db') as conn:
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
    
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
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
    with sqlite3.connect('inventory.db') as conn:
        c = conn.cursor()
        c.executescript('''CREATE TABLE IF NOT EXISTS invoices (
                bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_name TEXT,
                invoice_no TEXT
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
        for row in rows:
            print("-------------------check -1",row)
            invoice_no = row.get("Invoice No", "")
            pdf_name = row.get("AWB Number", "UNKNOWN_PDF")
            c.execute("INSERT INTO invoices (pdf_name, invoice_no) VALUES (?, ?)", (pdf_name, invoice_no))
            print("----execute")
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
    init_db()
    app.run(host='0.0.0.0', port=8000, debug=True)