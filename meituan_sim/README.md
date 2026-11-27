# 美团菜品接口模拟端

该目录按美团技术服务合作中心的公共协议模拟外卖菜品接口：

- 请求方式：`HTTP POST`
- Content-Type：`application/x-www-form-urlencoded;charset=utf-8`
- 签名：`SHA1(signKey + 按参数名字典序拼接的 key1value1key2value2...)`
- 响应：`{"code":"OP_SUCCESS","msg":"成功","traceId":"...","data":...}`

## 已实现接口

| 接口 | 用途 |
| --- | --- |
| `/waimai/dish/batchUpload` | 批量新增或更新菜品及 SKU |
| `/waimai/dish/queryListByEPoiId` | 按 ERP 门店查询菜品 |
| `/waimai/ng/dish/queryFoodList` | 查询门店菜品列表 |
| `/waimai/dish/queryCatList` | 查询菜品分类 |
| `/waimai/dish/updatePrice` | 更新 SKU 价格 |
| `/waimai/dish/updateStock` | 更新 SKU 库存 |
| `/waimai/dish/delete` | 删除菜品 |

## 启动

```powershell
cd D:\my_agent
.\venv\Scripts\python.exe -m meituan_sim.server
```

默认地址为 `http://127.0.0.1:18080`，健康检查为：

```text
GET http://127.0.0.1:18080/health
```

## 可视化前端

服务端同时托管新版前端（`meituan_sim/web/`），不需要 npm 或任何构建步骤：

| 页面 | 地址 |
| --- | --- |
| 发现 / 今日推荐 | `http://127.0.0.1:18080/` |
| 商家目录 | `http://127.0.0.1:18080/stores` |
| 单店菜单 | `http://127.0.0.1:18080/menu?ePoiId=4211` |
| 用户画像 | `http://127.0.0.1:18080/profile` |
| 全局搜索 | `http://127.0.0.1:18080/search?q=面` |

AI 对话固定在首页左侧目录栏下方，是首页的一部分，不是独立页面，也不使用浮动
弹窗；移动端会自动放到首页内容区。`/api/chat` 调用 `nl2sql.NL2SQLAgent`，需要先
启动 Ollama 和 `qwen2:7b-instruct`；旧的 `/chat` 地址会重定向到首页。
前端提供个性化推荐、菜系筛选、店内搜索、购物车、下单、收藏、评分、
不感兴趣、画像可视化与明确偏好在线编辑。
所有交互都会写入 `user_events` / `order_history`，并复用 `TakeoutStorage`
的画像重建逻辑。

前端说明与截图见项目根目录的 [前端说明.md](../前端说明.md)。

## 前端 API

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | `/api/restaurants` | 商家列表、菜系聚合、营业状态 |
| GET | `/api/menu?ePoiId=4211` | 商家信息、菜品、分类、偏好 |
| GET | `/api/recommendations` | 个性化推荐 |
| GET | `/api/profile` | 画像摘要、行为、订单 |
| GET | `/api/search?q=面` | 商家与菜品搜索 |
| GET | `/api/chat/status` | Ollama / 模型是否就绪 |
| GET | `/api/chat/history?session_id=web-xxx` | 网页对话历史 |
| POST | `/api/chat` | 发送消息并调用本地 AI |
| POST | `/api/action` | 行为上报 / 下单 |
| POST | `/api/preferences` | 明确偏好写入 / 删除 |

当前示例数据包含 33 家商家、100 道菜和 16 个菜系，每个菜系至少有
2 家商家。

## 与 NL2SQL 的关系

美团模拟端会把菜品同步到现有 `dishes` 表，同时保存完整美团字段到
`meituan_dishes` 表。NL2SQL 的 `execute_sql` 仍然只读，新增和修改菜品
必须通过 `meituan_batch_upload` 等标准工具完成。
