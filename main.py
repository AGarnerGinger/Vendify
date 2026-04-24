from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
import datetime

app = Flask(__name__)
app.secret_key = "vendify-sec-key"

# ===================== DATABASE =====================
engine = create_engine("mysql+pymysql://root:cset155@localhost/multi_vendor_ecommerce", echo=False)
conn = engine.connect()

# ===================== HELPERS =====================
def current_user():
    if 'user_id' in session:
        return conn.execute(text("SELECT * FROM users WHERE user_id = :id"),
                          {"id": session['user_id']}).fetchone()
    return None

# ===================== ROUTES =====================

@app.route('/')
def index():
    products = conn.execute(text("SELECT * FROM products LIMIT 12")).fetchall()
    return render_template('index.html', products=products)

# ------------------ AUTH ------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form.get('user_type', 'customer')

        if conn.execute(text("SELECT 1 FROM users WHERE username=:u OR email=:e"),
                       {"u": username, "e": email}).fetchone():
            return "Username or Email already taken!"

        hashed = generate_password_hash(password)
        conn.execute(text("""
            INSERT INTO users (username, email, password_hash, user_type)
            VALUES (:u, :e, :p, :t)
        """), {"u": username, "e": email, "p": hashed, "t": user_type})
        conn.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cred = request.form['username']
        pw = request.form['password']
        user = conn.execute(text("""
            SELECT * FROM users WHERE username = :c OR email = :c
        """), {"c": cred}).fetchone()
        if user and check_password_hash(user.password_hash, pw):
            session['user_id'] = user.user_id
            session['username'] = user.username
            session['user_type'] = user.user_type
            return redirect(url_for('index'))
        return "Invalid login"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ------------------ PRODUCTS ------------------
@app.route('/products')
def products_page():
    search = request.args.get('search', '')
    minp = request.args.get('min_price')
    maxp = request.args.get('max_price')
    q = "SELECT * FROM products WHERE 1=1"
    params = {}
    if search:
        q += " AND title LIKE :s"; params['s'] = f"%{search}%"
    if minp: q += " AND price >= :minp"; params['minp'] = minp
    if maxp: q += " AND price <= :maxp"; params['maxp'] = maxp
    prods = conn.execute(text(q), params).fetchall()
    return render_template('products.html', products=prods)

@app.route('/product/<int:pid>')
def product_detail(pid):
    p = conn.execute(text("SELECT * FROM products WHERE product_id = :id"), {"id": pid}).fetchone()
    return render_template('product_detail.html', product=p)

# ------------------ VENDOR ------------------
@app.route('/vendor/products')
def vendor_products():
    if session.get('user_type') != 'vendor': return "Unauthorized"
    prods = conn.execute(text("SELECT * FROM products WHERE vendor_id = :vid"),
                       {"vid": session['user_id']}).fetchall()
    return render_template('vendor_products.html', products=prods)

@app.route('/add-product', methods=['GET','POST'])
def add_product():
    if session.get('user_type') != 'vendor': return "Unauthorized"
    if request.method == 'POST':
        conn.execute(text("""
            INSERT INTO products (title, price, inventory, description, vendor_id)
            VALUES (:t, :p, :i, :d, :v)
        """), {
            "t": request.form['title'],
            "p": request.form['price'],
            "i": request.form['inventory'],
            "d": request.form.get('description',''),
            "v": session['user_id']
        })
        conn.commit()
        return redirect(url_for('vendor_products'))
    return render_template('add_product.html')

@app.route('/edit-product/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    if session.get('user_type') != 'vendor': return "Unauthorized"
    if request.method == 'POST':
        conn.execute(text("""
            UPDATE products SET title=:t, price=:p, inventory=:i, description=:d
            WHERE product_id=:id AND vendor_id=:vid
        """), {**request.form, "id": pid, "vid": session['user_id']})
        conn.commit()
        return redirect(url_for('vendor_products'))
    p = conn.execute(text("SELECT * FROM products WHERE product_id=:id"), {"id": pid}).fetchone()
    return render_template('edit_product.html', product=p)

@app.route('/delete-product/<int:pid>')
def delete_product(pid):
    if session.get('user_type') != 'vendor': return "Unauthorized"
    conn.execute(text("DELETE FROM products WHERE product_id=:id AND vendor_id=:vid"),
               {"id": pid, "vid": session['user_id']})
    conn.commit()
    return redirect(url_for('vendor_products'))

# ------------------ CART ------------------
@app.route('/cart')
def cart():
    if 'user_id' not in session: return redirect('/login')
    items = conn.execute(text("""
        SELECT c.*, p.title, p.price FROM cart_items c 
        JOIN products p ON c.product_id = p.product_id 
        WHERE c.user_id = :uid
    """), {"uid": session['user_id']}).fetchall()
    return render_template('cart.html', items=items)

@app.route('/cart/add/<int:pid>', methods=['POST'])
def add_to_cart(pid):
    if 'user_id' not in session: return jsonify({"error":"login"}), 401
    conn.execute(text("""
        INSERT INTO cart_items (user_id, product_id, quantity) 
        VALUES (:uid, :pid, 1)
        ON DUPLICATE KEY UPDATE quantity = quantity + 1
    """), {"uid": session['user_id'], "pid": pid})
    conn.commit()
    return jsonify({"success": True})

# ------------------ ORDERS & CHECKOUT (Basic) ------------------
@app.route('/checkout', methods=['GET','POST'])
def checkout():
    if 'user_id' not in session: return redirect('/login')
    if request.method == 'POST':
        # Simple order creation logic (expandable)
        total = 100.0  # calculate properly in real version
        result = conn.execute(text("INSERT INTO orders (user_id, total_amount, status) VALUES (:u, :t, 'pending')"),
                            {"u": session['user_id'], "t": total})
        order_id = result.lastrowid
        # Move cart to order_items (logic omitted for brevity)
        return redirect(f'/orders')
    return render_template('checkout.html')

@app.route('/orders')
def my_orders():
    if 'user_id' not in session: return redirect('/login')
    orders = conn.execute(text("SELECT * FROM orders WHERE user_id = :uid"),
                        {"uid": session['user_id']}).fetchall()
    return render_template('orders.html', orders=orders)


# ====================== REVIEWS ======================
@app.route('/reviews')
def reviews():
    # Show all reviews or reviews for a product (simple version)
    reviews_list = conn.execute(text("""
        SELECT r.*, p.title as product_title, u.username 
        FROM reviews r 
        JOIN products p ON r.product_id = p.product_id 
        JOIN users u ON r.user_id = u.user_id 
        ORDER BY r.created_at DESC
    """)).fetchall()
    return render_template('reviews.html', reviews=reviews_list)


@app.route('/product/<int:pid>/review', methods=['POST'])
def add_review(pid):
    if 'user_id' not in session:
        return redirect('/login')
    rating = request.form.get('rating')
    description = request.form.get('description')
    if rating:
        conn.execute(text("""
            INSERT INTO reviews (product_id, user_id, rating, description)
            VALUES (:pid, :uid, :rating, :desc)
        """), {"pid": pid, "uid": session['user_id'], "rating": rating, "desc": description})
        conn.commit()
    return redirect(f'/product/{pid}')


# ====================== COMPLAINTS ======================
@app.route('/complaints', methods=['GET', 'POST'])
def complaints_page():
    if 'user_id' not in session:
        return redirect('/login')

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        demand_type = request.form['demand_type']

        conn.execute(text("""
            INSERT INTO complaints (user_id, title, description, demand_type)
            VALUES (:uid, :t, :d, :dt)
        """), {"uid": session['user_id'], "t": title, "d": description, "dt": demand_type})
        conn.commit()
        return redirect('/complaints')

    my_complaints = conn.execute(text("""
        SELECT * FROM complaints WHERE user_id = :uid ORDER BY created_at DESC
    """), {"uid": session['user_id']}).fetchall()

    return render_template('complaints.html', complaints=my_complaints)


# ====================== CHAT ======================
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        return redirect('/login')

    # Simple chat: show messages with all vendors + form to send to a vendor
    if request.method == 'POST':
        receiver_id = int(request.form['receiver_id'])
        message_text = request.form['message']
        conn.execute(text("""
            INSERT INTO messages (sender_id, receiver_id, message_text)
            VALUES (:sender, :receiver, :msg)
        """), {"sender": session['user_id'], "receiver": receiver_id, "msg": message_text})
        conn.commit()

    # Get vendors
    vendors = conn.execute(text("SELECT user_id, username FROM users WHERE user_type = 'vendor'")).fetchall()

    # Get recent messages for current user
    recent_messages = conn.execute(text("""
        SELECT m.*, u.username as other_user 
        FROM messages m
        JOIN users u ON (CASE WHEN m.sender_id = :uid THEN m.receiver_id ELSE m.sender_id END) = u.user_id
        WHERE m.sender_id = :uid OR m.receiver_id = :uid
        ORDER BY m.sent_at DESC LIMIT 20
    """), {"uid": session['user_id']}).fetchall()

    return render_template('chat.html', vendors=vendors, messages=recent_messages)

# ------------------ ADMIN ------------------
@app.route('/admin')
def admin_dashboard():
    if session.get('user_type') != 'admin': return "Unauthorized"
    users = conn.execute(text("SELECT * FROM users")).fetchall()
    return render_template('admin_dashboard.html', users=users)

# Run the app
if __name__ == '__main__':
    app.run(debug=True)