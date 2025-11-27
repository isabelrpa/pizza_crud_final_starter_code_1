import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

# Initialize Flask app
app = Flask(__name__)

# Database setup
DB_PATH = os.path.join('data', 'pizzas.db')

# Create data directory if it doesn't exist
if not os.path.exists('data'):
    os.makedirs('data')

def get_db_connection():
    """Get a connection to the database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create database tables if they don't exist"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create Pizza table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS Pizza (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL
            )
        ''')
        
        # Create Order table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS "Order" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pizza_id INTEGER,
                quantity INTEGER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pizza_id) REFERENCES Pizza (id)
            )
        ''')
        
        # Add sample pizzas if table is empty
        cursor.execute('SELECT COUNT(*) FROM Pizza')
        if cursor.fetchone()[0] == 0:
            sample_pizzas = [
                ('Pepperoni', 13.99),      # Move Pepperoni first with correct price
                ('Margherita', 14.99),
                ('Hawaiian', 99.99),
                ('Vegetarian', 12.99),
                ('Supreme', 14.99),
                ('BBQ Chicken', 13.99),
                ('Meat Lovers', 15.99),
                ('Buffalo', 16.99)
            ]
            cursor.executemany('INSERT INTO Pizza (name, price) VALUES (?, ?)', sample_pizzas)
            conn.commit()
    except Exception as e:
        print(f"Error initializing database: {e}")
        if 'conn' in locals():
            conn.rollback()
        raise
    finally:
        if 'conn' in locals():
            conn.close()

def get_all_pizzas():
    """Get all pizzas from the database"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, price FROM Pizza ORDER BY id')
        return cursor.fetchall()
    finally:
        conn.close()

def save_order(pizza_id, quantity, customer_name, promo_code_id=None):
    """Save order to database and return order ID"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            'INSERT INTO "Order" (pizza_id, quantity, customer_name, order_date, promo_code_id) VALUES (?, ?, ?, ?, ?)',
            (pizza_id, quantity, customer_name, current_time, promo_code_id)
        )
        order_id = cursor.lastrowid
        conn.commit()
        return order_id
    finally:
        conn.close()

def get_order_details(order_id):
    """Get order details from database"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT o.id, p.name, p.price, o.quantity, pc.code, pc.discount_percent, o.customer_name
            FROM "Order" o
            JOIN Pizza p ON o.pizza_id = p.id
            LEFT JOIN PromoCode pc ON o.promo_code_id = pc.id
            WHERE o.id = ?
        ''', (order_id,))
        return cursor.fetchone()
    finally:
        conn.close()

# Routes
@app.route('/')
def menu():
    """Show the pizza menu and order form"""
    pizzas = get_all_pizzas()
    return render_template('menu.html', pizzas=pizzas)

@app.route('/order', methods=['POST'])
def create_order():
    """Process the pizza order"""
    pizza_id = request.form.get('pizza_id')
    quantity = request.form.get('quantity')
    customer_name = request.form.get('customer_name')
    promo_code = request.form.get('promo_code')
    
    print(f"DEBUG - customer_name received: '{customer_name}'")
    
    if not pizza_id or not quantity or not customer_name:
        return redirect(url_for('menu'))
    
    # Look up promo code ID if provided
    promo_code_id = None
    if promo_code:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM PromoCode WHERE code = ?', (promo_code.upper(),))
            result = cursor.fetchone()
            if result:
                promo_code_id = result[0]
        finally:
            conn.close()
    
    order_id = save_order(pizza_id, quantity, customer_name, promo_code_id)
    return redirect(url_for('confirmation', order_id=order_id))

@app.route('/confirmation')
def confirmation():
    """Show order confirmation"""
    order_id = request.args.get('order_id')
    if not order_id:
        return redirect(url_for('menu'))
        
    order = get_order_details(order_id)
    if not order:
        return redirect(url_for('menu'))
    
    subtotal = order[2] * order[3]
    discount_percent = order[5] if order[5] else 0
    discount_amount = subtotal * (discount_percent / 100)
    discounted_total = subtotal - discount_amount
        
    order_data = {
        'order_id': order[0],
        'pizza_name': order[1],
        'price': order[2],
        'quantity': order[3],
        'promo_code': order[4] if order[4] else 'None',
        'discount_percent': order[5] if order[5] else None,
        'total': subtotal,
        'discount_amount': discount_amount,
        'discounted_total': discounted_total
    }
    
    return render_template('confirmation.html', 
                         order=order_data, 
                         display_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

def migrate_order_table():
    """Migrate Order table to add customer_name and promo_code_id"""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Check if migration is needed
        cursor.execute("PRAGMA table_info(\"Order\")")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'customer_name' not in columns:
            print("Migrating Order table...")
            
            # Create new table with updated schema
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS "Order_new" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pizza_id INTEGER,
                    quantity INTEGER NOT NULL,
                    customer_name TEXT NOT NULL,
                    order_date TEXT NOT NULL,
                    promo_code_id INTEGER,
                    FOREIGN KEY (pizza_id) REFERENCES Pizza(id),
                    FOREIGN KEY (promo_code_id) REFERENCES PromoCode(id)
                )
            ''')
            
            # Copy existing data (if any)
            cursor.execute('''
                INSERT INTO "Order_new" (id, pizza_id, quantity, customer_name, order_date, promo_code_id)
                SELECT id, pizza_id, quantity, 'Unknown', order_date, NULL
                FROM "Order"
            ''')
            
            # Drop old table and rename new one
            cursor.execute('DROP TABLE "Order"')
            cursor.execute('ALTER TABLE "Order_new" RENAME TO "Order"')
            
            conn.commit()
            print("Order table migration complete")
        else:
            print("Order table already migrated")
            
    except Exception as e:
        print(f"Error migrating Order table: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    init_db()
    migrate_order_table()
    app.run(debug=True, host='0.0.0.0', port=5001)
