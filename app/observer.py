"""Bounded interval observer, retaining previous information after sensor loss.

Coverage is conditional: R/G within declared ranges, piecewise constant over a
simulation step, fresh measurement errors within tolerance, and this model topology.
No probability of physical states or unconditional fault detection is claimed.
"""
import itertools
from .model import Parameters,airflow,gas_step,SENSORS,GAS_SOURCES,VOLUMES

R_RANGE=(.65,2.5)
G_RANGE=(.5,2.)
QUANTITIES=('qa','qb','ql','qt','ca','cb','cr')


def interval(lo,hi):
    return {'low':lo,'high':hi,'mean':(lo+hi)/2}


class IntervalObserver:
    def __init__(self,initial=None):
        self.gas={key:interval(initial[i],initial[i]) if initial is not None else interval(0.,100.)
                  for i,key in enumerate(('ca','cb'))}
        self.faults=[]
        self.flows={}

    def intersect(self,bounds,lo,hi,key,now):
        lower=max(bounds['low'],lo);upper=min(bounds['high'],hi)
        if lower>upper+1e-9:
            issue={'quantity':key,'time':now,'predicted':[bounds['low'],bounds['high']], 'measured_interval':[lo,hi]}
            if not self.faults or self.faults[-1]['quantity']!=key:
                self.faults.append(issue);self.faults=self.faults[-12:]
            return bounds
        return interval(lower,max(lower,upper))

    def update(self,dt,fan,leakage,readings,metadata,now):
        # Extrema of each flow occur at corners for this series/parallel network.
        corners=[airflow(Parameters(fan=fan,leakage=leakage,resistance_a=ra,resistance_b=rb))
                 for ra,rb in itertools.product(R_RANGE,repeat=2)]
        flows={key:interval(min(x[key] for x in corners),max(x[key] for x in corners)) for key in ('qa','qb','ql','qt')}
        for key in ('qa','qb','qt'):
            if metadata[key]['usable']:
                tol=SENSORS[key]['tolerance'];value=readings[key]
                flows[key]=self.intersect(flows[key],value-tol,value+tol,key,now)
        # Interval constraint propagation of QT=QA+QB+QL. Overapproximation keeps
        # unknown correlations rather than inventing precision from grid points.
        for _ in range(3):
            for key,others in (('qt',('qa','qb','ql')),):
                flows[key]=self.intersect(flows[key],sum(flows[k]['low'] for k in others),sum(flows[k]['high'] for k in others),key,now)
            for key in ('qa','qb','ql'):
                others=[k for k in ('qa','qb','ql') if k!=key]
                flows[key]=self.intersect(flows[key],max(0.,flows['qt']['low']-sum(flows[k]['high'] for k in others)),
                                          flows['qt']['high']-sum(flows[k]['low'] for k in others),key,now)
        for key,suffix in (('ca','a'),('cb','b')):
            q=flows['q'+suffix];prior=self.gas[key]
            predicted=interval(gas_step(prior['low'],q['high'],GAS_SOURCES[suffix]*G_RANGE[0],VOLUMES[suffix],dt),
                               gas_step(prior['high'],q['low'],GAS_SOURCES[suffix]*G_RANGE[1],VOLUMES[suffix],dt))
            if metadata[key]['usable']:
                tol=SENSORS[key]['tolerance'];value=readings[key]
                predicted=self.intersect(predicted,max(0.,value-tol),min(100.,value+tol),key,now)
            self.gas[key]=predicted
        self.flows=flows
        # A zero-storage mixing junction is a convex combination, including clean bypass.
        # A broad bound is used instead of a midpoint that loses unknown correlations.
        ga,gb=GAS_SOURCES['a'],GAS_SOURCES['b']
        lower=((flows['qa']['low']+ga*G_RANGE[0])*self.gas['ca']['low']+
               (flows['qb']['low']+gb*G_RANGE[0])*self.gas['cb']['low'])/(flows['qt']['high']+(ga+gb)*G_RANGE[1])
        upper=((flows['qa']['high']+ga*G_RANGE[1])*self.gas['ca']['high']+
               (flows['qb']['high']+gb*G_RANGE[1])*self.gas['cb']['high'])/(flows['qt']['low']+(ga+gb)*G_RANGE[0])
        cr=interval(max(0.,lower),min(upper,max(self.gas['ca']['high'],self.gas['cb']['high'])))
        return {**flows,**{k:dict(v) for k,v in self.gas.items()},'cr':cr}

    @property
    def conflict(self):return bool(self.faults)


def rank_measurements(estimate,missing,costs):
    """Current CH4 width objective; finite uniform quadrature is a design heuristic.

    Flow restoration cannot retrospectively tighten the independent concentration
    intervals in this observer, so its immediate gain is zero. A forecasting task
    would require a different objective. No physical probabilities are assumed.
    """
    width=sum(estimate[key]['high']-estimate[key]['low'] for key in ('ca','cb'))
    rows=[]
    for key in sorted(missing):
        gains=[]
        if key in ('ca','cb'):
            e=estimate[key];tol=SENSORS[key]['tolerance']
            for i in range(25):
                true=e['low']+(e['high']-e['low'])*i/24
                for error in (-tol,0.,tol):
                    measurement=true+error
                    residual=max(0.,min(e['high'],measurement+tol)-max(e['low'],measurement-tol))
                    gains.append(max(0.,e['high']-e['low']-residual))
        else:gains=[0.]
        gain=sum(gains)/len(gains)
        rows.append({'sensor':key,'gain':gain,'score':gain/costs[key], 'residual':width-gain,'cost':costs[key],
                     'worst_gain':min(gains),'best_gain':max(gains),
                     'reason':'direct_current_methane_interval' if key.startswith('c') else 'no_immediate_CH4_gain_in_interval_observer'})
    return sorted(rows,key=lambda r:(-r['score'],r['sensor']))
