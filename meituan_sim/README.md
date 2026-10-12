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

浏览器查看全部商家和菜系竞争：

```text
http://127.0.0.1:18080/stores
```

单个商家菜单：

```text
http://127.0.0.1:18080/menu?ePoiId=4213
```

当前示例数据包含 33 家商家、99 道菜和 16 个菜系，每个菜系至少有
2 家商家。

## 与 NL2SQL 的关系

美团模拟端会把菜品同步到现有 `dishes` 表，同时保存完整美团字段到
`meituan_dishes` 表。NL2SQL 的 `execute_sql` 仍然只读，新增和修改菜品
必须通过 `meituan_batch_upload` 等标准工具完成。
