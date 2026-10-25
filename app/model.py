"""Small explicit ventilation network; SI internally, methane in percent at API.

Declining synthetic fan curve, quasi-steady air, well-mixed gas volumes.
State intervals are conditional on declared bounds, not confidence intervals.
"""
import math
import itertools
import uuid
import copy
import hashlib
from pathlib import Path
from dataclasses import dataclass, asdict

MODEL_SIGNATURE=hashlib.sha256(b''.join((Path(__file__).parent/name).read_bytes() for name in ('model.py','observer.py','measurements.py'))).hexdigest()


@dataclass
class Parameters:
    fan: float = 1.0
    resistance_a: float = 1.0
    resistance_b: float = 1.0
    leakage: float = 1.0
    gas_a: float = 1.0
    gas_b: float = 1.0


SENSORS = {
    "qa": {"name": "A · расход", "unit": "м³/с", "tolerance": 1.5, "cost": 2},
    "qb": {"name": "B · расход", "unit": "м³/с", "tolerance": 1.5, "cost": 2},
    "ca": {"name": "A · метан", "unit": "% об.", "tolerance": .12, "cost": 3},
    "cb": {"name": "B · метан", "unit": "% об.", "tolerance": .12, "cost": 3},
    "qt": {"name": "Вход · расход", "unit": "м³/с", "tolerance": 2.0, "cost": 1},
}
LIMIT = 1.0  # illustrative experiment threshold, not a regulatory setting
BASE_RESISTANCE = {"a": .10, "b": .14, "bypass": .8, "common": .035}
VOLUMES = {"a": 1800., "b": 2400.}
GAS_SOURCES = {"a": .35, "b": .22}
# Synthetic fan curve anchored to the original 600 Pa baseline operating point.
FAN_CURVE_K = .025
_BASE_REQ = 1/sum(1/math.sqrt(BASE_RESISTANCE[k]) for k in ('a','b','bypass'))**2
FAN_SHUTOFF_PA = 600*(1+FAN_CURVE_K/(BASE_RESISTANCE['common']+_BASE_REQ))


def airflow(p):
    """Exact series/parallel network solution for P = R*Q*abs(Q)."""
    ra, rb, rl = BASE_RESISTANCE['a']*p.resistance_a, BASE_RESISTANCE['b']*p.resistance_b, BASE_RESISTANCE['bypass']/p.leakage
    req = 1 / (1/math.sqrt(ra) + 1/math.sqrt(rb) + 1/math.sqrt(rl))**2
    qt = math.sqrt(FAN_SHUTOFF_PA*p.fan**2/(BASE_RESISTANCE['common']+req+FAN_CURVE_K))
    pressure = FAN_SHUTOFF_PA*p.fan**2-FAN_CURVE_K*qt**2
    dp = qt*qt*req
    qa, qb, ql = (math.sqrt(dp/r) for r in (ra, rb, rl))
    return {"qa": qa, "qb": qb, "ql": ql, "qt": qt, "pressure": pressure,
            "parallel_dp": dp, "power_kw": pressure*qt/.72/1000,
            "continuity_error": abs(qt-qa-qb-ql), "fan_curve_residual_pa":
            abs(pressure-(BASE_RESISTANCE['common']+req)*qt**2)}


def gas_step(c_pct, flow, source, volume, dt):
    """V dc/dt = G*(1-c) - Q*c. Clean incoming air; exact constant-input step."""
    if dt==0:return c_pct
    equilibrium = source / (flow+source) if flow+source else 0
    c = equilibrium + (c_pct/100-equilibrium)*math.exp(-(flow+source)*dt/volume)
    return 100*c


def advance(state, p, dt):
    f = airflow(p)
    ca = gas_step(state[0], f["qa"], GAS_SOURCES['a']*p.gas_a, VOLUMES['a'], dt)
    cb = gas_step(state[1], f["qb"], GAS_SOURCES['b']*p.gas_b, VOLUMES['b'], dt)
    # Two well-mixed face volumes discharge into a zero-storage return junction.
    ga, gb = .35*p.gas_a, .22*p.gas_b
    cr = ((f["qa"]+ga)*ca + (f["qb"]+gb)*cb)/(f["qt"]+ga+gb)
    return {**f, "ca": ca, "cb": cb, "cr": cr}


def risk_interval(lo, hi):
    if lo >= LIMIT:
        return "exceedance"
    if hi < LIMIT:
        return "below"
    return "uncertain"


class Twin:
    def __init__(self,seed=20261025):
        self.seed=seed
        self.reset()

    def reset(self):
        self.experiment_id = uuid.uuid4().hex
        self.revision = 0
        self.params = Parameters()
        self.costs={k:v['cost'] for k,v in SENSORS.items()}
        self.target_width=.5
        self.timeline=[]
        self.replay_available=True
        self.checkpoint=None
        self.last_decision=None
        f = airflow(self.params)
        self.gas = [100*.35/(f["qa"]+.35), 100*.22/(f["qb"]+.22)]
        self.time = 0.0
        self.paused = False
        self.speed = 5
        self.failed = set()
        self.bias = {k: 0.0 for k in SENSORS}
        self.history = []
        self.events = [{"time": 0, "text": "Новый эксперимент · синтетический участок"}]
        # Explicit parameter hypotheses. All share the declared initial gas state.
        self.hypotheses = []
        for ra, rb, ga, gb in itertools.product((.65, 1, 1.45, 2.5), (.65, 1, 1.45, 2.5),
                                                (.5, 1, 1.4, 2), (.5, 1, 1.4, 2)):
            self.hypotheses.append({"p": Parameters(resistance_a=ra, resistance_b=rb,
                                                   gas_a=ga, gas_b=gb), "gas": self.gas[:]})
        self.truth = advance(self.gas, self.params, 0)
        from .measurements import SensorBank
        from .observer import IntervalObserver
        self.measurements=SensorBank(SENSORS,self.seed)
        self.measurements.capture(self.truth,self.time,self.bias)
        self.guard=IntervalObserver(self.gas)
        self._observer_dt=0.
        self.snapshot = self.observe()

    def record(self,item):
        if len(self.timeline)<4000:self.timeline.append(copy.deepcopy(item))
        else:self.replay_available=False

    def export_experiment(self):
        if not self.replay_available:raise ValueError('Журнал превысил 4000 действий; начните новый опыт для воспроизведения')
        return {'schema_version':2,'model_version':'bounded-interval-v2','model_signature':self.model_signature(),
                'seed':self.seed,'timeline':copy.deepcopy(self.timeline)}

    @staticmethod
    def model_signature():
        return MODEL_SIGNATURE

    @classmethod
    def replay(cls,data):
        if not isinstance(data,dict) or data.get('schema_version')!=2 or data.get('model_version')!='bounded-interval-v2':
            raise ValueError('Неподдерживаемая версия эксперимента')
        if data.get('model_signature')!=cls.model_signature():raise ValueError('Опыт сохранён с другой версией физики или наблюдателя')
        seed=data.get('seed')
        if type(seed) is not int or not 0<=seed<2**31:raise ValueError('Некорректный seed')
        timeline=data.get('timeline')
        if not isinstance(timeline,list) or len(timeline)>4000:raise ValueError('Некорректный журнал')
        twin=cls(seed=seed)
        elapsed=0.
        for item in timeline:
            if not isinstance(item,dict):raise ValueError('Некорректная запись')
            if item.get('kind')=='step':
                dt=float(item['dt']);elapsed+=dt
                if elapsed>100000:raise ValueError('Слишком длинный опыт')
                twin.tick(dt)
            elif item.get('kind')=='command' and isinstance(item.get('data'),dict):
                if item['data'].get('action')=='reset':raise ValueError('Сброс внутри журнала не допускается')
                twin.command(item['data'])
            else:raise ValueError('Неизвестная запись журнала')
        return twin

    def tick(self, dt):
        if not math.isfinite(dt) or not 0<dt<=3600:raise ValueError('Шаг должен быть в (0; 3600] секунд')
        self.record({'kind':'step','dt':dt})
        self.revision += 1
        if not self.paused:
            self.time += dt
            self.truth = advance(self.gas, self.params, dt)
            self.gas = [self.truth["ca"], self.truth["cb"]]
            for h in self.hypotheses:
                # Only actual known commands are passed to the observer.
                h["p"].fan = self.params.fan
                h["p"].leakage = self.params.leakage
                h["v"] = advance(h["gas"], h["p"], dt)
                h["gas"] = [h["v"]["ca"], h["v"]["cb"]]
            self.measurements.capture(self.truth,self.time,self.bias,keys=[key for key in SENSORS if key not in self.failed])
            self._observer_dt=dt
        self.snapshot = self.observe()
        if not self.paused:
            self.history.append({"t": round(self.time, 1), "ca": self.truth["ca"],
                                 "cb": self.truth["cb"], "estimate": self.snapshot["estimate"], "conflict":self.snapshot['conflict']})
            self.history = self.history[-240:]
        return self.snapshot

    def observe(self):
        from .observer import rank_measurements
        readings,metadata=self.measurements.readings(self.time,self.failed)
        usable={k:readings[k] if metadata[k]['usable'] else None for k in SENSORS}
        candidates = []
        for h in self.hypotheses:
            v = h.get("v") or advance(h["gas"], h["p"], 0)
            if all(x is None or abs(v[k]-x) <= SENSORS[k]["tolerance"] for k, x in usable.items()):
                candidates.append(v)
        nominal_conflict = not candidates
        pool = candidates or [h.get("v") or advance(h["gas"], h["p"], 0) for h in self.hypotheses]
        def bounds(items):
            return {k: {"low": min(v[k] for v in items), "high": max(v[k] for v in items),
                        "mean": sum(v[k] for v in items)/len(items)} for k in ("qa", "qb", "ql", "qt", "ca", "cb", "cr")}
        nominal_estimate=bounds(pool)
        estimate=self.guard.update(self._observer_dt,self.params.fan,self.params.leakage,readings,metadata,self.time)
        self._observer_dt=0.
        conflict=self.guard.conflict
        width=sum(estimate[k]['high']-estimate[k]['low'] for k in ('ca','cb'))
        missing=[k for k in SENSORS if not metadata[k]['usable']]
        rankings=[] if conflict else rank_measurements(estimate,missing,self.costs)
        mission_status='inspect' if conflict else 'target_met' if width<=self.target_width else 'choose' if missing else 'precision_limited'
        return {"experiment_id": self.experiment_id, "revision": self.revision,
                "time": self.time, "params": asdict(self.params), "paused": self.paused,
                "speed": self.speed, "truth": self.truth, "readings": readings,
                "sensors": {k: {**v, **metadata[k], "cost":self.costs[k], "failed": k in self.failed, "bias": self.bias[k]}
                            for k, v in SENSORS.items()}, "estimate": estimate,
                "candidate_count": len(candidates), "hypothesis_count": len(self.hypotheses),
                "conflict": conflict, "width": width, "rankings": rankings,
                "nominal_estimate":nominal_estimate,
                "quality":{"method":"bounded_interval","used_channels":[k for k in SENSORS if metadata[k]['usable']],
                           "faults":copy.deepcopy(self.guard.faults),"nominal_conflict":nominal_conflict,
                           "limits":{"resistance_factors":[.65,2.5],"gas_factors":[.5,2.]},
                           "claim":"conditional_on_bounds_and_measurement_error; not a confidence interval"},
                "mission":{"target_width_pp":self.target_width,"status":mission_status,"metric":"sum of current A+B CH4 interval widths"},
                "checkpoint":copy.deepcopy(self.checkpoint),"last_decision":copy.deepcopy(self.last_decision),
                "seed":self.seed,"replay_available":self.replay_available,
                "risk": {k: "conflict" if conflict else risk_interval(estimate[k]["low"], estimate[k]["high"])
                         for k in ("ca", "cb")},
                "events": self.events[-12:], "threshold": LIMIT}

    def command(self, data):
        action = data.get("action")
        before_width=self.snapshot['width']
        before_conflict=self.snapshot['conflict']
        expected=next((r for r in self.snapshot['rankings'] if r['sensor']==data.get('sensor')),None)
        if action == "reset":
            if 'seed' in data:
                if type(data['seed']) is not int or not 0<=data['seed']<2**31:raise ValueError('Некорректный seed')
                self.seed=data['seed']
            self.reset()
            return
        if action == 'checkpoint':
            self.checkpoint={'time':self.time,'estimate':copy.deepcopy(self.snapshot['estimate']),
                             'width':self.snapshot['width'],'conflict':self.snapshot['conflict'],'readings':copy.deepcopy(self.snapshot['readings'])}
        elif action == 'target':
            value=float(data['value'])
            if not math.isfinite(value) or not .05<=value<=20:raise ValueError('Цель: 0,05–20 п.п.')
            self.target_width=value
        elif action == 'cost':
            key=data.get('sensor');value=float(data['value'])
            if key not in SENSORS or not math.isfinite(value) or not .1<=value<=100:raise ValueError('Стоимость: 0,1–100')
            self.costs[key]=value
        elif action == 'sensor_config':
            key=data.get('sensor');changes=data.get('settings')
            if key not in SENSORS or not isinstance(changes,dict) or not changes:raise ValueError('Некорректная настройка датчика')
            validated={}
            for name,value in changes.items():
                if name=='frozen':
                    if type(value) is not bool:raise ValueError('frozen должен быть логическим')
                    validated[name]=value
                elif name in ('noise','delay_s'):
                    value=float(value)
                    if not math.isfinite(value) or not 0<=value<=(20 if name=='noise' else 120):raise ValueError('Некорректная величина ошибки/задержки')
                    validated[name]=value
                else:raise ValueError('Неизвестная настройка датчика')
            self.measurements.config[key].update(validated)
        elif action == 'observer_reset':
            from .observer import IntervalObserver
            self.guard=IntervalObserver()
        elif action == "pause":
            self.paused = not self.paused
        elif action == "speed":
            val = float(data["value"])
            if val not in (1, 5, 10):
                raise ValueError("Скорость: 1, 5 или 10")
            self.speed = val
        elif action in ("fail", "restore", "bias"):
            sensor = data.get("sensor")
            if sensor not in SENSORS:
                raise ValueError("Неизвестный датчик")
            if action == "fail":
                self.failed.add(sensor)
            elif action == "restore":
                self.failed.discard(sensor)
                self.bias[sensor] = 0.0
                self.measurements.repair(sensor)
                if self.guard.conflict:
                    from .observer import IntervalObserver
                    self.guard=IntervalObserver()
            else:
                value = float(data.get("value", .5))
                if not math.isfinite(value) or abs(value)>20:
                    raise ValueError("Некорректное смещение")
                self.bias[sensor] = value
        elif action == "scenario":
            name = data.get("name")
            if name == "blind_a":
                self.failed.update(("qa", "ca"))
            elif name == 'blind_b':
                self.failed.update(('qb','cb'))
            elif name == 'noise':
                for key in SENSORS:self.measurements.config[key]['noise']=SENSORS[key]['tolerance']*.5
            elif name == 'delay_ca':
                self.measurements.config['ca']['delay_s']=15.
            elif name == 'freeze_ca':
                self.measurements.config['ca']['frozen']=True
            elif name == 'outside':
                self.params.gas_a=3.5
            elif name == 'combined':
                self.params.fan=.65;self.failed.update(('qa','ca'))
            elif name == "blind_all":
                self.failed = set(SENSORS)
            elif name == "door":
                self.params.resistance_a = 2.5
            elif name == "gas":
                self.params.gas_a = 1.4
            elif name == "fan":
                self.params.fan = .65
            elif name == "bias_ca":
                self.bias["ca"] = .5
            elif name == "cancel":
                self.params = Parameters()
                self.failed.clear()
                self.bias = {k: 0.0 for k in SENSORS}
                for key in SENSORS:self.measurements.repair(key)
                if self.guard.conflict:
                    from .observer import IntervalObserver
                    self.guard=IntervalObserver()
            else:
                raise ValueError("Неизвестный сценарий")
        elif action == "parameter":
            name, value = data.get("name"), float(data["value"])
            limits = {"fan": (.2, 1.2), "leakage": (.25, 3), "gas_a":(.2,4), "gas_b":(.2,4), "resistance_a":(.4,3.5), "resistance_b":(.4,3.5)}
            if name not in limits or not math.isfinite(value) or not limits[name][0] <= value <= limits[name][1]:
                raise ValueError("Параметр вне диапазона")
            setattr(self.params, name, value)
        else:
            raise ValueError("Неизвестная команда")
        self.record({'kind':'command','data':data})
        self.revision += 1
        self.truth = advance(self.gas, self.params, 0)
        # Update instantaneous airflow in hypotheses without advancing simulated time.
        for h in self.hypotheses:
            h["p"].fan, h["p"].leakage = self.params.fan, self.params.leakage
            h["v"] = advance(h["gas"], h["p"], 0)
        keys=[]
        if action in ('restore','bias','sensor_config'):keys=[data['sensor']]
        elif action=='parameter' and data['name'] in ('fan','leakage','resistance_a','resistance_b'):keys=['qa','qb','qt']
        elif action=='scenario':
            name=data['name']
            if name in ('noise','cancel'):keys=list(SENSORS)
            elif name=='bias_ca':keys=['ca']
            elif name in ('door','fan','combined'):keys=['qa','qb','qt']
        if keys:self.measurements.capture(self.truth,self.time,self.bias,keys=[key for key in keys if key not in self.failed])
        descriptions = {"blind_a": "Потеря измерений расхода и метана A", "blind_all": "Потеря всех измерений",
                        "door": "Сопротивление ветви A увеличено в 2,5 раза", "gas": "Газовыделение A увеличено в 1,4 раза",
                        "fan": "Скорость вентилятора снижена до 65%", "bias_ca": "Смещение CA +0,5 п.п.",
                        "cancel": "Воздействия отменены; газ возвращается динамически",
                        'blind_b':'Потеря измерений B','noise':'Ограниченный шум ±0,5 допуска',
                        'delay_ca':'Задержка CA 15 с','freeze_ca':'Показание CA зависло',
                        'outside':'Источник A за пределами допущений наблюдателя',
                        'combined':'Снижение вентиляции и потеря наблюдения A'}
        if action == "scenario":
            text = descriptions[data["name"]]
        elif action in ("fail", "restore", "bias"):
            text = {"fail": "Канал отключён", "restore": "Канал восстановлен", "bias": "Изменено смещение"}[action]+": "+data["sensor"].upper()
        elif action == "pause":
            text = "Пауза" if self.paused else "Эксперимент продолжен"
        elif action == 'checkpoint':text='Зафиксирована контрольная точка для сравнения'
        elif action == 'observer_reset':text='Наблюдатель перезапущен без знания эталона'
        elif action == 'sensor_config':text='Настроены ошибки канала '+data['sensor'].upper()
        elif action == 'cost':text='Изменена условная стоимость '+data['sensor'].upper()
        elif action == 'target':text='Изменена целевая ширина диапазонов'
        else:
            text = f"Изменён параметр {data.get('name', action)}: {data.get('value')}"
        self.events.append({"time": round(self.time, 1), "text": text, "command": dict(data)})
        self.snapshot = self.observe()
        if action=='restore':
            self.last_decision={'time':self.time,'sensor':data['sensor'],'before_width':before_width,
                                'after_width':self.snapshot['width'],'actual_gain':before_width-self.snapshot['width'],
                                'before_conflict':before_conflict,'after_conflict':self.snapshot['conflict'],
                                'expected_gain':None if expected is None else expected['gain'],'cost':self.costs[data['sensor']]}
            self.snapshot['last_decision']=copy.deepcopy(self.last_decision)
