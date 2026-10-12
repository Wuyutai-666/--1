import sqlite3

conn = sqlite3.connect("D:/my_agent/data/agent.db")
c = conn.cursor()

# 查看所有表
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# 各表数据量
for t in [
    "restaurants",
    "dishes",
    "order_history",
    "meituan_dishes",
    "user_events",
    "user_profile_features",
    "recommendation_batches",
    "recommendation_impressions",
]:
    c.execute(f"SELECT COUNT(*) FROM {t}")
    print(f"  {t}: {c.fetchone()[0]} rows")

# 抽几条数据看看
print("\n--- restaurants sample ---")
c.execute("SELECT id, name, category, rating FROM restaurants")
for r in c.fetchall():
    print(" ", r)

print("\n--- dishes sample ---")
c.execute("SELECT id, restaurant_id, name, price, spicy_level FROM dishes LIMIT 5")
for r in c.fetchall():
    print(" ", r)

conn.close()
