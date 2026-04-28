---
id: SEED-001
status: dormant
planted: 2026-04-28
planted_during: v1.4 — reindex post-999.12 (trickle running, 400+/734 files done)
trigger_when: reindex 734/734 completed — immediately actionable
scope: Medium
---

# SEED-001: Безопасная архитектура миграций — вынести авто-вайп из startup в явный admin-скрипт

## Why This Matters

Сегодня (2026-04-28) мы потеряли ~3 часа и дважды сбросили прогресс reindex из-за
автоматического вайпа, который срабатывал при каждом запуске `dotmd search` / `dotmd status`
пока reindex шёл. Первопричина: `_check_weights_changed` вызывал `delete_all()` который
стирал `schema_version` sentinel, и следующий `_check_schema_version` видел None → вайп.

Оба бага закрыты (два патча в этой сессии), но **архитектурная проблема остаётся**:
авто-вайп при старте — это заряженное ружьё без предохранителя для сервиса, где
полный reindex занимает 2+ суток. Любой будущий баг, убивающий sentinel, потенциально
стоит 48+ часов вычислений.

Консультация с expert panel (2026-04-28) подтвердила: это стандартная антипаттерна,
от которой уходят все серьёзные системы (Postgres/Alembic требуют явного оператора
для деструктивных миграций).

## When to Surface

**Trigger:** reindex 734/734 завершён — задача немедленно актуальна

This seed should be presented during `/gsd-new-milestone` when the milestone scope
matches any of these conditions:
- Milestone содержит infrastructure / reliability / operations фазы
- Milestone затрагивает schema, embeddings, или pipeline rework
- Любое следующее milestone после завершения v1.4 reindex

## Scope Estimate

**Medium** — 1-2 фазы:
- Фаза A: рефакторинг `_check_schema_version` (read-only → raise `SchemaMigrationRequired`)
- Фаза B: `dotmd admin migrate` subcommand с `migration_log` таблицей

## Рекомендованный план (из expert panel 2026-04-28)

### Ключевые решения

**1. `dotmd serve` никогда не вайпает автоматически**
- `_check_schema_version`: read-only — читает sentinel, если mismatch → `SchemaMigrationRequired(version_found, version_expected)` с инструкцией
- Добавить тест: запуск с несовпадающей версией → выход с кодом 1 + инструкция, никогда не вайп

**2. `dotmd admin migrate` — явный double-opt-in**
```
dotmd admin migrate \
  --confirm \
  --i-understand-rebuild-takes-days \
  [--dry-run]                          # показать что удалится без действия
  [--components graph,vectors]         # будущее: точечный вайп компонентов
  [--backup-sentinel /tmp/sentinel.json]
```

**3. Append-only `migration_log` таблица** (QA рекомендация — crash-safe)
```sql
CREATE TABLE migration_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_version TEXT,
  to_version TEXT,
  component TEXT,          -- 'all' | 'vectors' | 'graph' | 'weights'
  status TEXT,             -- 'started' | 'completed' | 'failed'
  started_at TEXT,
  finished_at TEXT
);
```
На старте: если есть строка `status='started'` без `finished_at` → auto-resume
(безопасно — уже согласованное решение оператора). Новый вайп без явного запуска → никогда.

**4. Компонентный вайп — отложить на потом** (Kaizen решение)
Сейчас: full-wipe через admin-скрипт — достаточно.
Добавить per-component только когда второй тип миграции реально понадобится:

| Тип изменения | Стоимость | Нужен ли полный вайп |
|---|---|---|
| Смена весов (text/meta) | Минуты — recompute e_fused из компонентов | Нет (если добавить) |
| Смена модели embeddings | Дни — re-embed всё | Да |
| Смена chunking strategy | Дни — re-chunk + re-embed | Да |
| Изменение graph schema | Часы — только граф | Нет (если добавить) |

**5. Тест на регрессию** (QA настаивает)
```python
def test_schema_mismatch_raises_not_wipes():
    # Записать version=1, запустить pipeline с SCHEMA_VERSION=2
    # Проверить: SystemExit(1) или SchemaMigrationRequired raised
    # Проверить: chunk_fingerprints НЕ очищены
```

### Risk Register

| Риск | Митигация |
|---|---|
| Sentinel удалён новым `delete_all()` | 2 патча в этой сессии закрывают оба пути. migration_log — backup |
| Оператор запустит `migrate` случайно | Double flag: `--confirm` + `--i-understand-rebuild-takes-days` |
| Краш mid-wipe → partial state | `migration_log` строка `status=started` → auto-resume при следующем `migrate` |
| Будущий разработчик добавит авто-вайп обратно | Комментарий в коде + тест |

## Breadcrumbs

Ключевые файлы для реализации:

- `backend/src/dotmd/ingestion/pipeline.py`
  - `_check_schema_version()` — строки ~2204-2340: здесь убрать wipe path, добавить `raise SchemaMigrationRequired`
  - `_check_weights_changed()` — строки ~2344-2480: исправлено в этой сессии (2 патча)
  - `SCHEMA_VERSION = '2'` — строка ~60: константа версии

- `backend/src/dotmd/storage/sqlite_vec.py`
  - `delete_all()` — строка ~354: удаляет `schema_version` из config таблицы — это и есть корень проблемы
  - Исправлено в `_check_weights_changed`, но `delete_all()` по-прежнему деструктивен

- `backend/src/dotmd/cli.py`
  - Здесь добавить `@cli.group('admin')` + `@admin.command('migrate')`

- `backend/src/dotmd/api/service.py`
  - `status()` строка ~429: исправлено (live graph counts)

## Session Context (2026-04-28)

Что случилось сегодня — для контекста:
1. Container startup (17:34 UTC): wipe #1 — старые fingerprints в pre-999.12 формате (ожидаемо)
2. `dotmd search` (17:59 UTC): wipe #2 — `_check_weights_changed` стёр sentinel через `delete_all()`
3. `dotmd search` (18:09 UTC): wipe #3 — та же причина
4. Патч 1: early return в `_check_weights_changed` когда `weights_used is None`
5. Патч 2: restore sentinel после `delete_all()` в пути реального изменения весов
6. Ручная запись sentinel + weights_used → стабилизация
7. Expert panel → этот seed

Reindex запущен заново в 18:09 UTC 2026-04-28. ETA ~22:00 UTC 2026-04-28.
После завершения — этот seed актуален.
