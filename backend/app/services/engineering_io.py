"""Owner-scoped material import, visual sheet reading and engineering exports."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import struct
from urllib.parse import urlparse, urlencode
import xml.etree.ElementTree as ET
import zipfile

import aiohttp

ALLOWED_SUFFIXES={'.pdf','.docx','.png','.jpg','.jpeg','.webp','.txt','.md','.csv','.dxf','.svg'}
MAX_FILE=20*1024*1024
MAX_TOTAL=64*1024*1024


class EngineeringResult(str):
    """Only trusted tool code can attach image/files outside the textual output."""
    def __new__(cls,text,*,image_data_url=None,files=None):
        obj=super().__new__(cls,text);obj.image_data_url=image_data_url;obj.files=files or []
        return obj


def _save(user_id,path,data):
    from app.services.workspace_fs import resolve_in_jail,user_root,_dir_size,QUOTA_BYTES
    target=resolve_in_jail(user_id,path)
    if target.exists():raise ValueError('Файл уже существует: '+path)
    if len(data)>MAX_TOTAL or _dir_size(user_root(user_id))+len(data)>QUOTA_BYTES:
        raise ValueError('Превышена квота песочницы')
    target.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation protects concurrent employees from silently overwriting data.
    with target.open('xb') as stream:stream.write(data)
    return target


def _extract(path):
    if path.suffix.lower()=='.pdf':
        import fitz
        from document_parser import _pdf_text_is_usable
        with fitz.open(path) as doc:
            rows=[]
            for index,page in enumerate(doc):
                if index>=100:break
                text=page.get_text()[:12000]
                usable=_pdf_text_is_usable(text) and sum(ord(ch)<32 and not ch.isspace() for ch in text)<=max(1,len(text)*.03)
                rows.append({'page':index+1,'text':text,'has_text':usable,
                             'width_pt':page.rect.width,'height_pt':page.rect.height,
                             'fonts':sorted(set(font[3].split('+')[-1] for font in page.get_fonts()))})
            return {'pages':len(doc),'page_text':rows,'text_truncated':len(doc)>100}
    if path.suffix.lower()=='.docx':
        with zipfile.ZipFile(path) as archive:
            info=archive.getinfo('word/document.xml')
            if info.file_size>20*1024*1024:raise ValueError('Слишком большой XML документа')
            root=ET.fromstring(archive.read(info))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs=[''.join(node.itertext()) for node in root.findall('.//w:t',ns)]
        return {'pages':None,'text':'\n'.join(paragraphs)[:200000]}
    if path.suffix.lower() in {'.txt','.md','.csv'}:
        return {'pages':None,'text':path.read_text(encoding='utf-8-sig',errors='replace')[:200000]}
    return {'pages':None,'visual':path.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}}


def _registered_source(user_id,path,name=None,url=None):
    from app.services.workspace_fs import resolve_in_jail
    actual=resolve_in_jail(user_id,path);raw=actual.read_bytes()
    sha=hashlib.sha256(raw).hexdigest();source={'id':'S_'+sha[:16],'name':name or actual.name,
                                             'path':path,'sha256':sha,'bytes':len(raw),'url':url}
    try:detail=_extract(actual)
    except Exception as exc:detail={'error':type(exc).__name__,'pages':None}
    source['pages']=detail.get('pages')
    if detail.get('page_text'):
        from app.services.engineering_drawing import infer_format
        source['sheet_formats']=[infer_format(p['width_pt']*25.4/72,p['height_pt']*25.4/72) for p in detail['page_text']]
        if any(any('gosttypea' in font.lower() for font in p.get('fonts',[])) for p in detail['page_text']):source['suggested_style']='kompas'
    if actual.suffix.lower()=='.docx':
        images=[]
        with zipfile.ZipFile(actual) as archive:
            media=[i for i in archive.infolist() if i.filename.startswith('word/media/') and Path(i.filename).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}]
            if sum(i.file_size for i in media)>MAX_TOTAL:raise ValueError('Изображения DOCX превышают лимит 64 МБ')
            for item in media[:30]:
                if item.file_size>MAX_FILE:continue
                image_path=path+'.images/'+Path(item.filename).name
                _save(user_id,image_path,archive.read(item))
                images.append({'path':image_path,'locator':item.filename})
        detail['images']=images
        source['image_count']=len(images)
        source['image_paths']=[image['path'] for image in images[:3]]
    manifest_path=path+'.source.json'
    _save(user_id,manifest_path,json.dumps({'source':source,'extraction':detail},ensure_ascii=False).encode())
    source['manifest_path']=manifest_path
    source['text_path']=manifest_path
    source['needs_visual_read']=bool(detail.get('images')) or (actual.suffix.lower()=='.pdf' and any(not p['has_text'] or any('symbol' in font.lower() for font in p.get('fonts',[])) for p in detail.get('page_text',[])))
    if detail.get('error'):source['parse_error']=detail['error']
    return source


def import_chat_file(user_id,filename,max_files=200):
    from conversations import conversation_manager
    conv=conversation_manager.conversation_for_turn(user_id)
    match=None
    for message in reversed(getattr(conv,'messages',[]) if conv else []):
        att=getattr(message,'attachment',None) or {}
        for entry in [att,*(att.get('files') or [])]:
            if entry.get('name')==filename or entry.get('filename')==filename:
                match=conversation_manager._attachment_disk_path(entry);break
        if match:break
    if not match or not match.is_file():raise ValueError('Файл не найден в текущей беседе. Сначала list_chat_files.')
    if match.suffix.lower() not in ALLOWED_SUFFIXES|{'.zip'} or match.stat().st_size>(MAX_TOTAL if match.suffix.lower()=='.zip' else MAX_FILE):
        raise ValueError('Неподдерживаемый формат или превышен размер файла')
    prefix='engineering/materials/'+secrets.token_hex(6)
    sources=[];errors=[]
    raw=match.read_bytes()
    if match.suffix.lower()=='.zip':
        entries,errors=_archive_manifest(raw,max(1,min(int(max_files),200)))
    else:entries=[(Path(filename).name,raw)]
    for name,data in entries:
        relative=prefix+'/'+name
        _save(user_id,relative,data)
        try:
            source=_registered_source(user_id,relative,name)
            sources.append(source)
            if source.get('parse_error'):errors.append({'name':name,'reason':'Ошибка чтения '+source['parse_error']})
        except Exception as exc:errors.append({'name':name,'reason':str(exc)[:200]})
    result={'status':'partial' if errors else 'ok','sources':sources,'errors':errors,'bytes':sum(len(data) for _,data in entries)}
    path=prefix+'/materials-manifest.json'
    _save(user_id,path,json.dumps(result,ensure_ascii=False,indent=2).encode())
    result['manifest_path']=path
    return _compact_inventory(result)


def _compact_inventory(result):
    """All files are saved; keep tool context small and expose full inventory path."""
    return {**result,'source_count':len(result['sources']),'sources':result['sources'][:20],
            'sources_omitted':max(0,len(result['sources'])-20),
            'next_step':'Если sources_omitted>0, прочитай manifest_path через workspace_read; там все источники.'}


def _download_host(url):
    p=urlparse(url);host=(p.hostname or '').lower()
    if p.scheme!='https' or p.username or p.password or p.port not in {None,443}:
        raise ValueError('Некорректная ссылка загрузки')
    if not (host in {'cloud-api.yandex.net','disk.yandex.ru','downloader.disk.yandex.ru'} or host.endswith('.storage.yandex.net') or host.endswith('.storage.yandex.ru')):
        raise ValueError('Неподдерживаемый сервер публичного Яндекс Диска')
    return url


async def _download(session,url,limit=MAX_FILE):
    from computer_tools import _assert_public_http_url
    for _ in range(6):
        _download_host(url)
        await asyncio.to_thread(_assert_public_http_url,url)
        async with session.get(url,allow_redirects=False) as response:
            if response.status in {301,302,303,307,308}:
                from urllib.parse import urljoin
                url=urljoin(url,response.headers.get('Location',''));continue
            response.raise_for_status()
            data=bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data)>limit:raise ValueError('Файл превысил лимит загрузки')
            return bytes(data)
    raise ValueError('Слишком много переадресаций')


async def import_yandex(user_id,url,limit=20):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='disk.yandex.ru' or not parsed.path.startswith('/d/') or parsed.query or parsed.fragment:
        raise ValueError('Нужна публичная ссылка вида https://disk.yandex.ru/d/...')
    limit=max(1,min(int(limit),40));prefix='engineering/materials/'+secrets.token_hex(6)
    sources=[];errors=[];total=0
    timeout=aiohttp.ClientTimeout(total=25,connect=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        base='https://cloud-api.yandex.net/v1/disk/public/resources'
        metadata=json.loads(await _download(session,base+'?'+urlencode({'public_key':url,'limit':100}),2*1024*1024))
        items=metadata.get('_embedded',{}).get('items',[]) if metadata.get('type')=='dir' else [metadata]
        # Folder archives use a different delivery route from individual storage
        # nodes. Prefer the single bounded download before slow per-file retries.
        if metadata.get('type')=='dir':
            try:
                link=json.loads(await _download(session,base+'/download?'+urlencode({'public_key':url}),100000))['href']
                raw=await _download(session,link,MAX_TOTAL)
                entries,archive_errors=_archive_manifest(raw,limit)
                errors.extend(archive_errors)
                for name,data in entries:
                    path=prefix+'/'+name;await asyncio.to_thread(_save,user_id,path,data)
                    sources.append(await asyncio.to_thread(_registered_source,user_id,path,name,url));total+=len(data)
                included={name.split('/')[0] for name,_ in entries}
                for item in items:
                    if item.get('name') not in included:errors.append({'name':item.get('name',''),'reason':'Не включён в ограниченный архивный импорт'})
                result={'status':'partial' if errors else 'ok','sources':sources,'errors':errors,'bytes':total}
                manifest_path=prefix+'/materials-manifest.json'
                await asyncio.to_thread(_save,user_id,manifest_path,json.dumps(result,ensure_ascii=False,indent=2).encode())
                result['manifest_path']=manifest_path
                return result
            except Exception:
                # A failed archive is not evidence of an inaccessible document.
                # If some files were saved, retain them and avoid overwriting.
                pass
        selected=[]
        for item in items:
            name=item.get('name','')
            if any(s['name']==name for s in sources):continue
            if item.get('type')!='file':errors.append({'name':name,'reason':'Подпапка: загрузите её отдельной ссылкой'});continue
            if Path(name).name!=name or Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                errors.append({'name':name,'reason':'Неподдерживаемый формат'});continue
            if len(selected)>=limit or int(item.get('size',0))>MAX_FILE:
                errors.append({'name':name,'reason':'Лимит числа/размера файлов'});continue
            selected.append(item)
        semaphore=asyncio.Semaphore(3);completed=0
        async def read(item):
            nonlocal total,completed
            name=item['name']
            async with semaphore:
                try:
                    link=json.loads(await _download(session,base+'/download?'+urlencode({'public_key':url,'path':item.get('path','/')}),100000))['href']
                    data=await _download(session,link)
                    if not data or (item.get('size') is not None and len(data)!=int(item['size'])):
                        raise ValueError('Размер загруженного файла не совпадает с опубликованным')
                    if item.get('sha256') and hashlib.sha256(data).hexdigest()!=item['sha256']:
                        raise ValueError('Контрольная сумма исходного файла не совпала')
                    # Reservation is atomic in this event loop before awaiting disk work.
                    if total+len(data)>MAX_TOTAL:raise ValueError('Общий лимит 64 МБ')
                    total+=len(data);path=prefix+'/'+name
                    await asyncio.to_thread(_save,user_id,path,data)
                    source=await asyncio.to_thread(_registered_source,user_id,path,name,url)
                    sources.append(source)
                    if source.get('parse_error'):errors.append({'name':name,'reason':'Ошибка чтения '+source['parse_error']})
                except Exception as exc:errors.append({'name':name,'reason':type(exc).__name__})
                finally:
                    completed+=1
                    if completed%3==0 or completed==len(selected):
                        from status_feed import push_status
                        await push_status('think',f'Обработаны материалы {completed}/{len(selected)}, загружено {len(sources)}')
        tasks=[asyncio.create_task(read(item)) for item in selected]
        try:
            done,pending=await asyncio.wait(tasks,timeout=90) if tasks else (set(),set())
            for task,item in zip(tasks,selected):
                if task in pending:errors.append({'name':item['name'],'reason':'Превышено время импорта 90 с'})
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    if metadata.get('_embedded',{}).get('total',0)>100:errors.append({'name':'Папка','reason':'Показаны первые 100 элементов'})
    manifest={'status':'partial' if errors else 'ok','sources':sources,'errors':errors,'bytes':total}
    manifest_path=prefix+'/materials-manifest.json'
    await asyncio.to_thread(_save,user_id,manifest_path,json.dumps(manifest,ensure_ascii=False,indent=2).encode())
    manifest['manifest_path']=manifest_path
    return manifest


def _archive_entries(data,limit):
    return _archive_manifest(data,limit)[0]


def _archive_manifest(data,limit):
    """Bound central directory before ZipInfo allocation and bound decompression."""
    end=data.rfind(b'PK\x05\x06',max(0,len(data)-65557))
    if end<0 or end+22>len(data):raise ValueError('Неверный ZIP')
    fields=struct.unpack_from('<4s4H2LH',data,end)
    if fields[1] or fields[2] or fields[4]>200 or fields[5]>1024*1024:
        raise ValueError('Слишком большой/многотомный/ZIP64 каталог')
    result=[];names=set();errors=[]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        if len(infos)>200 or sum(i.file_size for i in infos)>MAX_TOTAL:raise ValueError('Превышен лимит архива')
        for info in infos:
            name=info.filename.replace('\\','/')
            parts=name.split('/')
            if name.startswith('/') or any(part in {'..','.'} for part in parts) or ':' in name or '\x00' in name:
                raise ValueError('Недопустимый путь в архиве')
            if info.is_dir():continue
            if not all(parts) or (info.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Недопустимый путь или символическая ссылка')
            key=name.casefold()
            if key in names:raise ValueError('Совпадающие пути в архиве')
            names.add(key)
            if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
                errors.append({'name':name,'reason':'Неподдерживаемый формат; вложенные архивы не распаковываются'});continue
            if len(result)>=limit:
                errors.append({'name':name,'reason':'Лимит числа файлов'});continue
            if info.file_size>MAX_FILE or info.flag_bits&1:
                errors.append({'name':name,'reason':'Файл больше 20 МБ или зашифрован'});continue
            payload=archive.read(info)
            if len(payload)>MAX_FILE:raise ValueError('Размер файла превышен')
            result.append((name,payload))
    return result,errors


def inspect_page(user_id,path,page=1,crop=None):
    from app.services.workspace_fs import resolve_in_jail
    import fitz
    from PIL import Image
    actual=resolve_in_jail(user_id,path)
    if not actual.is_file() or actual.stat().st_size>MAX_FILE:raise ValueError('Файл не найден или больше 20 МБ')
    if actual.suffix.lower()=='.pdf':
        with fitz.open(actual) as doc:
            if not 1<=int(page)<=len(doc):raise ValueError('Страница вне документа')
            p=doc[int(page)-1];rect=p.rect
            if crop:
                if len(crop)!=4 or not all(isinstance(x,(float,int)) and 0<=x<=1 for x in crop):raise ValueError('crop: четыре числа 0..1')
                if crop[0]>=crop[2] or crop[1]>=crop[3]:raise ValueError('Пустой crop')
                rect=fitz.Rect(rect.width*crop[0],rect.height*crop[1],rect.width*crop[2],rect.height*crop[3])
            scale=min(4,2400/max(rect.width,rect.height))
            png=p.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=rect,alpha=False).tobytes('png')
            info={'path':path,'page':int(page),'pages':len(doc),'text':p.get_text(clip=rect)[:8000],
                  'visual_read_required':True,'crop':crop}
    elif actual.suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
        with Image.open(actual) as image:
            if image.width*image.height>30_000_000:raise ValueError('Изображение превышает 30 мегапикселей')
            image.thumbnail((2400,2400));buffer=io.BytesIO();image.convert('RGB').save(buffer,format='PNG');png=buffer.getvalue()
        info={'path':path,'page':1,'visual_read_required':True}
    else:raise ValueError('Для визуального чтения нужен PDF или изображение')
    return EngineeringResult(json.dumps(info,ensure_ascii=False),image_data_url='data:image/png;base64,'+base64.b64encode(png).decode())


def build_project(user_id,spec_path):
    from app.services.workspace_fs import resolve_in_jail
    from app.services.engineering_drawing import render_project
    path=resolve_in_jail(user_id,spec_path)
    if not path.is_file() or path.stat().st_size>1_500_000:raise ValueError('Проект JSON не найден или слишком большой')
    spec=json.loads(path.read_text(encoding='utf-8-sig'))
    # A file source must really exist in this owner's workspace; it cannot be
    # an invented filename or another user's path. Hash changes invalidate it.
    source_checks=[]
    source_map={source['id']:source for source in spec.get('sources',[])}
    for source in spec.get('sources',[]):
        if source.get('path'):
            source_path=resolve_in_jail(user_id,source['path'])
            if not source_path.is_file() or source_path.stat().st_size>MAX_FILE:raise ValueError('Источник не найден: '+source['id'])
            digest=hashlib.sha256(source_path.read_bytes()).hexdigest()
            if source.get('sha256') and source['sha256']!=digest:raise ValueError('Источник изменился: '+source['id'])
            source['sha256']=digest
            detail=_extract(source_path)
            if detail.get('pages'):source['pages']=detail['pages']
            source_checks.append({'id':source['id'],'file_verified':True,'pages':detail.get('pages')})
        elif source.get('kind')=='user':
            from conversations import conversation_manager
            conv=conversation_manager.conversation_for_turn(user_id)
            user_messages=[str(m.content or '') for m in getattr(conv,'messages',[]) if m.role=='user'] if conv else []
            if not source.get('text') or not any(source['text'] in text for text in user_messages):
                raise ValueError('Источник user не совпадает с сообщением человека')
            source_checks.append({'id':source['id'],'user_text_verified':True})
    for fact in spec.get('facts',[]):
        if fact.get('state')!='confirmed':continue
        for evidence in fact.get('evidence',[]):
            source=source_map.get(evidence.get('source_id'),{})
            if not source.get('path') and source.get('kind')!='user':
                raise ValueError('Подтверждённый факт требует загруженный файл или проверенное сообщение пользователя')
    spec['_source_validation']=source_checks
    output,report=render_project(spec)
    prefix='engineering/output/'+secrets.token_hex(6)
    for name,data in output.items():_save(user_id,prefix+'/'+name,data)
    compact={key:report[key] for key in ['status','drawing_sheets','bom_sheets','pdf_pages','entities','facts','parts']}
    compact['issues']=report['issues'][:40];compact['issues_omitted']=max(0,len(report['issues'])-40)
    response={'status':'preliminary','output_dir':prefix,'validation':compact,
              'validation_path':prefix+'/validation.json',
              'pdf':prefix+'/drawings.pdf','zip':prefix+'/engineering-package.zip',
              'next_step':'Прочитай PDF через engineering_read_page; проверь разрезы, размеры и надписи. Исправь JSON и пересобери при ошибке.'}
    preview=inspect_page(user_id,prefix+'/drawings.pdf',1)
    return EngineeringResult(json.dumps(response,ensure_ascii=False),image_data_url=preview.image_data_url,files=[
        {'filename':'Чертежи — предварительный комплект.pdf','bytes':output['drawings.pdf'],'mime_type':'application/pdf'},
        {'filename':'Редактируемый комплект чертежей.zip','bytes':output['engineering-package.zip'],'mime_type':'application/zip'},
    ])


def guard_completion(answer,record):
    """Expose the actual package/material state, even if synthesis omits it."""
    import re
    engineering=record.engineering
    if engineering.get('last_build_failed'):
        answer+='\n\nПоследняя попытка сборки не прошла проверку. Запрошенный комплект не считается готовым.'
    if engineering.get('latest_build'):
        answer=re.sub(r'(?i)полный\s+аналог\s+(?:готов|создан|подготовлен)', 'Предварительная реконструкция подготовлена',answer)
        answer=re.sub(r'(?i)(?:готов|создан|подготовлен)\s+полный\s+аналог', 'Подготовлена предварительная реконструкция',answer)
        if not re.search(r'(?i)предварительн|реконструкц',answer):
            answer+='\n\nСтатус файлов: предварительная реконструкция. Полный аналог исходного изделия не подтверждён.'
        issues=engineering['latest_build'].get('issues',[])
        missing=[str(i.get('name',i.get('part_id',''))) for i in issues if i.get('type')=='missing_part_drawing']
        if missing:
            answer+='\n\nБез деталировки остались: '+', '.join(missing[:8])+'.'
    if engineering.get('materials_partial'):
        names=engineering.get('missing_materials',[])
        answer+='\n\nЧасть исходных материалов не загрузилась'+(': '+', '.join(names[:5]) if names else '')+'. Они не считаются изученными.'
    return answer
