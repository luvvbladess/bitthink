"""
Менеджер бесед пользователей
Хранит историю сообщений для каждой беседы и настройки пользователя
"""

import json
import os
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timezone, timedelta

from config import DEFAULT_MODEL

MSK_TZ = timezone(timedelta(hours=3))  # Москва не переходит на летнее время — фиксированный UTC+3


def _msk_now() -> datetime:
    """Текущее время в МСК, независимо от часового пояса сервера (используется для сброса трат)."""
    return datetime.now(MSK_TZ)

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Сообщение в беседе"""
    role: str  # 'user' или 'assistant'
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    attachment: Optional[dict] = None
    search: Optional[List[Dict[str, str]]] = None

    def to_dict(self) -> dict:
        data = {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }
        if self.attachment:
            data["attachment"] = self.attachment
        if self.search:
            data["search"] = self.search
        return data


@dataclass  
class Conversation:
    """Беседа с историей сообщений"""
    id: str
    title: str
    messages: List[Message] = field(default_factory=list)
    documents: List[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "documents": getattr(self, "documents", []),
            "created_at": self.created_at
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        messages = [Message(**m) for m in data.get("messages", [])]
        return cls(
            id=data["id"],
            title=data["title"],
            messages=messages,
            documents=data.get("documents", []),
            created_at=data.get("created_at", datetime.now().isoformat())
        )


class ConversationManager:
    """Менеджер бесед для всех пользователей"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        
        # user_id -> {conversation_id -> Conversation} (user_id can be int or str)
        self._conversations: Dict[Union[int, str], Dict[str, Conversation]] = {}
        # user_id -> active_conversation_id
        self._active_conversations: Dict[Union[int, str], str] = {}
        # user_id -> selected_model
        self._user_models: Dict[Union[int, str], str] = {}
        # user_id -> dict
        self._subscriptions: Dict[Union[int, str], dict] = {}
        # user_id -> edit_mode (True/False)
        self._edit_mode: Dict[int, bool] = {}
        # user_id -> stored image bytes for editing
        self._user_images: Dict[int, bytes] = {}
        # user_id -> dalle_mode (True/False)
        self._dalle_mode: Dict[int, bool] = {}
        # user_id -> stored dalle image bytes
        self._dalle_images: Dict[int, bytes] = {}
        # user_id -> template_mode (True/False)
        self._template_mode: Dict[int, bool] = {}
        # user_id -> stored template doc bytes
        self._template_docs: Dict[int, bytes] = {}
        # user_id -> stored template doc filename
        self._template_names: Dict[int, str] = {}
        # user_id -> base_template_mode (True/False)
        self._base_template_mode: Dict[int, bool] = {}
        # user_id -> stored base template doc bytes
        self._base_template_docs: Dict[int, bytes] = {}
        # user_id -> stored base template doc filename
        self._base_template_names: Dict[int, str] = {}
        # user_id -> cached custom prompts list
        self._custom_prompts: Dict[int, List[str]] = {}
        # user_id -> active custom prompt text
        self._active_custom_prompt: Dict[int, str] = {}
        
        # user_id -> dict with metadata (name, username, etc.)
        self._user_profiles: Dict[Union[int, str], dict] = {}
        # user_id -> {"YYYY-MM": {model: {"input": N, "output": N, "images": N}}}
        self._token_usage: Dict[Union[int, str], dict] = {}
        
        # context_id -> is_enabled (для групп и тем)
        self._allowed_contexts: Dict[str, bool] = {}
        self._load_allowed_contexts()
        
        
    def _get_user_file(self, user_id: Union[int, str]) -> str:
        return os.path.join(self.data_dir, f"user_{user_id}.json")
    
    def _load_user_data(self, user_id: Union[int, str]) -> None:
        """Загружает данные пользователя из файла"""
        if user_id in self._conversations:
            return
        file_path = self._get_user_file(user_id)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                self._conversations[user_id] = {}
                for conv_data in data.get("conversations", []):
                    conv = Conversation.from_dict(conv_data)
                    self._conversations[user_id][conv.id] = conv
                    
                self._active_conversations[user_id] = data.get("active_conversation_id")
                saved_model = data.get("selected_model", DEFAULT_MODEL)
                if saved_model == "gpt-5.2":
                    saved_model = "gpt-5.5"
                elif saved_model == "gpt-5.2-pro":
                    saved_model = "gpt-5.5-pro"
                elif saved_model == "gpt-5-mini":
                    saved_model = "gpt-5.4-mini"
                # Миграция на линейку GPT-5.6 (Sol/Terra/Luna) - применяется цепочкой,
                # чтобы даже очень старые сохранённые значения (gpt-5.2 -> gpt-5.5 -> ...)
                # корректно доехали до актуального ID за одну загрузку.
                if saved_model == "gpt-5.5":
                    saved_model = "gpt-5.6-sol"
                elif saved_model == "gpt-5.5-pro":
                    saved_model = "gpt-5.6-sol-pro"
                elif saved_model == "gpt-5.4-mini":
                    saved_model = "gpt-5.6-luna"
                elif saved_model == "gpt-5.4":
                    saved_model = "gpt-5.6-terra"
                if saved_model in {"gpt-5.6-sol", "gpt-5.6-sol-pro", "gpt-5.6-terra"}:
                    saved_model = "gpt-6-sol"
                elif saved_model == "gpt-5.6-luna":
                    saved_model = "gpt-6-luna"
                self._user_models[user_id] = saved_model
                
                # Загружаем кастомные промпты
                self._custom_prompts[user_id] = data.get("custom_prompts", [])
                
                # Загружаем подписку
                self._subscriptions[user_id] = data.get("subscription", self._get_default_subscription(user_id))
                
                # Загружаем профиль
                self._user_profiles[user_id] = data.get("profile", {"first_name": "User", "username": None})

                # Загружаем траты на токены
                self._token_usage[user_id] = data.get("token_usage", {})
            except Exception:
                self._conversations[user_id] = {}
                self._active_conversations[user_id] = None
                self._user_models[user_id] = DEFAULT_MODEL
                self._subscriptions[user_id] = self._get_default_subscription(user_id)
                self._user_profiles[user_id] = {"first_name": "User", "username": None}
                self._token_usage[user_id] = {}
        else:
            self._conversations[user_id] = {}
            self._active_conversations[user_id] = None
            self._user_models[user_id] = DEFAULT_MODEL
            self._subscriptions[user_id] = self._get_default_subscription(user_id)
            self._user_profiles[user_id] = {"first_name": "User", "username": None}
            self._token_usage[user_id] = {}

    def _save_user_data(self, user_id: Union[int, str]) -> None:
        """Сохраняет данные пользователя в файл (атомарно)"""
        file_path = self._get_user_file(user_id)
        temp_path = file_path + ".tmp"

        data = {
            "conversations": [conv.to_dict() for conv in self._conversations.get(user_id, {}).values()],
            "active_conversation_id": self._active_conversations.get(user_id),
            "selected_model": self._user_models.get(user_id, DEFAULT_MODEL),
            "subscription": self._subscriptions.get(user_id, self._get_default_subscription(user_id)),
            "custom_prompts": self._custom_prompts.get(user_id, []),
            "profile": self._user_profiles.get(user_id, {"first_name": "User", "username": None}),
            "token_usage": self._token_usage.get(user_id, {})
        }
        
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Атомарная замена файла (работает и на Windows, и на Linux)
            if os.path.exists(file_path):
                os.replace(temp_path, file_path)
            else:
                os.rename(temp_path, file_path)
        except Exception as e:
            logger.error(f"Error saving user data for {user_id}: {e}")
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except: pass

    def _load_allowed_contexts(self) -> None:
        """Загружает список разрешенных групп/тем"""
        file_path = os.path.join(self.data_dir, "allowed_contexts.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self._allowed_contexts = json.load(f)
            except Exception:
                self._allowed_contexts = {}
        else:
            self._allowed_contexts = {}

    def _save_allowed_contexts(self) -> None:
        """Сохраняет список разрешенных групп/тем"""
        file_path = os.path.join(self.data_dir, "allowed_contexts.json")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self._allowed_contexts, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def is_context_allowed(self, context_id: Union[int, str]) -> bool:
        """Проверяет, разрешена ли работа в данном контексте"""
        # Личные чаты разрешены всегда
        if isinstance(context_id, int) or (isinstance(context_id, str) and context_id.isdigit()):
            return True
            
        if str(context_id) in self._allowed_contexts:
            return self._allowed_contexts[str(context_id)]
        
        # Если это тема вида topic_CHATID_THREADID, проверяем также просто CHATID
        if isinstance(context_id, str) and context_id.startswith("topic_"):
            parts = context_id.split("_")
            if len(parts) >= 2:
                chat_id = parts[1]
                if chat_id in self._allowed_contexts:
                    return self._allowed_contexts[chat_id]
        
        return False

    def set_context_allowed(self, context_id: str, status: bool) -> None:
        """Устанавливает статус разрешения для контекста"""
        self._allowed_contexts[str(context_id)] = status
        self._save_allowed_contexts()


    def get_all_users(self) -> list[Union[int, str]]:
        """Возвращает список всех ID пользователей (из файлов), включая строковые ID тем"""
        if not os.path.exists(self.data_dir):
            return []
        users = []
        for filename in os.listdir(self.data_dir):
            if filename.startswith("user_") and filename.endswith(".json"):
                try:
                    raw_id = filename.split("_", 1)[1].rsplit(".", 1)[0]
                    # Пытаемся преобразовать в int, если возможно
                    if raw_id.isdigit() or (raw_id.startswith("-") and raw_id[1:].isdigit()):
                        users.append(int(raw_id))
                    else:
                        users.append(raw_id)
                except (ValueError, IndexError):
                    pass
        return users

    # ===== Методы для учёта трат на токены/изображения =====

    def track_tokens(
        self,
        user_id: int,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """Прибавляет токены к счётчику пользователя за сегодняшний день"""
        if not input_tokens and not output_tokens:
            return
        self._load_user_data(user_id)
        day = _msk_now().strftime("%Y-%m-%d")
        day_data = self._token_usage.setdefault(user_id, {}).setdefault(day, {})
        entry = day_data.setdefault(model, {"input": 0, "output": 0, "images": 0, "calls": 0})
        entry["input"] += input_tokens
        entry["output"] += output_tokens
        self._save_user_data(user_id)
        try:
            from app.billing.quota import debit_model_usage

            debit_model_usage(
                user_id, model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens
            )
        except Exception:
            logger.exception("Failed to debit plan tokens for user %s", user_id)

    def track_image(self, user_id: int, model: str, count: int = 1) -> None:
        """Прибавляет счётчик сгенерированных изображений за сегодняшний день"""
        self._load_user_data(user_id)
        day = _msk_now().strftime("%Y-%m-%d")
        day_data = self._token_usage.setdefault(user_id, {}).setdefault(day, {})
        entry = day_data.setdefault(model, {"input": 0, "output": 0, "images": 0, "calls": 0})
        entry["images"] += count
        self._save_user_data(user_id)
        try:
            self.debit_plan_images(user_id, count)
        except Exception:
            logger.exception("Failed to debit plan images for user %s", user_id)

    def track_calls(self, user_id: int, model: str, count: int = 1) -> None:
        """Прибавляет счётчик платных вызовов инструмента (например, $web_search у Kimi) за сегодняшний день"""
        self._load_user_data(user_id)
        day = _msk_now().strftime("%Y-%m-%d")
        day_data = self._token_usage.setdefault(user_id, {}).setdefault(day, {})
        entry = day_data.setdefault(model, {"input": 0, "output": 0, "images": 0, "calls": 0})
        entry["calls"] += count
        self._save_user_data(user_id)

    def get_day_usage(self, user_id: Union[int, str], day: str = None) -> dict:
        """Возвращает траты пользователя {model: {input, output, images, calls}} за один день (по умолчанию сегодня)"""
        self._load_user_data(user_id)
        day = day or _msk_now().strftime("%Y-%m-%d")
        return self._token_usage.get(user_id, {}).get(day, {})

    def get_month_usage(self, user_id: Union[int, str], month: str = None) -> dict:
        """Суммирует траты пользователя {model: {input, output, images, calls}} по всем дням месяца (по умолчанию текущий)"""
        self._load_user_data(user_id)
        month = month or _msk_now().strftime("%Y-%m")
        total: dict = {}
        for key, day_data in self._token_usage.get(user_id, {}).items():
            if not key.startswith(month):
                continue
            for model, counts in day_data.items():
                entry = total.setdefault(model, {"input": 0, "output": 0, "images": 0, "calls": 0})
                for field in ("input", "output", "images", "calls"):
                    entry[field] += counts.get(field, 0)
        return total

    # ===== Методы для работы с подписками =====
    
    def get_user_profile(self, user_id: Union[int, str]) -> dict:
        """Получает профиль пользователя"""
        self._load_user_data(user_id)
        return self._user_profiles.get(user_id, {"first_name": "User", "username": None})
    
    def update_user_profile(self, user_id: Union[int, str], first_name: str = None, username: str = None) -> None:
        """Обновляет данные профиля пользователя"""
        self._load_user_data(user_id)
        profile = self._user_profiles.get(user_id, {"first_name": "User", "username": None})
        if first_name:
            profile["first_name"] = first_name
        if username:
            profile["username"] = username
        self._user_profiles[user_id] = profile
        self._save_user_data(user_id)

    def _get_default_subscription(self, user_id: int) -> dict:
        return {
            "tier": "free",
            "expires_at": 0,
            "daily_nano_mini": 0,
            "daily_gpt54": 0,
            "daily_director": 0,
            "daily_images": 0,
            "daily_docs": 0,
            "last_reset_date": datetime.now().strftime("%Y-%m-%d"),
            "has_used_trial": False,
            "active_promocode": None,
            "last_reminded_date": None,
            "period_start": datetime.now().strftime("%Y-%m"),
            "chat_tokens_used": 0,
            "computer_tokens_used": 0,
            "images_used": 0,
            "nano_cushion_date": datetime.now().strftime("%Y-%m-%d"),
            "nano_cushion_used": 0,
            "session_started_at": 0,
            "session_chat_used": 0,
            "session_computer_used": 0,
            "week_start": "",
            "week_chat_used": 0,
            "week_computer_used": 0,
        }
        
    def get_subscription(self, user_id: Union[int, str]) -> dict:
        """Возвращает данные о подписке пользователя, сбрасывая лимиты при наступлении нового дня"""
        from app.billing.quota import refresh_windows

        self._load_user_data(user_id)
        sub = self._subscriptions.get(user_id, self._get_default_subscription(user_id))
        refresh_windows(sub)

        # Миграция старого ключа (если есть)
        if "daily_gpt52" in sub:
            sub["daily_gpt54"] = sub.pop("daily_gpt52")

        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)
        return sub
        
    def update_subscription_limits(self, user_id: Union[int, str], field: str, value: int = 1) -> None:
        """Обновляет счетчики использования для пользователя (или другие поля)"""
        sub = self.get_subscription(user_id)
        if field in sub and isinstance(sub[field], int):
            sub[field] += value
        else:
            sub[field] = value
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    def set_active_promocode(self, user_id: int, promocode: str) -> None:
        """Активирует промокод для пользователя"""
        sub = self.get_subscription(user_id)
        sub["active_promocode"] = promocode
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)
        
    def get_active_promocode(self, user_id: int) -> str:
        """Возвращает активный промокод пользователя"""
        sub = self.get_subscription(user_id)
        return sub.get("active_promocode")
        
    def set_reminded_date(self, user_id: int) -> None:
        """Отмечает, что пользователю отправлена напоминалка сегодня"""
        sub = self.get_subscription(user_id)
        sub["last_reminded_date"] = datetime.now().strftime("%Y-%m-%d")
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    def set_subscription_tier(self, user_id: int, tier: str, duration_days: int = 30, from_today: bool = False) -> None:
        """Устанавливает новый тариф для пользователя на указанное число дней"""
        sub = self.get_subscription(user_id)
        sub["tier"] = tier
        
        if tier == "free" or duration_days <= 0:
            # Сброс на бесплатный тариф — явно обнуляем срок действия
            sub["expires_at"] = 0
        else:
            now_ts = int(datetime.now().timestamp())
            if from_today:
                start_ts = now_ts
            else:
                # Продление: если подписка еще активна, добавляем к ней. Если нет — от текущего момента.
                start_ts = max(now_ts, sub.get("expires_at", 0))
            sub["expires_at"] = start_ts + (duration_days * 24 * 60 * 60)
        
        # Если активирован trial, отмечаем
        if tier == "trial":
            sub["has_used_trial"] = True
            
        # При успешной покупке сбрасываем промокод (но не при откате на free)
        if tier != "free":
            sub["active_promocode"] = None
        sub["period_start"] = datetime.now().strftime("%Y-%m")
        sub["chat_tokens_used"] = 0
        sub["computer_tokens_used"] = 0
        sub["images_used"] = 0
        sub["nano_cushion_date"] = datetime.now().strftime("%Y-%m-%d")
        sub["nano_cushion_used"] = 0
        sub["session_started_at"] = 0
        sub["session_chat_used"] = 0
        sub["session_computer_used"] = 0
        from app.billing.quota import msk_monday
        sub["week_start"] = msk_monday()
        sub["week_chat_used"] = 0
        sub["week_computer_used"] = 0
        
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    def debit_plan_tokens(self, user_id: int, pool: str, amount: int, model: str = "") -> None:
        if amount <= 0:
            return
        from app.billing.quota import apply_token_debit

        sub = self.get_subscription(user_id)
        apply_token_debit(sub, pool, amount)
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    def debit_plan_images(self, user_id: int, count: int = 1) -> None:
        if count <= 0:
            return
        from app.billing.plans import plan_for

        sub = self.get_subscription(user_id)
        if plan_for(sub.get("tier")).get("unlimited"):
            return
        sub["images_used"] = int(sub.get("images_used") or 0) + count
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    def increment_nano_cushion(self, user_id: int) -> None:
        sub = self.get_subscription(user_id)
        sub["nano_cushion_used"] = int(sub.get("nano_cushion_used") or 0) + 1
        self._subscriptions[user_id] = sub
        self._save_user_data(user_id)

    # ===== Методы для работы с моделями =====
    
    def get_user_model(self, user_id: Union[int, str]) -> str:
        """Получает выбранную модель пользователя"""
        self._load_user_data(user_id)
        return self._user_models.get(user_id, DEFAULT_MODEL)
    
    def set_user_model(self, user_id: Union[int, str], model: str) -> None:
        """Устанавливает модель для пользователя"""
        self._load_user_data(user_id)
        self._user_models[user_id] = model
        self._save_user_data(user_id)
    
    # ===== Методы для режима редактирования =====
    
    def is_edit_mode(self, user_id: int) -> bool:
        """Проверяет, включён ли режим редактирования"""
        return self._edit_mode.get(user_id, False)
    
    def set_edit_mode(self, user_id: int, enabled: bool) -> None:
        """Включает/выключает режим редактирования"""
        self._edit_mode[user_id] = enabled
        if not enabled:
            # При выключении режима очищаем сохранённое изображение
            self._user_images.pop(user_id, None)
    
    def get_user_image(self, user_id: int) -> Optional[bytes]:
        """Получает сохранённое изображение пользователя"""
        return self._user_images.get(user_id)
    
    def set_user_image(self, user_id: int, image_bytes: bytes) -> None:
        """Сохраняет изображение пользователя для редактирования"""
        self._user_images[user_id] = image_bytes
    
    def clear_user_image(self, user_id: int) -> None:
        """Очищает сохранённое изображение"""
        self._user_images.pop(user_id, None)
    
    # ===== Методы для DALL-E режима =====
    
    def is_dalle_mode(self, user_id: int) -> bool:
        """Проверяет, включён ли DALL-E режим"""
        return self._dalle_mode.get(user_id, False)
    
    def set_dalle_mode(self, user_id: int, enabled: bool) -> None:
        """Включает/выключает DALL-E режим"""
        self._dalle_mode[user_id] = enabled
        if not enabled:
            self._dalle_images.pop(user_id, None)
    
    def get_dalle_image(self, user_id: int) -> Optional[bytes]:
        """Получает последнее сгенерированное DALL-E изображение"""
        return self._dalle_images.get(user_id)
    
    def set_dalle_image(self, user_id: int, image_bytes: bytes) -> None:
        """Сохраняет сгенерированное изображение"""
        if not hasattr(self, '_dalle_images'):
            self._dalle_images = {}
        self._dalle_images[user_id] = image_bytes

    # ===== Методы для режима шаблонов документов =====
    
    def is_template_mode(self, user_id: int) -> bool:
        """Проверяет, включён ли режим шаблонов"""
        return self._template_mode.get(user_id, False)
    
    def set_template_mode(self, user_id: int, enabled: bool) -> None:
        """Включает/выключает режим шаблонов"""
        self._template_mode[user_id] = enabled
        if not enabled:
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)
    
    def get_template_doc(self, user_id: int) -> Optional[bytes]:
        """Получает сохранённый шаблон документа"""
        return self._template_docs.get(user_id)
    
    def get_template_name(self, user_id: int) -> Optional[str]:
        """Получает имя сохранённого шаблона"""
        return self._template_names.get(user_id)
    
    def set_template_doc(self, user_id: int, doc_bytes: bytes, filename: str) -> None:
        """Сохраняет шаблон документа"""
        self._template_docs[user_id] = doc_bytes
        self._template_names[user_id] = filename

    # ===== Методы для базового шаблона (основа генерации) =====
    
    def is_base_template_mode(self, user_id: int) -> bool:
        return self._base_template_mode.get(user_id, False)
    
    def set_base_template_mode(self, user_id: int, enabled: bool) -> None:
        self._base_template_mode[user_id] = enabled
    
    def _get_template_dir(self) -> str:
        """Путь к папке с шаблонами"""
        template_dir = os.path.join(self.data_dir, "templates")
        os.makedirs(template_dir, exist_ok=True)
        return template_dir
    
    def _get_template_path(self, user_id: int) -> str:
        return os.path.join(self._get_template_dir(), f"template_{user_id}.docx")
    
    def _get_template_meta_path(self, user_id: int) -> str:
        return os.path.join(self._get_template_dir(), f"template_{user_id}.meta")
    
    def get_base_template(self, user_id: int) -> Optional[bytes]:
        # Сначала проверяем кэш в памяти
        if user_id in self._base_template_docs:
            return self._base_template_docs[user_id]
        
        # Если нет в памяти — читаем с диска
        path = self._get_template_path(user_id)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                data = f.read()
            self._base_template_docs[user_id] = data
            return data
        return None
    
    def get_base_template_name(self, user_id: int) -> Optional[str]:
        if user_id in self._base_template_names:
            return self._base_template_names[user_id]
        
        # Читаем с диска
        meta_path = self._get_template_meta_path(user_id)
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                name = f.read().strip()
            self._base_template_names[user_id] = name
            return name
        return None
    
    def set_base_template(self, user_id: int, doc_bytes: bytes, filename: str) -> None:
        if not hasattr(self, '_base_template_docs'):
            self._base_template_docs = {}
        if not hasattr(self, '_base_template_names'):
            self._base_template_names = {}
        
        # Сохраняем в память (кэш)
        self._base_template_docs[user_id] = doc_bytes
        self._base_template_names[user_id] = filename
        
        # Сохраняем на диск
        with open(self._get_template_path(user_id), 'wb') as f:
            f.write(doc_bytes)
        with open(self._get_template_meta_path(user_id), 'w', encoding='utf-8') as f:
            f.write(filename)

    def clear_base_template(self, user_id: int) -> bool:
        """Удаляет сохранённый базовый шаблон (память + диск). Возвращает True, если что-то было удалено."""
        had_template = (
            user_id in self._base_template_docs
            or os.path.exists(self._get_template_path(user_id))
        )

        self._base_template_docs.pop(user_id, None)
        self._base_template_names.pop(user_id, None)
        self._base_template_mode[user_id] = False

        path = self._get_template_path(user_id)
        if os.path.exists(path):
            os.remove(path)
        meta_path = self._get_template_meta_path(user_id)
        if os.path.exists(meta_path):
            os.remove(meta_path)

        return had_template

    # ===== Методы для кастомных промптов =====
    
    def get_custom_prompts(self, user_id: int) -> List[str]:
        """Получает список кастомных промптов пользователя (максимум 2)"""
        self._load_user_data(user_id)
        return self._custom_prompts.get(user_id, [])
    
    def add_custom_prompt(self, user_id: int, prompt: str) -> int:
        """
        Добавляет кастомный промпт пользователю.
        Если уже 2 промпта, старейший заменяется на новый.
        Возвращает индекс добавленного/заменённого промпта (1 или 2).
        """
        self._load_user_data(user_id)
        if not hasattr(self, '_custom_prompts'):
            self._custom_prompts = {}
        
        if user_id not in self._custom_prompts:
            self._custom_prompts[user_id] = []
        
        prompts = self._custom_prompts[user_id]
        
        if len(prompts) < 2:
            # Есть место - просто добавляем
            prompts.append(prompt)
            self._save_custom_prompts(user_id)
            return len(prompts)
        else:
            # Все слоты заняты - заменяем самый старый (первый)
            prompts.pop(0)
            prompts.append(prompt)
            self._save_custom_prompts(user_id)
            return 2  # Новый всегда становится вторым
    
    def get_active_custom_prompt(self, user_id: int) -> Optional[str]:
        """Получает активный кастомный промпт (если выбран)"""
        return self._active_custom_prompt.get(user_id)
    
    def set_active_custom_prompt(self, user_id: int, index: Optional[int]) -> None:
        """Устанавливает активный кастомный промпт по индексу (0, 1) или None для отключения"""
        if index is None:
            self._active_custom_prompt.pop(user_id, None)
        else:
            prompts = self.get_custom_prompts(user_id)
            if 0 <= index < len(prompts):
                self._active_custom_prompt[user_id] = prompts[index]
    
    def delete_custom_prompt(self, user_id: int, index: int) -> bool:
        """Удаляет кастомный промпт по индексу (0 или 1)"""
        prompts = self._custom_prompts.get(user_id, [])
        if 0 <= index < len(prompts):
            prompts.pop(index)
            # Если удалили активный промпт, сбрасываем
            if user_id in self._active_custom_prompt:
                if self._active_custom_prompt[user_id] not in prompts:
                    self._active_custom_prompt.pop(user_id, None)
            self._save_custom_prompts(user_id)
            return True
        return False
    
    def _save_custom_prompts(self, user_id: int) -> None:
        """Сохраняет кастомные промпты в файл пользователя"""
        # Загружаем текущие данные и добавляем промпты
        file_path = self._get_user_file(user_id)
        data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        
        data["custom_prompts"] = self._custom_prompts.get(user_id, [])
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    
    # ===== Методы для работы с беседами =====
    
    def get_conversations(self, user_id: Union[int, str]) -> List[Conversation]:
        """Получает список всех бесед пользователя"""
        self._load_user_data(user_id)
        return list(self._conversations.get(user_id, {}).values())
    
    def get_active_conversation(self, user_id: Union[int, str]) -> Optional[Conversation]:
        """Получает активную беседу пользователя"""
        self._load_user_data(user_id)
        active_id = self._active_conversations.get(user_id)
        if active_id and user_id in self._conversations:
            return self._conversations[user_id].get(active_id)
        return None
    
    def create_conversation(self, user_id: Union[int, str], title: str = None) -> Conversation:
        """Создаёт новую беседу"""
        self._load_user_data(user_id)
        
        # Генерируем ID
        conv_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Генерируем название
        if not title:
            title = "Новый чат"
        
        conversation = Conversation(id=conv_id, title=title)
        
        if user_id not in self._conversations:
            self._conversations[user_id] = {}
        
        self._conversations[user_id][conv_id] = conversation
        self._active_conversations[user_id] = conv_id
        
        self._save_user_data(user_id)
        return conversation
    
    def set_active_conversation(self, user_id: int, conv_id: str) -> Optional[Conversation]:
        """Устанавливает активную беседу"""
        self._load_user_data(user_id)
        
        if user_id in self._conversations and conv_id in self._conversations[user_id]:
            self._active_conversations[user_id] = conv_id
            self._save_user_data(user_id)
            return self._conversations[user_id][conv_id]
        return None
    
    def delete_conversation(self, user_id: int, conv_id: str) -> bool:
        """Удаляет беседу"""
        self._load_user_data(user_id)
        
        if user_id in self._conversations and conv_id in self._conversations[user_id]:
            del self._conversations[user_id][conv_id]
            
            # Если удалили активную беседу, сбрасываем
            if self._active_conversations.get(user_id) == conv_id:
                self._active_conversations[user_id] = None
            
            self._save_user_data(user_id)
            return True
        return False
    
    def delete_all_conversations(self, user_id: int) -> None:
        """Полностью удаляет все беседы пользователя и сбрасывает состояние"""
        self._load_user_data(user_id)
        
        self._conversations[user_id] = {}
        self._active_conversations[user_id] = None
        
        self._save_user_data(user_id)
        
    def clear_conversation(self, user_id: Union[int, str], conv_id: str, new_title: str = None) -> bool:
        """Очищает историю беседы и все связанные документы. Опционально меняет название."""
        self._load_user_data(user_id)
        
        if user_id in self._conversations and conv_id in self._conversations[user_id]:
            conv = self._conversations[user_id][conv_id]
            conv.messages = []
            if hasattr(conv, 'documents'):
                conv.documents = []
            
            if new_title:
                conv.title = new_title
            
            # При очистке беседы также сбрасываем временные режимы и файлы, 
            # чтобы пользователь чувствовал "чистый лист"
            self._user_images.pop(user_id, None)
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)
            self._edit_mode[user_id] = False
            self._template_mode[user_id] = False
            
            self._save_user_data(user_id)
            return True
        return False
    
    def add_message(
        self, user_id: Union[int, str], role: str, content: str, max_messages: int = 20,
        attachment: Optional[dict] = None, search: Optional[List[Dict[str, str]]] = None,
    ) -> Message:
        """Добавляет сообщение в активную беседу"""
        self._load_user_data(user_id)
        
        conv = self.get_active_conversation(user_id)
        if not conv:
            conv = self.create_conversation(user_id)
        
        message = Message(role=role, content=content, attachment=attachment, search=search)
        conv.messages.append(message)
        
        # Ограничиваем количество сообщений
        if len(conv.messages) > max_messages:
            conv.messages = conv.messages[-max_messages:]
        
        self._save_user_data(user_id)
        return message
        
    def add_document(self, user_id: Union[int, str], filename: str, content: str) -> None:
        """Добавляет текст документа к активной беседе"""
        self._load_user_data(user_id)
        
        conv = self.get_active_conversation(user_id)
        if not conv:
            conv = self.create_conversation(user_id)
            
        if not hasattr(conv, 'documents'):
            conv.documents = []
            
        # Обновляем, если такой файл уже есть
        for doc in conv.documents:
            if doc.get('filename') == filename:
                doc['content'] = content
                self._save_user_data(user_id)
                return
                
        conv.documents.append({"filename": filename, "content": content})
        self._save_user_data(user_id)
        
    def get_documents(self, user_id: Union[int, str]) -> List[dict]:
        """Получает список ассоциированных документов"""
        conv = self.get_active_conversation(user_id)
        if conv and hasattr(conv, 'documents'):
            return conv.documents
        return []
        
    def remove_document(self, user_id: Union[int, str], filename: str) -> bool:
        """Удаляет конкретный документ по имени файла из активной беседы"""
        self._load_user_data(user_id)
        
        conv = self.get_active_conversation(user_id)
        if not conv or not hasattr(conv, 'documents'):
            return False
        
        kept = []
        removed = False
        prefix = f"{filename}/"
        for doc in conv.documents:
            name = str(doc.get("filename") or "")
            if name == filename or name.startswith(prefix):
                removed = True
                continue
            kept.append(doc)
        if not removed:
            return False
        conv.documents = kept
        self._save_user_data(user_id)
        return True
    
    def clear_documents(self, user_id: Union[int, str], conv_id: Optional[str] = None) -> bool:
        """Очищает список документов в конкретной беседе или активной"""
        self._load_user_data(user_id)
        
        cid = conv_id or self._active_conversations.get(user_id)
        if cid and user_id in self._conversations and cid in self._conversations[user_id]:
            conv = self._conversations[user_id][cid]
            conv.documents = []
            
            # Также очищаем временный шаблон, если он был загружен, 
            # так как пользователь хочет "очистить доки"
            self._template_docs.pop(user_id, None)
            self._template_names.pop(user_id, None)
            self._template_mode[user_id] = False
            
            self._save_user_data(user_id)
            return True
        return False
    
    def _clean_text(self, text: Any) -> str:
        """Базовая очистка текста от null-байтов."""
        if text is None: return ""
        if not isinstance(text, str): text = str(text)
        return text.replace('\x00', '')

    def get_messages_for_api(self, context_id: Union[int, str], system_prompt: str, requesting_user_id: Optional[int] = None) -> List[dict]:
        """
        Получает сообщения в формате OpenAI API для конкретного контекста.
        Если указан requesting_user_id, ограничивает количество документов в контексте 
        согласно тарифному плану этого пользователя.
        """
        conv = self.get_active_conversation(context_id)
        
        messages = [{"role": "system", "content": system_prompt}]
        
        if conv:
            if hasattr(conv, 'documents') and conv.documents:
                # Определяем лимит документов для конкретного пользователя, если он указан
                doc_limit = 999 # По умолчанию без ограничений
                
                if requesting_user_id:
                    sub = self.get_subscription(requesting_user_id)
                    tier = sub.get("tier", "free")
                    
                    if tier == "creator":
                        doc_limit = 999
                    else:
                        # Лимиты дублируют логику из check_limits в handlers.py
                        limits = {"free": 1, "trial": 3, "start": 3, "pro": 10, "max": 30}
                        doc_limit = limits.get(tier, 1)

                # Добавляем документы, но не больше лимита пользователя
                for i, doc in enumerate(conv.documents):
                    if i >= doc_limit:
                        logger.info(f"Context: limiting documents for user {requesting_user_id} (tier {tier}) to {doc_limit}")
                        break
                        
                    filename = self._clean_text(doc.get('filename', 'doc'))
                    content = self._clean_text(doc.get('content', ''))
                    
                    messages.append({
                        "role": "system", 
                        "content": f"Пользователь предоставил документ для контекста: {filename}\n\nСодержание:\n{content}\n\nПожалуйста, используй эту информацию для ответов."
                    })
                
            for msg in conv.messages:
                messages.append({"role": msg.role, "content": msg.content})
        
        return messages

    
    def rename_conversation(self, user_id: Union[int, str], conv_id: str, new_title: str) -> bool:
        """Переименовывает беседу"""
        self._load_user_data(user_id)
        
        if user_id in self._conversations and conv_id in self._conversations[user_id]:
            self._conversations[user_id][conv_id].title = new_title
            self._save_user_data(user_id)
            return True
        return False


# Глобальный экземпляр менеджера
# Для веб-версии используем PostgreSQL-бэкенд, сохраняя совместимость API.
from app.bot_core.db_conversations import DatabaseConversationManager

conversation_manager = DatabaseConversationManager()
