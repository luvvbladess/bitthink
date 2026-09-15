---
name: infographic
description: Одноэкранный кадр как у дизайнера – composed сетка и фото, не ряд карточек. После visual_system.
---

Один кадр – одна история. По умолчанию `layout_id: composed`, не process/kpi_strip.

Сделай уникальную сетку в процентах. Можно:
- огромная цифра слева, путь справа;
- фото на 60% кадра, типографический столбец;
- лента фактов снизу, объект сверху.

`elements.type`: text, number, image, card, rounded, ellipse, rule, bullets.
Обязателен `image_prompt` фона по теме. 1–3 type:image с разными кадрами.

Ориентация landscape 16:9, portrait только если просили stories.

Запрещено: пять одинаковых скруглений, emoji, clipart, футер «Bit-Think Studio».

```json
{
  "kind": "infographic",
  "theme_id": "custom",
  "theme": {"bg":"#E7DFD2","surface":"#F6F0E6","text":"#1C1814","muted":"#6F675C","accent":"#2C4A3E","line":"#D4C8B6"},
  "layout_id": "composed",
  "orientation": "landscape",
  "headline": "...",
  "image_prompt": "atmospheric still of the subject, no text",
  "elements": [
    {"type":"text","x":6,"y":8,"w":55,"h":16,"style":"display","text":"..."},
    {"type":"number","x":6,"y":30,"w":22,"h":18,"text":"04"},
    {"type":"image","x":52,"y":12,"w":42,"h":76,"prompt":"specific object crop, no text"}
  ]
}
```

Фиксированные layout (timeline/process/funnel/kpi_strip/compare_cards/hierarchy) – если бриф просит воронку, таймлайн, **схему процесса / swimlane / блок-схему**. Тогда `layout_id: process`, живые русские подписи в каждом узле, один кадр (не многостраничный A3 PDF).

Кириллица только в studio_build или PNG с DejaVu. ReportLab + Helvetica даёт нечитаемые палки – так схему не сдавай.

Дальше `studio_render` → `studio_build`.
