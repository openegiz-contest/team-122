"""Metric realization, NOT a surveyed Gucheng plan. Published lengths/areas preserved."""
import math

COORDS={
 'V1':(0,0,0),'V2':(0,0,-500),'V5':(3000,0,-500),'V7':(8000,0,-500),'V8':(8000,0,0),
 'V3':(-2000,3910,0),'V4':(-2000,3910,-500),'V6':(3000,3910,-500),'V9':(6000,3910,-500),'V10':(6000,3910,0)}

def enrich(objects):
    """Attach explicit provenance and local metric geometry to the shared catalog."""
    objects['site']['spatial']={
        'crs':'local engineering XYZ, metres; no geographic registration',
        'origin':'synthetic orthogonal realization of the published equivalent network',
        'surveyed':False,'coordinate_units':'m','assumed_depth_m':500,
        'assumptions':['Exterior nodes are placed on z=0; internal nodes on z=-500 m.',
                       '500 m boundary branches are represented as vertical shafts by design, not source identification.',
                       'This is one length-preserving realization, not reconstruction of actual headings.',
                       'Square section shape inferred from area; actual shape is unknown.',
                       'No natural ventilation head is added; hydraulic assumptions are unchanged.'],
        'bounds_m':{'x':[-2000,8000],'y':[0,3910],'z':[-500,0]},
        'source_dimensions':['branch length','cross-sectional area'],
        'synthetic_dimensions':['XYZ coordinates','orientation','depth','section shape']}
    for name,xyz in COORDS.items():
        objects[name]['spatial']={'xyz_m':list(xyz),'origin':'synthetic length-preserving layout','surveyed':False}
    for name,obj in objects.items():
        if obj['kind'] not in ('airway','fan-airway'):continue
        a,b=COORDS[obj['from']],COORDS[obj['to']]
        length=math.dist(a,b)
        if abs(length-obj['length'])>1e-8:raise ValueError('Spatial length mismatch: '+name)
        obj['spatial']={'centerline_m':[list(a),list(b)],'length_m':length,
                        'length_error_m':length-obj['length'],'square_section_side_m':math.sqrt(obj['area']),
                        'volume_m3':length*obj['area'],'coordinate_origin':'synthetic',
                        'length_area_origin':'published table 4','surveyed':False}
    for obj in objects.values():
        if obj['kind']!='sensor':continue
        target=objects[obj['target']]['spatial']
        xyz=target.get('xyz_m')
        if xyz is None:xyz=[(a+b)/2 for a,b in zip(*target['centerline_m'])]
        obj['spatial']={'xyz_m':xyz,'origin':'target node or branch midpoint; synthetic mounting position','surveyed':False}
    return objects
