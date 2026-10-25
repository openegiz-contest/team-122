"""Finite hypothesis trajectories, not guaranteed intervals or probabilities.

Only public commands and measurements enter this module. Hidden plant state is
never passed in. Uniform weighting is an experimental design choice.
"""
import itertools
from .network import DEFAULT, INTERNAL, SENSORS, solve, steady, advance, values

TARGETS=('V5','V6','V7','V9')
GRID=(.5,1.,2.,4.)

def bounds(hypotheses):
    return {n:{'low':100*min(h['c'][n] for h in hypotheses),'high':100*max(h['c'][n] for h in hypotheses)} for n in INTERNAL}

def width(hypotheses):
    b=bounds(hypotheses)
    return sum(b[n]['high']-b[n]['low'] for n in TARGETS)

class Observer:
    def __init__(self):
        self.hypotheses=[]
        for resistance,gas in itertools.product(GRID,GRID):
            p={**DEFAULT,'resistance_e6':resistance,'gas':gas};a=solve(p)
            self.hypotheses.append({'p':p,'air':a,'c':steady(a,gas)})
        self.pool=self.hypotheses[:];self.conflict=False

    def step(self,dt,known):
        for h in self.hypotheses:
            h['p'].update(known);h['air']=solve(h['p'])
            h['c'],_=advance(h['c'],h['air'],h['p']['gas'],dt)

    def restart_uncertainty(self,known):
        # A declared disturbance time, never its hidden amplitude, is observable.
        # Keep all pre-disturbance gas trajectories and cross with new parameters.
        # Deduplicate states and bound bank size explicitly.
        states=[]
        for h in self.pool:
            if h['c'] not in states:states.append(h['c'])
        states=states[:16]
        self.hypotheses=[]
        for c,(resistance,gas) in itertools.product(states,itertools.product(GRID,GRID)):
            p={**DEFAULT,**known,'resistance_e6':resistance,'gas':gas}
            self.hypotheses.append({'p':p,'air':solve(p),'c':dict(c)})
        self.pool=self.hypotheses[:]

    def observe(self,readings,metadata):
        valid={k:v for k,v in readings.items() if metadata[k]['usable']}
        candidates=[h for h in self.hypotheses if all(abs(values(h['c'],h['air'])[k]-v)<=SENSORS[k]['tolerance']+1e-9 for k,v in valid.items())]
        self.conflict=not candidates
        self.pool=candidates or self.hypotheses[:]
        # Preserve information acquired earlier when a channel subsequently fails.
        # Only a declared disturbance can expand the parameter bank again.
        if candidates:self.hypotheses=candidates
        return bounds(self.pool)

    def forecast(self,horizon):
        return [{'p':h['p'],'air':h['air'],'c':advance(h['c'],h['air'],h['p']['gas'],horizon)[0]} for h in self.pool]

    def rank(self,missing,horizon):
        if self.conflict:return [],None
        future=self.forecast(horizon);base=width(future);rank=[]
        for key in missing:
            s=SENSORS[key]
            if s['repair_s']>horizon:continue
            at_repair=[values(advance(h['c'],h['air'],h['p']['gas'],s['repair_s'])[0],h['air'])[key] for h in self.pool]
            # Uniform hypothetical outcomes; ±2 tolerance includes the possible
            # error on both the simulated outcome and the candidate reading.
            conditional=[]
            for value in at_repair:
                group=[f for v,f in zip(at_repair,future) if abs(v-value)<=2*s['tolerance']+1e-9]
                conditional.append(width(group))
            gain=max(0.,base-sum(conditional)/len(conditional))
            rank.append({'sensor':key,'gain':gain,'score':gain/s['cost'],'repair_s':s['repair_s'],'cost':s['cost']})
        return sorted(rank,key=lambda r:(-r['score'],r['sensor'])),bounds(future)
