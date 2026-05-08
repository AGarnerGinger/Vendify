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
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# DATABASE
engine = create_engine(
    "mysql+pymysql://root:DevonCSET155@localhost/multi_vendor_ecommerce",
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
        featured = conn.execute(text("""
            SELECT * FROM products 
            WHERE parent_product_id IS NULL 
            ORDER BY product_id DESC LIMIT 8
        """)).fetchall()

        on_sale = conn.execute(text("""
            SELECT * FROM products 
            WHERE parent_product_id IS NULL AND sale_price IS NOT NULL 
            LIMIT 6
        """)).fetchall()
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

            flash("Registration successful!", "success")
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

            flash("Invalid credentials", "danger")
        except Exception:
            flash("Login error", "danger")
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
            prods = conn.execute(text("""
                SELECT * FROM products 
                WHERE parent_product_id IS NULL 
                  AND title LIKE :s
            """), {"s": f"%{search}%"}).fetchall()
        else:
            prods = conn.execute(text("""
                SELECT * FROM products 
                WHERE parent_product_id IS NULL
            """)).fetchall()
    return render_template('products.html', products=prods)

@app.route('/product/<int:pid>')
def product_detail(pid):
    with get_db() as conn:
        # Main product
        product = conn.execute(text("SELECT * FROM products WHERE product_id = :id"),
                               {"id": pid}).fetchone()

        # Variants + base product
        variants = conn.execute(text("""
            SELECT * FROM products 
            WHERE (parent_product_id = :pid OR product_id = :pid)
              AND (variant_name IS NOT NULL OR product_id = :pid)
            ORDER BY variant_name IS NULL DESC, variant_name
        """), {"pid": pid}).fetchall()

    return render_template('product_detail.html', product=product, variants=variants)


# ====================== VENDOR ======================
@app.route('/vendor/products')
def vendor_products():
    if session.get('user_type') != 'vendor':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))
    with get_db() as conn:
        prods = conn.execute(text("""
            SELECT * FROM products 
            WHERE vendor_id = :vid 
              AND parent_product_id IS NULL
        """), {"vid": session['user_id']}).fetchall()
    return render_template('vendor_products.html', products=prods)

@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if session.get('user_type') != 'vendor':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            # Main product image
            main_image = None
            image = request.files.get('main_image')
            if image and image.filename and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                main_image = f"{int(datetime.datetime.now().timestamp())}_{filename}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], main_image))

            base_price = float(request.form['price'])
            base_sale_price = request.form.get('sale_price')
            base_sale_price = float(base_sale_price) if base_sale_price and base_sale_price.strip() else None

            with get_db() as conn:
                # Create main product
                result = conn.execute(text("""
                    INSERT INTO products (title, price, sale_price, inventory, description, image, vendor_id, variant_name, parent_product_id)
                    VALUES (:t, :p, :sp, 0, :d, :img, :v, NULL, NULL)
                """), {
                    "t": request.form['title'],
                    "p": base_price,
                    "sp": base_sale_price,
                    "d": request.form.get('description', ''),
                    "img": main_image,
                    "v": session['user_id']
                })
                main_product_id = result.lastrowid

                # Create variants (use same sale price as base)
                variant_names = request.form.getlist('variant_name[]')
                variant_prices = request.form.getlist('variant_price[]')
                variant_inventories = request.form.getlist('variant_inventory[]')
                variant_images = request.files.getlist('variant_image[]')

                for i, name in enumerate(variant_names):
                    name = name.strip()
                    if not name:
                        continue

                    v_price = float(variant_prices[i]) if variant_prices[i] and variant_prices[i].strip() else base_price
                    v_inventory = int(variant_inventories[i]) if i < len(variant_inventories) and variant_inventories[i].strip() else 10

                    v_image = None
                    if i < len(variant_images) and variant_images[i].filename and allowed_file(variant_images[i].filename):
                        fname = secure_filename(variant_images[i].filename)
                        v_image = f"{int(datetime.datetime.now().timestamp())}_{fname}"
                        variant_images[i].save(os.path.join(app.config['UPLOAD_FOLDER'], v_image))

                    conn.execute(text("""
                        INSERT INTO products (title, price, sale_price, inventory, description, image, vendor_id, variant_name, parent_product_id)
                        VALUES (:t, :p, :sp, :inv, :d, :img, :v, :vname, :parent)
                    """), {
                        "t": request.form['title'],
                        "p": v_price,
                        "sp": base_sale_price,          # ← Same sale price as base
                        "inv": v_inventory,
                        "d": request.form.get('description', ''),
                        "img": v_image or main_image,
                        "v": session['user_id'],
                        "vname": name,
                        "parent": main_product_id
                    })

                conn.commit()

            flash("Product and variants added successfully!", "success")
            return redirect(url_for('vendor_products'))

        except Exception as e:
            flash(f"Error adding product: {str(e)}", "danger")
            print("Error:", str(e))

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
                        UPDATE products SET title=:t, price=:p, sale_price=:sp, inventory=:i, description=:d, image=:img
                        WHERE product_id=:id AND vendor_id=:vid
                    """), {
                        "t": request.form['title'], "p": float(request.form['price']),
                        "sp": sale_price, "i": int(request.form.get('inventory', 0)),
                        "d": request.form.get('description', ''), "img": image_filename,
                        "id": pid, "vid": session['user_id']
                    })
                else:
                    conn.execute(text("""
                        UPDATE products SET title=:t, price=:p, sale_price=:sp, inventory=:i, description=:d
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
            SELECT 
                c.*,
                p.title,
                p.price,
                p.sale_price,
                p.image,
                p.variant_name,
                p.parent_product_id
            FROM cart_items c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_id = :uid
        """), {"uid": session['user_id']}).fetchall()

    # Calculate total
    total = 0
    for item in items:
        price = float(item.sale_price) if item.sale_price else float(item.price)
        total += price * item.quantity

    return render_template('cart.html', items=items, total=total)


@app.route('/cart/add/<int:pid>', methods=['POST'])
def add_to_cart(pid):
    if 'user_id' not in session:
        return jsonify({"error": "login"}), 401

    with get_db() as conn:
        try:
            conn.execute(text("""
                INSERT INTO cart_items (user_id, product_id, quantity)
                VALUES (:uid, :pid, 1)
                ON DUPLICATE KEY UPDATE quantity = quantity + 1
            """), {"uid": session['user_id'], "pid": pid})
            conn.commit()
            return jsonify({"success": True})
        except Exception as e:
            print("Cart Error:", str(e))
            return jsonify({"error": str(e)}), 500


@app.route('/cart/remove/<int:pid>', methods=['POST'])
def remove_from_cart(pid):
    if 'user_id' not in session:
        return jsonify({"error": "login"}), 401

    with get_db() as conn:
        conn.execute(text("""
            UPDATE cart_items 
            SET quantity = quantity - 1 
            WHERE user_id = :uid AND product_id = :pid AND quantity > 0
        """), {"uid": session['user_id'], "pid": pid})

        conn.execute(text("""
            DELETE FROM cart_items 
            WHERE user_id = :uid AND product_id = :pid AND quantity <= 0
        """), {"uid": session['user_id'], "pid": pid})

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
                    FROM cart_items c JOIN products p ON c.product_id = p.product_id 
                    WHERE c.user_id = :uid
                """), {"uid": session['user_id']}).fetchall()

                total = sum((float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)

                result = conn.execute(text("""
                    INSERT INTO orders (user_id, total_amount, status, order_date)
                    VALUES (:uid, :total, 'pending', NOW())
                """), {"uid": session['user_id'], "total": total})
                order_id = result.lastrowid

                for item in items:
                    conn.execute(text("UPDATE products SET inventory = inventory - :qty WHERE product_id = :pid"),
                               {"qty": item.quantity, "pid": item.product_id})

                conn.execute(text("DELETE FROM cart_items WHERE user_id = :uid"), {"uid": session['user_id']})
                conn.commit()

            flash(f"Order #{order_id} placed successfully!", "success")
            return redirect(url_for('my_orders'))
        except Exception:
            flash("Failed to place order", "danger")
            return redirect(url_for('cart'))

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

# ====================== CHAT ======================
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get selected vendor from URL query string (e.g. /chat?vendor_id=5)
    selected_vendor_id = request.args.get('vendor_id', type=int)

    if request.method == 'POST':
        try:
            receiver_id = int(request.form.get('receiver_id') or 0)
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
                # Stay in the same conversation after sending
                return redirect(url_for('chat', vendor_id=receiver_id))
        except Exception as e:
            print("Chat send error:", str(e))
            flash("Failed to send message", "danger")
            if selected_vendor_id:
                return redirect(url_for('chat', vendor_id=selected_vendor_id))

    with get_db() as conn:
        # All vendors (for the sidebar)
        vendors = conn.execute(text("SELECT user_id, username FROM users WHERE user_type = 'vendor'")).fetchall()

        # Messages for the selected vendor only (chronological order)
        if selected_vendor_id:
            messages = conn.execute(text("""
                SELECT m.*, u.username as other_user 
                FROM messages m
                JOIN users u ON (
                    CASE 
                        WHEN m.sender_id = :uid THEN m.receiver_id 
                        ELSE m.sender_id 
                    END
                ) = u.user_id
                WHERE ((m.sender_id = :uid AND m.receiver_id = :vid) 
                   OR (m.sender_id = :vid AND m.receiver_id = :uid))
                ORDER BY m.sent_at ASC
            """), {"uid": session['user_id'], "vid": selected_vendor_id}).fetchall()
        else:
            # No vendor selected yet → show empty or recent messages
            messages = []

    return render_template('chat.html',
                           vendors=vendors,
                           messages=messages,
                           selected_vendor_id=selected_vendor_id)

# ====================== COMPLAINTS ======================
@app.route('/complaints', methods=['GET', 'POST'])
def complaints_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('user_type') == 'admin':
        # Admin can view all and update status
        if request.method == 'POST':
            try:
                complaint_id = request.form.get('complaint_id')
                new_status = request.form.get('status')
                if complaint_id and new_status:
                    with get_db() as conn:
                        conn.execute(text("UPDATE complaints SET status = :status WHERE complaint_id = :id"),
                                   {"status": new_status, "id": complaint_id})
                        conn.commit()
                    flash("Complaint status updated.", "success")
            except Exception:
                flash("Error updating status.", "danger")

        with get_db() as conn:
            complaints = conn.execute(text("""
                SELECT c.*, u.username 
                FROM complaints c 
                JOIN users u ON c.user_id = u.user_id 
                ORDER BY c.created_at DESC
            """)).fetchall()
        return render_template('complaints.html', complaints=complaints, is_admin=True)

    # Regular user
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
    return render_template('complaints.html', complaints=complaints, is_admin=False)

# ====================== ADMIN ======================
@app.route('/admin')
def admin_dashboard():
    if session.get('user_type') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    with get_db() as conn:
        users = conn.execute(text("SELECT * FROM users")).fetchall()
        products = conn.execute(text("SELECT * FROM products")).fetchall()
        complaints = conn.execute(text("SELECT * FROM complaints")).fetchall()
        pending_complaints = conn.execute(text("SELECT * FROM complaints WHERE status = 'pending'")).fetchall()

    return render_template('admin_dashboard.html',
                           users=users,
                           products=products,
                           complaints=complaints,
                           pending_complaints=pending_complaints)

@app.route('/admin/products')
def admin_products():
    if session.get('user_type') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    with get_db() as conn:
        products = conn.execute(text("SELECT * FROM products ORDER BY product_id DESC")).fetchall()
    return render_template('admin_products.html', products=products)

@app.route('/admin/delete-product/<int:pid>')
def admin_delete_product(pid):
    if session.get('user_type') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    with get_db() as conn:
        conn.execute(text("DELETE FROM products WHERE product_id = :pid"), {"pid": pid})
        conn.commit()
    flash("Product deleted successfully.", "success")
    return redirect(url_for('admin_products'))

@app.route('/admin/delete-user/<int:uid>')
def admin_delete_user(uid):
    if session.get('user_type') != 'admin':
        flash("Unauthorized", "danger")
        return redirect(url_for('index'))

    with get_db() as conn:
        conn.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": uid})
        conn.commit()
    flash("User deleted successfully.", "success")
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(debug=True)