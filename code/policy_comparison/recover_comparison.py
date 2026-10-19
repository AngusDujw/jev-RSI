"""Complete the originally requested comparison using fresh missing-slot trials."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import signal
import sys

import run_batch as batch


def selected(mode,task,trial,layout):
    stem=f'{mode}-{task}-trial{trial}-layout{layout}'
    for run in sorted(batch.ARTIFACT_ROOT.glob(stem+'*')):
        status=run/'status.json'
        if not status.exists():continue
        row=json.loads(status.read_text())
        if row.get('infrastructure_interrupted'):continue
        if (row.get('native') or {}).get('complete') is True:return row
        # A started model-policy failure is retained as a failed trial. Previous
        # interrupted infrastructure slots are replaced once, never resumed.
        if mode=='decisions' and (run/'controller/run.json').exists() and row.get('status') in ('failed','controller_finished'):
            return row
        if '-completion-' in run.name and (run/'controller/run.json').exists() and row.get('status') in ('failed','controller_finished'):
            return row
    return None


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recovery',default='completion-20261019b')
    parser.add_argument('--parallel',type=int,choices=(1,2,3),default=3)
    args=parser.parse_args()
    signal.signal(signal.SIGINT,lambda *_:batch.STOP.set())
    signal.signal(signal.SIGTERM,lambda *_:batch.STOP.set())
    batch.validate_store()
    sys.path.insert(0,str(batch.ROOT/'official_runtime'))
    report=dict(luna=[],decisions=[],original_attempts_preserved=True)
    for mode,layouts in (('luna',[0,1,0]),('decisions',[0,1,0,1,0])):
        if batch.STOP.is_set():break
        def slot(task,gpu,trial,layout):
                if batch.STOP.is_set():return
                row=selected(mode,task,trial,layout)
                if row is None:
                    suffix=args.recovery
                    if (batch.ARTIFACT_ROOT/f'{mode}-{task}-trial{trial}-layout{layout}-{suffix}').exists():
                        raise RuntimeError('Completion attempt already exists; inspect rather than replay')
                    row=batch.run_one(task,layout,(trial-1)*2+gpu,mode,trial,recovery=suffix)
                with batch.LOCK:
                    report[mode].append(row)
                    (batch.ARTIFACT_ROOT/'comparison_completion_status.json').write_text(json.dumps(report,indent=2)+'\n')
                if row.get('infrastructure_interrupted'):
                    raise RuntimeError('Infrastructure interruption is not a completed trial slot')
                if not (batch.ARTIFACT_ROOT/Path(row['remote']).name/'controller/run.json').exists():
                    # Do not terminate another active episode after setup failure.
                    raise RuntimeError('This slot failed before observations; other task continues')
        # A shared queue avoids serializing all repeats of one task. Heavy native
        # startup remains serialized by run_batch.STARTUP; admission caps RAM/GPU.
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            failures=[]
            futures=[pool.submit(slot,task,gpu,trial,layout)
                for trial,layout in enumerate(layouts,1)
                for gpu,task in enumerate(('stack_blocks','classify_objects'))]
            for future in as_completed(futures):
                try:future.result()
                except Exception as error:failures.append(str(error))
            if failures:raise RuntimeError('; '.join(failures))
        if len(report[mode]) != len(layouts)*2 or any(row.get('infrastructure_interrupted') for row in report[mode]):
            raise RuntimeError('Phase barrier: all valid slots must finish before next model')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
