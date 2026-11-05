"""Real edits in disposable projects; acceptance is independent of model prose."""
import asyncio
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time

CASES = [
    dict(id='discount',file='pricing.py',source='KEEP = "unrelated"\n\ndef total(price, percent):\n    return price * (1 + percent / 100)\n',
         ask='Исправь скидку в pricing.py: 10% должны уменьшать сумму, а не увеличивать. Остальное не меняй.',
         test='from pricing import total\nassert total(100,10)==90\nassert total(80,0)==80\nassert total(20,100)==0\n'),
    dict(id='boundary',file='limits.py',source='KEEP = "unrelated"\n\ndef allowed(size, limit):\n    return size < limit\n',
         ask='Исправь limits.py: размер, равный лимиту, тоже допустим. Сохрани функцию и остальное поведение.',
         test='from limits import allowed\nassert allowed(5,5)\nassert allowed(4,5)\nassert not allowed(6,5)\nassert allowed(0,0)\n'),
    dict(id='mutable',file='collect.py',source='KEEP = "unrelated"\n\ndef collect(item, items=[]):\n    items.append(item)\n    return items\n',
         ask='Исправь collect.py: независимые вызовы collect(1) и collect(2) сейчас делят один список. Переданный явно список должен по-прежнему изменяться на месте.',
         test='from collect import collect\nassert collect(1)==[1]\nassert collect(2)==[2]\na=[]\nassert collect(3,a) is a\nassert a==[3]\n'),
    dict(id='unicode',file='labels.py',source='KEEP = "unrelated"\nSAVE = "Сохрнить"\nCODE_SAMPLE = "#include <iostream>\\nint x = 1 << 2; // ** keep **"\n',
         ask='Замени опечатку «Сохрнить» на «Сохранить» в labels.py. Строку CODE_SAMPLE и остальное оставь буквально.',
         test='from labels import SAVE,CODE_SAMPLE\nassert SAVE=="Сохранить"\nassert CODE_SAMPLE=="#include <iostream>\\nint x = 1 << 2; // ** keep **"\n'),
    dict(id='empty',file='stats.py',source='KEEP = "unrelated"\n\ndef average(values):\n    return sum(values) / len(values)\n',
         ask='Добавь в stats.py обработку пустого списка в average: для [] вернуть 0. Другие случаи и API не меняй.',
         test='from stats import average\nassert average([])==0\nassert average([2,4])==3\nassert average([-1,1])==0\n'),
    dict(id='config',file='settings.json',source='{"retry_seconds": 10, "keep": "unchanged", "enabled": true}\n',
         ask='Измени retry_seconds с 10 на 15 в settings.json. Другие значения сохрани; формат остаётся JSON.',
         test='import json\nfrom pathlib import Path\na=json.loads(Path("settings.json").read_text())\nassert a=={"retry_seconds":15,"keep":"unchanged","enabled":True}\n'),
]


async def main(out):
    from app.config import get_settings
    from app.db.base import Base
    import app.db.models, app.db.project_models, app.db.generation_models, app.db.experience_models
    from app.db.engine import sync_engine
    Base.metadata.create_all(sync_engine)
    from app.core.repository import repo
    from app.services.workspace_fs import user_root
    from app.services.orchestrator_metrics import model_trace
    from app.billing.costs import model_cost_usd
    from app.services.run_protocol import current_run
    import director_router as dr
    import computer_tools as ct
    from config import SYSTEM_PROMPT
    from contextvars import ContextVar
    active = ContextVar('edit_eval_calls', default=None)
    calls = ContextVar('edit_eval_models', default=None)
    real_tool = ct.run_computer_tool

    async def tool(name,args,*a,**kw):
        row=active.get()
        if row is not None:row.append({'name':name,'path':args.get('path'),'command':args.get('argv') or args.get('command')})
        return await real_tool(name,args,*a,**kw)
    ct.run_computer_tool=tool

    class Collector(logging.Handler):
        def emit(self,record):
            s=record.getMessage()
            if s.startswith('orchestrator_call ') and calls.get() is not None:calls.get().append(json.loads(s.split(' ',1)[1]))
    logger=logging.getLogger('app.services.orchestrator_metrics');logger.setLevel(logging.INFO);logger.addHandler(Collector())
    report=[];lock=asyncio.Semaphore(2)
    async def one(case):
        async with lock:
            email='code-edit-'+case['id']+'@example.invalid'
            uid=await repo.ensure_user(email);await repo.set_subscription_tier(email,'creator',30)
            root=user_root(uid);root.mkdir(parents=True,exist_ok=True)
            (root/case['file']).write_text(case['source'],encoding='utf8')
            tests='import unittest\nclass Acceptance(unittest.TestCase):\n def test_contract(self):\n'+''.join('  '+line+'\n' for line in case['test'].splitlines())
            (root/'test_contract.py').write_text(tests,encoding='utf8')
            (root/'unrelated.py').write_text('SENTINEL = "KEEP EXACTLY"\n',encoding='utf8')
            protected={p.name:p.read_bytes() for p in [root/'test_contract.py',root/'unrelated.py']}
            original={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
            prompt=case['ask']+' Работай с существующими файлами в мастерской. Проверь результат через python -m unittest. Не меняй test_contract.py и unrelated.py.'
            t=time.monotonic();tools=[];models=[];tok=active.set(tools);mt=calls.set(models)
            row={'id':case['id'],'prompt':prompt,'surface':'cloud','errors':[]}
            try:
                with model_trace('code-edit-eval') as metrics:
                    response=await asyncio.wait_for(dr.get_director_response([{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':prompt}],prompt,uid,None),timeout=210)
                row.update(answer=response[0],metrics=metrics)
            except Exception as e:row['errors'].append(type(e).__name__)
            finally:active.reset(tok);calls.reset(mt)
            check=subprocess.run([sys.executable,'-m','unittest','-v'],cwd=root,capture_output=True,text=True,timeout=20)
            if check.returncode:row['errors'].append('independent_contract_failed')
            for name,data in protected.items():
                if not (root/name).exists() or (root/name).read_bytes()!=data:row['errors'].append('protected_changed:'+name)
            changed=[p.name for p in root.iterdir() if p.is_file() and original.get(p.name)!=p.read_bytes()]
            if any(p!=case['file'] for p in changed):row['errors'].append('extra_changes')
            if case['file'] not in changed:row['errors'].append('target_not_changed')
            row.update(seconds=round(time.monotonic()-t,3),tools=tools,calls=models,changed=changed,check_exit=check.returncode,check_output=check.stdout+check.stderr,final_source=(root/case['file']).read_text(encoding='utf8'))
            row['cost_no_cache']=round(sum(model_cost_usd(c['model'],c['input'],c['output']) for c in models),8)
            report.append(row);(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(case['id'],row['errors'],row['seconds'],row['cost_no_cache'],len(models),flush=True)
    await asyncio.gather(*(one(c) for c in CASES))


if __name__=='__main__':
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    assert not (out/'fixture.sqlite').exists()
    for key,value in dict(DATABASE_URL='sqlite+aiosqlite:///'+str(out/'fixture.sqlite'),UPLOAD_DIR=str(out/'uploads'),DATA_DIR=str(out/'data'),WORKSPACES_DIR=str(out/'workspaces'),WORKSPACE_ALLOW_LOCAL_RUN='1',PROJECT_EMBEDDINGS_ENABLED='false',ORCHESTRATOR_MODEL_BUDGET_USD='.60').items():os.environ[key]=value
    os.environ.pop('SANDBOX_URL',None)
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(out))
