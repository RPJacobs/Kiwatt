import requests
import datetime
import json
from entsoe import EntsoeRawClient
import pandas as pd
import bs4
import requests

def get_forecast(cfg):
    #get forecast from forecast.solar
    url = 'https://api.forecast.solar/estimate/'+str(cfg["forecast.solar"]["lat"])+"/"+str(cfg["forecast.solar"]["long"])+"/"+str(cfg["forecast.solar"]["dec"])+"/"+str(cfg["forecast.solar"]["az"])+"/"+str(cfg["forecast.solar"]["kwp"])
    headers = {
        "content-type": "application/json"
    }
    estimate = requests.request("GET",url, headers=headers).json()

    #check if we get a result
    if estimate['result'] == None:
        #no result, get forcast from file
        f = open('forecast.json')
        estimate = json.load(f)
        f.close()
    else:
        #save forecast to file
        with open("forecast.json", "w") as outfile:
            outfile.write(json.dumps(estimate))

    now = datetime.datetime.now()
    tomorrow = (datetime.datetime.now()+ datetime.timedelta(days=1, hours=0)).replace(hour=0, minute=0, second=0, microsecond=0)

    #calculate total forcast production for today from now till 24:00
    to_produce = 0
    for hour in estimate['result']['watt_hours_period']:
        hour_time_obj = datetime.datetime.strptime(hour, '%Y-%m-%d %H:%M:%S')
        if(hour_time_obj > now and hour_time_obj < tomorrow):
            to_produce = to_produce + estimate['result']['watt_hours_period'][hour]/1000

    return to_produce

def get_hour_prices(cfg):
    #connect to entsoe
    client = EntsoeRawClient(api_key=cfg["entsoe"]["key"])

    #get prices for today or tomorrow if after 23:00
    now = int(datetime.datetime.now().strftime("%Y%m%d"))
    now1 = int((datetime.datetime.now()+ datetime.timedelta(days=1, hours=0)).strftime("%Y%m%d"))
    now2 = int((datetime.datetime.now()+ datetime.timedelta(days=2, hours=0)).strftime("%Y%m%d"))
    if int(datetime.datetime.now().strftime("%H")) > 23:
        start = pd.Timestamp(str(now1), tz=cfg["entsoe"]["tz"])
        end = pd.Timestamp(str(now2), tz=cfg["entsoe"]["tz"])
    else:
        start = pd.Timestamp(str(now), tz=cfg["entsoe"]["tz"])
        end = pd.Timestamp(str(now1), tz=cfg["entsoe"]["tz"])
    country_code = cfg["entsoe"]["country"]
    ts = client.query_day_ahead_prices(country_code, start=start, end=end)
    soup = bs4.BeautifulSoup(ts, 'html.parser')

    #correct index hour 1 = 0:00, 2 = 1:00 etc
    price_hour = {}
    for point in soup.find_all('point'):
        price_hour[int(point.find('position').text)-1] = float(point.find('price.amount').text)
    
    return price_hour