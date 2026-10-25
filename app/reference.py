"""Reproduction of a published steady network; no fit to comparison flows.

Jia, Ma, Gao (2025), doi:10.1371/journal.pone.0320326, CC BY 4.0.
Equal external reduced pressures and zero additional natural head are assumptions.
"""
import csv
import json
from pathlib import Path


def linear_solve(matrix, rhs):
    a=[list(row)+[value] for row,value in zip(matrix,rhs)]
    n=len(a)
    for k in range(n):
        pivot=max(range(k,n),key=lambda i:abs(a[i][k]))
        a[k],a[pivot]=a[pivot],a[k]
        if abs(a[k][k])<1e-12:
            raise ArithmeticError("Singular network Jacobian")
        scale=a[k][k]
        a[k]=[v/scale for v in a[k]]
        for i in range(n):
            if i!=k:
                scale=a[i][k]
                a[i]=[x-scale*y for x,y in zip(a[i],a[k])]
    return [row[-1] for row in a]


def run(initial=(300.,60.,320.)):
    with (Path(__file__).parent/'data/gucheng-network.csv').open(encoding='utf-8-sig',newline='') as handle:
        rows=list(csv.DictReader(handle))
    r={row['branch']:float(row['R_N_s2_m8']) for row in rows}
    def ha(q):return 3255.2+10.727*q-.044*q*q
    def hb(q):return 3372.4+9.703*q-.033*q*q
    def loss(q,resistance):return resistance*q*abs(q)
    def residual(v):
        x,y,z=v
        common=loss(x+y,r['e1']+r['e2'])
        out=loss(y+z,r['e7']+r['e9'])
        return [ha(x)-common-loss(x,r['e6']+r['e8']),
                hb(y+z)-common-loss(y,r['e5'])-out,
                hb(y+z)-loss(z,r['e3']+r['e4'])-out]
    v=list(initial)
    for iteration in range(80):
        f=residual(v)
        if max(map(abs,f))<1e-7:break
        jac=[[0.]*3 for _ in range(3)]
        for j in range(3):
            shifted=v[:];shifted[j]+=1e-4
            for i,value in enumerate(residual(shifted)):jac[i][j]=(value-f[i])/1e-4
        delta=linear_solve(jac,[-x for x in f])
        alpha=1.
        while alpha>1e-8:
            candidate=[x+alpha*d for x,d in zip(v,delta)]
            if min(candidate)>0 and max(map(abs,residual(candidate)))<max(map(abs,f)):
                v=candidate;break
            alpha/=2
        else:raise ArithmeticError("Network line search failed")
    else:raise ArithmeticError("Network did not converge")
    x,y,z=v
    qs=dict(zip(('e1','e2','e3','e4','e5','e6','e7','e8','e9'),(x+y,x+y,z,z,y,x,y+z,x,y+z)))
    pressures={'V1':0.,'V3':0.,'V8':0.,'V10':0.}
    for edge in ('e1','e2','e3','e4','e6','e7'):
        row=next(row for row in rows if row['branch']==edge)
        pressures[row['target_node']]=pressures[row['source_node']]-loss(qs[edge],r[edge])
    balances={node:0. for node in ('V2','V4','V5','V6','V7','V9')}
    energy=[];comparison=[]
    for row in rows:
        edge=row['branch'];q=qs[edge];head=ha(q) if edge=='e8' else hb(q) if edge=='e9' else 0
        energy.append(pressures[row['source_node']]-pressures[row['target_node']]+head-loss(q,r[edge]))
        if row['source_node'] in balances:balances[row['source_node']]-=q
        if row['target_node'] in balances:balances[row['target_node']]+=q
        published=float(row['comparison_q_m3_s'])
        comparison.append({'branch':edge,'from':row['source_node'],'to':row['target_node'],
                           'R':r[edge],'published_q':published,'computed_q':q,'relative_difference':q/published-1})
    return {'source':'https://doi.org/10.1371/journal.pone.0320326','license':'CC BY 4.0',
            'kind':'conditional steady reproduction, not independent field validation',
            'assumptions':['equal exterior reduced pressures','zero additional natural head','rounded published coefficients'],
            'iterations':iteration,'max_energy_residual_pa':max(map(abs,energy)),
            'max_continuity_residual_m3s':max(map(abs,balances.values())),
            'max_relative_flow_difference':max(abs(row['relative_difference']) for row in comparison),
            'branches':comparison,'node_pressures_pa':pressures,
            'does_not_validate':['methane sources','gas mixing volumes','dynamic sensor errors','industrial safety']}


if __name__=='__main__':
    result=run()
    Path('docs/reference-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('branches','node_pressures_pa')},ensure_ascii=False,indent=2))
