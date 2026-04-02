---
date: "2026-03-23 15:45"
promoted: false
---

Content-based chunk IDs: chunk_id сейчас позиционный (md5(path:index)), при изменении файла все чанки пересоздаются. Content-based (md5(path:heading:content)) позволит пропускать неизменённые секции при re-embed/re-NER. Отложено: основной паттерн write-once voicenotes, per-file purge достаточен. Вернуться когда частые модификации файлов станут нормой.
