from flask import Flask, render_template, request, redirect, session, url_for, jsonify, flash
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import datetime

app = Flask(__name__)
app.secret_key = "vendify-sec-key"

# ====================== CONFIG ======================
UPLOAD_FOLDER = 'static/uploads/products'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# DATABASE
engine = create_engine(
    "mysql+pymysql://root:cset155@localhost/multi_vendor_ecommerce",
    echo=False,
    pool_pre_ping=True
)

def get_db():
    return engine.connect()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ====================== ROUTES ======================

@app.route('/')
def index():
    with get_db() as conn:
        featured = conn.execute(text("SELECT * FROM products ORDER BY product_id DESC LIMIT 8")).fetchall()
        on_sale = conn.execute(text("SELECT * FROM products WHERE sale_price IS NOT NULL LIMIT 6")).fetchall()
    return render_template('index.html', products=featured, on_sale=on_sale)

# ====================== AUTH ======================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form['username']
            email = request.form['email']
            password = request.form['password']
            user_type = request.form.get('user_type', 'customer')

            with get_db() as conn:
                if conn.execute(text("SELECT 1 FROM users WHERE username=:u OR email=:e"),
                               {"u": username, "e": email}).fetchone():
                    flash("Username or Email already taken!", "danger")
                    return redirect(url_for('register'))

                hashed = generate_password_hash(password)
                conn.execute(text("""
                    INSERT INTO users (username, email, password_hash, user_type)
                    VALUES (:u, :e, :p, :t)
                """), {"u": username, "e": email, "p": hashed, "t": user_type})
                conn.commit()

            flash("Registration successful! Please log in.", "success")
            return redirect(url_for('login'))
        except Exception:
            flash("Registration failed.", "danger")
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            cred = request.form['username']
            pw = request.form['password']
            with get_db() as conn:
                user = conn.execute(text("SELECT * FROM users WHERE username = :c OR email = :c"),
                                  {"c": cred}).fetchone()

            if user and check_password_hash(user.password_hash, pw):
                session['user_id'] = user.user_id
                session['username'] = user.username
                session['user_type'] = user.user_type
                return redirect(url_for('index'))

            flash("Invalid username or password", "danger")
        except Exception:
            flash("Login error occurred", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ====================== PUBLIC PRODUCTS ======================
@app.route('/products')
def products_page():
    search = request.args.get('search', '')
    with get_db() as conn:
        if search:
            prods = conn.execute(text("SELECT * FROM products WHERE title LIKE :s"), {"s": f"%{search}%"}).fetchall()
        else:
            prods = conn.execute(text("SELECT * FROM products")).fetchall()
    return render_template('products.html', products=prods)

@app.route('/product/<int:pid>')
def product_detail(pid):
    with get_db() as conn:
        product = conn.execute(text("SELECT * FROM products WHERE product_id = :id"), {"id": pid}).fetchone()
    return render_template('product_detail.html', product=product)

# ====================== VENDOR SECTION ======================
@app.route('/vendor/products')
def vendor_products():
    if session.get('user_type') != 'vendor':
        flash("Unauthorized access", "danger")
        return redirect(url_for('index'))
    with get_db() as conn:
        prods = conn.execute(text("SELECT * FROM products WHERE vendor_id = :vid"),
                           {"vid": session['user_id']}).fetchall()
    return render_template('vendor_products.html', products=prods)

@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if session.get('user_type') != 'vendor':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            image_filename = None
            image = request.files.get('image')
            if image and image.filename and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                image_filename = f"{int(datetime.datetime.now().timestamp())}_{filename}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

            sale_price = request.form.get('sale_price')
            sale_price = float(sale_price) if sale_price and sale_price.strip() else None

            with get_db() as conn:
                conn.execute(text("""
                    INSERT INTO products (title, price, sale_price, inventory, description, image, vendor_id)
                    VALUES (:t, :p, :sp, :i, :d, :img, :v)
                """), {
                    "t": request.form['title'],
                    "p": float(request.form['price']),
                    "sp": sale_price,
                    "i": int(request.form.get('inventory', 0)),
                    "d": request.form.get('description', ''),
                    "img": image_filename,
                    "v": session['user_id']
                })
                conn.commit()
            flash("Product added successfully!", "success")
            return redirect(url_for('vendor_products'))
        except Exception as e:
            flash(f"Error adding product: {str(e)}", "danger")
    return render_template('add_product.html')

@app.route('/edit-product/<int:pid>', methods=['GET', 'POST'])
def edit_product(pid):
    if session.get('user_type') != 'vendor':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            image_filename = None
            image = request.files.get('image')
            if image and image.filename and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                image_filename = f"{int(datetime.datetime.now().timestamp())}_{filename}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

            sale_price = request.form.get('sale_price')
            sale_price = float(sale_price) if sale_price and sale_price.strip() else None

            with get_db() as conn:
                if image_filename:
                    conn.execute(text("""
                        UPDATE products 
                        SET title=:t, price=:p, sale_price=:sp, inventory=:i, description=:d, image=:img
                        WHERE product_id=:id AND vendor_id=:vid
                    """), {
                        "t": request.form['title'], "p": float(request.form['price']),
                        "sp": sale_price, "i": int(request.form.get('inventory', 0)),
                        "d": request.form.get('description', ''), "img": image_filename,
                        "id": pid, "vid": session['user_id']
                    })
                else:
                    conn.execute(text("""
                        UPDATE products 
                        SET title=:t, price=:p, sale_price=:sp, inventory=:i, description=:d
                        WHERE product_id=:id AND vendor_id=:vid
                    """), {
                        "t": request.form['title'], "p": float(request.form['price']),
                        "sp": sale_price, "i": int(request.form.get('inventory', 0)),
                        "d": request.form.get('description', ''), "id": pid, "vid": session['user_id']
                    })
                conn.commit()
            flash("Product updated successfully!", "success")
            return redirect(url_for('vendor_products'))
        except Exception as e:
            flash(f"Error updating product: {str(e)}", "danger")

    with get_db() as conn:
        product = conn.execute(text("SELECT * FROM products WHERE product_id = :id AND vendor_id = :vid"),
                             {"id": pid, "vid": session['user_id']}).fetchone()
    return render_template('edit_product.html', product=product)

@app.route('/delete-product/<int:pid>')
def delete_product(pid):
    if session.get('user_type') != 'vendor':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))
    with get_db() as conn:
        conn.execute(text("DELETE FROM products WHERE product_id=:id AND vendor_id=:vid"),
                   {"id": pid, "vid": session['user_id']})
        conn.commit()
    flash("Product deleted", "success")
    return redirect(url_for('vendor_products'))

# ====================== CART ======================
@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    with get_db() as conn:
        items = conn.execute(text("""
            SELECT c.*, p.title, p.price, p.sale_price, p.image 
            FROM cart_items c 
            JOIN products p ON c.product_id = p.product_id 
            WHERE c.user_id = :uid
        """), {"uid": session['user_id']}).fetchall()
    total = sum((float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/add/<int:pid>', methods=['POST'])
def add_to_cart(pid):
    if 'user_id' not in session:
        return jsonify({"error": "login"}), 401
    with get_db() as conn:
        conn.execute(text("""
            INSERT INTO cart_items (user_id, product_id, quantity) 
            VALUES (:uid, :pid, 1)
            ON DUPLICATE KEY UPDATE quantity = quantity + 1
        """), {"uid": session['user_id'], "pid": pid})
        conn.commit()
    return jsonify({"success": True})

@app.route('/cart/remove/<int:pid>', methods=['POST'])
def remove_from_cart(pid):
    if 'user_id' not in session:
        return jsonify({"error": "login"}), 401
    with get_db() as conn:
        conn.execute(text("UPDATE cart_items SET quantity = quantity - 1 WHERE user_id = :uid AND product_id = :pid AND quantity > 0"),
                    {"uid": session['user_id'], "pid": pid})
        conn.execute(text("DELETE FROM cart_items WHERE user_id = :uid AND product_id = :pid AND quantity <= 0"),
                    {"uid": session['user_id'], "pid": pid})
        conn.commit()
    return jsonify({"success": True})

# ====================== CHECKOUT & ORDERS ======================
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            with get_db() as conn:
                items = conn.execute(text("""
                    SELECT c.product_id, c.quantity, p.price, p.sale_price 
                    FROM cart_items c 
                    JOIN products p ON c.product_id = p.product_id 
                    WHERE c.user_id = :uid
                """), {"uid": session['user_id']}).fetchall()

                total = sum((float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)

                result = conn.execute(text("""
                    INSERT INTO orders (user_id, total_amount, status, order_date)
                    VALUES (:uid, :total, 'pending', NOW())
                """), {"uid": session['user_id'], "total": total})
                order_id = result.lastrowid

                # Reduce stock
                for item in items:
                    conn.execute(text("UPDATE products SET inventory = inventory - :qty WHERE product_id = :pid"),
                               {"qty": item.quantity, "pid": item.product_id})

                # Clear cart
                conn.execute(text("DELETE FROM cart_items WHERE user_id = :uid"), {"uid": session['user_id']})
                conn.commit()

            flash(f"Order #{order_id} placed successfully!", "success")
            return redirect(url_for('my_orders'))
        except Exception as e:
            flash("Failed to place order. Please try again.", "danger")
            return redirect(url_for('cart'))

    # GET request
    with get_db() as conn:
        items = conn.execute(text("""
            SELECT c.*, p.title, p.price, p.sale_price, p.image 
            FROM cart_items c JOIN products p ON c.product_id = p.product_id 
            WHERE c.user_id = :uid
        """), {"uid": session['user_id']}).fetchall()
    total = sum((float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)
    return render_template('checkout.html', items=items, total=total)

@app.route('/orders')
def my_orders():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    with get_db() as conn:
        orders = conn.execute(text("SELECT * FROM orders WHERE user_id = :uid ORDER BY order_date DESC"),
                            {"uid": session['user_id']}).fetchall()
    return render_template('orders.html', orders=orders)

# ====================== CHAT (Fixed) ======================
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            receiver_id = int(request.form.get('receiver_id'))
            message_text = request.form.get('message', '').strip()
            if receiver_id and message_text:
                with get_db() as conn:
                    conn.execute(text("""
                        INSERT INTO messages (sender_id, receiver_id, message_text, sent_at)
                        VALUES (:sender, :receiver, :msg, NOW())
                    """), {
                        "sender": session['user_id'],
                        "receiver": receiver_id,
                        "msg": message_text
                    })
                    conn.commit()
                flash("Message sent!", "success")
        except Exception:
            flash("Failed to send message", "danger")

    # Load page
    with get_db() as conn:
        vendors = conn.execute(text("SELECT user_id, username FROM users WHERE user_type = 'vendor'")).fetchall()
        messages = conn.execute(text("""
            SELECT m.*, u.username as other_user 
            FROM messages m
            JOIN users u ON (CASE WHEN m.sender_id = :uid THEN m.receiver_id ELSE m.sender_id END) = u.user_id
            WHERE m.sender_id = :uid OR m.receiver_id = :uid
            ORDER BY m.sent_at DESC LIMIT 50
        """), {"uid": session['user_id']}).fetchall()

    return render_template('chat.html', vendors=vendors, messages=messages)

# ====================== COMPLAINTS ======================
@app.route('/complaints', methods=['GET', 'POST'])
def complaints_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        with get_db() as conn:
            conn.execute(text("""
                INSERT INTO complaints (user_id, title, description, demand_type, status)
                VALUES (:uid, :t, :d, :dt, 'pending')
            """), {
                "uid": session['user_id'],
                "t": request.form['title'],
                "d": request.form['description'],
                "dt": request.form['demand_type']
            })
            conn.commit()
        flash("Complaint submitted successfully!", "success")
        return redirect(url_for('complaints_page'))

    with get_db() as conn:
        complaints = conn.execute(text("SELECT * FROM complaints WHERE user_id = :uid ORDER BY created_at DESC"),
                                {"uid": session['user_id']}).fetchall()
    return render_template('complaints.html', complaints=complaints)

# ====================== ADMIN ======================
@app.route('/admin')
def admin_dashboard():
    if session.get('user_type') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))
    with get_db() as conn:
        users = conn.execute(text("SELECT * FROM users")).fetchall()
    return render_template('admin_dashboard.html', users=users)

if __name__ == '__main__':
    app.run(debug=True)