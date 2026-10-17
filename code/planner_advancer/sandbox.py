"""Execute planner-authored processing without mounting simulator state or keys."""
from pathlib import Path
import subprocess
import os

PYTHON='/root/miniconda3/envs/isaacsim5.1'
ROBOT='/root/yekangjie/project/robodojo-jev/robodojo/Assets/Robots/x5'


def execute(workspace,inputs,output,command,readonly=False,timeout=150):
    workspace,inputs,output=map(lambda p:Path(p).resolve(),[workspace,inputs,output])
    output.mkdir(parents=True,exist_ok=True)
    for name in ('.home','.tmp','.cache','site-packages'):
        (workspace/name).mkdir(exist_ok=True)
    argv=['bwrap','--die-with-parent','--unshare-pid','--unshare-ipc','--clearenv']
    for path in ('/usr','/lib','/lib64','/bin','/sbin','/etc/ssl','/etc/ld.so.cache','/etc/resolv.conf'):
        if Path(path).exists():
            argv+=['--ro-bind',path,path]
    python_path='/work/site-packages'
    if os.environ.get('ROBO_PERCEPTION_TOOLS')=='1':
        assets=Path(__file__).resolve().parents[1]/'runs/company2-20261018/perception-tools'
        helper=Path(__file__).with_name('optional_perception.py')
        for required in [assets/'site-packages',assets/'weights/loftr_indoor_ds_new.ckpt',
                         assets/'weights/sam_vit_b_01ec64.pth',helper]:
            if not required.exists():
                raise RuntimeError('Optional RGB tool asset missing: '+str(required))
        argv+=['--dir','/perception','--ro-bind',str(assets/'site-packages'),'/perception/site-packages',
               '--ro-bind',str(assets/'weights'),'/perception/weights',
               '--ro-bind',str(helper),'/perception/optional_perception.py',
               '--setenv','CUDA_VISIBLE_DEVICES','']
        python_path+=':/perception:/perception/site-packages'
    argv+=['--dir','/root','--dir','/root/miniconda3','--dir','/root/miniconda3/envs',
           '--ro-bind',PYTHON,PYTHON,'--ro-bind',ROBOT,'/robot',
           '--proc','/proc','--dev','/dev',
           '--ro-bind' if readonly else '--bind',str(workspace),'/work',
           '--ro-bind',str(inputs),'/input','--bind',str(output),'/output',
           '--setenv','PATH',PYTHON+'/bin:/usr/bin:/bin',
           '--setenv','HOME','/output/.home','--setenv','TMPDIR','/output/.tmp',
           '--setenv','XDG_CACHE_HOME','/output/.cache','--setenv','MPLCONFIGDIR','/output/.cache/mpl',
           '--setenv','PYTHONPATH',python_path,
           '--setenv','HTTPS_PROXY','http://127.0.0.1:7897',
           '--setenv','HTTP_PROXY','http://127.0.0.1:7897',
           '--chdir','/work','/bin/bash','-c',command]
    for name in ('.home','.tmp','.cache'):
        (output/name).mkdir(exist_ok=True)
    result=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
    return dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)
