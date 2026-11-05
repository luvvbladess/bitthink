"""Execute generated solutions in disposable offline containers, never on host.

This is a functional acceptance suite, not a general intelligence score.
Enfusion is reviewed separately: its proprietary runtime is not available here.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import uuid


PY = {
'py_unique': '''
from itertools import islice, cycle
assert list(unique([3,1,3,2,1]))==[3,1,2]
assert list(unique([]))==[]
assert list(islice(unique(cycle([3,1,2])),3))==[3,1,2]
seen=[]
def source():
    for x in [1,2,1]:seen.append(x);yield x
it=iter(unique(source()));assert seen==[]
assert next(it)==1 and seen==[1]
''',
'py_intervals': '''
import copy, random
assert merge_intervals([(2,4),(1,2),(3,6),(8,8)]) == [(1,2),(2,6)]
assert merge_intervals([])==[]
try: merge_intervals([(3,2)])
except ValueError: pass
else: raise AssertionError('invalid interval')
random.seed(87)
for _ in range(150):
    xs=[tuple(sorted((random.randrange(-10,11),random.randrange(-10,11)))) for _ in range(15)]
    before=copy.deepcopy(xs); got=merge_intervals(xs)
    assert xs==before
    assert got==sorted(got) and all(a<b for a,b in got)
    assert all(got[i][1]<=got[i+1][0] for i in range(len(got)-1))
    assert {n for a,b in xs for n in range(a,b)}=={n for a,b in got for n in range(a,b)}
''',
'py_batches': '''
from itertools import count, islice
assert list(batches(range(5),2))==[[0,1],[2,3],[4]]
assert list(batches([],2))==[]
assert list(islice(batches(count(),3),2))==[[0,1,2],[3,4,5]]
for seq in ([],[1]):
    for size in (0,-1):
        try: next(iter(batches(seq,size)))
        except ValueError: pass
        else: raise AssertionError('invalid size')
seen=[]
def source():
    for i in range(9): seen.append(i); yield i
it=iter(batches(source(),3)); assert seen==[]
assert next(it)==[0,1,2] and seen==[0,1,2]
''',
'py_async': '''
import asyncio
async def verify():
    active=0; peak=0
    async def fn(x):
        nonlocal active,peak
        active+=1; peak=max(peak,active)
        try: await asyncio.sleep((7-x%7)*.001); return x*2
        finally: active-=1
    assert await async_map(fn,list(range(20)),3)==list(range(0,40,2))
    assert peak<=3 and active==0
    assert await async_map(fn,[],2)==[]
    for limit in (0,-1):
        try: await async_map(fn,[],limit)
        except ValueError: pass
        else: raise AssertionError('invalid limit')
    baseline=set(asyncio.all_tasks())
    async def bad(x):
        nonlocal active
        active+=1
        try:
            if x==1: await asyncio.sleep(.001); raise LookupError('original')
            await asyncio.sleep(10)
        finally: active-=1
    try: await async_map(bad,list(range(8)),3)
    except LookupError: pass
    else: raise AssertionError('lost failure')
    assert active==0 and set(asyncio.all_tasks())<=baseline
    task=asyncio.create_task(async_map(bad,[0]*8,3))
    await asyncio.sleep(.01); task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    else: raise AssertionError('lost cancellation')
    assert active==0 and set(asyncio.all_tasks())<=baseline
asyncio.run(verify())
''',
'sql_null': '''
import sqlite3
db=sqlite3.connect(':memory:')
db.executescript('CREATE TABLE customers(id INTEGER PRIMARY KEY); CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER NULL); INSERT INTO customers VALUES(1),(2),(3),(4); INSERT INTO orders VALUES(1,1),(2,NULL),(3,3),(4,1);')
assert db.execute(QUERY).fetchall()==[(2,),(4,)]
'''}

CPP = {
'cpp_lower': r'''
#include <cassert>
#include <algorithm>
int main(){for(auto a:std::vector<std::vector<int>>{{},{1},{1,1,2,4,4,9},{-8,-3,0}})for(int t=-10;t<=11;t++)assert(lower_bound_index(a,t)==size_t(std::lower_bound(a.begin(),a.end(),t)-a.begin()));}
''',
'cpp_parse': r'''
#include <cassert>
#include <limits>
#include <string>
int main(){
assert(ParseInt32("0")==0);assert(ParseInt32("+42")==42);assert(ParseInt32("-2147483648")==INT32_MIN);assert(ParseInt32("2147483647")==INT32_MAX);
for(auto s:{"","+","-"," 1","1 ","1x","2147483648","-2147483649","999999999999999999999999999999","--1","1.0"})assert(!ParseInt32(s));
assert(!ParseInt32(std::string("1\0",2)));
for(int64_t i=-100000;i<=100000;i+=137){assert(ParseInt32(std::to_string(i))==i);}
}
''',
'cpp_window': r'''
#include <cassert>
#include <algorithm>
#include <random>
int main(){
for(auto a:std::vector<std::vector<int>>{{},{1},{1,3,3,-7,9,2},{-1,-2,-3}}){
 for(size_t k=0;k<=a.size()+1;++k){
 if(k==0||k>a.size()){try{sliding_max(a,k);assert(false);}catch(const std::invalid_argument&){}continue;}
 std::vector<int> expected;for(size_t i=0;i+k<=a.size();++i)expected.push_back(*std::max_element(a.begin()+i,a.begin()+i+k));assert(sliding_max(a,k)==expected);
 }}
std::mt19937 rng(17);for(int j=0;j<100;++j){std::vector<int>a(100);for(auto&v:a)v=int(rng()%101)-50;for(size_t k=1;k<=a.size();k++){std::vector<int>e;for(size_t i=0;i+k<=a.size();++i)e.push_back(*std::max_element(a.begin()+i,a.begin()+i+k));assert(sliding_max(a,k)==e);}}
}
''',
'cpp_erase': r'''
#include <cassert>
int main(){std::vector<int>a{-5,-4,-3,-2,-1,0,1,2,3,4,5};erase_odds(a);assert((a==std::vector<int>{-4,-2,0,2,4}));a.clear();erase_odds(a);assert(a.empty());a={1,-1};erase_odds(a);assert(a.empty());}
''',
'm0_ticks': r'''
#include <cassert>
int main(){assert(elapsed(3,UINT32_MAX-4,8));assert(!elapsed(3,UINT32_MAX-4,9));assert(elapsed(0,0,0));assert(elapsed(UINT32_MAX,0,UINT32_MAX));assert(!elapsed(0,0,UINT32_MAX));}
''',
'm0_irq': r'''
#include <cassert>
static bool called=false;
static void callback(){called=true;assert(mock_mask==1);}
int main(){for(uint32_t original:{0u,1u}){mock_mask=original;called=false;with_irq_mask(callback);assert(called&&mock_mask==original);}}
'''}

RUST = {
'rust_unicode': '''
fn main(){assert_eq!(first_index("é猫é",'猫'),Some(2));assert_eq!(first_index("é猫é",'é'),Some(0));assert_eq!(first_index("猫z",'z'),Some(3));assert_eq!(first_index("",'z'),None);assert_eq!(first_index("abc",'z'),None);}
''',
'rust_parse': '''
fn main(){assert_eq!(parse_numbers("  "),Ok(vec![]));assert_eq!(parse_numbers(" -2147483648, +4,2147483647 "),Ok(vec![i32::MIN,4,i32::MAX]));for s in [",","1,","1,,2","2147483648","x","1 2"]{assert!(parse_numbers(s).is_err(),"{}",s);}}
''',
'rust_transaction': '''
fn main(){
use std::collections::HashMap;
let mut d=HashMap::from([("a".to_string(),4),("z".to_string(),u64::MAX)]);
let s=HashMap::from([("a".to_string(),3),("empty".to_string(),0)]);
add_counts(&mut d,&s).expect("valid");assert_eq!(d.get("a"),Some(&7));assert_eq!(d.get("empty"),Some(&0));assert_eq!(s.len(),2);
for _ in 0..100{let before=d.clone();let s=HashMap::from([("a".to_string(),1),("new".to_string(),3),("z".to_string(),1)]);assert!(add_counts(&mut d,&s).is_err());assert_eq!(d,before);}
}
''',
'rust_dedup': '''
#[derive(Debug)]struct Item(i32,i32);
impl PartialEq for Item {fn eq(&self,other:&Self)->bool {self.0==other.0}}impl Eq for Item{}
fn main(){let out=dedup_sorted(vec![Item(1,10),Item(1,20),Item(2,30),Item(1,40)]);assert_eq!(out.len(),3);assert_eq!(out[0].1,10);assert_eq!(out[2].1,40);assert!(dedup_sorted::<Item>(vec![]).is_empty());}
'''}

JS = '''
import assert from 'node:assert/strict';
(async()=>{
for(const v of [0,-1,1.5,NaN,Infinity])await assert.rejects(mapLimit([],v,async x=>x),RangeError);
let active=0,peak=0;
assert.deepEqual(await mapLimit([1,2,3,4,5],2,async x=>{active++;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,8-x));active--;return x*2}),[2,4,6,8,10]);assert(peak<=2&&active===0);
assert.deepEqual(await mapLimit([],2,async x=>x),[]);
let started=[];let ended=[];const error=new Error('original');
await assert.rejects(mapLimit([0,1,2,3,4],2,async x=>{started.push(x);if(x===0){await new Promise(r=>setTimeout(r,2));throw error;}await new Promise(r=>setTimeout(r,25));ended.push(x)}),e=>e===error);
assert.deepEqual(started,[0,1]);assert.deepEqual(ended,[1]);
await assert.rejects(mapLimit([0,1],1,()=>{throw error}),e=>e===error);
})().catch(e=>{console.error(e);process.exitCode=1});
'''

CS_COMMON = '''
using System;
using System.Collections;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
'''
CS = {
'cs_count': '''
sealed class Once : IEnumerable<int>{bool used;public IEnumerator<int> GetEnumerator(){if(used)throw new Exception("twice");used=true;yield return 1;yield return 2;yield return 4;}IEnumerator IEnumerable.GetEnumerator()=>GetEnumerator();}
class Program {static void Main(){if(Solution.CountWhere(new Once(),x=>x%2==0)!=2 || Solution.CountWhere(Array.Empty<int>(),x=>true)!=0)throw new Exception("count");try{Solution.CountWhere<int>(null!,x=>true);throw new Exception("null source");}catch(ArgumentNullException){}try{Solution.CountWhere(new[]{1},(Func<int,bool>)null!);throw new Exception("null predicate");}catch(ArgumentNullException){}}}
''',
'cs_enumerable': '''
sealed class Once : IEnumerable<long>{bool used;public IEnumerator<long> GetEnumerator(){if(used)throw new Exception("twice");used=true;yield return long.MinValue;yield return -1;yield return 4;}IEnumerator IEnumerable.GetEnumerator()=>GetEnumerator();}
class Program {static void Main(){if(Solution.MaxOrNull(new Once())!=4 || Solution.MaxOrNull(new long[]{long.MinValue})!=long.MinValue || Solution.MaxOrNull(Array.Empty<long>())!=null)throw new Exception("maximum");try{Solution.MaxOrNull(null!);throw new Exception("missing null check");}catch(ArgumentNullException){}}}
''',
'cs_cancel': '''
class Program {static async Task Main(){
if(await Solution.WithTimeout<int>(ct=>Task.FromResult(7),TimeSpan.FromSeconds(2),default)!=7)throw new Exception("value");
if(await Solution.WithTimeout<int>(ct=>Task.FromResult(9),TimeSpan.FromDays(30),default)!=9)throw new Exception("valid long timeout");
bool ended=false;try{await Solution.WithTimeout<int>(async ct=>{try{await Task.Delay(10000,ct);return 1;}finally{ended=true;}},TimeSpan.FromMilliseconds(30),default);throw new Exception("timeout missing");}catch(TimeoutException){}if(!ended)throw new Exception("orphan operation");
using var caller=new CancellationTokenSource();caller.CancelAfter(30);ended=false;
try{await Solution.WithTimeout<int>(async ct=>{try{await Task.Delay(10000,ct);return 1;}finally{ended=true;}},TimeSpan.FromSeconds(2),caller.Token);throw new Exception("caller cancellation missing");}catch(OperationCanceledException){}if(!ended)throw new Exception("orphan operation");
var original=new InvalidOperationException("original");try{await Solution.WithTimeout<int>(ct=>Task.FromException<int>(original),TimeSpan.FromSeconds(2),default);throw new Exception("failure missing");}catch(InvalidOperationException ex)when(ReferenceEquals(ex,original)){}
try{await Solution.WithTimeout<int>(ct=>throw original,TimeSpan.FromSeconds(2),default);throw new Exception("sync failure missing");}catch(InvalidOperationException ex)when(ReferenceEquals(ex,original)){}
try{await Solution.WithTimeout<int>(async ct=>{try{await Task.Delay(10000,ct);return 1;}finally{throw original;}},TimeSpan.FromMilliseconds(30),default);throw new Exception("cleanup failure missing");}catch(InvalidOperationException ex)when(ReferenceEquals(ex,original)){}
}}
'''}


def run(args, folder, image, command):
    name='bt-breadth-check-'+uuid.uuid4().hex
    cmd=['docker','run','--rm','--name',name,'--network','none','--read-only','--user','65534:65534',
         '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','128',
         '--memory','768m','--cpus','1','--tmpfs','/tmp:rw,exec,mode=1777,size=256m',
         '-e','HOME=/tmp','-e','DOTNET_CLI_HOME=/tmp','-e','DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1',
         '-v',str(folder.resolve())+':/src:ro', image,*command]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=65)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=15)
        return {'exit':124,'output':'Isolated execution exceeded 65 seconds.'}
    return {'exit':p.returncode,'output':(p.stdout+p.stderr)[-7000:]}


def verify(args):
    data=json.loads(args.results.read_text());args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for row in data['cases']:
        name=row['id'];answer=row.get('answer','')
        if name not in PY|CPP|RUST|CS and name!='js_limit':continue
        folder=args.output/(name+'-'+str(row.get('repeat',0)));folder.mkdir(exist_ok=True)
        blocks=re.findall(r'```[^\n]*\n([\s\S]*?)```',answer)
        item={'id':name,'repeat':row.get('repeat',0),'format_ok':bool(re.fullmatch(r'\s*```[^\n]*\n[\s\S]*?```\s*',answer)), 'checks':[]}
        if len(blocks)!=1:
            item.update(passed=False,error='expected one complete code block');results.append(item);continue
        code=blocks[0]
        if name in PY:
            code=('QUERY='+repr(code)+'\n' if name=='sql_null' else code+'\n')+PY[name]
            (folder/'test.py').write_text(code)
            item['checks'].append(run(args,folder,args.python,['python','-B','/src/test.py']))
        elif name in CPP:
            original=code
            if name=='m0_irq':
                # Declared by the prompt; this fixture simulates CMSIS for host behavior.
                (folder/'cmsis_compiler.h').write_text('#pragma once\n')
                code='#include <cstdint>\n#include <initializer_list>\nstatic uint32_t mock_mask;\nuint32_t __get_PRIMASK(){return mock_mask;}\nvoid __disable_irq(){mock_mask=1;}\nvoid __set_PRIMASK(uint32_t x){mock_mask=x;}\n'+code
                original='#include <cstdint>\nuint32_t __get_PRIMASK();\nvoid __disable_irq();\nvoid __set_PRIMASK(uint32_t);\n'+original
            (folder/'test.cpp').write_text(code+'\n'+CPP[name])
            item['checks'].append(run(args,folder,args.toolchain,['sh','-c','g++ -std=c++17 -Wall -Wextra -pedantic -fsanitize=undefined -fno-sanitize-recover=all -I/src /src/test.cpp -o /tmp/test && /tmp/test']))
            if name.startswith('m0_'):
                (folder/'target.cpp').write_text(original)
                item['checks'].append(run(args,folder,args.toolchain,['arm-none-eabi-g++','-std=c++17','-mcpu=cortex-m0','-mthumb','-fno-exceptions','-fno-rtti','-ffreestanding','-I/src','-c','/src/target.cpp','-o','/tmp/target.o']))
        elif name in RUST:
            (folder/'test.rs').write_text(code+'\n'+RUST[name])
            item['checks'].append(run(args,folder,args.toolchain,['sh','-c','rustc --edition=2021 /src/test.rs -o /tmp/test && /tmp/test']))
        elif name=='js_limit':
            (folder/'test.mjs').write_text(code+'\n'+JS)
            item['checks'].append(run(args,folder,args.toolchain,['node','/src/test.mjs']))
        elif name in CS:
            # Keep solution imports separate; the harness may import independently.
            (folder/'Solution.cs').write_text(code)
            (folder/'Program.cs').write_text(CS_COMMON+CS[name])
            (folder/'test.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable></PropertyGroup></Project>')
            (folder/'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            (folder/'test.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net8.0','framework':{'name':'Microsoft.NETCore.App','version':'8.0.0'}}}))
            # Invoke the compiler directly: offline BCL references need no NuGet
            # restore or writable SDK installation/global migration mutex.
            script = ('refs=""; for p in /usr/share/dotnet/packs/Microsoft.NETCore.App.Ref/8.0.*/ref/net8.0/*.dll; do refs="$refs -r:$p"; done; '
                      'dotnet exec /usr/share/dotnet/sdk/8.0.*/Roslyn/bincore/csc.dll -nologo -nullable:enable -target:exe -out:/tmp/test.dll $refs /src/Solution.cs /src/Program.cs '
                      '&& cp /src/test.runtimeconfig.json /tmp/ && dotnet /tmp/test.dll')
            item['checks'].append(run(args,folder,args.dotnet,['sh','-c',script]))
        item['passed']=item['format_ok'] and all(x['exit']==0 for x in item['checks'])
        results.append(item)
        (args.output/'verification.json').write_text(json.dumps(results,indent=2))
    print(json.dumps({'tested':len(results),'passed':sum(x['passed'] for x in results),'failed':[x['id'] for x in results if not x['passed']]}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--python',default='bitthink-docx:20261104');p.add_argument('--toolchain',default='bitthink-breadth-toolchain:20261104');p.add_argument('--dotnet',default='mcr.microsoft.com/dotnet/sdk:8.0')
    verify(p.parse_args())
