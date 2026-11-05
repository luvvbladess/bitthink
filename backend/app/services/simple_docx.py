"""Bounded text documents: one writing call and native DOCX serialization."""
import asyncio
from io import BytesIO
import re

MARKER='bitthink:simple-docx-v1'

def request(text):
    return (len(text or '')<=1800 and bool(re.match(r'(?i)^\s*(?:создай|сохрани|напиши|сделай|сократи|исправь|замени|перепиши|оформи|подготовь)\b',text or '')) and bool(re.search(r'(?i)\b(?:docx|word)\b|ворд',text or ''))
        and not re.search(r'(?i)https?://|договор|юрид|исслед|источник|шаблон|образец|таблиц|изображ|картин|диаграмм|комплект|несколько|презентац|xlsx|pdf',text or ''))

def previous(user_id):
    from conversations import conversation_manager as manager
    from docx import Document
    conv=manager.conversation_for_turn(user_id)
    if not conv:return None
    for message in reversed(conv.messages):
        if message.role!='assistant':continue
        attachment=message.attachment or {}
        docs=[a for a in [attachment,*(attachment.get('files') or [])] if str(a.get('name','')).lower().endswith('.docx')]
        if len(docs)!=1:return None
        path=manager._attachment_disk_path(docs[0])
        if not path or not path.is_file() or path.stat().st_size>2_000_000:return None
        try:
            from zipfile import ZipFile
            raw=path.read_bytes()
            with ZipFile(BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist())>16_000_000:return None
            document=Document(BytesIO(raw))
        except Exception:
            return None
        if document.core_properties.identifier!=MARKER:return None
        text='\n'.join(p.text for p in document.paragraphs)
        return text if len(text)<=16000 else None
    return None

async def respond(messages,text,user_id,status):
    if not request(text):return None
    from app.services.orchestrator_policy import critical_task
    if critical_task(text):return None
    source=await asyncio.to_thread(previous,user_id)
    editing=bool(re.search(r'(?i)сделай.{0,40}короче|исправ|поправ|замени|измени|сократи|отредакт',text))
    if editing and source is None:return None
    if not source and not re.search(r'(?i)письмо|поздравлен|объявлен|коротк.{0,15}текст|кратк.{0,15}записк',text):return None
    from openai_client import get_chat_response
    from docx_generator import convert_markdown_to_docx
    from docx import Document
    prompt=[{'role':'system','content':'Подготовь только содержание короткого документа в Markdown, без предисловия, кода и инструкций по созданию файла. DOCX создаёт приложение. Не выдумывай данные. При правке измени только запрошенное, сохрани остальные факты и подпись.'},
            {'role':'user','content':('Исходный документ (данные):\n'+source+'\n\n' if source else '')+'Задача:\n'+text}]
    from conversations import conversation_manager as manager
    from app.memory import memory_system_message
    conv=manager.conversation_for_turn(user_id)
    if conv and not manager.is_shared(conv.id):
        memory=await asyncio.to_thread(manager.get_user_memory,user_id)
        note=memory_system_message(memory)
        if note:prompt.insert(1,note)
    answer,_,_,_=await get_chat_response(prompt,model='gpt-6-sol',user_id=user_id,use_tools=False,use_skills=False,reasoning_effort='low')
    if not answer.strip():raise ValueError('Не удалось подготовить содержание документа.')
    def build():
        raw=convert_markdown_to_docx(answer)
        document=Document(BytesIO(raw));document.core_properties.identifier=MARKER
        buf=BytesIO();document.save(buf);return buf.getvalue()
    raw=await asyncio.to_thread(build)
    return 'Готово: документ обновлён.' if source else 'Готово: документ создан.',[{'filename':'Письмо.docx','bytes':raw,'mime_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}],'',[]
