from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    first_name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: str
    email: str
    first_name: Optional[str]
    avatar_url: Optional[str] = None
    role: str = "user"
    subscription_tier: str
    selected_model: str
    expires_at: int


class ProfileUpdate(BaseModel):
    first_name: str = Field(min_length=1, max_length=255)


class ConversationCreate(BaseModel):
    title: Optional[str] = None


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    document_count: int
    is_active: bool


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    attachment: Optional[dict] = None
    search: Optional[list[dict]] = None


class ChatMessage(BaseModel):
    content: str = Field(min_length=1)
    conversation_id: Optional[str] = None


class ModelSelect(BaseModel):
    model: str


class PromptCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class PromptActivate(BaseModel):
    index: Optional[int] = None


class PromocodeApply(BaseModel):
    code: str


class SubscriptionOut(BaseModel):
    tier: str
    expires_at: int = 0
    name: str = ""
    period: str = ""
    unlimited: bool = False
    chat: dict | None = None
    computer: dict | None = None
    images: dict | None = None
    nano_cushion: dict | None = None
    free_daily: dict | None = None
    windows: dict | None = None
    multipliers: dict | None = None
    spend: dict | None = None
    daily_nano_mini: int = 0
    daily_gpt54: int = 0
    daily_director: int = 0
    daily_images: int = 0
    daily_docs: int = 0
    last_reset_date: str = ""
    active_promocode: Optional[str] = None


class PlanOut(BaseModel):
    id: str
    name: str
    price_rub: int = 0
    price_year_rub: int = 0
    price_stars: int = 0
    duration_days: int = 30
    description: str
    features: list[str]
    chat_tokens: int = 0
    computer_tokens: int = 0
    chat_week: int = 0
    chat_session: int = 0
    computer_week: int = 0
    computer_session: int = 0
    images: int = 0


class UsageOut(BaseModel):
    date: str
    usage: dict


class WSMessage(BaseModel):
    type: str
    payload: dict


class ConnectorCreate(BaseModel):
    type: str = Field(pattern="^(gmail|ssh|http|web)$")
    name: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)


class ConnectorOut(BaseModel):
    id: int
    type: str
    name: str
    hint: Optional[str] = None
    created_at: Optional[str] = None


class MemoryOut(BaseModel):
    notes: str = ""
    enabled: bool = True
    updated_at: int = 0


class MemoryUpdate(BaseModel):
    enabled: Optional[bool] = None
    notes: Optional[str] = None


class SkillOut(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    body: str = ""
    triggers: str = ""
    enabled: bool = True
    origin: str
    scope: str = "sandbox"
    updated_at: int = 0


class SkillsListOut(BaseModel):
    items: list[SkillOut]
    custom_count: int = 0
    custom_limit: int = 20


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    title: Optional[str] = Field(default="", max_length=80)
    description: str = Field(min_length=1, max_length=180)
    body: str = Field(min_length=12, max_length=4000)
    triggers: Optional[str] = Field(default="", max_length=400)


class SkillUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(default=None, max_length=180)
    body: Optional[str] = Field(default=None, max_length=4000)
    triggers: Optional[str] = Field(default=None, max_length=400)
    enabled: Optional[bool] = None
