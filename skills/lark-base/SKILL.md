---
name: lark-base
description: "Query and manage Gấm Vóc ERP data in Lark Base via lark-cli. Search orders by phone/SAPO code, list records, check order status, update production status."
version: 1.0.0
author: GV
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [lark, base, erp, orders, production, gấm-vóc]
    related_skills: [sapo-lark-sync]
---

# Lark Base — Gấm Vóc ERP

Query and manage Gấm Vóc ERP data in Lark Base using `lark-cli`.

## Base Info

| Item | Token/ID |
|------|----------|
| Base | `ZSZxbtXCXagSiZsZlO4jVb46pPg` |
| Đơn hàng (DH) | `tblZlQNNxxyMb4aS` |
| Sản xuất (SX) | `tblT60XXm76Xi7fz` |
| SAPO Staging | `tbloP45vaT4I2mwF` |

## Commands

### Search by phone number
```bash
lark-cli base +record-search \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --keyword "<phone>" \
  --search-field "SĐT"
```

### Search by SAPO order code
```bash
lark-cli base +record-search \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --keyword "<order_number>" \
  --search-field "Mã đơn hàng SAPO"
```

### Search by customer name
```bash
lark-cli base +record-search \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --keyword "<name>" \
  --search-field "Khách hàng"
```

### List recent records
```bash
lark-cli base +record-list \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --page-size 10
```

### Get record by ID
```bash
lark-cli base +record-get \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --record-id "<record_id>"
```

### Search production table (SX)
```bash
lark-cli base +record-search \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblT60XXm76Xi7fz \
  --keyword "<keyword>" \
  --search-field "Mã đơn hàng SAPO"
```

## Key Fields (DH Table)

| Field | Description |
|-------|-------------|
| Khách hàng | Customer name |
| SĐT | Phone number |
| Mã đơn hàng SAPO | SAPO order code (e.g. #1480) |
| Tên sản phẩm mới | Product name |
| Tổng tiền | Total amount |
| Tiền đã đặt cọc | Deposit paid |
| Tiền còn lại | Remaining amount |
| Tình hình công nợ | Debt status |
| Trạng thái sản xuất | Production status |
| Ghi chú | Notes |
| Hẹn giao | Delivery date |
| Ngày đặt hàng(cọc) | Order date |

## Usage Tips

- Always use `--base-token` (NOT `--app-token`)
- `--search-field` accepts field name or field ID
- `--keyword` is the search term (required for search)
- Use `--page-size` to control how many records to return
- Default output is markdown; use `--format json` for raw JSON

## Example: Customer asks "Đơn #1480 của tôi thế nào?"

```bash
lark-cli base +record-search \
  --base-token ZSZxbtXCXagSiZsZlO4jVb46pPg \
  --table-id tblZlQNNxxyMb4aS \
  --keyword "1480" \
  --search-field "Mã đơn hàng SAPO"
```

Then respond in Vietnamese with the order details from the result.
