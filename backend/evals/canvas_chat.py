"""Real chat creation/edit/new-artifact acceptance; isolated storage and users."""
import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();target=Path(args.output).resolve();target.mkdir(parents=True,exist_ok=True)
    assert not (target/'fixture.sqlite').exists()
    os.environ['DATABASE_URL']='sqlite+aiosqlite:///'+(target/'fixture.sqlite').as_posix()
    os.environ['UPLOAD_DIR']=str(target/'uploads');os.environ['DATA_DIR']=str(target/'data')
    os.environ['PROJECT_EMBEDDINGS_ENABLED']='false'
    os.environ['ORCHESTRATOR_MODEL_BUDGET_USD']='1'
    from app.db.base import Base
    import app.db.models,app.db.project_models,app.db.generation_models,app.db.experience_models
    from app.db.engine import sync_engine
    Base.metadata.create_all(sync_engine)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(evaluate(target))


async def evaluate(target):
    from app.core.repository import repo
    from app.core.request_context import generation_preferences
    from app.services import chat_service
    from app.services.orchestrator_metrics import model_trace
    # Unrelated background preference extraction is outside this acceptance run.
    chat_service.schedule_memory_refresh=lambda *args:None
    email='canvas-acceptance@example.invalid'
    uid=await repo.ensure_user(email)
    await repo.set_subscription_tier(email,'creator',30)
    await repo.set_user_model(email,'auto')
    conversation=await repo.create_conversation(email,'Synthetic canvas acceptance')
    cid=conversation['id']
    results=[]
    previous=None
    prompts=[
        ('create','Создай одностраничный сайт учебной кофейни «Север». Это вымышленный пример. Заголовок «Кофейня Север», три позиции меню: эспрессо 150 рублей, капучино 220 рублей, фильтр 180 рублей. Контакты: вымышленный адрес Лесная, 10. Кнопка «Показать меню» ведёт к секции меню. Спокойная тёмная тема, крупная типографика. Без интернета, без изображений и внешних действий. Нужен готовый интерактивный HTML на холсте, не описание.'),
        ('edit','Сделай заголовок крупнее и замени основной заголовок на «Кофе рядом с домом». Сохрани меню, цены и контакты. Без интернета и без изображений.'),
        ('new','Создай новую инфографику о трёх этапах сортировки отходов: 1 — бумага, 2 — пластик, 3 — стекло. У каждого этапа короткая подпись. Это отдельная новая работа, не сайт кофейни. Светлая тема. Без интернета, без изображений и внешних действий. Нужен готовый HTML на холсте.'),
    ]
    async def noop(*args,**kwargs):pass
    for kind,prompt in prompts:
        chunks=[];files=[];statuses=[]
        async def status(text):statuses.append(text)
        async def chunk(text):chunks.append(text)
        async def file(*args):files.append([str(x) if not isinstance(x,bytes) else len(x) for x in args])
        token=generation_preferences.set({'user_id':uid,'selected_model':'auto','reasoning_effort':'none',
            'image_quality':'high','canvas_target':previous['url'] if previous and kind=='edit' else None})
        started=time.monotonic()
        try:
            with model_trace('canvas-acceptance') as metrics:
                await asyncio.wait_for(chat_service.run_chat(email,prompt,cid,status,chunk,file,noop,noop,noop),timeout=180)
        finally:generation_preferences.reset(token)
        history=await repo.get_messages(email,cid)
        answer=next(m for m in reversed(history) if m['role']=='assistant')
        attachment=answer.get('attachment') or {}
        html_items=[item for item in [attachment,*(attachment.get('files') or [])] if item.get('canvas') or str(item.get('name','')).endswith('.html')]
        assert html_items,kind+': no persisted HTML'
        artifact=html_items[0]
        path=repo._manager._attachment_disk_path(artifact)
        html=path.read_text(encoding='utf8')
        (target/(kind+'.html')).write_text(html,encoding='utf8')
        text=' '.join(re.sub(r'<[^>]+>',' ',html).split())
        assert re.search(r'<h1\b',html,re.I),kind+': missing visible heading'
        assert 'не сдан' not in answer['content'].casefold(),kind+': fallback does not count as success'
        if kind=='create':
            assert 'Север' in text and '220' in text and 'Лесная' in text
        elif kind=='edit':
            assert 'Кофе рядом с домом' in text and '220' in text and 'Лесная' in text
            assert artifact['url']!=previous['url']
            assert hashlib.sha256(previous['path'].read_bytes()).hexdigest()==previous['sha256']
        else:
            assert all(word in text.casefold() for word in ('бумага','пластик','стекло'))
            assert 'Кофе рядом с домом' not in text
        assert await repo.get_user_model(email)=='auto'
        result={'kind':kind,'prompt':prompt,'answer':answer['content'],'artifact':artifact,
            'seconds':time.monotonic()-started,'events':files,'statuses':statuses,'metrics':metrics,'passed':True}
        results.append(result)
        previous={'url':artifact['url'],'path':path,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        (target/(kind+'.html')).write_text(html,encoding='utf8')
        (target/'results.json').write_text(json.dumps({'cases':results,'accepted':len(results)==3},ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'kind':kind,'passed':True,'seconds':result['seconds'],'model_still_auto':True},ensure_ascii=False),flush=True)
    print('PASS actual chat: create, exact-source edit, new artifact; mode unchanged',flush=True)


if __name__=='__main__':main()
