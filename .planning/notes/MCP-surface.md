# MCP Tool Surface Design

## Competitive Context

How RAG/knowledge-base MCP servers typically design their tool surface:

| Service | Search | Follow-up |
|---------|--------|-----------|
| **Mem0/Supermemory** | `recall(query)` → полные memories сразу | нет — маленькие записи, всё в одном ответе |
| **Notion** | `search(query)` → snippets + ID | `fetch(id)` → полный контент страницы |
| **Obsidian** | `search_content(query)` → snippets + paths | `read_notes(paths)` + `get_frontmatter(path)` + `backlinks(path)` |
| **dotmd** | `search(query, top_k?)` → snippet + file_paths + heading + score | `drill(file_path)` |

**Вывод:** memory-сервисы (mem0, supermemory) всё возвращают сразу, потому что у них маленькие записи.
Obsidian и Notion — классический двушаговый паттерн: search → get.
Obsidian разделяет контент, метаданные и связи на три отдельных инструмента.

## Design Decisions

### search() — только нужное
До: `search(query, top_k, mode, rerank)` — 4 параметра, из которых агент использует только 1.
После: `search(query, top_k?)` — `mode` и `rerank` убраны как internal details.

Из ответа убраны:
- `matched_engines` — какие движки сработали (internal)
- `start_time` — первый `[HH:MM:SS]` из текста чанка (internal, timestamps из сниппета вырезаются, но не возвращаются)

Ответ search: `file_paths`, `heading`, `snippet`, `score`.

`heading` — breadcrumb заголовков над чанком (`"Meeting Notes > Action Items"`).
Для войснотов, разбитых по спикерам, это имя спикера.

### drill(file_path) — follow-up инструмент
Мотивация: Гермес нашёл войснот про Даннинга-Крюгера (score 0.904), но не мог получить
speaker, tags, дату и связанные документы. `file_path` уже есть в search-результатах —
агенту нужен только один дополнительный вызов.

Название `drill` выбрано вместо `get_document` (мы не возвращаем документ) и `get_metadata`
(слишком сухо). `drill` передаёт намерение: нашёл в search → провалился глубже.

Возвращает:
```json
{
  "file_path": "/mnt/knowledgebase/...",
  "frontmatter": { "title": "...", "date": "...", "tags": [...], "speaker": "..." },
  "chunk_count": 12,
  "entities": ["Даннинг-Крюгер", "когнитивные искажения", ...]
}
```

- `frontmatter` — читается с диска через `parse_frontmatter`
- `chunk_count` — из M2M таблицы активной стратегии
- `entities` — `MATCH (s:Section {file_path})--(e:Entity) RETURN DISTINCT e.id` (FalkorDB)

Entities — мост к графу без отдельного graph-инструмента: агент видит имена сущностей
и может формулировать follow-up поиск по ним.

## Current Tool Surface (after changes)

```
search(query, top_k=10)
  → [{file_paths, heading, snippet, score}, ...]

drill(file_path)
  → {file_path, frontmatter, chunk_count, entities}

status()
  → index stats + graph counts
```

## What's Still Missing (backlog)

- **999.9**: MCP tool — graph entity inspection. Traverse FalkorDB от entity name → related entities + documents. Пока агент может использовать entities из drill() как входные данные для follow-up search, но прямого граф-обхода нет.
- **999.11**: MCP list_resources — реестр индексированных файлов.
