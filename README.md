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

估计抄表 → 只读试算 → 录入实际结算（生成差值记录、关闭估计）→ 正式测算

| 接口 | 说明 |
| --- | --- |
| `POST /api/readings` | 写入抄表（`source=estimate/actual`），同户同账期双有效返回 409 可读原因 |
| `POST /api/readings/{id}/preview` | 试算分段，只读不写测算记录 |
| `POST /api/readings/{id}/settle` | 录入实际电量结算：单事务生成差值记录并关闭估计有效态 |
| `GET /api/accounts/{id}` | 户详情，含抄表历史（状态标记）与差值记录 |

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。
