"""A bounded report is writing plus serialization, not a software project."""
import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
import re


def eligible(text):
    text=text or ''
    if len(text)>1800 or not re.match(r'(?i)^\s*(?:привет[,!]?\s*)?(?:напиши|подготовь|сделай|создай|оформи|составь)\b',text):return False
    if not re.search(r'(?i)\b(?:docx|word)\b|ворд',text):return False
    if not re.search(r'(?i)доклад|реферат|конспект|эссе|памятк|обзор',text):return False
    if re.search(r'(?i)\b(?:два|две|три|четыре|пять|[2-9]|\d{2,})\s+(?:доклад|реферат|конспект|файл|документ)|\b(?:доклады|рефераты|конспекты)\b',text):return False
    # Keep templates, source-dependent research, revisions and other actions
    # on their existing workflows. Only root-Drive upload is supported here.
    if re.search(r'(?i)https?://|прикрепл|вложени|шаблон|гост|исследован|первоисточ|источник|ссылк|'
                 r'актуальн|сегодня|последн\w*\s+(?:данн|событ)|таблиц|изображ|картин|диаграмм|'
                 r'несколько|комплект|презентац|\b(?:pdf|xlsx|pptx)\b|'
                 r'договор|медицин|диагноз|юрид|судебн|сертификац|папк|тысяч|'
                 r'на\s+основе|по\s+(?:документ|материал|этому\s+тексту)|яндекс|dropbox|onedrive|'
                 r'перепиши|исправь|измени|обнови|замени|удали|почт|email|телеграм|начальник|опубликуй|распечатай|\bсайт\w*',text):return False
    sizes=[int(n) for n in re.findall(r'(?i)\b(\d+)\s*(?:страниц|лист|тысяч|000\s*слов)',text)]
    words=[int(n) for n in re.findall(r'(?i)\b(\d+)\s*слов',text)]
    return (not sizes or max(sizes)<=6) and (not words or max(words)<=1400)


def drive_requested(text):
    return bool(re.search(r'(?i)(?<!не )\b(?:положи|сохрани|загрузи|помести|выложи|отправь)\b'
        r'[^.!?\n]{0,90}\b(?:на|в)\s+(?:мой\s+)?(?:google\s*(?:drive|диск)|гугл\s*диск)',text or ''))


def validate(data, markdown):
    from docx import Document
    from docx_generator import CONVERSION_FAILED_MARKER
    document=Document(BytesIO(data))
    content='\n'.join(p.text for p in document.paragraphs)
    if len(content.strip())<80 or CONVERSION_FAILED_MARKER in content:
        raise ValueError('Документ не прошёл проверку содержимого.')
    # Do not silently lose C++ templates, indices or operators in serialization.
    for code in re.findall(r'```[^\n]*\n([\s\S]*?)```',markdown):
        for line in code.splitlines():
            if line.strip() and line not in content:
                raise ValueError('При сборке документа изменился фрагмент кода.')
    return content


def _has_external_action():
    from app.services.computer_context import computer_task_id
    from app.db.engine import SyncSessionLocal
    from app.db.models import ComputerEvent
    from sqlalchemy import select
    task_id=computer_task_id.get()
    if not task_id:return True  # An unknown resumed scope is not safe to restart.
    with SyncSessionLocal() as session:
        return session.scalar(select(ComputerEvent.id).where(ComputerEvent.task_id==task_id,
            ComputerEvent.kind=='action_receipt').limit(1)) is not None


async def respond(messages,text,user_id):
    if not eligible(text):return None
    from app.services.conversation_context import workspaces
    from app.services.desktop_context import desktop_executor
    from app.services.task_checkpoints import resumed_journal
    from app.services.request_intent import classify_request
    if workspaces.get() or desktop_executor.get() is not None:return None
    from app.core.request_context import generation_instructions
    runtime=generation_instructions.get() or {}
    if resumed_journal.get() or runtime.get('resuming'):
        # A pre-upload draft can use the bounded path on explicit resume. Never
        # restart writing/uploading after a done or uncertain external action.
        if await asyncio.to_thread(_has_external_action):return None
    if classify_request(text,messages).task=='transformation':return None
    from app.services.response_policy import compact_messages
    from app.billing.plans import allowed_models
    from app.billing.quota import effective_tier
    from conversations import conversation_manager
    tier=effective_tier(await asyncio.to_thread(conversation_manager.get_subscription,user_id))
    model='gpt-6-sol' if 'gpt-6-sol' in allowed_models(tier) else 'gpt-6-luna'
    from openai_client import get_chat_response
    from status_feed import push_status
    from computer_tools import run_computer_tool
    from turn_scope import request_file_export,turn_conversation_id
    from app.services.computer_context import computer_task_id
    await push_status('think','Готовлю содержание документа')
    chat=compact_messages(messages)
    chat.insert(-1,{'role':'system','content':
        'Подготовь только содержание запрошенного документа в Markdown, без внешней обёртки. '
        'Приложение само собирает DOCX и при явной просьбе загружает на Google Диск. '
        'Не описывай план работы, загрузку и скрипты сборки. '
        'По умолчанию 700–1100 слов, связный доклад с заголовком, введением, разделами и выводом; '
        'явные требования пользователя к объёму важнее. Не выдумывай источники. '
        'Если просят реализацию алгоритма, включи законченный код указанного языка, '
        'условия применимости, объяснение, сложность и согласованный пример. '
        'Весь программный код заключай в блоки с языком. Не обещай запуск кода.'})
    answer,_,_,_=await get_chat_response(chat,model=model,user_id=user_id,use_tools=False,
        use_skills=False,reasoning_effort='low',output_token_limit=6000)
    if len(answer.strip())<80 or answer.count('```')%2 or answer.lstrip().startswith(('❌','Нет ответа от модели')):
        return 'Не удалось подготовить содержание документа. Сборка и загрузка не запускались.',[], '',[]
    scope=computer_task_id.get() or turn_conversation_id() or str(user_id)
    key=hashlib.sha256((str(scope)+'\n'+text).encode()).hexdigest()[:16]
    path=f'documents/{key}/Доклад.docx'
    await push_status('file','Собираю DOCX')
    written=await run_computer_tool('workspace_write',{'path':path,'content':answer},user_id)
    if not written.startswith('Записал '):
        return 'DOCX не создан. '+written,[], '',[]
    from google_tools import _load_file
    loaded=await asyncio.to_thread(_load_file,user_id,path)
    if isinstance(loaded,str):return 'DOCX записан, но его не удалось прочитать для проверки. '+loaded,[], '',[]
    name,data=loaded
    try:await asyncio.to_thread(validate,data,answer)
    except Exception:
        return 'DOCX не прошёл проверку, загрузка не выполнялась. Повторная сборка автоматически не запускается.',[], '',[]
    request_file_export(path)
    files=[{'filename':Path(name).name,'bytes':data,'mime_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','workspace_path':path}]
    result='Доклад готов в DOCX.'
    if drive_requested(text):
        await push_status('file','Сохраняю документ на Google Диск')
        try:
            uploaded=await run_computer_tool('google_drive_upload',{'file':path,'name':'Доклад.docx'},user_id)
        except Exception:
            uploaded='Сервис не подтвердил результат. Автоматический повтор загрузки не выполнялся.'
        if 'Сохранено на Google Диск:' in uploaded:
            result+='\n'+uploaded
        else:
            result+='\nЗагрузка на Google Диск не подтверждена: '+uploaded
    return result,files,'',[]
