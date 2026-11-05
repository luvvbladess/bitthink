import asyncio
from io import BytesIO
from types import SimpleNamespace
from PIL import Image
import openai_client as oc

def test_edit_uses_source_dimensions_and_local_change_instructions(monkeypatch):
    buf=BytesIO();Image.new('RGB',(1600,900)).save(buf,format='PNG')
    seen={}
    async def edit(**kwargs):
        seen.update(kwargs);return SimpleNamespace(data=[])
    monkeypatch.setattr(oc.client.images,'edit',edit)
    asyncio.run(oc.edit_image(buf.getvalue(),'Уменьши только цену'))
    assert seen['size']=='1600x900'
    assert 'измени только явно запрошенную область' in seen['prompt']
    assert 'Сохрани остальные' in seen['prompt']
    asyncio.run(oc.edit_image(buf.getvalue(),'Сделай квадрат',size='1024x1024'))
    assert seen['size']=='1024x1024'
