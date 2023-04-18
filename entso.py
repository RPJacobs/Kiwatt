from pysolarmanv5 import PySolarmanV5
import datetime
import requests
import json
import math
from functions import get_forecast, get_hour_prices

with open("config.json") as json_data_file:
    cfg = json.load(json_data_file)

priceHour = get_hour_prices(cfg)
production_start, productionToday = get_forecast(cfg)


modbus = PySolarmanV5(cfg["kiwatt"]["ip"], cfg["kiwatt"]["sn"], port=cfg["kiwatt"]["port"], mb_slave_id=1, verbose=0)
#get battery capacity (kWh)
batt_capacity = modbus.read_holding_registers(register_addr=102, quantity=1)[0]*50/1000
#sell_mode_time_point = modbus.read_holding_registers(register_addr=154, quantity=6)

perc = modbus.read_holding_registers(register_addr=588, quantity=1)
hourNow = int(datetime.datetime.now().strftime("%H"))+1

ranking = []
low1 = min(priceHour, key=priceHour.get)
priceHour.pop(low1)
low2 = min(priceHour, key=priceHour.get)
priceHour.pop(low2)
low3 = min(priceHour, key=priceHour.get)
priceHour.pop(low3)
if(low1 >= hourNow):
   ranking.append(low1)
if(low2 >= hourNow):
   ranking.append(low2)
if(low3 >= hourNow):
   ranking.append(low3)
low = sorted(ranking)


#how long to battery is empty
batt_empty = math.floor((perc[0]-10) / cfg["kiwatt"]["unload_perc_hour"]) + hourNow

#check if there is any solar production
if production_start == 0:
    production_start = batt_empty

#setpoints hour*100 + minute
setPoints = []
#loadpoints 0=off 1=on
loadPoints = []
#load percentage
loads = []

# check if first loadpoint is after batt_empty and 
# production starts after batt_empty 
# low1 = 14/ batt_empty = 10
if low[0] > batt_empty and production_start >= batt_empty:
    requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text=Low ('+str(low[0])+') before batt_empty ('+str(batt_empty)+')')
    loadpoint = 99
    #find lowest loadpoint before batt_empty
    while loadpoint > batt_empty:
        loadpoint = min(priceHour, key=priceHour.get)
        priceHour.pop(loadpoint)
    #add loadpoint to list
    requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text=lowest loadpoint ('+str(loadpoint)+') needs additional load ('+str((batt_empty-loadpoint)*cfg["kiwatt"]["unload_perc_hour"]+10)+')')

    setPoints.append(loadpoint*100)
    loadPoints.append(1)
    loads.append((batt_empty-loadpoint)*cfg["kiwatt"]["unload_perc_hour"]+10)
    setPoints.append((loadpoint+1)*100)
    loadPoints.append(0)
    loads.append(10)


#current capacity (kWh) of battery
batLoad = perc[0]*batt_capacity/100
#load needed today until 18:00
loadToday = (18 - hourNow) * batt_capacity * cfg["kiwatt"]["unload_perc_hour"] / 100

#max load capacity of battery (kWh)
maxload = float(modbus.read_holding_registers(register_addr=108, quantity=1)[0]) * 50 / 1000

#postion of setpoint in time
count = 0
#calculated load before this setpoint
calcLoad = 0
for setpoint in low:
    #check if setpoint is in the future
    if(setpoint < hourNow):
        continue
    #get position of setpoint in ranking (cheapest first)
    rank = ranking.index(setpoint)
    #calculate kWh needed to load battery to max_percload
    toLoad = batt_capacity*cfg["kiwatt"]["max_percload"]/100-(batLoad + productionToday - loadToday  + calcLoad)
    requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text=toLoad ('+str(toLoad)+') = batLoad ('+str(batLoad)+'kWh) + productionToday ('+str(productionToday)+'kWh) - loadToday ('+str(loadToday)+'kWh) - calcLoad ('+str(calcLoad)+'kWh)')

    #calc hours to correct based on ranking and cheapest price
    correct = 0
    if(rank-count >= 0):
        correct = rank-count
    #calc hours to load
    loadHours = toLoad/maxload - correct
    if(loadHours <= 0):
        loadHours = 0
    else:
        #round up to full hour
        if(loadHours > 1 ):
            loadHours = 1

        #calculate load percentage this hour
        loadPerc = int(round(perc[0]+(((loadHours*maxload)+calcLoad)/(batt_capacity/100)), 0))
        if(loadPerc > cfg["kiwatt"]["max_percload"]):
            loadPerc = cfg["kiwatt"]["max_percload"]
        #add load to calculated load for next hour
        calcLoad += loadHours*maxload
        #check if setpoint is already in list
        if (setpoint*100) in setPoints:
            setPoints.remove(setpoint*100)
            loadPoints.pop()
            loads.pop()
        #add setpoint to list
        setPoints.append(setpoint*100)
        loadPoints.append(1)
        loads.append(loadPerc)
        #add next setpoint to list to stop charging
        setPoints.append((setpoint+1)*100)
        loadPoints.append(0)
        loads.append(cfg["kiwatt"]["min_percload"])
    #stop after 5 setpoints to be able to stop charging after setpoint 5
    if len(setPoints) >= 5:
        break
    count = count+1

#check if setpoint list is full
if len(setPoints) < 6:
    #add setpoints to fill list
    for x in range(6-len(setPoints)):
        #check if last setpoint empty
        if(len(setPoints) == 0):
            last = 2300
        else:
            #get last setpoint
            last =  (setPoints[len(setPoints)-1])
        #check if last setpoint is before 22:59
        if (last <= 2259):
            setPoints.append(last+100)
        else:
            #add setpoint at 0:00
            setPoints.append(0)
        loadPoints.append(0)
        loads.append(cfg["kiwatt"]["min_percload"])

#read current setpoints, loads and loadpoints
setPoints_now = modbus.read_holding_registers(register_addr=148, quantity=6)
loads_now = modbus.read_holding_registers(register_addr=166, quantity=6)
loadPoints_now = modbus.read_holding_registers(register_addr=172, quantity=6)

#create text for telegram
text = 'Batterij ('+str(perc[0])+'%)'

#check if setpoints,loads or loadpoints are different
if (setPoints_now != setPoints or loads_now != loads or loadPoints_now != loadPoints):
    """set time 1"""
    modbus.write_multiple_holding_registers(register_addr=148, values=setPoints)
    """set loads"""
    modbus.write_multiple_holding_registers(register_addr=166, values=loads)
    """set loadPoints"""
    modbus.write_multiple_holding_registers(register_addr=172, values=loadPoints)
    #send update telegram message
    requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text='+text+'\n'+str(setPoints)+'\n'+str(loadPoints)+'\n'+str(loads))
else:
    #send telegram message
    requests.post('https://api.telegram.org/bot'+cfg["telegram"]["botID"]+'/sendMessage?chat_id='+cfg["telegram"]["chatID"]+'&text='+text)

