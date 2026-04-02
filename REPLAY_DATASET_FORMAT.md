# Replay Dataset Format (ndjson_v1)

This document defines the replay file format consumed by the Admin API replay runtime.

## File Format

1. UTF-8 text file.
2. One JSON object per line (NDJSON).
3. Lines are processed in file order.
4. Timestamps must be non-decreasing.

## Required Fields

Every line must include:

1. `type`: one of `orderbook`, `candle`, `trade`.
2. `symbol`: trading symbol string (for example, `AAPL`).
3. `ts` or `t`: numeric timestamp.

Timestamp normalization:

1. Seconds are converted to microseconds.
2. Milliseconds are converted to microseconds.
3. Microseconds are used as-is.

## Event Schemas

## orderbook

Required:

1. `mid`

Optional (defaulted if missing):

1. `spread` -> `0.0`
2. `bids` -> `[]`
3. `asks` -> `[]`

Example:

```json
{"type":"orderbook","symbol":"AAPL","ts":1712000000123456,"mid":188.25,"spread":0.04,"bids":[[188.23,10.0,3]],"asks":[[188.27,9.5,4]]}
```

## candle

Required:

1. `c`

Optional (defaulted if missing):

1. `o` -> `c`
2. `h` -> `c`
3. `l` -> `c`
4. `v` -> `0.0`
5. `t` -> derived from `ts`

Example:

```json
{"type":"candle","symbol":"AAPL","t":1712000000000,"o":188.10,"h":188.30,"l":188.05,"c":188.25,"v":1200.5}
```

## trade

Required:

1. `price`
2. `qty`

Optional (defaulted if missing):

1. `id` -> `0`
2. `buyer` -> `replay_buyer`
3. `seller` -> `replay_seller`

Example:

```json
{"type":"trade","symbol":"AAPL","ts":1712000000456789,"id":42,"price":188.26,"qty":5.0,"buyer":"user_a","seller":"user_b"}
```

## Validation Rules

The API validator rejects datasets if:

1. JSON parsing fails on any line.
2. `type` is not supported.
3. `symbol` is missing.
4. Timestamp is missing or invalid.
5. Timestamps decrease.
6. Event-type required fields are missing.

Use endpoint:

1. `POST /api/market-datasets/{dataset_id}/validate`

to validate and persist integrity status before replay runs.
