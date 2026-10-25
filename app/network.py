"""Gucheng equivalent air network + synthetic dilute methane transport.

Published air resistance/geometry, equal exterior pressure, no natural head.
Gas is a passive dilute tracer; injected gas does not alter volumetric airflow.
No claim of CFD, field validation, or guaranteed observer enclosure.
"""
import csv
import math
from functools import lru_cache
from pathlib import Path
from .reference import linear_solve

SOURCE = 'https://doi.org/10.1371/journal.pone.0320326'
with (Path(__file__).parent/'data/gucheng-network.csv').open(encoding='utf-8-sig') as f:
    EDGES = {r['branch']: {'id':r['branch'], 'from':r['source_node'], 'to':r['target_node'],
             'R':float(r['R_N_s2_m8']), 'length':float(r['length_m']), 'area':float(r['area_m2'])}
             for r in csv.DictReader(f)}
INTERNAL = ('V2','V4','V5','V6','V7','V9')
EXTERIOR = ('V1','V3','V8','V10')
# Half of the incident published tunnel volume is allocated to each internal node.
# This is a lumping assumption, not a measured mixing volume.
VOLUMES = {n:sum(e['length']*e['area']/2 for e in EDGES.values() if n in (e['from'],e['to'])) for n in INTERNAL}
SOURCES = {'V2':0.,'V4':0.,'V5':.5,'V6':.35,'V7':.3,'V9':.2}
DEFAULT = {'fan_a':1.,'fan_b':1.,'resistance_e6':1.,'resistance_e5':1.,'gas':1.,'closed':False}

def fan(q, speed, which):
    a,b,c = (3255.2,10.727,.044) if which=='a' else (3372.4,9.703,.033)
    return a*speed**2+b*speed*q-c*q*q

def solve(parameters=None):
    p={**DEFAULT,**(parameters or {})}
    if set(p)!=set(DEFAULT):raise ValueError('Unknown network parameter')
    for k in DEFAULT:
        if k=='closed':
            if type(p[k]) is not bool:raise ValueError('closed must be boolean')
        elif not math.isfinite(p[k]) or not (.5<=p[k]<=1.2 if k.startswith('fan') else .25<=p[k]<=4):
            raise ValueError('Unsupported network parameter: '+k)
    return _solve(tuple(p[k] for k in DEFAULT))

@lru_cache(maxsize=2048)
def _solve(values):
    p=dict(zip(DEFAULT,values));r={k:e['R'] for k,e in EDGES.items()}
    r['e6']*=p['resistance_e6'];r['e5']*=p['resistance_e5']
    def loss(q,res):return res*q*abs(q)
    def residual(v):
        x,y,z=v;common=loss(x+y,r['e1']+r['e2']);out=loss(y+z,r['e7']+r['e9'])
        return [fan(x,p['fan_a'],'a')-common-loss(x,r['e6']+r['e8']),
                y if p['closed'] else fan(y+z,p['fan_b'],'b')-common-loss(y,r['e5'])-out,
                fan(y+z,p['fan_b'],'b')-loss(z,r['e3']+r['e4'])-out]
    v=[300.,0. if p['closed'] else 60.,320.]
    for iteration in range(80):
        f=residual(v)
        if max(map(abs,f))<1e-7:break
        jac=[[0.]*3 for _ in range(3)]
        for j in range(3):
            w=v[:];w[j]+=1e-4
            for i,t in enumerate(residual(w)):jac[i][j]=(t-f[i])/1e-4
        delta=linear_solve(jac,[-t for t in f]);alpha=1.
        while alpha>1e-9:
            w=[t+alpha*d for t,d in zip(v,delta)];x,y,z=w
            if min(x,z,x+y,y+z)>0 and max(map(abs,residual(w)))<max(map(abs,f)):
                v=w;break
            alpha/=2
        else:raise ArithmeticError('Unsupported operating point / line search failed')
    else:raise ArithmeticError('Air network did not converge')
    x,y,z=v
    q=dict(zip(EDGES,(x+y,x+y,z,z,y,x,y+z,x,y+z)))
    pressure={n:0. for n in EXTERIOR}
    for k in ('e1','e2','e3','e4','e6','e7'):
        e=EDGES[k];pressure[e['to']]=pressure[e['from']]-loss(q[k],r[k])
    balances={n:0. for n in INTERNAL};energy=[];heads={}
    for k,e in EDGES.items():
        head=fan(q[k],p['fan_a'],'a') if k=='e8' else fan(q[k],p['fan_b'],'b') if k=='e9' else 0.
        if k in ('e8','e9'):
            if head<=0:raise ArithmeticError('Nonpositive fan head unsupported')
            heads[k]=head
        if not (p['closed'] and k=='e5'):
            energy.append(pressure[e['from']]-pressure[e['to']]+head-loss(q[k],r[k]))
        for n,sign in ((e['from'],-1),(e['to'],1)):
            if n in balances:balances[n]+=sign*q[k]
    err=max(map(abs,energy));mass=max(map(abs,balances.values()))
    if err>1e-5 or mass>1e-8:raise ArithmeticError('Air residual tolerance exceeded')
    return {'q':q,'pressure':pressure,'head':heads,'resistance':r,'closed':p['closed'],
            'energy_residual_pa':err,'continuity_residual_m3s':mass,'iterations':iteration,
            'power_kw':sum(heads[k]*q[k]/.72/1000 for k in heads)}

def transport(air):
    incoming={n:[] for n in INTERNAL};out={n:0. for n in INTERNAL}
    for k,e in EDGES.items():
        q=air['q'][k];a,b=(e['from'],e['to']) if q>=0 else (e['to'],e['from']);q=abs(q)
        if b in incoming:incoming[b].append((a,q))
        if a in out:out[a]+=q
    return incoming,out

def steady(air,gas=1.):
    incoming,out=transport(air);matrix=[];rhs=[]
    for n in INTERNAL:
        matrix.append([(out[n] if n==m else 0)-sum(q for a,q in incoming[n] if a==m) for m in INTERNAL])
        rhs.append(SOURCES[n]*gas)
    return dict(zip(INTERNAL,linear_solve(matrix,rhs)))

def advance(c,air,gas,dt,max_step=5.):
    """Conservative explicit finite volumes, CFL <= .2, concentrations fractions."""
    if not math.isfinite(dt) or dt<0 or dt>3600:raise ValueError('dt outside [0,3600]')
    incoming,out=transport(air);c=dict(c)
    initial=sum(VOLUMES[n]*c[n] for n in INTERNAL);injected=0.;exhausted=0.
    step=min(max_step,min(.2*VOLUMES[n]/q for n,q in out.items() if q>0))
    count=max(1,math.ceil(dt/step));h=dt/count
    for _ in range(count):
        dc={n:(sum(q*c.get(a,0.) for a,q in incoming[n])+SOURCES[n]*gas-out[n]*c[n])*h/VOLUMES[n] for n in INTERNAL}
        # Boundary tracer flux; all supported exterior inflows are clean.
        for k,e in EDGES.items():
            q=air['q'][k];a,b=(e['from'],e['to']) if q>=0 else (e['to'],e['from'])
            if b in EXTERIOR:exhausted+=h*abs(q)*c.get(a,0.)
        injected+=h*sum(SOURCES.values())*gas
        c={n:c[n]+dc[n] for n in INTERNAL}
    final=sum(VOLUMES[n]*c[n] for n in INTERNAL)
    if any(not math.isfinite(v) or v<0 or v>.05 for v in c.values()):raise ArithmeticError('Dilute gas range exceeded')
    return c,{'stored_m3':final,'injected_m3':injected,'exhausted_m3':exhausted,
              'mass_residual_m3':final-initial-injected+exhausted,'substeps':count}

def values(c,air):
    return {**{'q_'+k:v for k,v in air['q'].items()},**{'c_'+n:100*v for n,v in c.items()}}

SENSORS={**{'q_'+k:{'name':'Расход '+k,'unit':'м³/с','tolerance':3.,'cost':1.,'repair_s':10.,'target':k} for k in ('e2','e5','e6','e7')},
         **{'c_'+n:{'name':'Метан '+n,'unit':'% об.','tolerance':.02,'cost':2.,'repair_s':30.,'target':n} for n in ('V5','V6','V7','V9')}}

def catalog():
    objects={'site':{'id':'site','kind':'ventilation-system','source':SOURCE,'license':'CC BY 4.0',
                     'description':'Equivalent Gucheng air network with synthetic dilute methane',
                     'links':list(EDGES)}}
    for n in (*INTERNAL,*EXTERIOR):
        objects[n]={'id':n,'kind':'boundary' if n in EXTERIOR else 'mixing-node',
                    'volume_m3':VOLUMES.get(n,0),'gas_source_m3_s':SOURCES.get(n,0),
                    'units':{'volume_m3':'m³','gas_source_m3_s':'m³ CH4/s','pressure':'Pa','methane':'% vol'},
                    'origin':{'volume':'half incident published geometry; lumping assumption','gas':'synthetic scenario'},
                    'links':[k for k,e in EDGES.items() if n in (e['from'],e['to'])]}
    for k,e in EDGES.items():
        objects[k]={**e,'kind':'fan-airway' if k in ('e8','e9') else 'airway','source':SOURCE,
                    'units':{'R':'Pa s²/m⁶','length':'m','area':'m²'},'links':[e['from'],e['to']]}
    for k,coefficients in (('e8',[3255.2,10.727,-.044]),('e9',[3372.4,9.703,-.033])):
        objects[k]['fan_curve']={'coefficients':coefficients,'formula':'a*n^2+b*n*Q+c*Q^2',
                                'coefficient_units':['Pa','Pa s/m³','Pa s²/m⁶'],
                                'speed_range':[.5,1.2],'origin':'coefficients from source; speed scaling assumed',
                                'efficiency':.72,'efficiency_origin':'synthetic assumption'}
    for k,s in SENSORS.items():objects['sensor-'+k]={'id':'sensor-'+k,'kind':'sensor',**s,'origin':'synthetic tolerance/cost/repair time','links':[s['target']]}
    from .spatial import enrich
    return enrich(objects)
