# data/init_db.py
"""初始化外卖推荐 SQLite 数据库：建表 + 灌测试数据"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "agent.db")


def ensure_column(cursor, table: str, column: str, definition: str) -> None:
    columns = {
        row[1]
        for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        cursor.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init(verbose: bool = True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON")

    # 建表
    c.executescript("""
        CREATE TABLE IF NOT EXISTS restaurants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            rating REAL,
            min_order REAL,
            delivery_fee REAL,
            distance_km REAL,
            business_hours TEXT
        );

        CREATE TABLE IF NOT EXISTS dishes (
            id TEXT PRIMARY KEY,
            restaurant_id TEXT,
            name TEXT NOT NULL,
            price REAL,
            spicy_level INTEGER,
            month_sales INTEGER,
            tags TEXT,
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
        );

        CREATE TABLE IF NOT EXISTS order_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dish_name TEXT,
            restaurant_name TEXT,
            price REAL,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source TEXT DEFAULT 'user',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, key),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            summary TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT DEFAULT '',
            tool_call_id TEXT,
            tool_calls_json TEXT,
            tool_name TEXT,
            is_summarized INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
        );

        CREATE TABLE IF NOT EXISTS meituan_dishes (
            spu_id TEXT PRIMARY KEY,
            e_poi_id TEXT NOT NULL,
            e_dish_code TEXT NOT NULL,
            dish_name TEXT NOT NULL,
            category_name TEXT,
            description TEXT,
            price REAL,
            picture TEXT,
            unit TEXT,
            is_sold_out INTEGER DEFAULT 0,
            min_order_count INTEGER DEFAULT 1,
            sequence INTEGER,
            skus_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (e_poi_id, e_dish_code)
        );

        CREATE TABLE IF NOT EXISTS user_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            dish_id TEXT,
            restaurant_id TEXT,
            session_id TEXT,
            search_query TEXT,
            context_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS user_profile_features (
            user_id TEXT NOT NULL,
            feature_key TEXT NOT NULL,
            feature_value TEXT,
            score REAL DEFAULT 0,
            confidence REAL DEFAULT 0,
            source TEXT DEFAULT 'behavior',
            update_count INTEGER DEFAULT 0,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, feature_key),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS recommendation_batches (
            batch_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT,
            algorithm_version TEXT NOT NULL,
            context_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE TABLE IF NOT EXISTS recommendation_impressions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            dish_id TEXT NOT NULL,
            restaurant_id TEXT,
            rank INTEGER NOT NULL,
            score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (batch_id, dish_id),
            FOREIGN KEY (batch_id) REFERENCES recommendation_batches(batch_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_dishes_restaurant_id
            ON dishes(restaurant_id);

        CREATE INDEX IF NOT EXISTS idx_dishes_month_sales
            ON dishes(month_sales DESC);

        CREATE INDEX IF NOT EXISTS idx_order_history_created_at
            ON order_history(created_at DESC);
    """)

    # 兼容已经存在的旧数据库，只追加字段，不重建表。
    ensure_column(c, "order_history", "user_id", "TEXT")
    ensure_column(c, "order_history", "dish_id", "TEXT")
    ensure_column(c, "order_history", "restaurant_id", "TEXT")
    ensure_column(c, "order_history", "rating", "REAL")
    ensure_column(c, "order_history", "source", "TEXT DEFAULT 'user'")
    ensure_column(c, "restaurants", "e_poi_id", "TEXT")
    ensure_column(c, "dishes", "meituan_spu_id", "TEXT")
    ensure_column(c, "dishes", "e_dish_code", "TEXT")
    ensure_column(c, "dishes", "category_name", "TEXT")
    ensure_column(c, "dishes", "description", "TEXT")
    ensure_column(c, "dishes", "picture", "TEXT")
    ensure_column(c, "dishes", "unit", "TEXT")
    ensure_column(c, "dishes", "is_sold_out", "INTEGER DEFAULT 0")
    ensure_column(c, "dishes", "min_order_count", "INTEGER DEFAULT 1")
    ensure_column(c, "dishes", "sequence", "INTEGER")
    ensure_column(c, "dishes", "skus_json", "TEXT")
    ensure_column(c, "dishes", "source", "TEXT DEFAULT 'seed'")
    ensure_column(c, "dishes", "updated_at", "TIMESTAMP")

    c.execute(
        """
        UPDATE order_history
        SET user_id = 'default'
        WHERE user_id IS NULL OR user_id = ''
        """
    )
    c.execute(
        """
        UPDATE order_history
        SET dish_id = (
            SELECT id FROM dishes
            WHERE dishes.name = order_history.dish_name
            LIMIT 1
        )
        WHERE dish_id IS NULL
          AND EXISTS (
              SELECT 1 FROM dishes
              WHERE dishes.name = order_history.dish_name
          )
        """
    )
    c.execute(
        """
        UPDATE order_history
        SET restaurant_id = (
            SELECT id FROM restaurants
            WHERE restaurants.name = order_history.restaurant_name
            LIMIT 1
        )
        WHERE restaurant_id IS NULL
          AND EXISTS (
              SELECT 1 FROM restaurants
              WHERE restaurants.name = order_history.restaurant_name
          )
        """
    )

    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id);

        CREATE INDEX IF NOT EXISTS idx_chat_messages_pending
            ON chat_messages(session_id, is_summarized, id);

        CREATE INDEX IF NOT EXISTS idx_order_history_user_created
            ON order_history(user_id, created_at DESC);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_restaurants_epoi
            ON restaurants(e_poi_id)
            WHERE e_poi_id IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_dishes_meituan_spu
            ON dishes(meituan_spu_id)
            WHERE meituan_spu_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_meituan_dishes_epoi
            ON meituan_dishes(e_poi_id, sequence);

        CREATE INDEX IF NOT EXISTS idx_user_events_user_created
            ON user_events(user_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_user_profile_features_user
            ON user_profile_features(user_id, score DESC);

        CREATE INDEX IF NOT EXISTS idx_recommendation_impressions_batch
            ON recommendation_impressions(batch_id, rank);
    """)

    c.execute(
        """
        INSERT INTO users (user_id, display_name)
        VALUES ('default', '默认用户')
        ON CONFLICT(user_id) DO NOTHING
        """
    )

    # 灌商家测试数据
    c.executemany(
        """
        INSERT INTO restaurants (
            id, name, category, rating, min_order,
            delivery_fee, distance_km, business_hours
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            rating = excluded.rating,
            min_order = excluded.min_order,
            delivery_fee = excluded.delivery_fee,
            distance_km = excluded.distance_km,
            business_hours = excluded.business_hours
        """,
        [
            ("r001", "川味小厨", "川菜", 4.8, 20, 3, 1.2, "10:00-22:00"),
            ("r002", "轻食沙拉屋", "轻食", 4.6, 25, 5, 2.0, "09:00-21:00"),
            ("r003", "老北京炸酱面", "面食", 4.5, 15, 2, 0.8, "07:00-20:00"),
            ("r004", "日式拉面馆", "日料", 4.7, 30, 4, 1.5, "11:00-21:00"),
            ("r005", "披萨玛尚诺", "西餐", 4.4, 35, 6, 2.5, "10:30-22:00"),
        ],
    )

    c.executemany(
        """
        INSERT INTO restaurants (
            id, name, category, rating, min_order,
            delivery_fee, distance_km, business_hours
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            category = excluded.category,
            rating = excluded.rating,
            min_order = excluded.min_order,
            delivery_fee = excluded.delivery_fee,
            distance_km = excluded.distance_km,
            business_hours = excluded.business_hours
        """,
        [
            ("r006", "蜀香苑", "川菜", 4.7, 25, 4, 2.2, "10:00-22:00"),
            ("r007", "粤膳轩", "粤菜", 4.8, 30, 5, 1.8, "10:30-22:00"),
            ("r008", "广府人家", "粤菜", 4.6, 25, 4, 2.8, "10:00-21:30"),
            ("r009", "湘聚楼", "湘菜", 4.7, 20, 3, 1.5, "10:30-22:00"),
            ("r010", "湘味小馆", "湘菜", 4.5, 18, 3, 2.4, "09:30-21:30"),
            ("r011", "鲁香居", "鲁菜", 4.6, 25, 4, 2.1, "10:00-21:30"),
            ("r012", "齐鲁家常菜", "鲁菜", 4.4, 20, 3, 3.0, "09:30-21:00"),
            ("r013", "江南小灶", "苏菜", 4.7, 30, 5, 1.7, "10:30-21:30"),
            ("r014", "姑苏人家", "苏菜", 4.5, 25, 4, 2.6, "10:00-21:00"),
            ("r015", "杭帮味道", "浙菜", 4.8, 28, 5, 1.9, "10:30-22:00"),
            ("r016", "浙里鲜", "浙菜", 4.5, 22, 4, 2.7, "10:00-21:00"),
            ("r017", "闽南古早味", "闽菜", 4.6, 25, 4, 2.3, "10:30-21:30"),
            ("r018", "徽州家宴", "徽菜", 4.5, 28, 5, 2.9, "10:00-21:00"),
            ("r019", "东北饺子馆", "东北菜", 4.6, 18, 3, 1.4, "09:00-21:30"),
            ("r020", "大东北铁锅炖", "东北菜", 4.4, 35, 6, 3.2, "10:30-22:00"),
            ("r021", "沸腾火锅", "火锅", 4.7, 40, 6, 2.0, "11:00-23:30"),
            ("r022", "牛油火锅局", "火锅", 4.5, 35, 5, 2.8, "11:00-23:00"),
            ("r023", "炭火烧烤", "烧烤", 4.6, 25, 4, 1.9, "16:00-01:00"),
            ("r024", "夜宵烤串", "烧烤", 4.4, 20, 3, 2.5, "17:00-02:00"),
            ("r025", "樱町日料", "日料", 4.8, 35, 5, 1.6, "11:00-22:00"),
            ("r026", "首尔拌饭", "韩餐", 4.5, 25, 4, 2.2, "10:30-22:00"),
            ("r027", "意式小馆", "西餐", 4.6, 30, 5, 2.1, "10:30-22:00"),
            ("r028", "绿野轻食", "轻食", 4.7, 25, 4, 1.5, "08:30-21:00"),
            ("r029", "兰州牛肉面", "面食", 4.5, 15, 2, 1.1, "07:00-21:00"),
            ("r030", "披萨工坊", "西餐", 4.4, 35, 6, 2.9, "10:30-22:30"),
            ("r031", "新安小馆", "徽菜", 4.6, 28, 4, 2.4, "10:30-21:30"),
            ("r032", "闽味小厨", "闽菜", 4.5, 25, 4, 2.2, "10:30-21:30"),
            ("r033", "韩香屋", "韩餐", 4.7, 28, 4, 1.8, "10:30-22:30"),
        ],
    )

    c.executemany(
        "UPDATE restaurants SET e_poi_id = ? WHERE id = ?",
        [
            ("4211", "r001"),
            ("4212", "r002"),
            ("4213", "r003"),
            ("4214", "r004"),
            ("4215", "r005"),
            ("4216", "r006"),
            ("4217", "r007"),
            ("4218", "r008"),
            ("4219", "r009"),
            ("4220", "r010"),
            ("4221", "r011"),
            ("4222", "r012"),
            ("4223", "r013"),
            ("4224", "r014"),
            ("4225", "r015"),
            ("4226", "r016"),
            ("4227", "r017"),
            ("4228", "r018"),
            ("4229", "r019"),
            ("4230", "r020"),
            ("4231", "r021"),
            ("4232", "r022"),
            ("4233", "r023"),
            ("4234", "r024"),
            ("4235", "r025"),
            ("4236", "r026"),
            ("4237", "r027"),
            ("4238", "r028"),
            ("4239", "r029"),
            ("4240", "r030"),
            ("4241", "r031"),
            ("4242", "r032"),
            ("4243", "r033"),
        ],
    )

    # 灌菜品测试数据
    c.executemany(
        """
        INSERT INTO dishes (
            id, restaurant_id, name, price,
            spicy_level, month_sales, tags
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            restaurant_id = excluded.restaurant_id,
            name = excluded.name,
            price = excluded.price,
            spicy_level = excluded.spicy_level,
            month_sales = excluded.month_sales,
            tags = excluded.tags
        """,
        [
            ("d001", "r001", "麻婆豆腐", 18, 3, 1200, "辣,下饭,招牌"),
            ("d002", "r001", "宫保鸡丁", 28, 2, 980, "微辣,招牌"),
            ("d003", "r001", "水煮鱼", 58, 4, 650, "辣,硬菜"),
            ("d004", "r001", "回锅肉", 32, 3, 760, "辣,下饭"),
            ("d005", "r002", "鸡胸肉沙拉", 32, 0, 800, "低卡,高蛋白,招牌"),
            ("d006", "r002", "牛油果三明治", 26, 0, 520, "低卡,早餐"),
            ("d007", "r002", "藜麦碗", 38, 0, 430, "低卡,素食"),
            ("d008", "r003", "炸酱面", 16, 0, 2100, "招牌,实惠"),
            ("d009", "r003", "凉拌黄瓜", 8, 1, 890, "小菜,清爽"),
            ("d010", "r003", "西红柿鸡蛋面", 18, 0, 1500, "不辣,家常"),
            ("d011", "r004", "豚骨拉面", 42, 1, 1100, "招牌,浓汤"),
            ("d012", "r004", "地狱辣拉面", 45, 4, 720, "辣,刺激"),
            ("d013", "r004", "炸鸡块", 22, 0, 900, "小吃,经典"),
            ("d014", "r005", "玛格丽特披萨", 55, 0, 680, "招牌,芝士"),
            ("d015", "r005", "意面", 48, 0, 550, "番茄,经典"),
        ],
    )

    c.executemany(
        """
        INSERT INTO dishes (
            id, restaurant_id, name, price,
            spicy_level, month_sales, tags
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            restaurant_id = excluded.restaurant_id,
            name = excluded.name,
            price = excluded.price,
            spicy_level = excluded.spicy_level,
            month_sales = excluded.month_sales,
            tags = excluded.tags
        """,
        [
            ("d016", "r006", "水煮牛肉", 48, 4, 900, "麻辣,招牌"),
            ("d017", "r006", "辣子鸡", 42, 4, 1000, "干香,辣"),
            ("d018", "r006", "鱼香肉丝", 26, 2, 1300, "下饭,微辣"),
            ("d019", "r007", "白切鸡", 38, 0, 1300, "粤菜,清淡"),
            ("d020", "r007", "叉烧拼盘", 46, 0, 900, "烧味,招牌"),
            ("d021", "r007", "虾饺", 28, 0, 1100, "点心,鲜香"),
            ("d022", "r008", "烧鹅饭", 36, 0, 1500, "烧味,主食"),
            ("d023", "r008", "干炒牛河", 30, 1, 1200, "粤式,锅气"),
            ("d024", "r008", "艇仔粥", 18, 0, 800, "清淡,粥品"),
            ("d025", "r009", "剁椒鱼头", 58, 5, 950, "重辣,招牌"),
            ("d026", "r009", "小炒黄牛肉", 38, 4, 880, "湖南辣,下饭"),
            ("d027", "r009", "农家小炒肉", 32, 3, 1100, "辣椒炒肉"),
            ("d028", "r010", "辣椒炒肉", 26, 3, 1600, "招牌,下饭"),
            ("d029", "r010", "香辣虾", 48, 4, 750, "香辣,聚餐"),
            ("d030", "r010", "酸豆角肉末", 22, 2, 900, "酸辣,下饭"),
            ("d031", "r011", "九转大肠", 48, 1, 620, "鲁菜,经典"),
            ("d032", "r011", "糖醋鲤鱼", 58, 0, 700, "酸甜,招牌"),
            ("d033", "r011", "葱烧海参", 88, 0, 320, "鲁菜,宴席"),
            ("d034", "r012", "把子肉", 22, 1, 1200, "济南,家常"),
            ("d035", "r012", "四喜丸子", 32, 0, 680, "家常,宴席"),
            ("d036", "r012", "山东煎饼", 12, 0, 950, "早餐,粗粮"),
            ("d037", "r013", "松鼠桂鱼", 68, 0, 760, "苏帮菜,招牌"),
            ("d038", "r013", "响油鳝糊", 48, 1, 540, "苏菜,经典"),
            ("d039", "r013", "阳春面", 16, 0, 1300, "清淡,主食"),
            ("d040", "r014", "苏式红烧肉", 36, 0, 880, "甜香,招牌"),
            ("d041", "r014", "蟹粉豆腐", 42, 0, 530, "鲜香,苏菜"),
            ("d042", "r014", "桂花糖藕", 24, 0, 410, "甜品,江南"),
            ("d043", "r015", "西湖醋鱼", 46, 0, 820, "杭帮菜,招牌"),
            ("d044", "r015", "东坡肉", 38, 0, 1100, "杭帮菜,经典"),
            ("d045", "r015", "龙井虾仁", 58, 0, 640, "清淡,鲜香"),
            ("d046", "r016", "宋嫂鱼羹", 32, 0, 520, "汤羹,浙菜"),
            ("d047", "r016", "杭州小笼包", 22, 0, 1300, "点心,主食"),
            ("d048", "r016", "笋干老鸭煲", 58, 0, 470, "汤煲,清淡"),
            ("d049", "r017", "沙茶面", 25, 1, 980, "闽南,汤面"),
            ("d050", "r017", "海蛎煎", 28, 0, 720, "闽南小吃"),
            ("d051", "r017", "闽南咸饭", 18, 0, 860, "主食,家常"),
            ("d052", "r018", "臭鳜鱼", 58, 2, 680, "徽菜,招牌"),
            ("d053", "r018", "毛豆腐", 28, 2, 540, "徽州特色"),
            ("d054", "r018", "徽州一品锅", 68, 1, 360, "炖锅,宴席"),
            ("d055", "r019", "猪肉白菜饺子", 22, 0, 1800, "饺子,招牌"),
            ("d056", "r019", "酸菜猪肉饺子", 24, 1, 1300, "酸香,饺子"),
            ("d057", "r019", "锅包肉", 32, 0, 1500, "东北菜,酸甜"),
            ("d058", "r020", "排骨炖豆角", 42, 1, 820, "铁锅炖,家常"),
            ("d059", "r020", "铁锅炖大鹅", 68, 2, 760, "东北菜,聚餐"),
            ("d060", "r020", "东北乱炖", 38, 1, 690, "炖菜,实惠"),
            ("d061", "r021", "牛油麻辣锅", 88, 5, 1300, "火锅,重辣"),
            ("d062", "r021", "番茄锅", 68, 0, 900, "火锅,不辣"),
            ("d063", "r021", "毛肚", 38, 4, 1100, "火锅配菜"),
            ("d064", "r022", "精品肥牛", 48, 2, 1200, "火锅,招牌"),
            ("d065", "r022", "虾滑", 36, 1, 980, "火锅配菜"),
            ("d066", "r022", "黄喉", 32, 3, 760, "火锅,脆爽"),
            ("d067", "r023", "烤羊肉串", 30, 2, 1500, "烧烤,招牌"),
            ("d068", "r023", "烤鸡翅", 28, 1, 1100, "烧烤,经典"),
            ("d069", "r023", "烤茄子", 18, 1, 920, "烧烤,素菜"),
            ("d070", "r024", "烤五花肉", 32, 2, 1300, "烧烤,夜宵"),
            ("d071", "r024", "烤韭菜", 12, 1, 700, "烧烤,素菜"),
            ("d072", "r024", "烤鱼", 68, 4, 880, "烧烤,重辣"),
            ("d073", "r025", "三文鱼刺身", 58, 0, 760, "日料,生鲜"),
            ("d074", "r025", "鳗鱼饭", 48, 0, 920, "日料,主食"),
            ("d075", "r025", "寿喜锅", 68, 0, 630, "日料,锅物"),
            ("d076", "r026", "石锅拌饭", 28, 2, 1100, "韩餐,主食"),
            ("d077", "r026", "部队火锅", 58, 3, 850, "韩餐,火锅"),
            ("d078", "r026", "韩式炸鸡", 42, 2, 1200, "韩餐,炸鸡"),
            ("d079", "r027", "黑椒牛排", 78, 0, 560, "西餐,招牌"),
            ("d080", "r027", "奶油蘑菇意面", 42, 0, 780, "西餐,意面"),
            ("d081", "r027", "凯撒沙拉", 28, 0, 620, "西餐,轻食"),
            ("d082", "r028", "鸡胸藜麦沙拉", 32, 0, 980, "低卡,高蛋白"),
            ("d083", "r028", "牛油果能量碗", 36, 0, 760, "轻食,健康"),
            ("d084", "r028", "低脂意面", 30, 0, 690, "轻食,主食"),
            ("d085", "r029", "招牌牛肉面", 26, 1, 1900, "面食,招牌"),
            ("d086", "r029", "番茄牛肉面", 28, 0, 1200, "面食,不辣"),
            ("d087", "r029", "凉拌牛肉", 24, 2, 800, "面食,小菜"),
            ("d088", "r030", "芝士披萨", 58, 0, 960, "披萨,芝士"),
            ("d089", "r030", "培根披萨", 62, 0, 720, "披萨,经典"),
            ("d090", "r030", "夏威夷披萨", 55, 0, 680, "披萨,水果"),
            ("d091", "r031", "胡适一品锅", 58, 1, 420, "徽菜,炖锅"),
            ("d092", "r031", "腌鲜鳜鱼", 62, 2, 380, "徽菜,招牌"),
            ("d093", "r031", "问政山笋", 32, 0, 510, "徽菜,山珍"),
            ("d094", "r032", "福州鱼丸", 26, 0, 780, "闽菜,汤品"),
            ("d095", "r032", "佛跳墙", 88, 0, 360, "闽菜,宴席"),
            ("d096", "r032", "荔枝肉", 32, 0, 690, "闽菜,酸甜"),
            ("d097", "r033", "韩式烤肉", 58, 2, 920, "韩餐,烤肉"),
            ("d098", "r033", "泡菜汤", 32, 3, 680, "韩餐,汤品"),
            ("d099", "r033", "芝士年糕", 36, 2, 850, "韩餐,小吃"),
            ("d100", "r008", "猪脚饭", 32, 0, 640, "粤式,主食"),
        ],
    )

    # 为已有 NL2SQL 菜品建立美团 SPU 映射，使模拟接口可直接查询。
    c.execute(
        """
        UPDATE dishes
        SET meituan_spu_id = 'spu_' || id,
            e_dish_code = COALESCE(e_dish_code, id),
            category_name = COALESCE(
                category_name,
                (
                    SELECT restaurants.category
                    FROM restaurants
                    WHERE restaurants.id = dishes.restaurant_id
                )
            ),
            unit = COALESCE(unit, '份'),
            is_sold_out = COALESCE(is_sold_out, 0),
            min_order_count = COALESCE(min_order_count, 1),
            skus_json = COALESCE(skus_json, '[]'),
            source = COALESCE(source, 'seed')
        WHERE meituan_spu_id IS NULL
        """
    )
    c.execute(
        """
        INSERT OR IGNORE INTO meituan_dishes (
            spu_id, e_poi_id, e_dish_code, dish_name,
            category_name, description, price, picture, unit,
            is_sold_out, min_order_count, sequence, skus_json,
            created_at, updated_at
        )
        SELECT
            dishes.meituan_spu_id,
            restaurants.e_poi_id,
            dishes.e_dish_code,
            dishes.name,
            COALESCE(dishes.category_name, restaurants.category),
            COALESCE(dishes.description, ''),
            dishes.price,
            COALESCE(dishes.picture, ''),
            COALESCE(dishes.unit, '份'),
            COALESCE(dishes.is_sold_out, 0),
            COALESCE(dishes.min_order_count, 1),
            COALESCE(dishes.sequence, 0),
            COALESCE(dishes.skus_json, '[]'),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM dishes
        JOIN restaurants ON restaurants.id = dishes.restaurant_id
        WHERE restaurants.e_poi_id IS NOT NULL
          AND dishes.meituan_spu_id IS NOT NULL
        """
    )

    # 灌一些历史订单（用于推荐）
    order_count = c.execute("SELECT COUNT(*) FROM order_history").fetchone()[0]
    if order_count == 0:
        c.executemany(
            """
            INSERT INTO order_history (
                dish_name, restaurant_name, price, category,
                user_id, dish_id, restaurant_id, source
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            [
                ("麻婆豆腐", "川味小厨", 18, "川菜", "default", "d001", "r001", "seed"),
                ("炸酱面", "老北京炸酱面", 16, "面食", "default", "d008", "r003", "seed"),
                ("豚骨拉面", "日式拉面馆", 42, "日料", "default", "d011", "r004", "seed"),
                ("麻婆豆腐", "川味小厨", 18, "川菜", "default", "d001", "r001", "seed"),
                ("鸡胸肉沙拉", "轻食沙拉屋", 32, "轻食", "default", "d005", "r002", "seed"),
            ],
        )

    conn.commit()
    conn.close()
    if verbose:
        print(f"[OK] 数据库初始化完成：{DB_PATH}")


if __name__ == "__main__":
    init()
