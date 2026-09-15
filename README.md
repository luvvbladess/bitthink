# Bit-Think

Самостоятельная веб-версия AI-ассистента **Bit-Think** с тёмным интерфейсом, streaming-чатом и поддержкой нескольких языковых моделей.

> Это не веб-обёртка над Telegram-ботом, а полноценный преемник: всё ядро (модели, диалоги, парсинг документов, генерация изображений) живёт внутри `backend/app/bot_core`.

## Структура

```
.
├── backend/              # FastAPI + собственное ядро бота
│   ├── alembic/          # Миграции PostgreSQL
│   ├── app/
│   │   ├── api/          # REST + WebSocket endpoints
│   │   ├── bot_core/     # Ядро: LLM-клиенты, диалоги, инструменты
│   │   ├── core/         # ConversationRepository
│   │   ├── db/           # SQLAlchemy модели + engine
│   │   └── services/     # Chat service
│   ├── data/             # JSON-хранилище (legacy, для миграции)
│   ├── scripts/          # Скрипт миграции JSON → БД
│   ├── uploads/          # Загруженные файлы
│   └── requirements.txt
├── frontend/             # React 18 + TypeScript + Vite + MUI v6
├── data/                 # SQLite-файл (dev) / папка для миграции
├── .env                  # Переменные окружения
└── docker-compose.yml
```

## Быстрый старт (локально с SQLite)

```bash
# 1. Python-зависимости
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r backend/requirements.txt

# 2. Создай .env в корне (пример в backend/.env.example)
cp backend/.env.example .env

# 3. Backend — SQLite создаст таблицы автоматически
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Frontend (в другом окне)
cd ../frontend
npm install
npm run dev
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000
- Документация API: http://localhost:8000/docs

### Создание администратора

```bash
cd backend
python create_admin.py admin@example.com strongpassword
```

Админ-панель: http://localhost:5173/admin

## Быстрый старт (Docker Compose с PostgreSQL)

```bash
cp backend/.env.example .env
# Раскомментируй в .env строку с DATABASE_URL для PostgreSQL
docker-compose up --build
```

Применение миграций внутри контейнера выполняется автоматически.

## Миграция старых JSON-данных

Если у вас остались `backend/users.json` и `data/user_*.json`:

```bash
cd backend
# Для SQLite:
python -m scripts.migrate_json_to_pg

# Для PostgreSQL (таблицы должны быть созданы через alembic):
DATABASE_URL=postgresql+asyncpg://gpt_user:gpt_pass@localhost:5432/gpt_ultra python -m scripts.migrate_json_to_pg
```

## Переменные окружения

```env
SECRET_KEY=your-secret-key
APP_NAME=Bit-Think
DEBUG=true
CORS_ORIGINS=["https://bit-think.space","https://www.bit-think.space","http://localhost:5173","http://127.0.0.1:5173"]

# Database
DATABASE_URL=postgresql+asyncpg://gpt_user:gpt_pass@localhost:5432/gpt_ultra

# LLM API keys
OPENAI_API_KEY=...
DEEPSEEK_API_KEY=...
KIMI_API_KEY=...
KIMI_MODEL=kimi-k2.6
```

> API-ключи читаются из переменных окружения. Заполните `.env` перед запуском.

## Возможности

- Регистрация/вход по email и паролю (JWT access + refresh).
- Роли `user` / `admin`.
- Мультимодальный чат с историей бесед.
- Потоковая генерация ответов через WebSocket.
- Поддержка моделей OpenAI, DeepSeek, Kimi и режимов "Авто", "Дирижёр".
- Загрузка документов (PDF, DOCX, TXT, XLSX).
- Генерация и редактирование изображений.
- Экспорт ответов в DOCX.
- Кастомные системные промпты.
- Тарифы и статистика использования.
- Админ-панель для управления пользователями и их тарифами.

## API (основные endpoints)

- `POST /auth/register`, `POST /auth/login`
- `GET /auth/me`
- `GET /conversations`, `POST /conversations`
- `GET /conversations/{id}/messages`
- `WS /chat/ws?token=...`
- `GET /models`, `POST /models/select`
- `POST /documents`, `POST /media/images/generate`
- `GET /billing/subscription`, `GET /billing/plans`
- `GET /admin/users`, `GET /admin/users/{id}`, `POST /admin/users/{id}/subscription`

## Архитектура

- **PostgreSQL / SQLite** — единое хранилище пользователей, диалогов, сообщений, подписок и usage.
- **JWT-аутентификация** — access/refresh токены, роли в payload.
- **WebSocket-чат** — статусы "thinking" и стриминг чанками.
- **ConversationRepository** — адаптер над `ConversationManager`, отображает email-пользователей на стабильные числовые ID.
- **MD3 + Ethereal Glass** — тёмный OLED-интерфейс со стеклянными карточками и анимациями Framer Motion.

## Известные ограничения

- Онлайн-оплата пока не подключена: `POST /billing/payment/{plan}` отвечает 503, тариф выдаёт администратор.
- Пароли хешируются bcrypt. Старые SHA256+salt хеши принимаются и переписываются при следующем логине.
- Для production рекомендуется PostgreSQL + Alembic-миграции. CORS задаётся через `CORS_ORIGINS` в `.env`.

## Лицензия

Создано как преемник проекта GPT Ultra, теперь Bit-Think.
