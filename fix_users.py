from werkzeug.security import generate_password_hash
from sqlalchemy import create_engine, text

# === CHANGE NOTHING BELOW IF YOUR DB CONNECTION IS THE SAME ===
engine = create_engine("mysql+pymysql://root:cset155@localhost/multi_vendor_ecommerce", echo=False)
conn = engine.connect()

print("🔄 Resetting users table with proper hashed passwords...")

# Safely clear users (handles foreign key constraints)
conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
conn.execute(text("DELETE FROM users"))
conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

# Real hashed passwords
users_data = [
    ("admin1",    "admin1@vendify.com",    "admin123", "admin"),
    ("vendor1",   "v1@shop.com",          "pass123",  "vendor"),
    ("vendor2",   "v2@shop.com",          "pass123",  "vendor"),
    ("vendor3",   "v3@shop.com",          "pass123",  "vendor"),
    ("customer1", "c1@gmail.com",         "pass123",  "customer"),
    ("customer2", "c2@gmail.com",         "pass123",  "customer"),
    ("customer3", "c3@gmail.com",         "pass123",  "customer"),
]

for username, email, password, user_type in users_data:
    hashed_pw = generate_password_hash(password)
    conn.execute(text("""
        INSERT INTO users (username, email, password_hash, user_type)
        VALUES (:u, :e, :p, :t)
    """), {"u": username, "e": email, "p": hashed_pw, "t": user_type})
    print(f"✅ Added: {username} ({user_type})")

conn.commit()
print("\n🎉 Users fixed successfully!")
print("\nYou can now login with:")
print("   Admin    → admin1     / admin123")
print("   Vendor   → vendor1    / pass123")
print("   Customer → customer1  / pass123")