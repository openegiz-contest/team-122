"""Predeclared counterfactual evaluation of current-interval measurement value."""
import copy
import itertools
import json
from pathlib import Path
import random
import statistics
import time
from .model import Twin,SENSORS

MASKS={'loss_a':('qa','ca'),'loss_b':('qb','cb'),'methane_pair':('ca','cb'),'all':tuple(SENSORS)}
COSTS={'equal':dict.fromkeys(SENSORS,1.),'nominal':{k:v['cost'] for k,v in SENSORS.items()},
       'ca_expensive':{'qa':2.,'qb':2.,'qt':1.,'ca':6.,'cb':1.}}


def evaluate(t):
    if t.snapshot['conflict']:raise AssertionError('Cannot rank a conflicting state')
    before=t.snapshot['width'];ranks=t.snapshot['rankings']
    choices=[r['sensor'] for r in ranks]
    effects={}
    for key in choices:
        clone=copy.deepcopy(t)
        clone.command({'action':'restore','sensor':key})
        effects[key]={'gain':before-clone.snapshot['width'],
                      'per_cost':(before-clone.snapshot['width'])/t.costs[key]}
    chosen=ranks[0]['sensor']
    fixed=next(key for key in ('ca','cb','qa','qb','qt') if key in choices)
    simple=min(choices,key=lambda key:(-(t.snapshot['estimate'][key]['high']-t.snapshot['estimate'][key]['low'])/t.costs[key]
                                       if key.startswith('c') else 0,key))
    return {'selected_sensor':chosen,'fixed_sensor':fixed,'simple_sensor':simple,
            'selected':effects[chosen]['per_cost'],'fixed_priority':effects[fixed]['per_cost'],
            'simple_width_per_cost':effects[simple]['per_cost'],
            'random_expected':statistics.mean(v['per_cost'] for v in effects.values()),
            'oracle':max(v['per_cost'] for v in effects.values()),'before_width':before,
            'predicted_gain':ranks[0]['gain'],'actual_gain':effects[chosen]['gain'],'effects':effects}


def summary(records):
    strategies=('selected','fixed_priority','simple_width_per_cost','random_expected','oracle')
    return {'cases':len(records),'mean':{key:statistics.mean(r[key] for r in records) for key in strategies},
            'worst':{key:min(r[key] for r in records) for key in strategies},
            'mean_oracle_regret':statistics.mean(r['oracle']-r['selected'] for r in records),
            'gain_prediction_mae_pp':statistics.mean(abs(r['predicted_gain']-r['actual_gain']) for r in records),
            'versus':{key:{'better':sum(r['selected']>r[key]+1e-9 for r in records),
                           'equal':sum(abs(r['selected']-r[key])<=1e-9 for r in records),
                           'worse':sum(r['selected']<r[key]-1e-9 for r in records)}
                      for key in ('fixed_priority','simple_width_per_cost')}}


def stress_tests():
    records=[]
    for blind in (False,True):
        for fault in ('inside_switch','outside','bias','delay','freeze'):
            t=Twin(seed=701);t.tick(60)
            if blind:t.command({'action':'scenario','name':'blind_all'})
            if fault=='inside_switch':t.command({'action':'parameter','name':'gas_a','value':1.8})
            else:t.command({'action':'scenario','name':{'outside':'outside','bias':'bias_ca','delay':'delay_ca','freeze':'freeze_ca'}[fault]})
            for _ in range(30):t.tick(10)
            covered=all(t.snapshot['estimate'][key]['low']-1e-9<=t.truth[key]<=t.snapshot['estimate'][key]['high']+1e-9 for key in ('ca','cb'))
            records.append({'all_channels_failed':blind,'fault':fault,'conflict_detected':t.snapshot['conflict'],
                            'truth_inside_interval':covered,'used_channels':t.snapshot['quality']['used_channels']})
    return records


def run(quick=False):
    started=time.perf_counter();records=[];coverage_checks=0;coverage_failures=0
    parameters=list(itertools.product((.8,1.9),(.9,2.1),(.7,1.7),(.65,1.8)))
    if quick:parameters=parameters[:2]
    for case_id,(ra,rb,ga,gb) in enumerate(parameters):
        for (mask_name,mask),fan,horizon,noise in itertools.product(MASKS.items(),(1.,.65),(30,120),(0.,.5)):
            t=Twin(seed=1000+case_id)
            for name,value in {'resistance_a':ra,'resistance_b':rb,'gas_a':ga,'gas_b':gb,'fan':fan}.items():
                t.command({'action':'parameter','name':name,'value':value})
            if noise:t.command({'action':'scenario','name':'noise'})
            for _ in range(6):t.tick(10)
            for key in mask:t.command({'action':'fail','sensor':key})
            for _ in range(horizon//10):
                t.tick(10);coverage_checks+=1
                if not all(t.snapshot['estimate'][key]['low']-1e-9<=t.truth[key]<=t.snapshot['estimate'][key]['high']+1e-9 for key in ('ca','cb')):
                    coverage_failures+=1
            for cost_name,costs in COSTS.items():
                scenario=copy.deepcopy(t)
                for key,value in costs.items():scenario.command({'action':'cost','sensor':key,'value':value})
                row=evaluate(scenario)
                records.append({**row,'case_id':case_id,'parameters':vars(scenario.params),
                                'mask':mask_name,'horizon_s':horizon,'noise_fraction_of_tolerance':noise,'cost_profile':cost_name})
    groups={name:{value:summary([r for r in records if str(r[name])==value])
                  for value in sorted({str(r[name]) for r in records})} for name in ('mask','cost_profile','noise_fraction_of_tolerance','horizon_s')}
    return {'model_version':'bounded-interval-v2','model_signature':Twin.model_signature(),'design':
            '16 held-out continuous parameter combinations x 4 masks x 2 fan regimes x 2 horizons x 2 noise profiles x 3 cost profiles; no outcome-based selection',
            'metric':'Observed current CH4 interval width reduction in percentage points / abstract restoration cost',
            'counterfactual':'Every restoration starts from a deep copy of exactly the same state and RNG streams; other channels are not resampled',
            'repair_assumption':'Restored channel obtains a fresh unbiased noiseless simulator reading; observer retains its stated tolerance',
            'summary':summary(records),'groups':groups,'coverage':{'checks':coverage_checks,'failures':coverage_failures,
                'scope':'empirical check inside declared bounds and bounded errors, not a statistical confidence level'},
            'stress_tests':stress_tests(),'runtime_seconds':time.perf_counter()-started,
            'limitations':['No field calibration or physical probabilities','Related cases are not independent field observations',
                           'Current methane width objective assigns zero immediate value to flow-only restoration',
                           'No crew logistics or real economic cost','Out-of-bound faults can escape detection without measurements'],
            'records':records}


if __name__=='__main__':
    result=run()
    Path('docs/evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','groups')},ensure_ascii=False,indent=2))
