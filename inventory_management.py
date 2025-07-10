from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

# Database initialization
def init_db():
    with sqlite3.connect('inventory.db') as conn:
        c = conn.cursor()
        # Create tables
        c.execute('''CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS types (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sizes (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
        c.execute('''CREATE TABLE IF NOT EXISTS purchase (
            id INTEGER PRIMARY KEY, category_id INTEGER, type_id INTEGER, size_id INTEGER, 
            company_id INTEGER, quantity INTEGER, price REAL, date TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(type_id) REFERENCES types(id),
            FOREIGN KEY(size_id) REFERENCES sizes(id),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS ready_to_sale (
            id INTEGER PRIMARY KEY, category_id INTEGER, type_id INTEGER, size_id INTEGER, 
            company_id INTEGER, quantity INTEGER, price REAL, date TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(type_id) REFERENCES types(id),
            FOREIGN KEY(size_id) REFERENCES sizes(id),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS sale (
            id INTEGER PRIMARY KEY, category_id INTEGER, type_id INTEGER, size_id INTEGER, 
            company_id INTEGER, quantity INTEGER, price REAL, date TEXT,
            FOREIGN KEY(category_id) REFERENCES categories(id),
            FOREIGN KEY(type_id) REFERENCES types(id),
            FOREIGN KEY(size_id) REFERENCES sizes(id),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )''')
        # Insert default values
        default_categories = ['panty', 'camisole', 'churidar', 'bra']
        default_types = ['bad', 'average', 'good']
        default_sizes = ['XS | 75 cm | 30', 'S | 80 cm | 32', 'M | 85 cm | 34', 
                        'L | 90 cm | 36', 'XL | 95 cm | 38', 'XXL | 100 cm | 40']
        default_companies = ['JTM', 'JMD', 'SUVRO GOLD', 'SUMON', 'BHOLA']
        
        for cat in default_categories:
            c.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (cat,))
        for typ in default_types:
            c.execute("INSERT OR IGNORE INTO types (name) VALUES (?)", (typ,))
        for size in default_sizes:
            c.execute("INSERT OR IGNORE INTO sizes (name) VALUES (?)", (size,))
        for comp in default_companies:
            c.execute("INSERT OR IGNORE INTO companies (name) VALUES (?)", (comp,))
        conn.commit()

# Helper functions
def get_db_connection():
    conn = sqlite3.connect('inventory.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

# API endpoints for dropdown data
@app.route('/api/categories', methods=['GET', 'POST'])
def manage_categories():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
        c.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        conn.commit()
        return jsonify({'status': 'success'})
    c.execute("SELECT * FROM categories")
    categories = [row['name'] for row in c.fetchall()]
    conn.close()
    return jsonify(categories)

@app.route('/api/types', methods=['GET', 'POST'])
def manage_types():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
        c.execute("INSERT OR IGNORE INTO types (name) VALUES (?)", (name,))
        conn.commit()
        return jsonify({'status': 'success'})
    c.execute("SELECT * FROM types")
    types = [row['name'] for row in c.fetchall()]
    conn.close()
    return jsonify(types)

@app.route('/api/sizes', methods=['GET', 'POST'])
def manage_sizes():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
        c.execute("INSERT OR IGNORE INTO sizes (name) VALUES (?)", (name,))
        conn.commit()
        return jsonify({'status': 'success'})
    c.execute("SELECT * FROM sizes")
    sizes = [row['name'] for row in c.fetchall()]
    conn.close()
    return jsonify(sizes)

@app.route('/api/companies', methods=['GET', 'POST'])
def manage_companies():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
        c.execute("INSERT OR IGNORE INTO companies (name) VALUES (?)", (name,))
        conn.commit()
        return jsonify({'status': 'success'})
    c.execute("SELECT * FROM companies")
    companies = [row['name'] for row in c.fetchall()]
    conn.close()
    return jsonify(companies)

# API endpoints for bills
@app.route('/api/purchase', methods=['POST'])
def add_purchase():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO purchase (category_id, type_id, size_id, company_id, quantity, price, date)
                 VALUES ((SELECT id FROM categories WHERE name=?),
                         (SELECT id FROM types WHERE name=?),
                         (SELECT id FROM sizes WHERE name=?),
                         (SELECT id FROM companies WHERE name=?),
                         ?, ?, ?)''',
              (data['category'], data['type'], data['size'], data['company'], 
               data['quantity'], data.get('price', None), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/ready_to_sale', methods=['GET', 'POST'])
def manage_ready_to_sale():
    conn = get_db_connection()
    c = conn.cursor()
    if request.method == 'POST':
        data = request.json
        c.execute('''INSERT INTO ready_to_sale (category_id, type_id, size_id, company_id, quantity, price, date)
                     VALUES ((SELECT id FROM categories WHERE name=?),
                             (SELECT id FROM types WHERE name=?),
                             (SELECT id FROM sizes WHERE name=?),
                             (SELECT id FROM companies WHERE name=?),
                             ?, ?, ?)''',
                  (data['category'], data['type'], data['size'], data['company'], 
                   data['quantity'], data.get('price', None), datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'})
    c.execute('''SELECT r.id, c.name as category, t.name as type, s.name as size, 
                 co.name as company, r.quantity, r.price, r.date 
                 FROM ready_to_sale r
                 JOIN categories c ON r.category_id = c.id
                 JOIN types t ON r.type_id = t.id
                 JOIN sizes s ON r.size_id = s.id
                 JOIN companies co ON r.company_id = co.id''')
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(items)

@app.route('/api/sale', methods=['POST'])
def add_sale():
    data = request.json
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''INSERT INTO sale (category_id, type_id, size_id, company_id, quantity, price, date)
                 VALUES ((SELECT id FROM categories WHERE name=?),
                         (SELECT id FROM types WHERE name=?),
                         (SELECT id FROM sizes WHERE name=?),
                         (SELECT id FROM companies WHERE name=?),
                         ?, ?, ?)''',
              (data['category'], data['type'], data['size'], data['company'], 
               data['quantity'], data.get('price', None), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/api/soldout/<int:id>', methods=['POST'])
def soldout(id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT * FROM ready_to_sale WHERE id=?''', (id,))
    item = c.fetchone()
    if item:
        c.execute('''INSERT INTO sale (category_id, type_id, size_id, company_id, quantity, price, date)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (item['category_id'], item['type_id'], item['size_id'], item['company_id'], 
                   item['quantity'], item['price'], datetime.now().isoformat()))
        c.execute('DELETE FROM ready_to_sale WHERE id=?', (id,))
        conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

# API endpoints for views
@app.route('/api/view/ready_to_sale_minus_sale')
def view_ready_to_sale_minus_sale():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT c.name as category, t.name as type, s.name as size, co.name as company, 
                 SUM(r.quantity) - SUM(COALESCE(sl.quantity, 0)) as quantity
                 FROM ready_to_sale r
                 JOIN categories c ON r.category_id = c.id
                 JOIN types t ON r.type_id = t.id
                 JOIN sizes s ON r.size_id = s.id
                 JOIN companies co ON r.company_id = co.id
                 LEFT JOIN sale sl ON sl.category_id = r.category_id AND sl.type_id = r.type_id 
                 AND sl.size_id = r.size_id AND sl.company_id = r.company_id
                 GROUP BY c.name, t.name, s.name, co.name
                 HAVING quantity > 0''')
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(items)

@app.route('/api/view/purchase_minus_ready_to_sale')
def view_purchase_minus_ready_to_sale():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT c.name as category, t.name as type, s.name as size, co.name as company, 
                 SUM(p.quantity) - SUM(COALESCE(r.quantity, 0)) as quantity
                 FROM purchase p
                 JOIN categories c ON p.category_id = c.id
                 JOIN types t ON p.type_id = t.id
                 JOIN sizes s ON p.size_id = s.id
                 JOIN companies co ON p.company_id = co.id
                 LEFT JOIN ready_to_sale r ON r.category_id = p.category_id AND r.type_id = p.type_id 
                 AND r.size_id = p.size_id AND r.company_id = p.company_id
                 GROUP BY c.name, t.name, s.name, co.name
                 HAVING quantity > 0''')
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(items)

@app.route('/api/view/purchase_minus_sale')
def view_purchase_minus_sale():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT c.name as category, t.name as type, s.name as size, co.name as company, 
                 SUM(p.quantity) - SUM(COALESCE(sl.quantity, 0)) as quantity
                 FROM purchase p
                 JOIN categories c ON p.category_id = c.id
                 JOIN types t ON p.type_id = t.id
                 JOIN sizes s ON p.size_id = s.id
                 JOIN companies co ON p.company_id = co.id
                 LEFT JOIN sale sl ON sl.category_id = p.category_id AND sl.type_id = p.type_id 
                 AND sl.size_id = p.size_id AND sl.company_id = p.company_id
                 GROUP BY c.name, t.name, s.name, co.name
                 HAVING quantity > 0''')
    items = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(items)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)