---
name: Bit-Think
description: Мультимодельный AI-ассистент в спокойном тёмном интерфейсе с циановым акцентом
colors:
  zinc-base: "#111111"
  zinc-sidebar: "#171717"
  zinc-paper: "#1c1c1c"
  zinc-elevated: "#242424"
  ink-primary: "#ececec"
  ink-secondary: "#9a9a9a"
  ink-muted: "#737373"
  teal-accent: "#21A0CE"
  teal-deep: "#1B87AE"
  hairline: "#ffffff14"
typography:
  display:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "clamp(2rem, 5vw, 3.25rem)"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "clamp(1.5rem, 3vw, 2rem)"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "normal"
  label:
    fontFamily: "Inter Variable, Inter, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
rounded:
  pill: "999px"
  lg: "16px"
  md: "12px"
  sm: "8px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.teal-accent}"
    textColor: "#0b1214"
    rounded: "{rounded.pill}"
    padding: "12px 22px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.pill}"
    padding: "10px 18px"
  input:
    backgroundColor: "{colors.zinc-elevated}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.lg}"
    padding: "16px 14px"
  card:
    backgroundColor: "{colors.zinc-paper}"
    rounded: "{rounded.lg}"
    padding: "24px"
---

# Design System: Bit-Think

## 1. Overview

**Creative North Star: "Ask first"**

Интерфейс строится вокруг одного поля вопроса. Фон — тёплый zinc, не OLED-чёрный. Сайдбар чуть светлее холста. Ответ занимает узкую колонку (~720px). Единственный цвет — циан #21A0CE.

Система отвергает: стекло и blur, фиолетовый AI-акцент, пузыри чата, градиентный текст, одинаковые bento-карточки.

**Key Characteristics:**
- Фон #111111, сайдбар #171717, панели #1c1c1c
- Сплошные поверхности, 1px hairline, без backdrop-filter
- Pill только у кнопок и поискового поля; панели 12–16px
- Motion 150–250ms, только смена состояния

## 2. Colors

**The One Accent Rule.** Бирюза — единственный смысловой цвет. Hover CTA — #1a9aab. Текст на кнопке — почти чёрный (#0b1214), не белый: так контраст на бирюзе выше.

## 3. Typography

Одна гарнитура Inter Variable. В продукте фиксированный rem-масштаб, не clamp, кроме лендингового display.

Вопрос пользователя в треде: title (1.25–1.5rem, 600), не пузырь.
Ответ: body 1rem / 1.65, max-width 65–72ch.

## 4. Elevation

Нет стекла. Иерархия: фон → сайдбар → панель → elevated input. Тень не используется.

## 5. Do's and Don'ts

### Do
- Центрировать вопрос и ответ
- Показывать источники чипами под ответом
- Держать нав ≤ 64px, сайдбар ~260px

### Don't
- Glassmorphism, градиентный текст, фиолетовый неон
- Пузыри пользователя цветом акцента
- Три одинаковые ценовые башни с «Купить», пока оплаты нет

## 6. Light mode

Светлая тема - холодный фарфор с тем же цианом, не кремовая бумага.

- Фон #f3f7f8, сайдбар #eef4f5, панели #ffffff
- Чернила #122024 / #3d5157 / #5a6e74
- Акцент на кнопках остаётся #21A0CE; текст акцента на фарфоре - #187896
- Переключение: Система / Светлая / Тёмная, ключ `bit-think-color-mode`

