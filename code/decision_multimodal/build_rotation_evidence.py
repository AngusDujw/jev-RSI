"""Assemble the local served evidence page from untouched exported robot calls."""
import argparse
import json
from pathlib import Path
import shutil


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--preparation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(exist_ok=True,parents=True)
    shutil.copytree(args.source,args.output,dirs_exist_ok=True)
    data=json.loads((args.source/'evidence.json').read_text())
    assert len(data['audit']['episodes'])==9
    data['planner']=dict(prompt=(args.preparation/'planner-prompt.txt').read_text(),
        plan=json.loads((args.preparation/'pro-plan/plan.json').read_text()))
    (args.output/'evidence.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    (args.output/'audit.json').write_text(json.dumps(data['audit'],indent=2)+'\n')
    shutil.copyfile(Path(__file__).with_name('rotation_evidence.html'),args.output/'index.html')
    report=Path(__file__).with_name('LIBERO_ROTATION_RESULTS.md')
    if report.is_file():shutil.copyfile(report,args.output/'report.md')
    print(args.output/'index.html')


if __name__=='__main__':main()
