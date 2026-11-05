"""Read-only content/geometry checks for generated specialized deliverables."""
import argparse
import json
from pathlib import Path
import re
import zipfile
from evals.specialized import file_text


def check(case, paths):
    texts='\n'.join(file_text(p) for p in paths)
    required=[]
    if case=='docs_rewrite':
        commands=['ledgerctl queue pause','ledgerctl backup verify latest','ledgerctl deploy --version 2.4.1',
                  'ledgerctl health --timeout 60','ledgerctl rollback --previous','ledgerctl queue resume']
        assert all(command in texts for command in commands),'missing_or_changed_command'
        assert texts.index(commands[0])<texts.index(commands[1])<texts.index(commands[2])<texts.index(commands[3]),'incorrect_deploy_order'
        required=[r'24',r'нул|running_jobs\s*=\s*0|активн\w*\s+задач',r'откат|rollback',r'не.*(?:удал|миграц)|запрещ']
    elif case=='docs_migration':
        required=[r'/v1/users',r'/v2/accounts',r'display_name',r'account_id',r'201',r'Authorization',r'Bearer',r'curl',r'числов|numeric',r'нет|не\s+(?:предусмотр|поддерж|выполня)|отсутств']
    elif case=='holdout_doc_limits':
        required=[r'12\s*MiB|12\s*МиБ|12582912|12\s*[×*]\s*1024',r'3|тр[иё]',r'5',r'30',r'7',r'24',r'SLA',r'не\s+(?:указан|задан|определ)|нет|отсутств']
    elif case=='beam_report':
        required=[r'\b75(?:[.,]0+)?\s*(?:МПа|MPa)',r'2(?:[.,]0+)?\s*мм',r'2[.,]13',r'креплен|креплён|закреплен',r'допущ|линейн|упруг']
    elif case=='plate_dxf':
        import ezdxf
        path=next(p for p in paths if p.suffix.lower()=='.dxf')
        doc=ezdxf.readfile(path)
        assert doc.header.get('$INSUNITS')==4,'wrong_units'
        model=doc.modelspace();circles=list(model.query('CIRCLE'))
        assert len(circles)==4,'wrong_hole_count'
        actual={(round(c.dxf.center.x,5),round(c.dxf.center.y,5),round(c.dxf.radius,5)) for c in circles}
        assert actual=={(20,20,5),(180,20,5),(20,80,5),(180,80,5)},'incorrect_holes'
        outlines=list(model.query('LWPOLYLINE'))
        closed=[p for p in outlines if p.closed and len(p)==4]
        assert closed,'missing_closed_outline'
        vertices={(round(x,5),round(y,5)) for x,y,*_ in closed[0].get_points()}
        assert vertices=={(0,0),(200,0),(200,100),(0,100)},'incorrect_outline'
        assert all(c.dxf.layer=='HOLES' for c in circles),'incorrect_hole_layer'
        assert closed[0].dxf.layer=='OUTLINE','incorrect_outline_layer'
    for expression in required:
        assert re.search(expression,texts,re.I|re.S),'missing_artifact_content:'+expression
    if case.startswith(('python_','javascript_','typescript_','c_','holdout_python')):
        archives=[p for p in paths if p.suffix=='.zip']
        assert archives,'missing_archive'
        with zipfile.ZipFile(archives[0]) as z:
            names=z.namelist()
            assert any(Path(n).name.lower().startswith('readme') for n in names),'archive_missing_readme'
            assert any('test' in Path(n).name.lower() for n in names),'archive_missing_tests'
            assert not any('node_modules' in Path(n).parts or '.venv' in Path(n).parts for n in names),'archive_contains_dependencies'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--responses',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    rows=json.loads(args.responses.read_text(encoding='utf8'))['results'];results=[]
    for row in rows:
        if not row.get('artifacts'):continue
        try:
            check(row['id'],[Path(a['path']) for a in row['artifacts']])
            result={'id':row['id'],'passed':True}
        except Exception as exc:result={'id':row['id'],'passed':False,'error':str(exc)}
        results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')


if __name__=='__main__':main()
