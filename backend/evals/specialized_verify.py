"""Independent code checks, run only inside the disposable evaluation sandbox.

No model-written tests are trusted as the sole acceptance criterion. The report
names the synthetic workspace IDs. Unknown code is never executed on the host.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile


def execute(argv, cwd, uid, timeout=45, extra_env=None, input_text=None):
    import workspace_fs as fs
    env = {'PATH':'/usr/local/bin:/usr/bin:/bin', 'HOME':str(fs.user_root(uid)),
           'LANG':'C.UTF-8', 'TMPDIR':str(fs.user_root(uid)/'.tmp'),
           'NODE_OPTIONS':'--max-old-space-size=384', 'PYTHONDONTWRITEBYTECODE':'1',
           **(extra_env or {})}
    (fs.user_root(uid)/'.tmp').mkdir(exist_ok=True)
    child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True, preexec_fn=lambda:fs._prepare_child(uid,timeout,False,128))
    try:
        stdout, stderr = child.communicate(input=input_text, timeout=timeout)
        return child.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.communicate()
        return 124, '', 'validation timeout'
    finally:
        try:os.killpg(child.pid,signal.SIGKILL)
        except ProcessLookupError:pass


def find(root, name):
    paths = [p for p in root.rglob(name) if not any(x in {'.venv','node_modules','.tmp','verification'} for x in p.relative_to(root).parts)]
    if not paths:raise AssertionError('missing_source:' + name)
    return min(paths,key=lambda p:len(p.parts))


def as_json(argv,cwd,uid):
    code,out,err=execute(argv,cwd,uid)
    assert code==0, f'exit_{code}:' + err[-600:]
    return json.loads(out)


def http_request(port,path,uid,root,data=None):
    # The trusted evaluator uses Node as HTTP client. User Python's internal
    # address guard stays enabled; neither product code nor its guard is edited.
    script="""const http=require('node:http'); const spec=JSON.parse(process.argv[1]);
const body=process.argv[2]; const req=http.request(spec,res=>{let s='';res.on('data',x=>s+=x);res.on('end',()=>console.log(JSON.stringify({status:res.statusCode,body:s})));});
req.on('error',e=>{console.error(e.message);process.exitCode=1});req.setTimeout(1500,()=>req.destroy(new Error('timeout')));req.end(body==='__none__'?undefined:body);"""
    spec={'hostname':'127.0.0.1','port':port,'path':path,'method':'GET' if data is None else 'POST','headers':{'Content-Type':'application/json'}}
    return as_json(['node','-e',script,json.dumps(spec),data.decode() if data is not None else '__none__'],root,uid)


def check(case, uid, root_override=None):
    import workspace_fs as fs
    root=root_override or fs.user_root(uid)
    if case=='python_csv':
        main=find(root,'main.py')
        value=as_json([sys.executable,str(main),str(root/'inputs/sales.csv')],main.parent,uid)
        assert value=={'books':10.2,'food':6.0},repr(value)
        invalid=root/'inputs/invalid.csv';invalid.write_text('category,amount\nx,not-a-number\n')
        assert execute([sys.executable,str(main),str(invalid)],main.parent,uid)[0]!=0
    elif case=='javascript_cli':
        main=find(root,'main.mjs')
        value=as_json(['node',str(main),str(root/'inputs/tasks.json')],main.parent,uid)
        assert value=={'total':3,'done':1,'pending':2},repr(value)
        invalid=root/'inputs/invalid.json';invalid.write_text('{broken')
        assert execute(['node',str(main),str(invalid)],main.parent,uid)[0]!=0
    elif case=='c_cli':
        main=find(root,'main.c');binary=main.parent/'independent-check'
        sources=[p for p in main.parent.rglob('*.c')
                 if not any(x in {'test','tests','build','dist','node_modules','verification','verify_unzip'}
                            for x in p.relative_to(main.parent).parts)
                 and not p.name.startswith('test_')]
        code,out,err=execute(['gcc','-std=c11','-Wall','-Wextra','-Werror',*[str(p) for p in sorted(sources)],'-o',str(binary)],main.parent,uid)
        assert code==0,err[-1000:]
        assert as_json([str(binary),'4','-2','9'],main.parent,uid)=={'sum':11,'max':9}
        assert as_json([str(binary),'-7','-2','-4'],main.parent,uid)=={'sum':-13,'max':-2}
        for bad in [[],['12x'],['9223372036854775807','1']]:
            assert execute([str(binary),*bad],main.parent,uid)[0]!=0,'bad_argument_accepted:' + repr(bad)
    elif case=='typescript_cli':
        source=find(root,'main.ts');package=find(root,'package.json');directory=package.parent
        spec=json.loads(package.read_text())
        assert not spec.get('dependencies'), 'Unexpected runtime dependencies'
        assert set(spec.get('devDependencies',{})) <= {'typescript','@types/node'}, 'Unexpected dev dependencies'
        if not (directory/'node_modules/typescript').is_dir():
            code,out,err=execute(['npm','install','--ignore-scripts','--no-audit','--no-fund'],directory,uid,120)
            assert code==0,err[-800:]
        code,out,err=execute(['npm','run','build'],directory,uid,90)
        assert code==0,(out+err)[-1500:]
        candidates=[p for p in directory.rglob('main.js') if 'node_modules' not in p.parts]
        assert candidates,'compiled_entry_missing'
        # The prompt leaves input transport open. Honor the documented CLI:
        # stdin and a filename argument are both valid user-facing choices.
        readmes=list(directory.glob('README.md'))
        readme=readmes[0].read_text(errors='replace') if readmes else ''
        stdin_cli='stdin' in readme.lower()
        argv=['node',str(candidates[0])]+([] if stdin_cli else [str(root/'inputs/scores.json')])
        code,out,err=execute(argv,directory,uid,input_text=(root/'inputs/scores.json').read_text() if stdin_cli else None)
        assert code==0,err[-600:]
        value=json.loads(out)
        assert value==[{'name':'B','score':5},{'name':'C','score':5},{'name':'A','score':2}],repr(value)
    elif case=='holdout_python_fix':
        main=find(root,'main.py')
        script='from main import money; import json; print(json.dumps([money(s) for s in ["2.675","-2.675","4","0.005"]]))'
        assert as_json([sys.executable,'-c',script],main.parent,uid)==['2.68','-2.68','4.00','0.01']
        assert execute([sys.executable,'-m','unittest','discover'],main.parent,uid)[0]==0
    elif case=='python_service':
        candidates=[p for p in root.rglob('*.py') if not any(x in {'.venv','.tmp','tests','verification'} for x in p.relative_to(root).parts)
                    and not p.name.startswith(('test_','verify','run_')) and '__main__' in p.read_text(errors='ignore')]
        assert candidates,'service_entry_missing'
        modules=[p for p in candidates if p.name=='__main__.py' and (p.parent/'__init__.py').is_file()]
        main=min(modules or candidates,key=lambda p:len(p.parts));port=18000+uid%10000
        cwd=main.parent.parent if modules else main.parent
        argv=[sys.executable,'-m',main.parent.name] if modules else [sys.executable,str(main)]
        env={'PATH':'/usr/local/bin:/usr/bin:/bin','PORT':str(port),'HOME':str(root),'LANG':'C.UTF-8'}
        child=subprocess.Popen(argv,cwd=cwd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            start_new_session=True,preexec_fn=lambda:fs._prepare_child(uid,30,False,96))
        base='http://127.0.0.1:'+str(port)
        try:
            for _ in range(60):
                try:
                    response=http_request(port,'/health',uid,root)
                    value=json.loads(response['body'])
                    break
                except (OSError,ValueError,AssertionError):time.sleep(.1)
            else:raise AssertionError('health_unavailable')
            assert value=={'status':'ok'},repr(value)
            response=http_request(port,'/sum',uid,root,b'{"numbers":[1,2.5,-3]}')
            assert response['status']==200 and json.loads(response['body'])=={'sum':.5}
            for path,data,status in [('/sum',b'{bad',400),('/sum',b'{"numbers":[1,"2"]}',400),('/missing',None,404)]:
                response=http_request(port,path,uid,root,data)
                assert response['status']==status,(path,response['status'])
        finally:
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            child.wait()
    return {'id':case,'passed':True}


def check_archive(row):
    """Run the same independent checks on the exact bytes delivered to the user."""
    import workspace_fs as fs
    home=fs.user_root(row['uid'])
    artifact=next(a for a in row['artifacts'] if a['filename'].endswith('.zip'))
    candidates=[p for p in home.rglob(artifact['filename']) if p.is_file() and not p.is_symlink()
                and hashlib.sha256(p.read_bytes()).hexdigest()==artifact['sha256']]
    assert candidates,'delivered_archive_bytes_not_found'
    with tempfile.TemporaryDirectory(prefix='verification-',dir=home) as temporary:
        root=Path(temporary)
        with zipfile.ZipFile(candidates[0]) as archive:
            assert len(archive.infolist())<=1000 and sum(i.file_size for i in archive.infolist())<=100*1024*1024,'archive_too_large'
            for item in archive.infolist():
                path=(root/item.filename).resolve()
                assert path.is_relative_to(root),'archive_path_escape'
                assert (item.external_attr >> 16) & 0o170000 != 0o120000,'archive_symlink'
            archive.extractall(root)
        inputs=home/'inputs'
        if inputs.is_dir():
            for path in inputs.rglob('*'):
                if path.is_file():
                    assert not path.is_symlink() and path.resolve().is_relative_to(home),'unsafe_input_fixture'
                    target=root/'inputs'/path.relative_to(inputs);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(path,target)
        result=check(row['id'],row['uid'],root)
        result['scope']='delivered_archive'
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--responses',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--archives',action='store_true')
    a=p.parse_args()
    if os.getenv('SANDBOX_MODE')!='1':raise SystemExit('Execution verification requires the disposable sandbox')
    report=json.loads(a.responses.read_text())
    results=[]
    for row in report['results']:
        if row['category'] not in {'code_python','code_javascript','code_c','code_typescript','product'}:continue
        started=time.monotonic()
        try:value=check_archive(row) if a.archives else check(row['id'],row['uid'])
        except Exception as exc:value={'id':row['id'],'passed':False,'error':str(exc)[:1800]}
        value['seconds']=round(time.monotonic()-started,3);results.append(value)
        print(json.dumps(value),flush=True)
    a.output.write_text(json.dumps(results,indent=2))


if __name__=='__main__':main()
