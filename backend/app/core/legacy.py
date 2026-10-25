"""Compatibility boundary for the vendored engine; web domains import this adapter."""
import app.config  # initialize the existing engine's module search path once
import config as settings
import conversations


def create_manager():
    return conversations.DatabaseConversationManager()


def billing_manager():
    return conversations.conversation_manager
