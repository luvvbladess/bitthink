"""Explicit engine adapters. Only this boundary knows the legacy manager API.

No business rules are duplicated: accounting still uses the same transactions
and locks. Constructor injection permits isolated web-domain tests.
"""
from typing import Callable, Any

class EngineAccess:
    def __init__(self, manager: Callable[[], Any]):
        self._engine = manager

class ConversationAccess(EngineAccess):
    def owner(self, *args, **kwargs):
        return self._engine().conversation_owner(*args, **kwargs)

    def view(self, *args, **kwargs):
        return self._engine().conversation_view(*args, **kwargs)

    def list(self, *args, **kwargs):
        return self._engine().get_conversations(*args, **kwargs)

    def roles(self, *args, **kwargs):
        return self._engine().conversation_roles(*args, **kwargs)

class SharingAccess(EngineAccess):
    def status(self, *args, **kwargs):
        return self._engine().share_status(*args, **kwargs)

    def create(self, *args, **kwargs):
        return self._engine().create_share(*args, **kwargs)

    def revoke(self, *args, **kwargs):
        return self._engine().revoke_share(*args, **kwargs)

    def join(self, *args, **kwargs):
        return self._engine().join_share(*args, **kwargs)

class AsideAccess(EngineAccess):
    def list(self, *args, **kwargs):
        return self._engine().list_asides(*args, **kwargs)

    def add(self, *args, **kwargs):
        return self._engine().add_aside(*args, **kwargs)

class AuthorAccess(EngineAccess):
    def cards(self, *args, **kwargs):
        return self._engine().author_cards(*args, **kwargs)

class TemplateAccess(EngineAccess):
    def base(self, *args, **kwargs):
        return self._engine().get_base_template(*args, **kwargs)

class BillingAccess(EngineAccess):
    def get_subscription(self, *args, **kwargs):
        return self._engine().get_subscription(*args, **kwargs)

    def get_day_usage(self, *args, **kwargs):
        return self._engine().get_day_usage(*args, **kwargs)

    def get_month_usage(self, *args, **kwargs):
        return self._engine().get_month_usage(*args, **kwargs)

    def set_subscription_tier(self, *args, **kwargs):
        return self._engine().set_subscription_tier(*args, **kwargs)

    def check_and_hold_quota(self, *args, **kwargs):
        return self._engine().check_and_hold_quota(*args, **kwargs)

    def release_paid_window(self, *args, **kwargs):
        return self._engine().release_paid_window(*args, **kwargs)

    def debit_plan_tokens(self, *args, **kwargs):
        return self._engine().debit_plan_tokens(*args, **kwargs)

    def refund_plan_images(self, *args, **kwargs):
        return self._engine().refund_plan_images(*args, **kwargs)

    def track_tokens(self, *args, **kwargs):
        return self._engine().track_tokens(*args, **kwargs)

    def mark_free_reply_search(self, *args, **kwargs):
        return self._engine().mark_free_reply_search(*args, **kwargs)

    def refund_daily_counter(self, *args, **kwargs):
        return self._engine().refund_daily_counter(*args, **kwargs)

    def try_consume_images(self, *args, **kwargs):
        return self._engine().try_consume_images(*args, **kwargs)

    @property
    def transaction_lock(self):
        return self._engine().transaction_lock

    def lock_subscription(self, session, user_id):
        return self._engine().lock_subscription(session, user_id)

