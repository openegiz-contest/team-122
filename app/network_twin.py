import copy
import hashlib
import math
import uuid
from pathlib import Path
from .network import DEFAULT, EDGES, INTERNAL, SENSORS, SOURCES, VOLUMES, solve, steady, advance, values, catalog
from .network_observer import Observer, TARGETS
from .measurements import SensorBank

SCENARIOS={
 'fan':('Вентилятор A · 80%','Снижение напора e8 → перераспределение потоков → изменение выноса метана'),
 'resistance':('Сопротивление e6 ×2','Меньше воздуха через e6 → меняются e5 и e7 → метан V7 растёт'),
 'closure':('Закрыть связь e5','Нулевой расход e5 → два раздельных воздушных пути → новая смесь V6'),
 'gas':('Газовыделение ×2','Источники газа растут → концентрации V5/V6 → V7/V9'),
 'loss':('Потеря группы датчиков','Нет расхода e6 и метана V7/V9; прежняя информация сохраняется'),
 'blind_all':('Потеря всех датчиков','Остаются модельные гипотезы, без гарантии включения истины'),
 'delay':('Задержка метана V7','Показание стареет и исключается из текущего отбора'),
 'freeze':('Зависание метана V7','Возраст растёт; старое значение не считается текущим'),
 'bias':('Смещение метана V7','Ошибка +0,3 п.п. вне допуска может вызвать конфликт'),
 'noise':('Ограниченный шум','Шум ±половина допуска; воспроизводимый seed'),
 'outside':('Источник вне сетки','Газ ×3: стресс-тест конечного набора гипотез'),
 'cancel':('Отменить воздействия','Исходные команды и исправные датчики; газ возвращается постепенно')}

class NetworkTwin:
    def __init__(self,seed=20261025):self.seed=seed;self.reset()

    @staticmethod
    def model_signature():
        base=Path(__file__).parent
        return hashlib.sha256(b''.join((base/n).read_bytes() for n in ('network.py','network_observer.py','network_twin.py','measurements.py','spatial.py','data/gucheng-network.csv'))).hexdigest()

    def reset(self):
        self.params=dict(DEFAULT);self.air=solve(self.params);self.gas=steady(self.air)
        self.time=0.;self.speed=5;self.paused=False;self.revision=0;self.horizon=120.
        self.failed=set();self.pending={};self.bias={k:0. for k in SENSORS};self.measurements=SensorBank(SENSORS,self.seed)
        self.observer=Observer();self.checkpoint=None;self.last_decision=None;self.history=[];self.timeline=[]
        self.replay_available=True;self.experiment_id=uuid.uuid4().hex;self.events=[];self.ledger={}
        self.capture();self.snapshot=self.observe()

    def known(self):return {k:self.params[k] for k in ('fan_a','fan_b','closed','resistance_e5')}
    def capture(self):self.measurements.capture(values(self.gas,self.air),self.time,self.bias,keys=[k for k in SENSORS if k not in self.failed])
    def record(self,item):
        if len(self.timeline)<4000:self.timeline.append(copy.deepcopy(item))
        else:self.replay_available=False

    def tick(self,dt):
        if not math.isfinite(dt) or not 0<dt<=3600:raise ValueError('Шаг: (0;3600] секунд')
        if self.paused:return self.snapshot
        self.record({'kind':'step','dt':dt});self.revision+=1
        if not self.paused:
            self.air=solve(self.params)
            end=self.time+dt
            boundaries=sorted({due for due in self.pending.values() if self.time<due<end}|{end})
            for boundary in boundaries:
                elapsed=boundary-self.time
                self.gas,self.ledger=advance(self.gas,self.air,self.params['gas'],elapsed)
                self.observer.step(elapsed,self.known());self.time=boundary
                for key,due in list(self.pending.items()):
                    if self.time>=due:
                        self.failed.discard(key);self.bias[key]=0.;self.measurements.repair(key);del self.pending[key]
                        self.events.append({'time':self.time,'text':'Восстановлен '+key})
                self.capture()
                readings,metadata=self.measurements.readings(self.time,self.failed)
                self.observer.observe(readings,metadata)
                self.finish_decision()
        self.snapshot=self.observe()
        if not self.paused:
            self.history.append({'t':self.time,'gas':{n:100*v for n,v in self.gas.items()},'estimate':self.snapshot['estimate'],'width':self.snapshot['width']})
            self.history=self.history[-240:]
        return self.snapshot

    def finish_decision(self):
        if self.last_decision and not self.last_decision.get('completed') and self.last_decision['sensor'] not in self.pending:
            decision=self.last_decision
            remaining=max(0.,decision['target_time']-self.time)
            from .network_observer import width
            after=None if self.observer.conflict else width(self.observer.forecast(remaining))
            decision.update({'completed':True,'completed_at':self.time,'after_width_same_target':after,
                             'actual_gain':None if after is None or decision['before_width'] is None else decision['before_width']-after})

    def observe(self):
        readings,metadata=self.measurements.readings(self.time,self.failed)
        estimate=self.observer.observe(readings,metadata)
        rankings,forecast=self.observer.rank([k for k in SENSORS if not metadata[k]['usable']],self.horizon)
        if forecast is None:forecast={}
        width=sum(v['high']-v['low'] for n,v in forecast.items() if n in TARGETS) if forecast else None
        objects=catalog()
        for n in INTERNAL:objects[n]['state']={'methane_pct':self.gas[n]*100,'estimate':estimate[n],'pressure_pa':self.air['pressure'][n],
                                             'gas_source_m3_s':SOURCES[n]*self.params['gas']}
        for n in ('V1','V3','V8','V10'):objects[n]['state']={'pressure_pa':0.,'boundary_kind':'intake' if n in ('V1','V3') else 'exhaust'}
        for k in EDGES:objects[k]['state']={'flow_m3_s':self.air['q'][k],'resistance':self.air['resistance'][k],'head_pa':self.air['head'].get(k,0),'closed':k=='e5' and self.params['closed']}
        objects['e8']['state']['speed_factor']=self.params['fan_a'];objects['e9']['state']['speed_factor']=self.params['fan_b']
        for k in SENSORS:objects['sensor-'+k]['state']={'reading':readings[k],**metadata[k]}
        before=self.checkpoint
        changes={k:self.air['q'][k]-(before['air']['q'][k] if before else self.air['q'][k]) for k in EDGES}
        return {'model':'gucheng-network-v3','experiment_id':self.experiment_id,'revision':self.revision,'seed':self.seed,
                'time':self.time,'params':dict(self.params),'paused':self.paused,'speed':self.speed,'horizon_s':self.horizon,
                'air':self.air,'truth':{'gas_pct':{n:v*100 for n,v in self.gas.items()}},'estimate':estimate,
                'readings':readings,'sensors':{k:{**s,**metadata[k],'failed':k in self.failed,'repair_due':self.pending.get(k)} for k,s in SENSORS.items()},
                'forecast':forecast,'width':width,'rankings':rankings,'conflict':self.observer.conflict,
                'candidate_count':len(self.observer.pool) if not self.observer.conflict else 0,'hypothesis_count':len(self.observer.hypotheses),
                'quality':{'method':'finite trajectory ensemble; NOT guaranteed enclosure','used_channels':[k for k in SENSORS if metadata[k]['usable']],
                           'assumptions':'resistance e6 and global gas factors in {0.5,1,2,4}; public commands; dilute tracer; uniform hypothetical outcomes'},
                'objects':objects,'scenarios':SCENARIOS,'mass_balance':self.ledger,'checkpoint':before,'flow_changes':changes,
                'last_decision':self.last_decision,'events':self.events[-16:],'replay_available':self.replay_available}

    def command(self,data):
        if not isinstance(data,dict):raise ValueError('Ожидается объект')
        action=data.get('action');event=action;restart=False
        if action=='reset':
            seed=data.get('seed',self.seed)
            if type(seed) is not int or not 0<=seed<2**31:raise ValueError('Некорректный seed')
            self.seed=seed;self.reset();return
        if action=='pause':self.paused=not self.paused
        elif action=='speed':
            value=float(data['value'])
            if value not in (1,5,10):raise ValueError('Скорость 1/5/10')
            self.speed=value
        elif action=='horizon':
            value=float(data['value'])
            if value not in (60,120,300,600):raise ValueError('Горизонт 60/120/300/600 с')
            self.horizon=value
        elif action=='checkpoint':self.checkpoint={'time':self.time,'air':copy.deepcopy(self.air),'gas_pct':{n:v*100 for n,v in self.gas.items()},'width':self.snapshot['width']}
        elif action in ('fail','restore','bias','sensor_config'):
            key=data.get('sensor')
            if key not in SENSORS:raise ValueError('Неизвестный датчик')
            if action=='fail':self.failed.add(key)
            elif action=='restore':
                self.last_decision={'sensor':key,'before_width':self.snapshot['width'],'time':self.time,
                                    'target_time':self.time+self.horizon,
                                    'expected_gain':next((r['gain'] for r in self.snapshot['rankings'] if r['sensor']==key),None)}
                self.failed.add(key);self.pending[key]=self.time+SENSORS[key]['repair_s']
            elif action=='bias':
                v=float(data['value'])
                if not math.isfinite(v) or abs(v)>20:raise ValueError('Смещение вне диапазона')
                self.bias[key]=v
            else:
                changes=data.get('settings',{});valid={}
                if not isinstance(changes,dict) or not changes:raise ValueError('Пустая настройка')
                for k,v in changes.items():
                    if k=='frozen' and type(v) is bool:valid[k]=v
                    elif k in ('delay_s','noise') and isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=(120 if k=='delay_s' else 20):valid[k]=v
                    else:raise ValueError('Некорректная настройка')
                self.measurements.config[key].update(valid)
        elif action=='parameter':
            name=data.get('name')
            if name not in DEFAULT or name=='closed':raise ValueError('Неизвестный параметр')
            new={**self.params,name:float(data['value'])};solve(new)
            restart=name in ('resistance_e6','gas');self.params=new
        elif action=='scenario':
            name=data.get('name')
            if name not in SCENARIOS:raise ValueError('Неизвестный сценарий')
            event=SCENARIOS[name][0]
            if self.checkpoint is None:self.checkpoint={'time':self.time,'air':copy.deepcopy(self.air),'gas_pct':{n:v*100 for n,v in self.gas.items()},'width':self.snapshot['width']}
            if name=='fan':self.params['fan_a']=.8
            elif name=='resistance':self.params['resistance_e6']=2.;restart=True
            elif name=='closure':self.params['closed']=True
            elif name=='gas':self.params['gas']=2.;restart=True
            elif name=='outside':self.params['gas']=3.;restart=True
            elif name=='loss':self.failed.update(('q_e6','c_V7','c_V9'))
            elif name=='blind_all':self.failed=set(SENSORS)
            elif name=='delay':self.measurements.config['c_V7']['delay_s']=15.
            elif name=='freeze':self.measurements.config['c_V7']['frozen']=True
            elif name=='bias':self.bias['c_V7']=.3
            elif name=='noise':
                for k in SENSORS:self.measurements.config[k]['noise']=SENSORS[k]['tolerance']/2
            elif name=='cancel':
                self.params=dict(DEFAULT);self.failed.clear();self.pending.clear();self.bias={k:0. for k in SENSORS};restart=True
                for k in SENSORS:self.measurements.repair(k)
        elif action=='observer_reset':self.observer=Observer()
        else:raise ValueError('Неизвестная команда')
        self.air=solve(self.params)
        if restart:self.observer.restart_uncertainty(self.known())
        self.observer.step(0,self.known());self.capture();self.revision+=1
        self.record({'kind':'command','data':data});self.events.append({'time':self.time,'text':event})
        self.snapshot=self.observe()
        if action=='restore':
            self.last_decision['repair_due']=self.pending[key]
            self.last_decision['note']='Repair scheduled in simulation time; observed forecast widths logged in history.'

    def export_experiment(self):
        if not self.replay_available:raise ValueError('Журнал переполнен')
        return {'schema_version':3,'model_signature':self.model_signature(),'seed':self.seed,'timeline':copy.deepcopy(self.timeline)}

    @classmethod
    def replay(cls,data):
        if not isinstance(data,dict) or data.get('schema_version')!=3 or data.get('model_signature')!=cls.model_signature():raise ValueError('Несовместимая версия опыта')
        seed=data.get('seed');timeline=data.get('timeline')
        if type(seed) is not int or not 0<=seed<2**31 or not isinstance(timeline,list) or len(timeline)>4000:raise ValueError('Некорректный опыт')
        twin=cls(seed);elapsed=0.
        for item in timeline:
            if not isinstance(item,dict):raise ValueError('Некорректная запись')
            if item.get('kind')=='step':
                dt=float(item['dt']);elapsed+=dt
                if elapsed>100000:raise ValueError('Слишком длинный опыт')
                twin.tick(dt)
            elif item.get('kind')=='command' and isinstance(item.get('data'),dict) and item['data'].get('action')!='reset':twin.command(item['data'])
            else:raise ValueError('Некорректная запись')
        return twin
