"""Standalone scientific figures from audited JSON, with explicit denominators."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(); p.add_argument('--direction',type=Path,required=True)
    p.add_argument('--stack',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); a.output.mkdir(parents=True,exist_ok=True)
    d=json.loads(a.direction.read_text()); s=json.loads(a.stack.read_text())
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(12,9),layout='constrained')
    groups=d['groups']; all_=groups['all']
    cm=np.array(all_['confusion_rows_truth_columns_prediction_negative_hold_positive'])
    norm=cm/np.maximum(cm.sum(axis=1,keepdims=True),1)
    ax=axes[0,0]; ax.imshow(norm,vmin=0,vmax=1,cmap='Blues')
    for i in range(3):
        for j in range(3): ax.text(j,i,f'{cm[i,j]}\n{norm[i,j]:.1%}',ha='center',va='center',color='white' if norm[i,j]>.6 else 'black')
    ax.set(xticks=range(3),yticks=range(3),xticklabels=['negative','hold','positive'],yticklabels=['negative','hold','positive'],xlabel='Jev choice',ylabel='Reference class',title='Per-axis confusion (row normalized)')
    keys=['<0.5','0.5-2','2-5','5-20','>=20']; ax=axes[0,1]
    for i,key in enumerate(keys):
        g=groups.get('error:'+key)
        if not g: continue
        value=g['axis_correct']/g['axes']; ax.bar(i,value,color='#2878a8')
        ax.text(i,value+.02,f'{value:.1%}\nn={g["decisions"]}',ha='center',fontsize=9)
    ax.set(xticks=range(5),xticklabels=keys,ylim=(0,1.15),xlabel='Position error (mm)',ylabel='Axis accuracy',title='Accuracy vs error; observed trajectory distribution')
    keys_stage=['approach','descend','lift','carry','lower','withdraw']; ax=axes[1,0]
    for i,key in enumerate(keys_stage):
        g=groups['stage:'+key]; v=g['axis_correct']/g['axes']; ax.bar(i,v,color='#35826b')
        ax.text(i,v+.02,f'{v:.1%}',ha='center',fontsize=9)
    ax.set(xticks=range(6),xticklabels=keys_stage,ylim=(0,1.1),ylabel='Axis accuracy',title='Six supplied stages (not model-planned)')
    ax.tick_params(axis='x',rotation=25)
    ax=axes[1,1]
    for key in keys:
        values=[(amp,d['amplitudes'].get(f'{key}:{amp:g}mm')) for amp in (1,2,5,10)]
        values=[(amp,g) for amp,g in values if g]
        if values: ax.plot([v[0] for v in values],[v[1]['progress']/v[1]['n'] for v in values],marker='o',label=key+' mm')
    ax.set(xlabel='Requested amplitude (mm)',ylabel='Fraction reducing target distance',ylim=(-.04,1.04),title='Paired attempts; rejected commands remain in denominator')
    ax.legend(title='Initial error',fontsize=8)
    fig.suptitle(f'Embodied: {all_["decisions"]} decisions / {d["completed_runs"]} seed trajectories; hold tolerance 0.5 mm\nOracle state, supplied stage/goal; snapshots within each trajectory are correlated',fontsize=12)
    for ext in ('png','svg'): fig.savefig(a.output/f'direction-quality.{ext}',dpi=180)
    plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    eps=sorted(s['episodes'],key=lambda e:int(Path(e['folder']).name.split('-')[-1]))
    for i,e in enumerate(eps):
        axes[0].bar(i,e['steps'],color='#35826b' if e['native']['success'] else '#bb4433')
    axes[0].axhline(550,color='black',ls='--',label='Native 550-step limit')
    axes[0].set(xlabel='Fresh episode index',ylabel='Native physics control steps',title=f'Native successes: {s["successes"]}/{s["completed"]}')
    axes[0].legend()
    stages=['approach','descend','lift','carry','lower','retreat']
    for i,key in enumerate(stages):
        g=s['groups'].get('stage:'+key)
        if not g: continue
        axes[1].bar(i,g['actual_distance_decreased']/g['decisions'],color='#2878a8')
        axes[1].text(i,1.01,f'n={g["decisions"]}',ha='center',fontsize=8)
    axes[1].set(xticks=range(6),xticklabels=stages,ylim=(0,1.12),ylabel='Fraction reducing local distance',title='Actual execution; orientation may also change')
    axes[1].tick_params(axis='x',rotation=25)
    fig.suptitle('RoboDojo native stack: two layouts, repeated fresh episodes\nOracle geometry and external stages/orientation/gripper; Jev selects XYZ signs',fontsize=12)
    for ext in ('png','svg'): fig.savefig(a.output/f'stack-execution.{ext}',dpi=180)
    plt.close(fig)


if __name__=='__main__': main()
