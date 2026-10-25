"""Generate a dashboard using the upstream Ditto -> MQTT -> Telegraf field contract."""
import json
from pathlib import Path

def panel(i,title,thing,feature,x,y,w=12):
    query='''from(bucket: "default")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
  |> filter(fn: (r) => r["thingId"] == "org.openegiz.ventobserve:THING")
  |> filter(fn: (r) => r["_field"] == "value_FEATURE_properties_value")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
'''.replace("THING",thing).replace("FEATURE",feature)
    return {"id":i,"title":title,"type":"timeseries","gridPos":{"x":x,"y":y,"w":w,"h":8},
            "datasource":{"type":"influxdb","uid":"opentwins-influxdb"},"targets":[{"refId":"A","query":query}],
            "fieldConfig":{"defaults":{"color":{"mode":"palette-classic"}},"overrides":[]},"options":{"legend":{"displayMode":"list","placement":"bottom"}}}

dashboard={"uid":"ventobserve","title":"VentObserve — Ventilation Observatory","schemaVersion":39,
           "version":3,"tags":["VentObserve","research"],"time":{"from":"now-30m","to":"now"},"refresh":"5s",
           "panels":[panel(1,"Methane V7 (%)","V7","methane",0,0),
                     panel(2,"Methane V9 (%)","V9","methane",12,0),
                     panel(3,"Flow e6 (m3/s)","e6","airflow",0,8),
                     panel(4,"Forecast envelope width (percentage points)","site","uncertainty",12,8)]}
(Path(__file__).parent/"dashboard.json").write_text(json.dumps(dashboard,indent=2),encoding="utf-8")
