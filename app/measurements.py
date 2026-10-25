"""Seeded bounded errors and timestamped measurements; polling never resamples."""
from collections import deque
import random


class SensorBank:
    def __init__(self,sensors,seed):
        self.config={key:{'noise':0.,'delay_s':0.,'frozen':False} for key in sensors}
        self.buffers={key:deque(maxlen=4096) for key in sensors}
        # Separate streams keep one sensor's configuration from changing other errors.
        self.rng={key:random.Random(f'{seed}:{key}') for key in sensors}

    def capture(self,truth,now,bias,keys=None):
        for key,config in self.config.items():
            if keys is not None and key not in keys:continue
            buf=self.buffers[key]
            if config['frozen'] and buf:continue
            value=truth[key]+bias[key]+self.rng[key].uniform(-config['noise'],config['noise'])
            if buf and abs(buf[-1]['sample_time']-now)<1e-9:buf.pop()
            buf.append({'value':value,'sample_time':now})

    def readings(self,now,failed):
        values={};metadata={}
        for key,config in self.config.items():
            packet=next((p for p in reversed(self.buffers[key]) if p['sample_time']<=now-config['delay_s']+1e-9),None)
            age=None if packet is None else max(0.,now-packet['sample_time'])
            reason='failed' if key in failed else 'waiting' if packet is None else 'fresh' if age<=1e-9 else 'stale' if age>10 else 'delayed'
            values[key]=None if key in failed or packet is None else packet['value']
            metadata[key]={**config,'age_s':age,'sample_time':None if packet is None else packet['sample_time'],
                           'quality':reason,'usable':reason=='fresh','last_value':None if packet is None else packet['value']}
        return values,metadata

    def repair(self,key):
        self.config[key]={'noise':0.,'delay_s':0.,'frozen':False}
