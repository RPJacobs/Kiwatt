from pysolarmanv5 import PySolarmanV5
from entsoe import EntsoeRawClient
import datetime
import pandas as pd
import bs4
import requests
import json

with open("config.json") as json_data_file:
    cfg = json.load(json_data_file)

client = EntsoeRawClient(api_key=cfg["entsoe"]["key"])

now = int(datetime.datetime.now().strftime("%Y%m%d"))
start = pd.Timestamp(str(now+1), tz='Europe/Amsterdam')
end = pd.Timestamp(str(now+2), tz='Europe/Amsterdam')
country_code = 'NL'  # Netherlands

ts = client.query_day_ahead_prices(country_code, start=start, end=end)
soup = bs4.BeautifulSoup(ts, 'html.parser')

priceHour = {}
for point in soup.find_all('point'):
    priceHour[int(point.find('position').text)-1] = float(point.find('price.amount').text)

low1 = min(priceHour, key=priceHour.get)
priceHour.pop(low1)
low2 = min(priceHour, key=priceHour.get)
priceHour.pop(low2)
low3 = min(priceHour, key=priceHour.get)
low = sorted([low1, low2, low3])


setPoints = []
loadPoints = []
loads = []
count = 0
for setpoint in low:
    if (setpoint*100) in setPoints:
        setPoints.remove(setpoint*100)
        setPoints.append(setpoint*100+100)
    else:
        count = count + 2
        if len(setPoints) : 
            loadPoints.append(0)
            loads.append(10)
        setPoints.append(setpoint*100)
        setPoints.append(setpoint*100+100)
        loadPoints.append(1)
        loads.append(100)

if count < 6:
    for x in range(6-count):
        last =  (setPoints[len(setPoints)-1])
        if (last <= 2259):
            setPoints.append(last+100)
        else:
            setPoints.append(0)
        loadPoints.append(0)
        loads.append(10)

modbus = PySolarmanV5(
    cfg["kiwatt"]["ip"], cfg["kiwatt"]["sn"], port=cfg["kiwatt"]["port"], mb_slave_id=1, verbose=0
)


"""set time 1"""
modbus.write_multiple_holding_registers(register_addr=148, values=setPoints)
"""set loads"""
modbus.write_multiple_holding_registers(register_addr=166, values=loads)
"""set loadPoints"""
modbus.write_multiple_holding_registers(register_addr=172, values=loadPoints)

requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text=Batterij ingesteld: \n'+str(setPoints)+'\n'+str(loadPoints)+'\n'+str(loads))
"""check battery
print(modbus.read_holding_registers(register_addr=148, quantity=6))
print(modbus.read_holding_registers(register_addr=166, quantity=6))
print(modbus.read_holding_registers(register_addr=172, quantity=6))
"""

