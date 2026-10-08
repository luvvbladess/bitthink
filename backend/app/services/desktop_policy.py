"""Desktop context uses the configured mode budget; no website policy changes."""
from app.bot_core.model_context import window_for, input_budget_tokens, CHARS_PER_TOKEN

def context_policy():
    return {'budget':input_budget_tokens('director'),'model_window':window_for('director').context,'compact_at':.75}

def history_char_limit():
    return context_policy()['budget'] * CHARS_PER_TOKEN + 100_000

def format_local_history(messages):
    labels={'user':'Пользователь','assistant':'Ассистент'}
    parts=[labels[m['role']]+': '+m['content'] for m in messages if m.get('role') in labels and isinstance(m.get('content'),str)]
    text='\n\n'.join(parts)
    if len(text)>history_char_limit(): raise ValueError('История превышает рабочий контекст. Сожмите её командой /compact.')
    return text

def history_view_limit(limit, planner_limit):
    # Planner/composer see the complete client-managed history. Employees can
    # include 256K leaf models, so keep room for their task, tools and documents.
    return history_char_limit() if limit==planner_limit else min(600_000,context_policy()['budget']*2)
