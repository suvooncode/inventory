from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime
import uuid

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS categories (id TEXT PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS types (id TEXT PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS sizes (id TEXT PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS suppliers (id TEXT PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchases (
        id TEXT PRIMARY KEY, category_id TEXT, type_id TEXT, size_id TEXT, supplier_id TEXT,
        quantity INTEGER, price REAL, tax REAL, carry_cost REAL, extra_cost REAL, date TEXT,
        FOREIGN KEY (category_id) REFERENCES categories(id),
        FOREIGN KEY (type_id) REFERENCES types(id),
        FOREIGN KEY (size_id) REFERENCES sizes(id),
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS ready_to_sale (
        id TEXT PRIMARY KEY, purchase_id TEXT, quantity INTEGER, date TEXT,
        FOREIGN KEY (purchase_id) REFERENCES purchases(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
        id TEXT PRIMARY KEY, ready_to_sale_id TEXT, quantity INTEGER, date TEXT,
        FOREIGN KEY (ready_to_sale_id) REFERENCES ready_to_sale(id)
    )''')
    
    default_data = {
        'categories': ['Bra', 'Panty', 'Camisole', 'Nighty'],
        'types': ['Bad', 'Average', 'Good', 'Premium'],
        'sizes': ['XS | 75 cm | 30', 'S | 80 cm | 32', 'M | 85 cm | 34', 'L | 90 cm | 36', 
                 'XL | 95 cm | 38', 'XXL | 100 cm | 40'],
        'suppliers': ['Bhola', 'JTM', 'JMD', 'SUMON', 'SUVRO']
    }
    
    for table, names in default_data.items():
        for name in names:
            c.execute(f"SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?)", (name,))
            if not c.fetchone():
                c.execute(f"INSERT INTO {table} (id, name) VALUES (?, ?)", (str(uuid.uuid4()), name))
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/<table>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_table(table):
    if table not in ['categories', 'types', 'sizes', 'suppliers']:
        return jsonify({'error': 'Invalid table'}), 400
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute(f'SELECT * FROM {table}')
        items = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    
    if request.method == 'POST':
        data = request.json
        c.execute(f'SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?)', (data['name'],))
        if c.fetchone():
            conn.close()
            return jsonify({'error': f'{table[:-1]} with this name already exists'}), 400
        c.execute(f'INSERT INTO {table} (id, name) VALUES (?, ?)', (str(uuid.uuid4()), data['name']))
        conn.commit()
        conn.close()
        return jsonify({'message': f'{table[:-1]} added'})

    if request.method == 'PUT':
        data = request.json
        c.execute(f'SELECT 1 FROM {table} WHERE LOWER(name) = LOWER(?) AND id != ?', 
                 (data['name'], data['id']))
        if c.fetchone():
            conn.close()
            return jsonify({'error': f'{table[:-1]} with this name already exists'}), 400
        c.execute(f'UPDATE {table} SET name = ? WHERE id = ?', (data['name'], data['id']))
        conn.commit()
        conn.close()
        return jsonify({'message': f'{table[:-1]} updated'})

    if request.method == 'DELETE':
        data = request.json
        c.execute(f'SELECT 1 FROM purchases WHERE {table[:-1]}_id = ?', (data['id'],))
        if c.fetchone():
            conn.close()
            return jsonify({'error': f'Cannot delete {table[:-1]} used in purchases'}), 400
        c.execute(f'DELETE FROM {table} WHERE id = ?', (data['id'],))
        conn.commit()
        conn.close()
        return jsonify({'message': f'{table[:-1]} deleted'})

@app.route('/api/<table>/merge', methods=['POST'])
def merge_table(table):
    if table not in ['categories', 'types', 'sizes', 'suppliers']:
        return jsonify({'error': 'Invalid table'}), 400
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    data = request.json
    keep_id = data['keep_id']
    merge_id = data['merge_id']
    
    if keep_id == merge_id:
        conn.close()
        return jsonify({'error': 'Cannot merge an item with itself'}), 400
    
    c.execute(f'SELECT 1 FROM {table} WHERE id = ?', (keep_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': f'Keep {table[:-1]} not found'}), 400
    
    c.execute(f'SELECT 1 FROM {table} WHERE id = ?', (merge_id,))
    if not c.fetchone():
        conn.close()
        return jsonify({'error': f'Merge {table[:-1]} not found'}), 400
    
    c.execute(f'UPDATE purchases SET {table[:-1]}_id = ? WHERE {table[:-1]}_id = ?', 
             (keep_id, merge_id))
    c.execute(f'DELETE FROM {table} WHERE id = ?', (merge_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': f'{table[:-1]} merged'})

@app.route('/api/purchases', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_purchases():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute('''SELECT p.id, c.name as category, t.name as type, s.name as size, 
                    su.name as supplier, p.quantity, p.price, p.tax, p.carry_cost, 
                    p.extra_cost, p.date
                    FROM purchases p
                    JOIN categories c ON p.category_id = c.id
                    JOIN types t ON p.type_id = t.id
                    JOIN sizes s ON p.size_id = s.id
                    JOIN suppliers su ON p.supplier_id = su.id''')
        purchases = [dict(zip(['id', 'category', 'type', 'size', 'supplier', 'quantity', 
                             'price', 'tax', 'carry_cost', 'extra_cost', 'date'], row)) 
                    for row in c.fetchall()]
        conn.close()
        return jsonify(purchases)
    
    if request.method == 'POST':
        data = request.json
        c.execute('''INSERT INTO purchases (id, category_id, type_id, size_id, supplier_id, 
                    quantity, price, tax, carry_cost, extra_cost, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                 (str(uuid.uuid4()), data['category_id'], data['type_id'], data['size_id'], 
                  data['supplier_id'], data['quantity'], data.get('price', 0), 
                  data.get('tax', 0), data.get('carry_cost', 0), data.get('extra_cost', 0), 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Purchase added'})

    if request.method == 'PUT':
        data = request.json
        c.execute('''SELECT COALESCE(SUM(r.quantity), 0) FROM ready_to_sale r WHERE r.purchase_id = ?''', 
                 (data['id'],))
        ready_qty = c.fetchone()[0]
        if data['quantity'] < ready_qty:
            conn.close()
            return jsonify({'error': 'Quantity cannot be less than Ready to Sale quantity'}), 400
        c.execute('''UPDATE purchases SET category_id = ?, type_id = ?, size_id = ?, supplier_id = ?, 
                    quantity = ?, price = ?, tax = ?, carry_cost = ?, extra_cost = ?, date = ?
                    WHERE id = ?''',
                 (data['category_id'], data['type_id'], data['size_id'], data['supplier_id'], 
                  data['quantity'], data.get('price', 0), data.get('tax', 0), 
                  data.get('carry_cost', 0), data.get('extra_cost', 0), 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Purchase updated'})

    if request.method == 'DELETE':
        data = request.json
        c.execute('SELECT 1 FROM ready_to_sale WHERE purchase_id = ?', (data['id'],))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Cannot delete purchase used in Ready to Sale'}), 400
        c.execute('DELETE FROM purchases WHERE id = ?', (data['id'],))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Purchase deleted'})

@app.route('/api/ready_to_sale', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_ready_to_sale():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute('''
            SELECT r.id, p.id as purchase_id, c.name as category, t.name as type, 
                s.name as size, su.name as supplier, r.quantity, r.date
            FROM ready_to_sale r
            JOIN purchases p ON r.purchase_id = p.id
            JOIN categories c ON p.category_id = c.id
            JOIN types t ON p.type_id = t.id
            JOIN sizes s ON p.size_id = s.id
            JOIN suppliers su ON p.supplier_id = su.id
            LEFT JOIN sales sa ON sa.ready_to_sale_id = r.id
            GROUP BY r.id
            HAVING r.quantity > COALESCE(SUM(sa.quantity), 0)
        ''')
        items = [dict(zip(['id', 'purchase_id', 'category', 'type', 'size', 'supplier', 
                        'quantity', 'date'], row)) for row in c.fetchall()]
        conn.close()
        return jsonify(items)

    
    if request.method == 'POST':
        data = request.json
        c.execute('''SELECT p.quantity, COALESCE(SUM(r.quantity), 0) as ready_qty
                    FROM purchases p
                    LEFT JOIN ready_to_sale r ON r.purchase_id = p.id
                    WHERE p.id = ?
                    GROUP BY p.id''', (data['purchase_id'],))
        purchase = c.fetchone()
        if not purchase:
            conn.close()
            return jsonify({'error': 'Invalid purchase_id'}), 400
        temp_inventory = purchase[0] - purchase[1]
        if data['quantity'] > temp_inventory:
            conn.close()
            return jsonify({'error': 'Quantity exceeds available inventory'}), 400
        c.execute('''INSERT INTO ready_to_sale (id, purchase_id, quantity, date)
                    VALUES (?, ?, ?, ?)''',
                 (str(uuid.uuid4()), data['purchase_id'], data['quantity'], 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Added to Ready to Sale'})

    if request.method == 'PUT':
        data = request.json
        c.execute('''SELECT p.quantity, COALESCE(SUM(r.quantity), 0) as ready_qty, 
                    COALESCE(SUM(s.quantity), 0) as sale_qty
                    FROM ready_to_sale r
                    JOIN purchases p ON r.purchase_id = p.id
                    LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                    WHERE r.id = ?
                    GROUP BY p.id''', (data['id'],))
        result = c.fetchone()
        if not result:
            conn.close()
            return jsonify({'error': 'Invalid ready_to_sale_id'}), 400
        temp_inventory = result[0] - result[1] + result[2]
        if data['quantity'] > temp_inventory:
            conn.close()
            return jsonify({'error': 'Quantity exceeds available inventory'}), 400
        if data['quantity'] < result[2]:
            conn.close()
            return jsonify({'error': 'Quantity cannot be less than sold quantity'}), 400
        c.execute('''UPDATE ready_to_sale SET quantity = ?, date = ? WHERE id = ?''',
                 (data['quantity'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Ready to Sale updated'})

    if request.method == 'DELETE':
        data = request.json
        c.execute('SELECT 1 FROM sales WHERE ready_to_sale_id = ?', (data['id'],))
        if c.fetchone():
            conn.close()
            return jsonify({'error': 'Cannot delete Ready to Sale used in Sales'}), 400
        c.execute('DELETE FROM ready_to_sale WHERE id = ?', (data['id'],))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Ready to Sale deleted'})

@app.route('/api/sales', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_sales():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute('''SELECT s.id, r.id as ready_to_sale_id, c.name as category, t.name as type, 
                    sz.name as size, su.name as supplier, s.quantity, s.date
                    FROM sales s
                    JOIN ready_to_sale r ON s.ready_to_sale_id = r.id
                    JOIN purchases p ON r.purchase_id = p.id
                    JOIN categories c ON p.category_id = c.id
                    JOIN types t ON p.type_id = t.id
                    JOIN sizes sz ON p.size_id = sz.id
                    JOIN suppliers su ON p.supplier_id = su.id''')
        items = [dict(zip(['id', 'ready_to_sale_id', 'category', 'type', 'size', 'supplier', 
                          'quantity', 'date'], row)) for row in c.fetchall()]
        conn.close()
        return jsonify(items)
    
    if request.method == 'POST':
        data = request.json
        c.execute('''SELECT r.id, r.quantity, COALESCE(SUM(s.quantity), 0) as sale_qty
                    FROM ready_to_sale r
                    LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                    WHERE r.id = ?
                    GROUP BY r.id''', (data['ready_to_sale_id'],))
        ready = c.fetchone()
        if not ready:
            conn.close()
            return jsonify({'error': 'Invalid ready_to_sale_id'}), 400
        ready_inventory = ready[1] - ready[2]
        if data['quantity'] > ready_inventory:
            conn.close()
            return jsonify({'error': 'Quantity exceeds available inventory'}), 400
        c.execute('''INSERT INTO sales (id, ready_to_sale_id, quantity, date)
                    VALUES (?, ?, ?, ?)''',
                 (str(uuid.uuid4()), data['ready_to_sale_id'], data['quantity'], 
                  datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sale recorded'})

    if request.method == 'PUT':
        data = request.json
        c.execute('''SELECT r.quantity, COALESCE(SUM(s.quantity), 0) as sale_qty
                    FROM ready_to_sale r
                    LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                    WHERE r.id = (SELECT ready_to_sale_id FROM sales WHERE id = ?)
                    GROUP BY r.id''', (data['id'],))
        ready = c.fetchone()
        if not ready:
            conn.close()
            return jsonify({'error': 'Invalid sale_id'}), 400
        ready_inventory = ready[0] - ready[1]
        if data['quantity'] > ready_inventory:
            conn.close()
            return jsonify({'error': 'Quantity exceeds available inventory'}), 400
        c.execute('''UPDATE sales SET quantity = ?, date = ? WHERE id = ?''',
                 (data['quantity'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), data['id']))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sale updated'})

    if request.method == 'DELETE':
        data = request.json
        c.execute('DELETE FROM sales WHERE id = ?', (data['id'],))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Sale deleted'})

@app.route('/api/inventory_summary', methods=['GET'])
def inventory_summary():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    c.execute('''SELECT p.id, c.name as category, t.name as type, sz.name as size, 
                su.name as supplier, p.quantity as purchase_qty,
                COALESCE(SUM(r.quantity), 0) as ready_qty,
                COALESCE(SUM(s.quantity), 0) as sale_qty
                FROM purchases p
                JOIN categories c ON p.category_id = c.id
                JOIN types t ON p.type_id = t.id
                JOIN sizes sz ON p.size_id = sz.id
                JOIN suppliers su ON p.supplier_id = su.id
                LEFT JOIN ready_to_sale r ON r.purchase_id = p.id
                LEFT JOIN sales s ON s.ready_to_sale_id = r.id
                GROUP BY p.id, c.name, t.name, sz.name, su.name''')
    
    summary = []
    for row in c.fetchall():
        temp_inventory = row[5] - row[6]  # Purchase - Ready to Sale
        ready_inventory = row[6] - row[7]  # Ready to Sale - Sale
        summary.append({
            'purchase_id': row[0], 'category': row[1], 'type': row[2], 'size': row[3],
            'supplier': row[4], 'purchase_qty': row[5], 'ready_qty': row[6],
            'sale_qty': row[7], 'temp_inventory': temp_inventory, 'ready_inventory': ready_inventory
        })
    
    conn.close()
    return jsonify(summary)

@app.route('/api/report', methods=['GET'])
def get_report():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    
    c.execute('''SELECT 
    c.name AS category,
    t.name AS type,
    sz.name AS size,
    su.name AS supplier,
    COALESCE(p.total_purchase, 0) AS total_purchase,
    COALESCE(r.total_ready, 0) AS total_ready,
    COALESCE(s.total_sale, 0) AS total_sale,
    COALESCE(p.total_purchase, 0) - COALESCE(s.total_sale, 0) AS inventory,
    COALESCE(r.total_ready, 0) - COALESCE(s.total_sale, 0) AS temporary_inventory,
    COALESCE(p.total_purchase, 0) - (COALESCE(r.total_ready, 0) - COALESCE(s.total_sale, 0)) AS temporary_purchase_stock
FROM categories c
CROSS JOIN types t
CROSS JOIN sizes sz
CROSS JOIN suppliers su
LEFT JOIN (
    SELECT 
        category_id, 
        type_id, 
        size_id, 
        supplier_id, 
        SUM(quantity) AS total_purchase
    FROM purchases
    GROUP BY category_id, type_id, size_id, supplier_id
) p ON p.category_id = c.id AND p.type_id = t.id AND p.size_id = sz.id AND p.supplier_id = su.id
LEFT JOIN (
    SELECT 
        p.category_id, 
        p.type_id, 
        p.size_id, 
        p.supplier_id, 
        SUM(r.quantity) AS total_ready
    FROM ready_to_sale r
    JOIN purchases p ON r.purchase_id = p.id
    GROUP BY p.category_id, p.type_id, p.size_id, p.supplier_id
) r ON r.category_id = c.id AND r.type_id = t.id AND r.size_id = sz.id AND r.supplier_id = su.id
LEFT JOIN (
    SELECT 
        p.category_id, 
        p.type_id, 
        p.size_id, 
        p.supplier_id, 
        SUM(s.quantity) AS total_sale
    FROM sales s
    JOIN ready_to_sale r ON s.ready_to_sale_id = r.id
    JOIN purchases p ON r.purchase_id = p.id
    GROUP BY p.category_id, p.type_id, p.size_id, p.supplier_id
) s ON s.category_id = c.id AND s.type_id = t.id AND s.size_id = sz.id AND s.supplier_id = su.id
WHERE COALESCE(p.total_purchase, 0) > 0;''')
    
    report = []
    for row in c.fetchall():
        total_purchase = row[4]
        total_ready = row[5]
        total_sale = row[6]
        inventory = total_purchase - total_sale
        temporary_inventory = total_ready - total_sale
        temporary_purchase_stock = total_purchase - temporary_inventory
        report.append({
            'category': row[0], 'type': row[1], 'size': row[2], 'supplier': row[3],
            'total_purchase': total_purchase, 'total_ready': total_ready,
            'total_sale': total_sale, 'inventory': inventory, 
            'temporary_inventory': temporary_inventory,
            'temporary_purchase_stock': temporary_purchase_stock
        })
    
    conn.close()
    return jsonify(report)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8000, debug=True)