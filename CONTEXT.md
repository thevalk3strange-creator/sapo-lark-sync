# Context: Anycross Workflow "Update SAPO orders in Base"

## Problem

Workflow syncs SAPO order updates → Lark Base, but **always creates new records** instead of updating existing ones. Already at **v18** and still not fixed.

## Workflow Logic

```
Trigger (SAPO "orders/updated" webhook)
  → script-1: Extract order number → "#" + order_number         (e.g. "#12345")
  → script-2: Flatten order → array of line-item records         (each has "Mã đơn hàng SAPO" = "#12345")
  → branch-1: skip if script-2 returns empty
  →
  │  ★ DH path (table: tblZlQNNxxyMb4aS):
  │    → bitable-1:  SEARCH records in DH table (NO filter — fetches ALL, max 500)
  │    → script-update-dh:  filter results client-side for matching "Mã đơn hàng SAPO"
  │      → branch-2:
  │        → [match found]   bitable-7: UPDATE record
  │        → [no match]      script-create-dh → bitable-3: CREATE new record
  │
  │  ★ SX path (table: tblT60XXm76Xi7fz):
  │    → bitable-4:  SEARCH records in SX table (same, no filter)
  │    → script-update-sx:  filter client-side for matching "Mã đơn hàng SAPO"
  │      → branch-3:
  │        → [match found]   bitable-8: UPDATE record
  │        → [no match]      script-create-sx → bitable-6: CREATE new record
```

## Root Cause Analysis

The matching step (`script-update-dh` / `script-update-sx`) always returns empty, causing the flow to fall into the "create" branch.

```javascript
// In script-update-dh:
var on = _("$.script-1.result");                             // "#12345"
var mt = i.data.items.filter(function(r){
    return gv(r.fields["Mã đơn hàng SAPO"]) === on;           // must match exactly
});
```

Possible reasons the match **always** fails:

### 1. `bitable-1` response is empty or wrong structure
The script checks `i.data.items` — if bitable returns a different structure (e.g. pagination wrapper, or `items` under a different key), the matching code returns `[]` early.

### 2. Field name `Mã đơn hàng SAPO` doesn't match
- Unicode normalization differences (NFD vs NFC)
- Extra whitespace/hidden characters in the actual Lark field name
- The field might be named differently in the table

### 3. Field value format mismatch
- `script-2` stores value as `"#12345"` (string with `#`)
- But existing records might have `"12345"` (without `#`) or `"#12345 "` (with trailing space)
- Lark returns text fields as plain string, but `gv()` also handles `{text: "..."}` and `[{text: "..."}]` formats

### 4. `_("$.script-1.result")` returns null
- The SPEL reference might fail silently
- The `try/catch` catches the error and leaves `on` as `null`
- Then `if(!on) return []` exits early

### 5. Page limit (500)
- If DH table has > 500 records, matching record might not be in first page
- `bitable-1` has `page_size: 500` but no pagination logic

## Files

| File | Description |
|------|-------------|
| `Update-SAPO-orders-v17.zip` | Original workflow (working-ish but always creates) |
| `Update-SAPO-orders-v18.zip` | Latest version with JS fixes (trim + fallback matching) |

## What was tried in v18

1. Removed `filter` parameter from `bitable-1`/`bitable-4` (caused publish failure)
2. Added `.trim()` to `gv()` function
3. Added fallback matching — if exact match fails (`#12345`), retry without `#` prefix (`12345`)
4. Fixed field name in `script-update-sx`: `"Ngày đặt hàng(cọc)"` → `"Ngày đặt"` in update payload

## What I need you to investigate

1. **Open the v17 zip** and examine the full flow.json — especially `bitable-1` parameters and response structure
2. **Check if the Lark Base API actually returns `data.items`** for the search/list operation
3. **Determine the real response format** of bitable-1 so we can fix `script-update-dh` to parse it correctly
4. **Verify field names** — are there hidden characters or Unicode issues with `Mã đơn hàng SAPO`?
5. **Check if `page_size: 500` is the issue** — maybe need pagination
6. **Test the `_()` SPEL function** — does `_("$.script-1.result")` actually work in this context?

## How to help

1. Read `flow.json` inside the v17 zip to see the exact bitable connector configuration
2. Suggest a fix — either fix the JS matching logic, or change the bitable search to use proper filtering
3. If possible, generate a corrected `flow.json` that can be zipped as v19
