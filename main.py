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
        featured = conn.execute(text("""
            SELECT p.*, u.username as vendor_name 
            FROM products p 
            JOIN users u ON p.vendor_id = u.user_id
            WHERE p.parent_product_id IS NULL 
            ORDER BY p.product_id DESC LIMIT 8
        """)).fetchall()

        on_sale = conn.execute(text("""
            SELECT p.*, u.username as vendor_name 
            FROM products p 
            JOIN users u ON p.vendor_id = u.user_id
            WHERE p.parent_product_id IS NULL AND p.sale_price IS NOT NULL 
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
    vendor_filter = request.args.get('vendor_id', type=int)
    sort_by = request.args.get('sort', 'newest')

    with get_db() as conn:
        # Get vendors for filter dropdown
        vendors = conn.execute(text("""
            SELECT user_id, username 
            FROM users 
            WHERE user_type = 'vendor'
            ORDER BY username
        """)).fetchall()

        query = """
            SELECT p.*, u.username as vendor_name 
            FROM products p 
            JOIN users u ON p.vendor_id = u.user_id
            WHERE p.parent_product_id IS NULL
        """
        params = {}

        if search:
            query += " AND p.title LIKE :s"
            params["s"] = f"%{search}%"

        if vendor_filter:
            query += " AND p.vendor_id = :vid"
            params["vid"] = vendor_filter

        # MySQL-compatible sorting (NULL sale_price last)
        if sort_by == 'price_low':
            query += " ORDER BY p.sale_price IS NULL, p.sale_price ASC, p.price ASC"
        elif sort_by == 'price_high':
            query += " ORDER BY p.sale_price IS NULL DESC, p.sale_price DESC, p.price DESC"
        elif sort_by == 'vendor':
            query += " ORDER BY u.username ASC"
        else:  # newest (default)
            query += " ORDER BY p.product_id DESC"

        prods = conn.execute(text(query), params).fetchall()

    return render_template('products.html',
                           products=prods,
                           vendors=vendors,
                           search=search,
                           vendor_filter=vendor_filter,
                           sort_by=sort_by)

@app.route('/product/<int:pid>')
def product_detail(pid):
    with get_db() as conn:
        # Main product + vendor name
        product = conn.execute(text("""
            SELECT p.*, u.username as vendor_name 
            FROM products p 
            JOIN users u ON p.vendor_id = u.user_id
            WHERE p.product_id = :id
        """), {"id": pid}).fetchone()

        if not product:
            flash("Product not found", "danger")
            return redirect(url_for('products_page'))

        # Get variants from the product_variants table (this is the correct table)
        variants = conn.execute(text("""
            SELECT * FROM product_variants 
            WHERE product_id = :pid 
            ORDER BY variant_name
        """), {"pid": pid}).fetchall()

        # Get reviews
        reviews = conn.execute(text("""
            SELECT r.*, u.username 
            FROM reviews r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.product_id = :pid
            ORDER BY r.created_at DESC
        """), {"pid": pid}).fetchall()

    return render_template('product_detail.html',
                           product=product,
                           variants=variants,
                           reviews=reviews)

#============== REVIEWS ===============

@app.route('/review/<int:pid>', methods=['POST'])
def submit_review(pid):
    if 'user_id' not in session:
        flash("You must be logged in to leave a review.", "danger")
        return redirect(url_for('product_detail', pid=pid))

    try:
        rating = int(request.form.get('rating'))
        description = request.form.get('description', '').strip()

        if not (1 <= rating <= 5) or not description:
            flash("Please provide a valid rating and review text.", "danger")
            return redirect(url_for('product_detail', pid=pid))

        with get_db() as conn:
            conn.execute(text("""
                INSERT INTO reviews (product_id, user_id, rating, description)
                VALUES (:pid, :uid, :rating, :desc)
            """), {
                "pid": pid,
                "uid": session['user_id'],
                "rating": rating,
                "desc": description
            })
            conn.commit()

        flash("Thank you! Your review has been posted.", "success")
    except Exception as e:
        print("Review error:", e)
        flash("Failed to post review.", "danger")

    return redirect(url_for('product_detail', pid=pid))


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
            # === Main product image ===
            image_filename = None
            image = request.files.get('image')
            if image and image.filename and allowed_file(image.filename):
                filename = secure_filename(image.filename)
                image_filename = f"{int(datetime.datetime.now().timestamp())}_{filename}"
                image.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

            sale_price = request.form.get('sale_price')
            sale_price = float(sale_price) if sale_price and sale_price.strip() else None

            with get_db() as conn:
                result = conn.execute(text("""
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
                product_id = result.lastrowid
                conn.commit()

            # === Save variants + their images ===
            variant_names = request.form.getlist('variant_name[]')
            variant_prices = request.form.getlist('variant_price[]')
            variant_inventories = request.form.getlist('variant_inventory[]')
            variant_images = request.files.getlist('variant_image[]')

            if variant_names and any(v.strip() for v in variant_names):
                UPLOAD_FOLDER = 'static/uploads/variants'
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)

                with get_db() as conn:
                    for i, name in enumerate(variant_names):
                        if not name.strip():
                            continue

                        v_price = float(variant_prices[i]) if variant_prices[i] and variant_prices[i].strip() else None
                        v_inventory = int(variant_inventories[i]) if variant_inventories[i] else 0

                        # Variant image
                        v_image_filename = None
                        if i < len(variant_images) and variant_images[i].filename:
                            v_file = variant_images[i]
                            if allowed_file(v_file.filename):
                                v_filename = secure_filename(v_file.filename)
                                v_image_filename = f"var_{product_id}_{int(datetime.datetime.now().timestamp())}_{v_filename}"
                                v_file.save(os.path.join(UPLOAD_FOLDER, v_image_filename))

                        conn.execute(text("""
                            INSERT INTO product_variants 
                            (product_id, variant_name, price, inventory, image)
                            VALUES (:pid, :name, :price, :inv, :img)
                        """), {
                            "pid": product_id,
                            "name": name.strip(),
                            "price": v_price,
                            "inv": v_inventory,
                            "img": v_image_filename
                        })
                    conn.commit()

            flash("Product and variants added successfully!", "success")
            return redirect(url_for('vendor_products'))

        except Exception as e:
            flash(f"Error: {str(e)}", "danger")

    return render_template('add_product.html')

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
@app.route('/checkout', methods=['GET'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    with get_db() as conn:
        items = conn.execute(text("""
            SELECT c.*, p.title, p.price, p.sale_price, p.image 
            FROM cart_items c JOIN products p ON c.product_id = p.product_id 
            WHERE c.user_id = :uid
        """), {"uid": session['user_id']}).fetchall()
    total = sum((float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)

    return render_template('checkout.html', items=items, total=total)


@app.route('/checkout/confirm', methods=['POST'])
def checkout_confirm():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        email = request.form.get('email')

        with get_db() as conn:
            items = conn.execute(text("""
                SELECT c.quantity, p.product_id, p.title, p.price, p.sale_price 
                FROM cart_items c 
                JOIN products p ON c.product_id = p.product_id 
                WHERE c.user_id = :uid
            """), {"uid": session['user_id']}).fetchall()

            if not items:
                flash("Your cart is empty.", "warning")
                return redirect(url_for('cart'))

            total = sum(
                (float(item.sale_price) if item.sale_price else float(item.price)) * item.quantity for item in items)

            # Create order
            result = conn.execute(text("""
                INSERT INTO orders (user_id, total_amount, status, order_date)
                VALUES (:uid, :total, 'pending', NOW())
            """), {"uid": session['user_id'], "total": total})
            order_id = result.lastrowid

            # Reduce inventory
            for item in items:
                conn.execute(text("UPDATE products SET inventory = inventory - :qty WHERE product_id = :pid"),
                             {"qty": item.quantity, "pid": item.product_id})

            # Clear cart
            conn.execute(text("DELETE FROM cart_items WHERE user_id = :uid"), {"uid": session['user_id']})
            conn.commit()

        # Send confirmation email
        if email:
            try:
                import smtplib
                from email.mime.text import MIMEText

                sender_email = "your.email@gmail.com"  # ← CHANGE THIS
                sender_password = "your-app-password"  # ← CHANGE THIS

                order_items_text = "\n".join([f"• {item.title} × {item.quantity}" for item in items])

                msg = MIMEText(f"""
Your order has been confirmed!

Order #{order_id}
Total: ${total:.2f}

Items:
{order_items_text}

Thank you for shopping with Vendify!
                """.strip())

                msg['Subject'] = f"Order Confirmation #{order_id} - Vendify"
                msg['From'] = sender_email
                msg['To'] = email

                with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, email, msg.as_string())

                flash(f"Order #{order_id} placed successfully! Confirmation email sent.", "success")
            except Exception as e:
                print("Email error:", e)
                flash(f"Order #{order_id} placed successfully!", "success")
        else:
            flash(f"Order #{order_id} placed successfully!", "success")

        return redirect(url_for('my_orders'))

    except Exception as e:
        print("Checkout error:", str(e))
        flash("Failed to process your order. Please try again.", "danger")
        return redirect(url_for('checkout'))


@app.route('/orders')
def my_orders():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        with get_db() as conn:
            orders = conn.execute(text("""
                SELECT * FROM orders 
                WHERE user_id = :uid 
                ORDER BY order_date DESC
            """), {"uid": session['user_id']}).fetchall()

        return render_template('orders.html', orders=orders)

    except Exception as e:
        print("Orders error:", e)  # for debugging
        flash("There was an issue loading your orders.", "danger")
        return render_template('orders.html', orders=[])

# ====================== CHAT ======================
@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    uid = session['user_id']
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
                        "sender": uid,
                        "receiver": receiver_id,
                        "msg": message_text
                    })
                    conn.commit()
                # Refresh the same conversation
                return redirect(url_for('chat', vendor_id=receiver_id))
        except Exception as e:
            print("Chat error:", e)
            flash("Failed to send message", "danger")

    # GET - load page
    with get_db() as conn:
        if session.get('user_type') == 'customer':
            conversations = []
            vendors = conn.execute(text("""
                SELECT user_id, username 
                FROM users 
                WHERE user_type = 'vendor' AND user_id != :uid
            """), {"uid": uid}).fetchall()
        else:
            conversations = conn.execute(text("""
                WITH conv AS (
                    SELECT 
                        CASE WHEN sender_id = :uid THEN receiver_id ELSE sender_id END as partner_id,
                        MAX(sent_at) as last_at,
                        (SELECT sender_id FROM messages m2 
                         WHERE ((m2.sender_id = :uid AND m2.receiver_id = partner_id) 
                            OR (m2.sender_id = partner_id AND m2.receiver_id = :uid))
                         ORDER BY m2.sent_at DESC LIMIT 1) != :uid as has_unread
                    FROM messages 
                    WHERE sender_id = :uid OR receiver_id = :uid
                    GROUP BY partner_id
                )
                SELECT 
                    c.partner_id as user_id,
                    u.username,
                    c.last_at,
                    c.has_unread
                FROM conv c
                JOIN users u ON u.user_id = c.partner_id
                ORDER BY c.last_at DESC
            """), {"uid": uid}).fetchall()
            vendors = []

        messages = []
        if selected_vendor_id:
            messages = conn.execute(text("""
                SELECT m.*, u.username as other_user 
                FROM messages m
                JOIN users u ON (CASE WHEN m.sender_id = :uid THEN m.receiver_id 
                                     ELSE m.sender_id END) = u.user_id
                WHERE ((m.sender_id = :uid AND m.receiver_id = :vid) 
                   OR (m.sender_id = :vid AND m.receiver_id = :uid))
                ORDER BY m.sent_at ASC
            """), {"uid": uid, "vid": selected_vendor_id}).fetchall()

    return render_template('chat.html',
                           conversations=conversations,
                           messages=messages,
                           selected_vendor_id=selected_vendor_id,
                           vendors=vendors)

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