import asyncio
import copy
import io
import json
from pathlib import Path
import re
import zipfile
from types import SimpleNamespace as NS

import fitz
import pytest
from app.config import get_settings  # noqa: F401
from app.services.engineering_drawing import render_project,validate_project
from app.services.engineering_io import EngineeringResult,inspect_page,build_project,_download_host


def model():
    reference=Path(__file__).parents[1]/'app/bot_core/computer_skills/eng_reverse/references/schema.md'
    return json.loads(re.search(r'```json\s*(.*?)```',reference.read_text(encoding='utf-8'),re.S)[1])


def test_real_vector_pdf_editable_dxf_and_shared_geometry():
    import ezdxf
    output,report=render_project(model())
    assert report['status']=='preliminary' and len(report['issues'])==2
    with fitz.open(stream=output['drawings.pdf'],filetype='pdf') as document:
        assert len(document)==1 and 'Цилиндр' in document[0].get_text()
        assert document[0].get_drawings() and not document[0].get_images()
        assert document[0].rect.width==pytest.approx(210*72/25.4)
    dxf=ezdxf.read(io.StringIO(output['sheets/01.dxf'].decode('utf-8')))
    assert dxf.header['$INSUNITS']==4
    geometry=[e for block in dxf.modelspace().query('INSERT') for e in block.virtual_entities()]
    assert any(e.dxftype()=='LINE' and e.dxf.start.distance(e.dxf.end)==pytest.approx(32) for e in geometry)
    texts=[e.plain_text() for e in dxf.layouts.get('Drawing').query('TEXT')]
    assert any('Цилиндр' in text for text in texts)
    with zipfile.ZipFile(io.BytesIO(output['engineering-package.zip'])) as archive:
        assert {'drawings.pdf','project.json','traceability.md','validation.json','sheets/01.svg','sheets/01.dxf'}<=set(archive.namelist())


def test_kompas_fields_font_and_cad_line_styles_are_preserved():
    import ezdxf
    spec=model();spec['organization']='БитСинк';spec['sheets'][0]['material']='Сталь 10895'
    spec['sheets'][0]['views'][0]['entities'].append({'type':'linear_dim','from':[0,-8.5],'to':[0,8.5],'axis':'y','offset':-12,'fact_id':'diameter','prefix':'Ø'})
    output,report=render_project(spec)
    assert report['drawing_style']=='kompas-eskd-form1'
    with fitz.open(stream=output['drawings.pdf'],filetype='pdf') as doc:
        text=doc[0].get_text().replace('\xa0',' ')
        assert all(label in text for label in ['Разраб.','Н.контр.','№ докум.','Лит.','Масса','Масштаб','Инв. № подл.','БитСинк','Сталь 10895'])
        assert any('OpenGOST' in font[3] for font in doc[0].get_fonts())
        assert not doc[0].get_images()
        rotated=[line for block in doc[0].get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] if any('Инв. № подл.' in span['text'] for span in line['spans'])]
        assert rotated and abs(rotated[0]['dir'][0])<.001 and rotated[0]['dir'][1]<-.99
    dxf=ezdxf.read(io.StringIO(output['sheets/01.dxf'].decode('utf-8')))
    assert dxf.styles.get('Standard').dxf.font=='OpenGOSTtypeA-Regular.ttf'
    geometry=[e for block in dxf.modelspace().query('INSERT') for e in block.virtual_entities()]
    assert any(e.dxftype()=='TEXT' and e.dxf.rotation==90 and e.dxf.oblique==15 for e in geometry)
    assert any(e.dxftype()=='LINE' and e.dxf.linetype=='CENTER' for e in geometry)
    assert any(e.dxftype()=='SOLID' for e in geometry)
    assert b'@font-face' in output['sheets/01.svg'] and b'data:font/ttf;base64,' in output['sheets/01.svg']
    with zipfile.ZipFile(io.BytesIO(output['engineering-package.zip'])) as archive:
        assert archive.read('fonts/OpenGOSTtypeA-Regular.ttf')
        assert b'SIL OPEN FONT LICENSE' in archive.read('fonts/OFL.txt')


def test_dimension_override_wrong_geometry_and_missing_provenance_are_rejected():
    spec=model();spec['facts'][0]['value']=31
    with pytest.raises(ValueError,match='не совпадает'):validate_project(spec)
    spec=model();spec['sheets'][0]['views'][0]['entities'][2]['text']='32'
    with pytest.raises(ValueError,match='замена'):validate_project(spec)
    spec=model();spec['facts'][0]['state']='confirmed'
    with pytest.raises(ValueError,match='без источника'):validate_project(spec)


def test_unknowns_fit_nominal_conflict_missing_parts_and_calculation():
    spec=model();spec['parts'].append({'id':'coil','name':'Обмотка','qty':2})
    spec['facts'].extend([
        {'id':'hole','value':18,'unit':'mm','state':'assumed'},
        {'id':'stroke','value':None,'unit':'mm','state':'unknown'},
        {'id':'half','value':16,'unit':'mm','state':'calculated','inputs':['length'],'expression':'length / 2'},
    ])
    spec['fits']=[{'id':'fit1','hole':'hole','shaft':'diameter'}]
    issues=validate_project(spec)['issues']
    assert any(i['type']=='missing_part_drawing' and i['part_id']=='coil' for i in issues)
    assert any(i['type']=='fit_nominal_mismatch' for i in issues)
    spec['facts'][-1]['expression']='__import__("os").system("whoami")'
    with pytest.raises(ValueError):validate_project(spec)
    spec=model();spec['facts'][0].update(state='calculated',inputs=['length'],expression='length')
    with pytest.raises(ValueError,match='Циклическая'):validate_project(spec)


def test_bom_is_paginated_and_matches_actual_part_count():
    spec=model();spec['include_bom']=True
    spec['parts'] += [{'id':'p'+str(i),'name':'Деталь '+str(i),'qty':2,'required_drawing':False} for i in range(29)]
    output,report=render_project(spec)
    assert report['drawing_sheets']==1 and report['bom_sheets']==2 and report['pdf_pages']==3
    with fitz.open(stream=output['drawings.pdf'],filetype='pdf') as document:
        assert len(document)==3 and 'Деталь 28' in document[2].get_text().replace('\xa0',' ')
    assert len(output['bom.csv'].decode('utf-8-sig').splitlines())==31


def test_archive_boundaries_and_traversal():
    from app.services.engineering_io import _archive_entries
    def archive(name):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr(name,b'content')
        return stream.getvalue()
    assert _archive_entries(archive('Folder/file.txt'),20)==[('Folder/file.txt',b'content')]
    with pytest.raises(ValueError):_archive_entries(archive('../private.txt'),20)
    with pytest.raises(ValueError):_archive_entries(b'not zip',20)


def test_uploaded_zip_originals_subfolders_and_partial_manifest(tmp_path,monkeypatch):
    from app.services.engineering_io import import_chat_file
    from conversations import conversation_manager
    import app.services.workspace_fs as ws
    monkeypatch.setenv('WORKSPACES_DIR',str(tmp_path/'workspace'))
    original=tmp_path/'materials.zip'
    with zipfile.ZipFile(original,'w') as archive:
        archive.writestr('one/dimensions.txt','Диаметр 17')
        archive.writestr('two/dimensions.txt','Длина 32')
        archive.writestr('nested.zip',b'not expanded')
    conversation=NS(messages=[NS(attachment={'name':'materials.zip','url':'original'})])
    monkeypatch.setattr(conversation_manager,'conversation_for_turn',lambda uid:conversation)
    monkeypatch.setattr(conversation_manager,'_attachment_disk_path',lambda entry:original)
    imported=import_chat_file(903112,'materials.zip')
    assert imported['status']=='partial' and len(imported['sources'])==2
    assert imported['errors'][0]['name']=='nested.zip'
    assert {s['name'] for s in imported['sources']}=={'one/dimensions.txt','two/dimensions.txt'}
    assert all(ws.resolve_in_jail(903112,s['path']).is_file() for s in imported['sources'])
    assert json.loads(ws.collect_deliverables(903112))==[]
    assert ws.resolve_in_jail(903112,imported['manifest_path']).is_file()


def test_archive_duplicate_path_and_symlink_are_rejected():
    from app.services.engineering_io import _archive_manifest
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        item=zipfile.ZipInfo('link.txt');item.create_system=3;item.external_attr=0o120777<<16
        archive.writestr(item,'outside')
    with pytest.raises(ValueError,match='символическая'):_archive_manifest(stream.getvalue(),40)


def test_archive_original_is_discoverable_and_only_latest_build_is_delivered(tmp_path,monkeypatch):
    from conversations import conversation_manager
    import app.services.workspace_fs as ws
    monkeypatch.setattr(conversation_manager,'get_documents',lambda uid:[{'filename':'materials.zip/one.txt','content':'32'}])
    monkeypatch.setattr(conversation_manager,'list_chat_image_files',lambda uid:[])
    monkeypatch.setattr(conversation_manager,'conversation_for_turn',lambda uid:NS(messages=[NS(role='user',attachment={'name':'materials.zip','url':'/uploads/chat/original.zip'})]))
    assert '- materials.zip\n' in conversation_manager.list_chat_files(903114)+'\n'
    monkeypatch.setenv('WORKSPACES_DIR',str(tmp_path))
    import os
    for index,name in enumerate(['old','latest'],1):
        path=ws.resolve_in_jail(903114,'engineering/output/'+name+'/drawings.pdf')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'%PDF-'+name.encode());os.utime(path,(index,index))
    delivered=json.loads(ws.collect_deliverables(903114))
    assert len(delivered)==1 and '/latest/' in delivered[0]['path']


def test_large_drawing_archive_import_keeps_all_sources_in_manifest(tmp_path,monkeypatch):
    from app.services.engineering_io import import_chat_file
    from conversations import conversation_manager
    from app.services.workspace_fs import resolve_in_jail
    monkeypatch.setenv('WORKSPACES_DIR',str(tmp_path/'workspaces'))
    archive=tmp_path/'drawings.zip'
    with zipfile.ZipFile(archive,'w') as z:
        for index in range(85):z.writestr(f'{index}/drawing.txt',f'unique source {index}')
    monkeypatch.setattr(conversation_manager,'conversation_for_turn',lambda uid:NS(messages=[NS(attachment={'name':'drawings.zip','url':'original'})]))
    monkeypatch.setattr(conversation_manager,'_attachment_disk_path',lambda att:archive)
    imported=import_chat_file(903115,'drawings.zip')
    assert imported['status']=='ok' and imported['source_count']==85 and imported['sources_omitted']==65
    full=json.loads(resolve_in_jail(903115,imported['manifest_path']).read_text())
    assert len(full['sources'])==85 and all(resolve_in_jail(903115,s['path']).is_file() for s in full['sources'])


def test_extended_formats_and_separate_specification_stamps():
    from app.services.engineering_drawing import FORMATS,infer_format,MM
    assert FORMATS['A4x3']==(630,297) and FORMATS['A1x3']==(1782,841)
    assert infer_format(1783.1,842.1)=='A1x3'
    spec=model();spec['sheets'][0]['format']='А4×3';spec['include_bom']=True
    spec['parts'] += [{'id':f'p{i}','name':f'Контрольная позиция {i}','qty':1,'required_drawing':False} for i in range(29)]
    output,report=render_project(spec)
    assert report['bom_sheets']==2
    with fitz.open(stream=output['drawings.pdf'],filetype='pdf') as doc:
        assert doc[0].rect.width/MM==pytest.approx(630)
        first=doc[1].get_text();following=doc[2].get_text()
        assert 'Формат' in first and 'Зона' in first and 'Примечание' in first
        assert 'Разраб.' in first and 'Разраб.' not in following


def test_paper_bounds_and_malicious_markup_are_not_silently_accepted():
    spec=model();spec['sheets'][0]['views'][0]['origin']=[-100,100]
    with pytest.raises(ValueError,match='рабочее поле'):render_project(spec)
    spec=model();spec['sheets'][0]['views'][0]['entities'].append({'type':'text','at':[0,20],'text':'<script>x</script>'})
    output,_=render_project(spec)
    assert b'<script>' not in output['sheets/01.svg'] and b'&lt;script&gt;' in output['sheets/01.svg']


def test_owner_scoped_inspection_and_sources_not_delivered_as_outputs(tmp_path,monkeypatch):
    from app.services import workspace_fs as ws
    monkeypatch.setenv('WORKSPACES_DIR',str(tmp_path))
    owner=903111;path=ws.resolve_in_jail(owner,'engineering/materials/a/input.pdf');path.parent.mkdir(parents=True)
    pdf,_=render_project(model());path.write_bytes(pdf['drawings.pdf'])
    inspected=inspect_page(owner,'engineering/materials/a/input.pdf',1,[0,0,.9,.8])
    assert isinstance(inspected,EngineeringResult) and inspected.image_data_url.startswith('data:image/png;base64,')
    assert 'image_data_url' not in str(inspected)  # no image bytes in journals
    assert json.loads(ws.collect_deliverables(owner))==[]
    with pytest.raises(ValueError):inspect_page(owner,'../u903112/input.pdf')
    with pytest.raises(ValueError):inspect_page(owner,'engineering/materials/a/input.pdf',2)
    spec=model();spec['sources']=[{'id':'input','path':'engineering/materials/a/input.pdf','sha256':'wrong'}]
    source=ws.resolve_in_jail(owner,'engineering/project.json');source.write_text(json.dumps(spec),encoding='utf-8')
    with pytest.raises(ValueError,match='изменился'):build_project(owner,'engineering/project.json')
    spec['sources'][0].pop('sha256');source.write_text(json.dumps(spec),encoding='utf-8')
    built=build_project(owner,'engineering/project.json')
    assert len(built.files)==2 and all(f['bytes'] for f in built.files)
    delivered=json.loads(ws.collect_deliverables(owner))
    assert {Path(f['path']).suffix for f in delivered}=={'.pdf','.zip','.csv'}


@pytest.mark.parametrize('url',['http://disk.yandex.ru/file','https://evil.test/file','https://user:pass@disk.yandex.ru/file','https://disk.yandex.ru:8000/file','https://evil.storage.yandex.net.evil.test/'])
def test_download_host_cannot_be_arbitrary_or_private_transport(url):
    with pytest.raises(ValueError):_download_host(url)


def test_skill_and_drawing_request_get_build_path():
    from computer_skills.loader import match_skills,load_skill
    from director_router import _wants_file,_is_light_task,_is_document_package_task
    text='Сможешь начертить электромагнитный блок управления ЭМБУ? Нужен полный аналог соленоида по материалам.'
    assert 'eng_reverse' in match_skills(text,sandbox=True)
    assert _wants_file(text) and not _is_light_task(text,'',False,0)
    assert 'references/schema.md' in load_skill('eng_reverse')
    assert not _is_document_package_task('Начерти соленоид и собери комплект документов с чертежами')
    assert _is_document_package_task('Собери комплект документов по договорам')


def test_page_image_is_a_native_model_input_not_base64_text(monkeypatch):
    import openai_client as oc
    import computer_tools
    requests=[]
    call=NS(type='function_call',name='engineering_read_page',arguments='{"path":"input.pdf"}',call_id='c1',id='c1')
    message=NS(type='message',content=[NS(type='output_text',text='Диаметр прочитан',annotations=[])])
    replies=[[call],[message]]

    class Stream:
        def __init__(self,output):self.output=output
        def __aiter__(self):return self.events()
        async def events(self):yield NS(type='response.completed',response=NS(output=self.output,usage=None,status='completed'))
    async def create(**request):requests.append(request);return Stream(replies.pop(0))
    async def tool(name,args,user_id):return EngineeringResult('{"page":1}',image_data_url='data:image/png;base64,iVBORw0KGgo=')
    monkeypatch.setattr(oc,'client',NS(responses=NS(create=create)))
    monkeypatch.setattr(computer_tools,'run_computer_tool',tool)
    result=asyncio.run(oc.get_chat_response([{'role':'user','content':'Прочитай диаметр'}],model='gpt-6-luna',use_tools=True,use_skills=False,max_tool_loops=3))
    images=[part for item in requests[1]['input'] if isinstance(item,dict) for part in item.get('content',[]) if isinstance(part,dict) and part.get('type')=='input_image']
    assert len(images)==1 and images[0]['image_url'].startswith('data:image/png;base64,')
    tool_outputs=[item for item in requests[1]['input'] if isinstance(item,dict) and item.get('type')=='function_call_output']
    assert tool_outputs[0]['output']=='{"page":1}'
    assert result[0]=='Диаметр прочитан'
