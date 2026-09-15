---
name: deck
description: Изобретение слайдов – poster/mosaic/composed, не корпоративный каркас. После visual_system.
---

Не начинай с title → bullets → closing. Придумай, какие кадры нужны ЭТОМУ брифу.

Любимые layout_id (чередуй):
- `poster` / `visual` – full-bleed кадр, `anchor`: bottom-left | center | top-left | bottom-right
- `mosaic` – 2–3 разных image_prompt (деталь / среда / жест)
- `composed` – свой макет в % (x,y,w,h): text, number, image, card, rounded, ellipse, rule, bullets
- `statement` – одна фраза на холст
- `stack` – 3–6 имён вертикально
- `metric_row` – 2–4 цифры, только если они есть в брифе
- `split_visual` – текст + кадр, image_side left|right (чередуй сторону)
- `closing` – следующий шаг для зрителя презы

`composed` elements.type: text, number, image, card, rounded, ellipse, rule, bullets.
style текста: display_xl, display, title, body, caption, kpi.

6–10 слайдов. Минимум 4 с image_prompt. Минимум 2 composed. Никогда два одинаковых layout подряд.

Текст: заголовок ≤ 12 слов плюс subtitle или 3–5 фактов из ТЗ. Пустой слайд запрещён.
Если в документах есть образец PPTX — палитра и шрифты из него. Если есть ТЗ — содержание из него.

JSON-скелет (пример ритма, не копируй palettes):
```json
{
  "kind": "deck",
  "theme_id": "custom",
  "theme": {"bg":"#1A0C10","surface":"#26141A","text":"#F7EFE8","muted":"#B59A90","accent":"#E0B56A","line":"#3A2228","title_font":"Georgia"},
  "title": "Название из брифа",
  "slides": [
    {"layout_id":"poster","title":"...","subtitle":"...","anchor":"bottom-left","image_prompt":"specific scene, no text"},
    {"layout_id":"statement","title":"Одна жёсткая фраза."},
    {"layout_id":"mosaic","title":"...","tiles":[{"image_prompt":"...","caption":"..."},{"image_prompt":"...","caption":"..."}]},
    {"layout_id":"composed","elements":[
      {"type":"number","x":8,"y":18,"w":30,"h":22,"text":"01"},
      {"type":"text","x":8,"y":44,"w":50,"h":20,"style":"display","text":"..."},
      {"type":"image","x":55,"y":12,"w":40,"h":76,"prompt":"..."}
    ]},
    {"layout_id":"closing","title":"...","subtitle":"...","cta":"Первый шаг для зрителя"}
  ]
}
```

Дальше `studio_render` → `studio_build`.
