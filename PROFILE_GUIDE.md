# 用户画像修改与格式化教程

本项目当前采用单用户本地画像模式，默认用户 ID 为 `default`，不使用 Cookie。
所有网页操作、自然语言对话和 CLI 行为都会写入同一个本地 SQLite 数据库。

数据库位置：

```text
D:\my_agent\data\agent.db
```

## 1. 画像数据分成两部分

### 明确偏好

保存在 `user_preferences` 表中，代表用户主动表达、优先级最高的规则。

支持的标准字段：

| 字段 | 类型 | 示例 |
| --- | --- | --- |
| `preferred_categories` | 字符串数组 | `["川菜", "粤菜"]` |
| `avoided_categories` | 字符串数组 | `["西餐"]` |
| `preferred_foods` | 字符串数组 | `["水煮牛肉", "炸酱面"]` |
| `avoided_foods` | 字符串数组 | `["猪脚饭"]` |
| `budget_max` | 数字 | `30` |
| `spicy_max` | 整数 `0-5` | `0` |
| `min_rating` | 数字 `0-5` | `4.5` |
| `delivery_fee_max` | 数字 | `5` |
| `notes` | 字符串 | `"午餐预算不超过30元"` |

格式示例：

```json
{
  "preferred_categories": ["川菜", "粤菜"],
  "avoided_categories": ["西餐"],
  "preferred_foods": ["水煮牛肉", "炸酱面"],
  "avoided_foods": ["猪脚饭"],
  "budget_max": 30,
  "spicy_max": 0,
  "min_rating": 4.5,
  "delivery_fee_max": 5,
  "notes": "工作日午餐尽量控制在30元以内"
}
```

### 行为推断画像

保存在 `user_profile_features` 表中，由点击、详情、收藏、加购、下单、评分等行为计算得到。

行为标签包含：

```text
category:川菜
category:粤菜
dish:d016
restaurant:r006
```

数值画像包含：

```text
spicy_preference
price_preference
delivery_fee_preference
distance_preference
```

行为标签的 `feature_value` 格式为：

```json
{
  "label": "川菜",
  "raw_weight": 19.63,
  "event_count": 8,
  "normalized_weight": 0.72,
  "direction": "positive",
  "behaviors": {
    "click": {
      "count": 3,
      "raw_weight": 1.81
    },
    "order": {
      "count": 1,
      "raw_weight": 7.5
    }
  }
}
```

## 2. 查看当前画像

```powershell
cd D:\my_agent
.\venv\Scripts\python.exe .\profile_cli.py show
```

查看更多特征：

```powershell
.\venv\Scripts\python.exe .\profile_cli.py show --limit 50
```

查看最近行为：

```powershell
.\venv\Scripts\python.exe .\profile_cli.py events --limit 100
```

浏览器查看：

```text
http://127.0.0.1:18080/profile
```

## 3. 通过对话修改

启动：

```powershell
.\venv\Scripts\python.exe .\nl2sql.py
```

明确偏好示例：

```text
我以后不吃猪脚饭
我不吃辣，预算30元
我喜欢川菜和粤菜
我喜欢水煮牛肉
不要香菜
以后优先推荐4.5分以上的商家
配送费不要超过5元
```

取消偏好：

```text
我现在可以吃辣了
以后可以推荐猪脚饭
把预算提高到50元
我不再讨厌香菜
```

## 4. 通过网页行为修改

打开任意商家菜单：

```text
http://127.0.0.1:18080/stores
```

每道菜支持：

| 操作 | 事件 | 基础权重 |
| --- | --- | ---: |
| 点击 | `click` | `+1` |
| 详情 | `view_detail` | `+3` |
| 收藏 | `favorite` | `+4` |
| 加购 | `add_cart` | `+6` |
| 下单 | `order` | `+15` |
| 忽略 | `ignore` | `0` |
| 不感兴趣 | `disinterest` | `-10` |
| 评分 | `rating` | `(score-3)×4` |

评分映射：

```text
5分 -> +8
4分 -> +4
3分 -> 0
2分 -> -4
1分 -> -8
```

搜索框会写入 `search` 行为。

## 5. 通过事件 CLI 修改

```powershell
# 点击
.\venv\Scripts\python.exe .\event_cli.py click "炸酱面"

# 查看详情，停留45秒
.\venv\Scripts\python.exe .\event_cli.py view "炸酱面" --dwell-sec 45

# 收藏
.\venv\Scripts\python.exe .\event_cli.py favorite "炸酱面"

# 加购
.\venv\Scripts\python.exe .\event_cli.py cart "炸酱面"

# 下单
.\venv\Scripts\python.exe .\event_cli.py order "炸酱面"

# 下单并评分
.\venv\Scripts\python.exe .\event_cli.py order "炸酱面" --rating 5

# 单独评分
.\venv\Scripts\python.exe .\event_cli.py rating "炸酱面" --rating 2

# 忽略
.\venv\Scripts\python.exe .\event_cli.py dismiss "猪脚饭"

# 不感兴趣
.\venv\Scripts\python.exe .\event_cli.py not-interested "猪脚饭"

# 搜索
.\venv\Scripts\python.exe .\event_cli.py search --query "30元以内的粤菜"
```

指定用户：

```powershell
.\venv\Scripts\python.exe .\event_cli.py favorite "炸酱面" --user-id default
```

## 6. 使用 Python 修改明确偏好

格式要求：

- 列表字段必须使用 Python 列表。
- 数字字段使用 `int` 或 `float`。
- 字符串字段使用普通字符串。
- `set_preference` 会进行 JSON 序列化。

示例：

```python
from storage import TakeoutStorage

storage = TakeoutStorage()
user_id = "default"

storage.set_preference(
    user_id,
    "avoided_foods",
    ["猪脚饭", "香菜"],
)
storage.set_preference(
    user_id,
    "preferred_categories",
    ["川菜", "粤菜"],
)
storage.set_preference(
    user_id,
    "budget_max",
    30,
)
storage.set_preference(
    user_id,
    "spicy_max",
    0,
)
```

将代码保存为临时脚本后运行：

```powershell
.\venv\Scripts\python.exe .\your_profile_update.py
```

## 7. 行为权重公式

实现在：

```text
profile_weights.py
```

单个标签和行为组的贡献：

```text
contrib =
    W_base
  × e^(-ln2 / 7 × days_ago)
  × log2(1 + n)
```

查看详情时：

```text
W_base =
    3
  × min(dwell_sec / 30, 3)
```

正向标签归一化：

```text
P(u, t) =
    max(W(u, t), 0)
  / sum(max(W(u, t'), 0))
```

负权重不为零，而是保留为负向画像，用于降低相关推荐。

## 8. 手工覆盖行为画像

不建议直接修改 `source='behavior'` 的行为特征，因为下一次画像重建会覆盖它们。

如果需要永久手工覆盖一个标签，使用：

```sql
source = 'manual'
```

示例：永久增加“川菜”正向画像。

```python
import json
import sqlite3

payload = {
    "label": "川菜",
    "raw_weight": 40.0,
    "event_count": 0,
    "normalized_weight": 1.0,
    "direction": "positive",
    "behaviors": {},
}

conn = sqlite3.connect("data/agent.db")
conn.execute(
    """
    INSERT INTO user_profile_features (
        user_id, feature_key, feature_value, score,
        confidence, source, update_count,
        first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, 'manual', 0,
              CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id, feature_key) DO UPDATE SET
        feature_value = excluded.feature_value,
        score = excluded.score,
        confidence = excluded.confidence,
        source = 'manual',
        last_seen_at = CURRENT_TIMESTAMP
    """,
    (
        "default",
        "category:川菜",
        json.dumps(payload, ensure_ascii=False),
        40.0,
        1.0,
    ),
)
conn.commit()
conn.close()
```

负向手工画像使用：

```json
{
  "raw_weight": -40.0,
  "normalized_weight": 0.0,
  "direction": "negative"
}
```

## 9. 恢复或重置画像

只清空行为画像和事件，保留明确偏好：

```powershell
.\venv\Scripts\python.exe .\profile_cli.py reset --yes
```

同时清空明确偏好：

```powershell
.\venv\Scripts\python.exe .\profile_cli.py reset --yes --include-preferences
```

## 10. 修改后验证

```powershell
.\venv\Scripts\python.exe .\profile_cli.py show
.\venv\Scripts\python.exe .\profile_cli.py events --limit 20
```

浏览器画像页面：

```text
http://127.0.0.1:18080/profile
```

修改评估逻辑或权重后，必须重启运行中的服务：

```powershell
.\venv\Scripts\python.exe -m meituan_sim.server
.\venv\Scripts\python.exe .\nl2sql.py
```
