# Search Quality Baseline (E5-large + cosine + cross-encoder gate)

Date: 2026-03-30
Model: intfloat/multilingual-e5-large (1024-dim, TEI)
Distance: cosine (sqlite-vec)
Score floor: 0.85 relative
Cross-encoder gate: logit >= 0

## Test Queries

### "распределение прибыли" (semantic concept, hybrid)
Count: 5
1. [0.885] semantic — Рабочая встреча. Сергей Хабаров. Обсуждение репозиториев
2. [0.861] semantic — Рабочая встреча. Сергей Хабаров
3. [0.724] semantic — Xeon выгружает авторские и смежные (noise)
4. [0.657] semantic — Раскладка добавок на неделю (noise)
5. [0.630] semantic — CLIProxyAPI обновление и деплой (noise)

### "hiveon" (brand name, hybrid)
Count: 3
1. [0.965] keyword+semantic — Закрытие Hiveon: облегчение от ясности
2. [0.905] keyword+semantic — Закрытие Hiveon без новых контрактов
3. [0.861] keyword+semantic — Закрытие Hiveon: облегчение от ясности

### "trickle indexer" (negative test — not in index)
Count: 0 ✓

### "Николай Сенин как делить деньги" (entity+topic, hybrid)
Count: 10
1. [0.836] semantic — 20260318 Знакомство Николай Сенин
2. [0.830] semantic — 20260322 Рабочая встреча Николай Сенин
3. [0.802] semantic — 20260322
4. [0.791] keyword — 20260318
5. [0.732] semantic — 20260319 (contains "35 на 65" text)

### "docker compose" (keyword+semantic, hybrid)
Count: 3
1. [0.918] keyword+semantic — docker-compose.yml Troubleshooting
2. [0.918] keyword+semantic — Project control
3. [0.819] keyword+semantic — FastAPI Project Docker Compose

## Known Issues
- "распределение прибыли" has noise in positions 3-5
- "Николай Сенин делить деньги" — chunk with "35 на 65" at position 5, not top-3
- E5-large cosine anisotropy: all scores cluster 0.78-0.80 before cross-encoder gate
