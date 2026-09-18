# 12-ladderbill（阶梯电费）

Ladderbill — 居民阶梯电价分段累进（含尖峰系数）

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:4100 |
| API | http://localhost:9100 |

## 主链

抄表录入 → 阶梯分段计费 → 账单明细

## 估计抄表与结算

流程：写入**估计抄表**（estimate）→ `GET /api/readings/{id}/trial` 只读试算查看分段
→ `POST /api/readings/{id}/settle` 录入实抄完成结算（关闭估计有效态、写入实抄、生成差值记录，单事务）
→ 对实抄电量 `POST /api/bill` 正式测算入库。

- 同户同账期至多一条**有效**抄表：估计与正式（confirmed）不能双有效，冲突返回可读的 `409`。
- 试算只读，不写运行记录、不改状态。
- 结算失败整体回滚，不留“估计仍有效而实际半写入”。
- 户详情 `GET /api/accounts/{id}` 含抄表记录与 `settlements` 差值记录。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。
