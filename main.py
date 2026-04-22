from flask import Flask, render_template, request, redirect, session, url_for
from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = "vendify_secret"

# Database connection
conn_str = "mysql+pymysql://root:cset155@localhost/multi_vendor_ecommerce"
engine = create_engine(conn_str, echo=False)
conn = engine.connect()

# ------------------------
# HOME PAGE
# ------------------------
@app.route('/')
def index():
    products = conn.execute(text("SELECT * FROM products")).fetchall()
    return render_template('index.html', products=products)

# ------------------------
# REGISTER
# ------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        query = text("""
            INSERT INTO users (username, email, password_hash, user_type)
            VALUES (:username, :email, :password, :user_type)
        """)

        conn.execute(query, {
            "username": username,
            "email": email,
            "password": password,
            "user_type": user_type
        })

        return redirect(url_for('login'))

    return render_template('register.html')

# ------------------------
# LOGIN
# ------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        query = text("""
            SELECT * FROM users
            WHERE username = :username AND password_hash = :password
        """)

        user = conn.execute(query, {
            "username": username,
            "password": password
        }).fetchone()

        if user:
            session['user_id'] = user.user_id
            session['user_type'] = user.user_type
            return redirect(url_for('index'))
        else:
            return "Invalid login"

    return render_template('login.html')

# ------------------------
# LOGOUT
# ------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ------------------------
# ADD PRODUCT (Vendor)
# ------------------------
@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if 'user_type' not in session or session['user_type'] != 'vendor':
        return "Unauthorized"

    if request.method == 'POST':
        title = request.form['title']
        price = request.form['price']
        inventory = request.form['inventory']

        query = text("""
            INSERT INTO products (title, price, inventory)
            VALUES (:title, :price, :inventory)
        """)

        conn.execute(query, {
            "title": title,
            "price": price,
            "inventory": inventory
        })

        return redirect(url_for('index'))

    return render_template('add_product.html')

# ------------------------
# CART (basic placeholder)
# ------------------------
@app.route('/cart')
def cart():
    return render_template('cart.html')

# ------------------------
# ORDERS (basic placeholder)
# ------------------------
@app.route('/orders')
def orders():
    return render_template('orders.html')

# ------------------------
# RUN APP
# ------------------------
if __name__ == '__main__':
    app.run(debug=True)