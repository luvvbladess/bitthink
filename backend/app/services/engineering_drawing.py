"""Deterministic 2D engineering sheets, from a traceable JSON model.

This is an editable drawing exporter, not a solid modeller or a manufacturing
approval service. Coordinates are millimetres; view coordinates are Cartesian.
"""
from __future__ import annotations

import ast
import base64
import csv
import html
import io
import json
import math
from pathlib import Path
import zipfile

FORMATS = {'A4': (210, 297), 'A3': (420, 297), 'A2': (594, 420), 'A1': (841, 594), 'A0':(1189,841)}
for base in ['A4','A3','A2','A1','A0']:
    minimum,maximum=sorted(FORMATS[base])
    for multiple in range(2,10):
        FORMATS[base+'x'+str(multiple)]=(minimum*multiple,maximum)


def normalize_format(value):
    return str(value).upper().replace('А','A').replace('Х','x').replace('X','x').replace('×','x')


def infer_format(width,height):
    return next((name for name,size in FORMATS.items() if max(abs(a-b) for a,b in zip(sorted(size),sorted([width,height])))<=6),None)
STATES = {'confirmed', 'assumed', 'calculated', 'unknown'}
TYPES = {'line', 'circle', 'polyline', 'arc', 'text', 'linear_dim', 'diameter_dim', 'leader'}
MM = 72 / 25.4


def number(value):
    if isinstance(value, bool):
        raise ValueError('Логическое значение не является размером')
    result = float(str(value).replace(',', '.'))
    if not math.isfinite(result) or abs(result) > 100_000:
        raise ValueError('Некорректное числовое значение')
    return result


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Координата должна быть [x,y]')
    return tuple(number(x) for x in value)


def _formula(expression, values):
    """No eval, imports, calls or attribute access in calculation provenance."""
    operators = {ast.Add: lambda a,b:a+b, ast.Sub: lambda a,b:a-b,
                 ast.Mult: lambda a,b:a*b, ast.Div: lambda a,b:a/b}
    def visit(node):
        if isinstance(node, ast.Constant): return number(node.value)
        if isinstance(node, ast.Name) and node.id in values: return number(values[node.id])
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in operators:
            return number(operators[type(node.op)](visit(node.left), visit(node.right)))
        raise ValueError('В расчётной формуле разрешены числа, ID фактов и + - * /')
    if len(expression) > 500: raise ValueError('Слишком длинная формула')
    return visit(ast.parse(expression, mode='eval').body)


def _measurement(entity):
    if entity['type'] == 'diameter_dim': return 2 * number(entity['radius'])
    a,b=point(entity['from']),point(entity['to'])
    axis=entity.get('axis','x')
    if axis not in {'x','y'}: raise ValueError('Размерная ось должна быть x или y')
    return abs(b[0]-a[0]) if axis=='x' else abs(b[1]-a[1])


def validate_project(spec):
    if not isinstance(spec, dict): raise ValueError('Проект должен быть JSON-объектом')
    if len(json.dumps(spec, ensure_ascii=False)) > 1_500_000: raise ValueError('Проект слишком большой')
    facts, sources, parts = {}, {}, {}
    issues=[]
    for key, target, limit in [('sources',sources,200),('facts',facts,2000),('parts',parts,200)]:
        rows=spec.get(key,[])
        if not isinstance(rows,list) or len(rows)>limit: raise ValueError('Превышен лимит '+key)
        for row in rows:
            identifier=row.get('id') if isinstance(row,dict) else None
            if not isinstance(identifier,str) or not identifier or len(identifier)>80 or identifier in target:
                raise ValueError('Нет уникального ID в '+key)
            target[identifier]=row
    for fid,fact in facts.items():
        state=fact.get('state')
        if state not in STATES: raise ValueError('Неизвестный статус факта '+fid)
        if state=='unknown' and fact.get('value') is not None: raise ValueError('Неизвестный факт должен иметь value=null: '+fid)
        if state!='unknown' and fact.get('value') is None: raise ValueError('Не указано значение '+fid)
        if state=='confirmed':
            evidence=fact.get('evidence',[])
            if not evidence: raise ValueError('Подтверждённый факт без источника: '+fid)
            for item in evidence:
                source=sources.get(item.get('source_id'))
                if source is None or not (item.get('quote') or item.get('locator')):
                    raise ValueError('Не указано место в источнике для '+fid)
                if source.get('pages'):
                    page=item.get('page')
                    if not isinstance(page,int) or not 1<=page<=int(source['pages']):
                        raise ValueError('Номер страницы вне источника: '+fid)
        elif state=='calculated':
            inputs=fact.get('inputs',[])
            if not inputs or any(i not in facts or facts[i]['state']=='unknown' for i in inputs):
                raise ValueError('Расчёт без известных входных фактов: '+fid)
            computed=_formula(str(fact.get('expression','')), {i:facts[i]['value'] for i in inputs})
            if not math.isclose(computed,number(fact['value']),rel_tol=1e-7,abs_tol=1e-6):
                raise ValueError('Результат расчёта не совпадает с формулой: '+fid)
        if state!='confirmed': issues.append({'type':state,'fact_id':fid})
    active=set();done=set()
    def dependencies(fid):
        if fid in active:raise ValueError('Циклическая зависимость расчётных фактов')
        if fid in done:return
        active.add(fid)
        for parent in facts[fid].get('inputs',[]) if facts[fid]['state']=='calculated' else []:dependencies(parent)
        active.remove(fid);done.add(fid)
    for fid in facts:dependencies(fid)
    sheets=spec.get('sheets',[])
    if not isinstance(sheets,list) or not 1<=len(sheets)<=40: raise ValueError('Нужно от 1 до 40 листов')
    seen=set();count=0;drawn=set()
    for sheet in sheets:
        sid=sheet.get('id')
        if not sid or sid in seen: raise ValueError('Не указан уникальный ID листа')
        seen.add(sid)
        sheet['format']=normalize_format(sheet.get('format','A4'))
        if sheet['format'] not in FORMATS: raise ValueError('Неподдерживаемый формат листа')
        if sheet.get('part_id'):
            if sheet['part_id'] not in parts: raise ValueError('Лист относится к неизвестной детали')
            drawn.add(sheet['part_id'])
        for view in sheet.get('views',[]):
            point(view['origin']);scale=number(view.get('scale',sheet.get('scale',1)))
            if not .05<=scale<=20: raise ValueError('Масштаб вне поддерживаемого диапазона')
            entities=view.get('entities',[]);count+=len(entities)
            if count>10000: raise ValueError('Слишком много геометрических элементов')
            for e in entities:
                if e.get('type') not in TYPES: raise ValueError('Неизвестный тип геометрии')
                if e['type'] in {'linear_dim','diameter_dim'}:
                    fact=facts.get(e.get('fact_id'))
                    if fact is None: raise ValueError('Размер не привязан к факту')
                    if 'text' in e: raise ValueError('Ручная замена размерного значения запрещена')
                    if fact['state']!='unknown' and not math.isclose(_measurement(e),number(fact['value']),abs_tol=.01):
                        raise ValueError(f"Размер {e['fact_id']} не совпадает с геометрией листа {sid}")
                    if fact.get('unit','mm') not in {'mm','мм'}: raise ValueError('Размеры должны быть в мм')
                if e['type']=='circle' and number(e['radius'])<=0: raise ValueError('Радиус должен быть положительным')
                if e['type']=='polyline' and (len(e.get('points',[]))<2 or len(e['points'])>1000):
                    raise ValueError('Некорректная полилиния')
                if e.get('position_ref') and e['position_ref'] not in parts: raise ValueError('Неизвестная позиция сборки')
    for pid,part in parts.items():
        if not isinstance(part.get('qty',1),int) or part.get('qty',1)<1: raise ValueError('Некорректное количество '+pid)
        if part.get('required_drawing',True) and pid not in drawn:
            issues.append({'type':'missing_part_drawing','part_id':pid,'name':part.get('name',pid)})
    for fit in spec.get('fits',[]):
        hole,shaft=facts.get(fit.get('hole')),facts.get(fit.get('shaft'))
        if not hole or not shaft: raise ValueError('Посадка относится к неизвестным фактам')
        if hole['state']=='unknown' or shaft['state']=='unknown':
            issues.append({'type':'unknown_fit','id':fit.get('id','')});continue
        if not math.isclose(number(hole['value']),number(shaft['value']),abs_tol=.001):
            issues.append({'type':'fit_nominal_mismatch','id':fit.get('id',''),'hole':hole['value'],'shaft':shaft['value']})
    return {'status':'preliminary','issues':issues,'sheets':len(sheets),'entities':count,
            'facts':len(facts),'parts':len(parts),'confirmation_is_not_manufacturing_approval':True}


def _font_path():
    p=Path(__file__).with_name('engineering_fonts')/'OpenGOSTtypeA-Regular.ttf'
    if not p.is_file(): raise ValueError('Не найден чертёжный шрифт OpenGOST')
    return p


class Canvas:
    def __init__(self,width,height,page):
        import fitz
        self.w,self.h,self.page=width,height,page
        self.svg=[];self.dxf=[];self.dxf_views=[];self.bounds=[]
        self.font=fitz.Font(fontfile=str(_font_path()));page.insert_font(fontname='eng',fontfile=str(_font_path()))
        # OpenGOST cap height 1400 / 2200 em. Height means physical uppercase mm.
        self.cap_ratio=1400/2200

    def text_width(self,text,height):
        return self.font.text_length(str(text),fontsize=height*MM/self.cap_ratio)/MM

    def line(self,a,b,width=.25,layer='OUTLINE',color='#000000',dash=False):
        self.page.draw_line(tuple(v*MM for v in a),tuple(v*MM for v in b),width=width*MM,color=(0,0,0),dashes='['+' '.join(str(n*MM) for n in [6,1.5,.5,1.5])+'] 0' if dash else None)
        self.svg.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" stroke-width="{width}"'+(' stroke-dasharray="6 1.5 .5 1.5"' if dash else '')+'/>')
        self.dxf.extend([(0,'LINE'),(8,layer),(6,'CENTER' if dash else 'Continuous'),(370,min([13,18,25,35,50,70,100,140],key=lambda n:abs(n-width*100))),(10,a[0]),(20,self.h-a[1]),(30,0),(11,b[0]),(21,self.h-b[1]),(31,0)])
        self.bounds.extend([a,b])

    def circle(self,c,r,width=.5,layer='OUTLINE'):
        self.page.draw_circle(tuple(v*MM for v in c),r*MM,width=width*MM,color=(0,0,0))
        self.svg.append(f'<circle cx="{c[0]}" cy="{c[1]}" r="{r}" fill="none" stroke="black" stroke-width="{width}"/>')
        self.dxf.extend([(0,'CIRCLE'),(8,layer),(370,min([13,18,25,35,50,70,100,140],key=lambda n:abs(n-width*100))),(10,c[0]),(20,self.h-c[1]),(30,0),(40,r)])
        self.bounds.extend([(c[0]-r,c[1]-r),(c[0]+r,c[1]+r)])

    def text(self,p,text,height=3.5,anchor='start',layer='TEXT',rotation=0):
        import fitz
        text=str(text).replace('\n',' ')[:400]
        if any(not self.font.has_glyph(ord(ch)) for ch in text if not ch.isspace()):
            raise ValueError('Знак отсутствует в чертёжном шрифте: '+text[:60])
        width=self.text_width(text,height)
        x=p[0]-(width/2 if anchor=='middle' else width if anchor=='end' else 0)
        angle=math.radians(rotation);dx=x-p[0]
        origin=(p[0]+dx*math.cos(angle),p[1]-dx*math.sin(angle))
        tilt=math.tan(math.radians(15))
        # Conjugate the shear into page space: rotated text keeps a straight baseline.
        shear=fitz.Matrix(1,-tilt,0,1,0,0) if rotation%180==90 else fitz.Matrix(1,0,tilt,1,0,0)
        self.page.insert_text(tuple(v*MM for v in origin),text,fontname='eng',fontsize=height*MM/self.cap_ratio,color=(0,0,0),rotate=rotation,
                              morph=(fitz.Point(*[v*MM for v in origin]),shear))
        self.svg.append(f'<g transform="translate({p[0]} {p[1]}) rotate({-rotation}) skewX(-15)"><text x="{dx}" y="0" font-family="OpenGOST" font-size="{height/self.cap_ratio}">{html.escape(text)}</text></g>')
        self.dxf.extend([(0,'TEXT'),(8,layer),(10,origin[0]),(20,self.h-origin[1]),(30,0),(40,height),(50,rotation),(51,15),(1,_dxf_text(text))])
        for tx,ty in [(dx,-height),(dx+width+height*.27,-height),(dx+width,0),(dx,0)]:
            self.bounds.append((p[0]+tx*math.cos(angle)+ty*math.sin(angle),p[1]-tx*math.sin(angle)+ty*math.cos(angle)))

    def poly(self,points,closed=False,width=.5,layer='OUTLINE'):
        for a,b in zip(points,points[1:]): self.line(a,b,width,layer)
        if closed:self.line(points[-1],points[0],width,layer)

    def arrow(self,points):
        self.page.draw_polyline([tuple(v*MM for v in p) for p in points],closePath=True,color=(0,0,0),fill=(0,0,0),width=.1*MM)
        self.svg.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in points)+'" fill="black"/>')
        self.dxf.extend([(0,'SOLID'),(8,'DIMENSION'),*(row for index,p in enumerate([*points,points[-1]]) for row in [(10+index,p[0]),(20+index,self.h-p[1]),(30+index,0)])])
        self.bounds.extend(points)

    def svg_bytes(self):
        embedded=base64.b64encode(_font_path().read_bytes()).decode()
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}mm" height="{self.h}mm" viewBox="0 0 {self.w} {self.h}"><defs><style>@font-face{{font-family:OpenGOST;src:url(data:font/ttf;base64,{embedded})}}</style></defs><rect width="100%" height="100%" fill="white"/>'+''.join(self.svg)+'</svg>').encode()

    def dxf_bytes(self):
        import ezdxf
        document=ezdxf.new('R2010');document.units=ezdxf.units.MM
        document.styles.get('Standard').dxf.font=_font_path().name
        document.linetypes.new('CENTER',dxfattribs={'pattern':[9.5,6,-1.5,.5,-1.5]})
        model=document.modelspace()
        layout=document.layouts.new('Drawing')
        layout.page_setup(size=(self.w,self.h),margins=(0,0,0,0),units='mm')
        def emit(target,rows,transform=None):
            if not rows:return
            attrs=dict(rows);kind=attrs[0];layer=attrs.get(8,'0')
            if layer not in document.layers:document.layers.new(layer)
            common={'layer':layer,'linetype':attrs.get(6,'Continuous'),'lineweight':attrs.get(370,-1)}
            def pos(x,y):
                if not transform:return x,y
                ox,oy,scale=transform;return (x-ox)/scale,(y-oy)/scale
            factor=transform[2] if transform else 1
            if kind=='LINE':target.add_line(pos(attrs[10],attrs[20]),pos(attrs[11],attrs[21]),dxfattribs=common)
            elif kind=='CIRCLE':target.add_circle(pos(attrs[10],attrs[20]),attrs[40]/factor,dxfattribs=common)
            elif kind=='TEXT':target.add_text(attrs[1],dxfattribs={**common,'insert':pos(attrs[10],attrs[20]),'height':attrs[40]/factor,'rotation':attrs.get(50,0),'oblique':attrs.get(51,15)})
            elif kind=='SOLID':target.add_solid([pos(attrs[10+i],attrs[20+i]) for i in range(4)],dxfattribs=common)
        def entities(rows):
            current=[]
            for row in rows:
                if row[0]==0:
                    if current:yield current
                    current=[]
                current.append(row)
            if current:yield current
        covered=set();cursor=20
        for index,view in enumerate(self.dxf_views):
            start,end,origin,scale,bounds=view
            covered.update(range(start,end))
            block=document.blocks.new('VIEW_'+str(index+1))
            ox,oy=origin;transform=(ox,self.h-oy,scale)
            rows=self.dxf[start:end]
            for entity in entities(rows):emit(block,entity,transform)
            layout.add_blockref(block.name,(ox,self.h-oy),dxfattribs={'xscale':scale,'yscale':scale})
            # True-size model space plus a scaled paper layout. A 32mm part
            # stays 32mm in CAD even when its PDF view uses scale 2:1.
            xs=[(x-ox)/scale for x,_ in bounds]
            minimum=min(xs,default=0);maximum=max(xs,default=0)
            model.add_blockref(block.name,(cursor-minimum,0))
            cursor+=maximum-minimum+25
        paper=[row for index,row in enumerate(self.dxf) if index not in covered]
        for entity in entities(paper):emit(layout,entity)
        if not self.dxf_views:
            for entity in entities(paper):emit(model,entity)
        buffer=io.StringIO();document.write(buffer)
        return buffer.getvalue().encode('utf-8')


def _dxf_text(text):
    return text


def _hatch(poly,canvas):
    low=min(y-x for x,y in poly);high=max(y-x for x,y in poly)
    if (high-low)/2>1000:raise ValueError('Слишком большая область штриховки')
    level=math.floor(low/2)*2
    while level<=high:
        hits=[]
        for a,b in zip(poly,[*poly[1:],poly[0]]):
            va=a[1]-a[0]-level;vb=b[1]-b[0]-level
            if (va<=0<vb) or (vb<=0<va):
                t=va/(va-vb);hits.append((a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])))
        hits.sort()
        for i in range(0,len(hits)-1,2):canvas.line(hits[i],hits[i+1],.18,'HATCH')
        level+=2


def _arrow(canvas,tip,direction):
    dx,dy=direction
    canvas.arrow([tip,(tip[0]+1.8*dx+.6*dy,tip[1]+1.8*dy-.6*dx),(tip[0]+1.8*dx-.6*dy,tip[1]+1.8*dy+.6*dx)])


def _label(fact,entity):
    if fact['state']=='unknown':return '?'
    value=format(number(fact['value']),'.6g').replace('.',',')
    return str(entity.get('prefix',''))+value+str(fact.get('tolerance',''))+(' (доп.)' if fact['state']=='assumed' else ' (расч.)' if fact['state']=='calculated' else '')


def _entity(canvas,e,view,sheet,facts):
    ox,oy=point(view['origin']);scale=number(view.get('scale',sheet.get('scale',1)))
    def p(value):x,y=point(value);return ox+x*scale,oy-y*scale
    kind=e['type'];layer=e.get('layer','OUTLINE');width=number(e.get('width',.5))
    if not .1<=width<=1.5:raise ValueError('Толщина линии должна быть 0,1–1,5 мм')
    if kind=='line':canvas.line(p(e['from']),p(e['to']),width,layer,dash=e.get('style')=='center')
    elif kind=='circle':canvas.circle(p(e['center']),number(e['radius'])*scale,width,layer)
    elif kind=='polyline':
        pts=[p(v) for v in e['points']];canvas.poly(pts,bool(e.get('closed')),width,layer)
        if e.get('hatch'):
            if not e.get('closed'):raise ValueError('Штриховка требует замкнутого контура')
            _hatch(pts,canvas)
    elif kind=='arc':
        c=point(e['center']);r=number(e['radius']);start=number(e['start_angle']);end=number(e['end_angle'])
        if r<=0 or not 0<end-start<=360:raise ValueError('Некорректная дуга')
        n=max(4,int((end-start)/3));pts=[p([c[0]+r*math.cos(math.radians(start+(end-start)*i/n)),c[1]+r*math.sin(math.radians(start+(end-start)*i/n))]) for i in range(n+1)]
        canvas.poly(pts,width=width,layer=layer)
    elif kind=='text':canvas.text(p(e['at']),e['text'],number(e.get('height',3.5)),e.get('anchor','start'))
    elif kind=='leader':
        pts=[p(v) for v in e['points']];canvas.poly(pts,width=.25,layer='LEADER')
        canvas.text((pts[-1][0]+2,pts[-1][1]-2),e.get('text',e.get('position_ref','')),3.5)
    elif kind=='linear_dim':
        a,b=p(e['from']),p(e['to']);offset=number(e.get('offset',-8))
        if e.get('axis','x')=='x':
            y=min(a[1],b[1])+offset;u=(a[0],y);v=(b[0],y)
            canvas.line(a,(u[0],y-1.5),.18,'DIMENSION');canvas.line(b,(v[0],y-1.5),.18,'DIMENSION')
            direction=(1 if v[0]>u[0] else -1,0);label=((u[0]+v[0])/2,y-1.5)
        else:
            x=min(a[0],b[0])+offset;u=(x,a[1]);v=(x,b[1])
            canvas.line(a,(x-1.5,u[1]),.18,'DIMENSION');canvas.line(b,(x-1.5,v[1]),.18,'DIMENSION')
            direction=(0,1 if v[1]>u[1] else -1);label=(x-2,(u[1]+v[1])/2)
        canvas.line(u,v,.18,'DIMENSION');_arrow(canvas,u,direction);_arrow(canvas,v,(-direction[0],-direction[1]))
        canvas.text(label,_label(facts[e['fact_id']],e),3.5,'middle','DIMENSION',rotation=0 if e.get('axis','x')=='x' else 90)
    elif kind=='diameter_dim':
        c=p(e['center']);r=number(e['radius'])*scale;u=(c[0]-r,c[1]);v=(c[0]+r,c[1])
        canvas.line(u,v,.18,'DIMENSION');_arrow(canvas,u,(1,0));_arrow(canvas,v,(-1,0))
        canvas.text((c[0],c[1]-2),'Ø'+_label(facts[e['fact_id']],e),3.5,'middle','DIMENSION')


def _frame(canvas,sheet,index,total,project):
    w,h=canvas.w,canvas.h
    canvas.poly([(20,5),(w-5,5),(w-5,h-5),(20,h-5)],True,.5,'FRAME')
    x=w-190;y=h-60
    canvas.poly([(x,y),(w-5,y),(w-5,h-5),(x,h-5)],True,.5,'FRAME')
    # Graphic title block, form 1: change history + approvals + document fields.
    canvas.line((x+65,y),(x+65,y+55),.5,'FRAME')
    for dx in [7,17,40,55]:canvas.line((x+dx,y),(x+dx,y+25),.25,'FRAME')
    for dy in range(5,56,5):canvas.line((x,y+dy),(x+65,y+dy),.25,'FRAME')
    for dx in [17,40,55]:canvas.line((x+dx,y+25),(x+dx,y+55),.25,'FRAME')
    for left,right,title in [(0,7,'Изм.'),(7,17,'Лист'),(17,40,'№ докум.'),(40,55,'Подп.'),(55,65,'Дата')]:
        _boxed_text(canvas,x+left,y+20,right-left,5,title,3.5)
    for row,title in enumerate(['Разраб.','Пров.','Т.контр.','','Н.контр.','Утв.']):
        if title:_boxed_text(canvas,x,y+25+row*5,17,5,title,3.5)
    canvas.line((x+65,y+15),(x+185,y+15),.5,'FRAME')
    canvas.line((x+65,y+40),(x+185,y+40),.5,'FRAME')
    canvas.line((x+135,y+15),(x+135,y+55),.5,'FRAME')
    for dx in [150,167]:canvas.line((x+dx,y+15),(x+dx,y+35),.25,'FRAME')
    for dy in [20,35]:canvas.line((x+135,y+dy),(x+185,y+dy),.25,'FRAME')
    for dx in [140,145]:canvas.line((x+dx,y+20),(x+dx,y+35),.25,'FRAME')
    canvas.line((x+155,y+35),(x+155,y+40),.25,'FRAME')
    for left,right,title in [(135,150,'Лит.'),(150,167,'Масса'),(167,185,'Масштаб')]:
        _boxed_text(canvas,x+left,y+15,right-left,5,title,3.5)
    _boxed_text(canvas,x+65,y,120,15,sheet.get('designation',project.get('designation','')),7)
    _boxed_text(canvas,x+65,y+15,70,25,sheet.get('title',project.get('title','')),5)
    _boxed_text(canvas,x+65,y+40,70,15,str(sheet.get('material','')),5)
    _boxed_text(canvas,x+135,y+40,50,15,str(project.get('organization','')),3.5)
    scale=number(sheet.get('scale',1))
    scale_label=(format(scale,'.5g')+':1') if scale>=1 else ('1:'+format(1/scale,'.5g'))
    _boxed_text(canvas,x+167,y+20,18,15,scale_label.replace('.',','),5)
    _boxed_text(canvas,x+135,y+35,20,5,f'Лист {index}',3.5)
    _boxed_text(canvas,x+155,y+35,30,5,f'Листов {total}',3.5)
    designation=sheet.get('designation',project.get('designation',''))
    canvas.poly([(20,5),(90,5),(90,19),(20,19)],True,.5,'FRAME')
    if designation:canvas.text((55,12),str(designation),3.5,'middle','FRAME',rotation=180)
    canvas.text((95,12),'Предварительная реконструкция',2.5,'start','FRAME')
    _auxiliary_fields(canvas,sheet)


def _auxiliary_fields(canvas,sheet):
    h=canvas.h;w=canvas.w;bottom=h-5
    for title,length in [('Инв. № подл.',25),('Подп. и дата',35),('Взам. инв. №',25),('Инв. № дубл.',25),('Подп. и дата',35)]:
        top=bottom-length
        canvas.poly([(8,top),(20,top),(20,bottom),(8,bottom)],True,.25,'FRAME')
        canvas.line((13,top),(13,bottom),.25,'FRAME')
        canvas.text((12,top+length/2),title,3.5,'middle','FRAME',rotation=90)
        bottom=top
    for title,top,bottom in [('Перв. примен.',5,65),('Справ. №',65,125)]:
        canvas.poly([(8,top),(20,top),(20,bottom),(8,bottom)],True,.25,'FRAME')
        canvas.line((13,top),(13,bottom),.25,'FRAME')
        canvas.text((12,(top+bottom)/2),title,3.5,'middle','FRAME',rotation=90)
    canvas.text((100,h-1),'Копировал',2.5,'middle','FRAME')
    canvas.text((w-35,h-1),'Формат '+sheet.get('format','A4'),2.5,'middle','FRAME')


def _boxed_text(canvas,x,y,width,height,value,size,align='middle'):
    """Fit complete field content; never truncate designations or materials."""
    text=str(value).strip()
    if not text:return
    for candidate in [s for s in [7,5,3.5,2.5] if s<=size]:
        padding=max(1.5,candidate*.27+.2) if align=='start' else candidate*.27+.2
        lines=['']
        for word in text.split():
            joined=(lines[-1]+' '+word).strip()
            if canvas.text_width(joined,candidate)<=width-padding:lines[-1]=joined
            else:lines.append(word)
        lines=[line for line in lines if line]
        if lines and all(canvas.text_width(line,candidate)<=width-padding for line in lines) and len(lines)*candidate*1.35<=height:
            baseline=y+(height-len(lines)*candidate*1.35)/2+candidate*1.12
            for n,line in enumerate(lines):canvas.text((x+.6 if align=='start' else x+width/2-candidate*.135,baseline+n*candidate*1.35),line,candidate,align,'FRAME')
            return
    raise ValueError('Текст не помещается в графу основной надписи: '+text[:60])


def _cell_text(canvas,x,y,text,width):
    words=str(text).split();lines=['']
    for word in words:
        candidate=(lines[-1]+' '+word).strip()
        if canvas.text_width(candidate,2.5)<=width:
            lines[-1]=candidate
        elif len(lines)<2:lines.append(word)
        else:raise ValueError('Наименование детали не помещается в спецификацию')
    for index,line in enumerate(lines):
        if canvas.text_width(line,2.5)>width:raise ValueError('Слишком длинный элемент спецификации')
        canvas.text((x,y+index*3),line,2.5)


def _specification_pages(parts):
    rows=[];previous=None
    for index,part in enumerate(parts,1):
        section=str(part.get('section','Детали'))
        if section!=previous:
            if rows:rows.append({'blank':True})
            rows.append({'heading':section});previous=section
        rows.append({'part':part,'position':part.get('position',index)})
    pages=[]
    while rows:
        capacity=28 if not pages else 32
        pages.append(rows[:capacity]);rows=rows[capacity:]
        # A section heading must remain with its first item.
        if rows and pages[-1][-1].get('heading'):rows.insert(0,pages[-1].pop())
    return pages


def _spec_frame(canvas,index,total,project):
    height=40 if index==1 else 15;x=20;y=canvas.h-5-height
    canvas.poly([(20,5),(205,5),(205,292),(20,292)],True,.5,'FRAME')
    canvas.line((20,y),(205,y),.5,'FRAME')
    for dx in [7,17,40,55,65]:canvas.line((x+dx,y),(x+dx,y+15),.25,'FRAME')
    for dy in [5,10,15]:canvas.line((x,y+dy),(x+65,y+dy),.25,'FRAME')
    for left,right,title in [(0,7,'Изм.'),(7,17,'Лист'),(17,40,'№ докум.'),(40,55,'Подп.'),(55,65,'Дата')]:
        _boxed_text(canvas,x+left,y+10,right-left,5,title,3.5)
    if index==1:
        for dx in [17,40,55,65]:canvas.line((x+dx,y+15),(x+dx,y+40),.25,'FRAME')
        for dy in [20,25,30,35]:canvas.line((x,y+dy),(x+65,y+dy),.25,'FRAME')
        for row,label in enumerate(['Разраб.','Пров.','','Н.контр.','Утв.']):
            if label:_boxed_text(canvas,x,y+15+row*5,17,5,label,3.5)
        canvas.line((x+65,y+15),(205,y+15),.5,'FRAME')
        canvas.line((x+135,y+15),(x+135,y+40),.5,'FRAME')
        for dx in [150,165]:canvas.line((x+dx,y+15),(x+dx,y+25),.25,'FRAME')
        for dy in [20,25]:canvas.line((x+135,y+dy),(205,y+dy),.25,'FRAME')
        for left,right,label in [(135,150,'Лит.'),(150,165,'Лист'),(165,185,'Листов')]:
            _boxed_text(canvas,x+left,y+15,right-left,5,label,3.5)
        _boxed_text(canvas,x+150,y+20,15,5,index,3.5)
        _boxed_text(canvas,x+165,y+20,20,5,total,3.5)
        _boxed_text(canvas,x+65,y+15,70,25,project.get('title','Спецификация'),5)
        _boxed_text(canvas,x+135,y+25,50,15,project.get('organization',''),5)
        _boxed_text(canvas,x+65,y,120,15,project.get('designation',''),7)
    else:
        canvas.line((x+165,y),(x+165,y+15),.5,'FRAME')
        canvas.line((x+165,y+5),(205,y+5),.25,'FRAME')
        _boxed_text(canvas,x+165,y,20,5,'Лист',3.5)
        _boxed_text(canvas,x+165,y+5,20,10,index,5)
        _boxed_text(canvas,x+65,y,100,15,project.get('designation',''),7)
    _auxiliary_fields(canvas,{'format':'A4'})


def _draw_specification(canvas,rows,index,total,project,sheets):
    xs=[20,26,32,40,110,173,183,205];top=5;bottom=252 if index==1 else 277
    for x in xs:canvas.line((x,top),(x,bottom),.25,'FRAME')
    canvas.line((20,20),(205,20),.5,'FRAME')
    for y in range(28,bottom,8):
        if bottom-y>=4:canvas.line((20,y),(205,y),.18,'FRAME')
    for column,title in enumerate(['Формат','Зона','Поз.','Обозначение','Наименование','Кол.','Примечание']):
        if column in {0,1,2,5}:canvas.text(((xs[column]+xs[column+1])/2+1.5,12.5),title,3.5,'middle','TEXT',rotation=90)
        else:_boxed_text(canvas,xs[column],5,xs[column+1]-xs[column],15,title,3.5)
    formats={s.get('part_id'):s.get('format','') for s in sheets if s.get('part_id')}
    for offset,row in enumerate(rows):
        y=20+offset*8
        if row.get('heading'):
            value=row['heading'];_boxed_text(canvas,110,y,63,8,value,3.5)
            width=canvas.text_width(value,3.5)
            canvas.line((141.5-width/2,y+6),(141.5+width/2,y+6),.18,'TEXT')
        elif row.get('part'):
            p=row['part'];format_label=str(p.get('format',formats.get(p['id'],'')));note=str(p.get('note',''))
            if len(format_label)>2:
                note=('*) '+format_label.replace('x','×')+' '+note).strip();format_label='*)'
            values=[format_label,p.get('zone',''),row['position'],p.get('designation',p['id']),p.get('name',p['id']),p.get('qty',1),note]
            for column,value in enumerate(values):_boxed_text(canvas,xs[column],y,xs[column+1]-xs[column],8,value,3.5,align='start' if column in {3,4,6} else 'middle')
    _spec_frame(canvas,index,total,project)


def render_project(spec):
    import fitz
    report=validate_project(spec);facts={f['id']:f for f in spec.get('facts',[])}
    report['drawing_style']='kompas-eskd-form1'
    report['font']='OpenGOST type A, inclination 75 degrees'
    report['source_validation']=spec.get('_source_validation',[])
    output={};doc=fitz.open()
    parts=spec.get('parts',[]) if spec.get('include_bom',True) else []
    spec_pages=_specification_pages(parts)
    total=len(spec['sheets'])+len(spec_pages)
    if total>40:raise ValueError('Листы и спецификация вместе превышают 40 страниц')
    for index,sheet in enumerate(spec['sheets'],1):
        w,h=FORMATS[sheet.get('format','A4')]
        if sheet.get('orientation')=='landscape' and h>w:w,h=h,w
        if sheet.get('orientation')=='portrait' and w>h:w,h=h,w
        page=doc.new_page(width=w*MM,height=h*MM);canvas=Canvas(w,h,page)
        geometry_start=len(canvas.bounds)
        for view in sheet.get('views',[]):
            dxf_start=len(canvas.dxf)
            bounds_start=len(canvas.bounds)
            for entity in view.get('entities',[]):_entity(canvas,entity,view,sheet,facts)
            canvas.dxf_views.append((dxf_start,len(canvas.dxf),point(view['origin']),number(view.get('scale',sheet.get('scale',1))),canvas.bounds[bounds_start:]))
        if any(x<22 or x>w-7 or y<22 or y>h-66 for x,y in canvas.bounds[geometry_start:]):
            raise ValueError('Геометрия/размеры выходят за рабочее поле листа '+str(sheet['id']))
        notes=sheet.get('notes',[])
        if len(notes)>8:raise ValueError('Не более восьми коротких примечаний на лист')
        if notes and any(y>h-66-(len(notes)-1)*4-3 for _,y in canvas.bounds[geometry_start:]):
            raise ValueError('Геометрия перекрывает область технических примечаний')
        for ni,note in enumerate(notes):
            text=str(note)
            if canvas.text_width(text,2.5)>w-32:
                raise ValueError('Примечание не помещается по ширине листа '+str(sheet['id']))
            canvas.text((25,h-66-(len(notes)-ni-1)*4),text,2.5)
        _frame(canvas,sheet,index,total,spec)
        output[f'sheets/{index:02d}.svg']=canvas.svg_bytes()
        output[f'sheets/{index:02d}.dxf']=canvas.dxf_bytes()
    drawn={sheet.get('part_id') for sheet in spec['sheets']}
    for spec_index,rows in enumerate(spec_pages,1):
        page=doc.new_page(width=210*MM,height=297*MM);canvas=Canvas(210,297,page)
        _draw_specification(canvas,rows,spec_index,len(spec_pages),spec,spec['sheets'])
        index=len(spec['sheets'])+spec_index
        output[f'sheets/{index:02d}.svg']=canvas.svg_bytes();output[f'sheets/{index:02d}.dxf']=canvas.dxf_bytes()
    report['drawing_sheets']=len(spec['sheets']);report['bom_sheets']=len(spec_pages);report['pdf_pages']=total
    output['drawings.pdf']=doc.tobytes(garbage=4,deflate=True)
    output['fonts/'+_font_path().name]=_font_path().read_bytes()
    output['fonts/OFL.txt']=_font_path().with_name('OFL.txt').read_bytes()
    output['fonts/README.txt']=('Для сохранения чертёжного шрифта DXF установите OpenGOSTtypeA-Regular.ttf '
                              'или добавьте папку fonts в поиск шрифтов CAD. PDF и SVG уже содержат шрифт.\n'
                              'Источник: https://github.com/ingenium-am/open-gost-arm/releases/tag/v0.7\n'
                              'Наклон текста15° задаётся в PDF/SVG/DXF, файл шрифта не изменён.\n').encode()
    output['project.json']=json.dumps(spec,ensure_ascii=False,indent=2).encode()
    output['validation.json']=json.dumps(report,ensure_ascii=False,indent=2).encode()
    bom=io.StringIO();writer=csv.writer(bom);writer.writerow(['ID','Обозначение','Наименование','Количество','Нужен лист','Лист есть'])
    for part in spec.get('parts',[]):
        safe=lambda value:("'"+str(value)) if str(value).startswith(('=','+','-','@')) else str(value)
        writer.writerow([safe(part['id']),safe(part.get('designation','')),safe(part.get('name','')),part.get('qty',1),part.get('required_drawing',True),part['id'] in drawn])
    output['bom.csv']=bom.getvalue().encode('utf-8-sig')
    rows=['# Реестр реконструкции','', 'Комплект предварительный; выпуск в производство не подтверждён.','', '| ID | Значение | Единица | Статус | Источник / место |', '|---|---|---|---|---|']
    for fact in facts.values():
        evidence='; '.join(str(e.get('source_id',''))+' / '+str(e.get('page',e.get('locator',''))) for e in fact.get('evidence',[]))
        escape=lambda v:str(v).replace('|','/').replace('\n',' ')
        rows.append('| '+' | '.join(escape(v) for v in [fact['id'],fact.get('value','?'),fact.get('unit',''),fact['state'],evidence])+' |')
    rows.extend(['','## Проверки',json.dumps(report,ensure_ascii=False,indent=2),'','DXF: редактируемые линии, дуги-полилинии, окружности и тексты в мм; размеры не ассоциативные.','Оформление: машиностроительный стиль КОМПАС, основная надпись формы1.','PDF/SVG: векторная геометрия со встроенным шрифтом OpenGOST. Для DXF шрифт приложен в папке fonts.','Это не нативный .cdw; полное соответствие ЕСКД и готовность к производству не заявляются.'])
    output['traceability.md']='\n'.join(rows).encode()
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in output.items():z.writestr(name,data)
    output['engineering-package.zip']=archive.getvalue()
    doc.close()
    return output,report
