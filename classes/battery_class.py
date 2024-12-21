import json
import datetime
import requests
import bs4
from pysolarmanv5 import PySolarmanV5
import math
from homeassistant_api import Client

class Battery:
    """
    A class to manage and optimize the usage of a battery system based on electricity prices and production forecasts.

    Attributes:
        cfg (list): Configuration settings loaded from a JSON file.
        p24 (list): Prices for the next 24 hours.
        p48 (list): Prices for the next 48 hours.
        production_start (bool): Indicates if production has started today.
        production_today (float): Total production for today.
        modbus (bool): Connection to the battery using Modbus protocol.
        batt_capacity (float): Capacity of the battery in kWh.
        perc (float): Current percentage of battery charge.
        low (list): Three lowest prices for the next 24 hours.
        lowTomorrow (list): Three lowest prices for tomorrow.
        ranking (list): Sorted lowest prices for the next 24 hours.
        high_morning (int): Highest price for the next morning.
        high_afternoon (int): Highest price for the next afternoon.
        high_tomorrow (int): Highest price for tomorrow.
        low_tomorrow (int): Lowest price for tomorrow.
        set_points (list): Set points for battery charging (hour*100 + minute).
        load_points (list): Load points (0=off, 1=on).
        loads (list): Load requirements for each set point.
    """

    cfg = []
    p24 = []
    p48 = []
    production_start = False
    production_today = False
    modbus = False
    batt_capacity = False
    perc = False
    low = []
    lowTomorrow = []
    ranking = []
    high_morning = 0
    high_afternoon = 0
    high_tomorrow = 0
    low_tomorrow = 0
    set_points = []
    load_points = []
    loads = []

    def __init__(self):
        """
        Initializes the Battery class by setting up configuration, prices, and battery parameters.
        """
        # Get current hour
        self.hour_now = int(datetime.datetime.now().strftime("%H"))
        if int(datetime.datetime.now().strftime("%M")) > 58:
            self.hour_now += 1

        # Load configuration
        self.get_config()

        # Get prices and forecasts
        self.get_hour_prices()
        self.get_forecast()

        # Establish Modbus connection to the battery
        self.modbus = PySolarmanV5(self.cfg["kiwatt"]["ip"], self.cfg["kiwatt"]["sn"], port=self.cfg["kiwatt"]["port"], mb_slave_id=1, verbose=0)

        # Get battery capacity (kWh)
        self.batt_capacity = self.modbus.read_holding_registers(register_addr=102, quantity=1)[0] * 50 / 1000

        # Get current battery percentage
        self.perc = self.modbus.read_holding_registers(register_addr=588, quantity=1)[0]

        # Calculate estimated battery empty time
        self.batt_empty = math.floor((self.perc - self.cfg["kiwatt"]["min_percload"]) / self.cfg["kiwatt"]["unload_perc_hour"]) + self.hour_now

        # Determine lowest and highest prices
        self.get_low()
        self.get_high_low()

        # Check if additional load is needed
        self.additional_load_check()

        # Calculate load points for today
        self.calc_load_points()

        # Notify Home Assistant
        self.notify_ha()

    def notify(self, text):
        """
        Sends a notification via Telegram.

        Args:
            text (str): The message to send.
        """
        url = f'https://api.telegram.org/bot{self.cfg["telegram"]["botID"]}/sendMessage?chat_id={self.cfg["telegram"]["chatID"]}&text={text}'
        requests.post(url)

    def additional_load_check(self):
        """
        Checks if additional load is needed based on the battery's current state and price points.
        """
        # Check load points and battery status to determine additional load
        check_load = next((self.low[x] for x in range(len(self.low) - 1) if self.low[x] > self.hour_now), self.hour_now)

        # Check tomorrow if no more load points today
        if check_load < self.hour_now:
            check_load = 23
            if bool(self.lowTomorrow):
                check_load = min(self.lowTomorrow)

        # If the battery will be empty before the next load point
        if self.batt_empty < check_load:
            lowprice = 9999
            highcount = 0

            for x in range(self.hour_now, check_load):
                if x in self.p48:
                    if self.p48[x] < lowprice:
                        if highcount > 0:
                            break
                        else:
                            nextLoadpoint = x
                            lowprice = self.p48[x]
                    else:
                        highcount += 1

            load_needed = 99

            # Check low points tomorrow
            if highcount > 0:
                load_needed = self.cfg["kiwatt"]["min_percload"] + 10 + highcount * self.cfg["kiwatt"]["unload_perc_hour"]

            if nextLoadpoint < 24:
                if (load_needed > 99 or (self.p48[nextLoadpoint] < self.p48[self.low_tomorrow] and max(self.low) < self.hour_now)):
                    load_needed = 99

                self.notify('Additional after loadpoint found:' + str(nextLoadpoint))
                self.notify('%:' + str(load_needed))
                self.notify('Empty:' + str(self.batt_empty))

                self.set_points.append(nextLoadpoint * 100)
                self.load_points.append(1)
                self.loads.append(load_needed)

                if nextLoadpoint + 1 < 24:
                    self.set_points.append((nextLoadpoint + 1) * 100)
                else:
                    self.set_points.append(0)

                self.load_points.append(0)
                self.loads.append(self.cfg["kiwatt"]["min_percload"])

        # Check if the battery is empty before the first load point today
        nextLoadpoint = self.hour_now
        low = []

        for x in range(1, len(self.low)):
            if self.low[x] > self.hour_now:
                low.append(x)

        if low and self.batt_empty < min(low):
            # Find the lowest price between now and the first load point
            for x in range(self.hour_now, self.batt_empty):
                if self.p48[nextLoadpoint] > self.p48[x]:
                    nextLoadpoint = x

            # Check if the hours between this load point and the first low point are lower or higher
            for x in range(nextLoadpoint + 1, min(low)):
                if self.p48[nextLoadpoint] > self.p48[x]:
                    nextLoadpoint = x
                else:
                    break

            count = 0

            # Calculate how many hours we need to load before reaching the first low point
            for x in range(nextLoadpoint + 1, min(low)):
                if self.p48[nextLoadpoint] < self.p48[x]:
                    count += 1
                else:
                    break

            if count > 0:
                load_needed = self.perc + count * self.cfg["kiwatt"]["unload_perc_hour"] + 10
                self.notify('Additional before loadpoint found:' + str(nextLoadpoint))
                self.notify('%:' + str(load_needed))
                self.notify('Empty:' + str(self.batt_empty))

                self.set_points.append(nextLoadpoint * 100)
                self.load_points.append(1)
                self.loads.append(load_needed)
                self.set_points.append((nextLoadpoint + 1) * 100)
                self.load_points.append(0)
                self.loads.append(self.cfg["kiwatt"]["min_percload"])

    def check_sell(self):
        """
        Checks if the current time matches the optimal selling times and executes selling logic.
        """
        if self.hour_now == self.high_morning:
            self.notify('Battery percentage : ' + str(self.perc) + '%')
            self.selling_first(17)
            exit()

        if self.hour_now == self.high_afternoon:
            self.notify('High Afternoon: ' + str(self.high_afternoon) + ':00')
            if self.p48[self.high_afternoon] > self.p48[self.high_tomorrow]:
                # Enable selling first
                self.selling_first(40)
            else:
                self.notify('Not selling because price is lower than tomorrow morning (' + self.get_price(self.p48[self.high_afternoon]) + '/' + self.get_price(self.p48[self.high_tomorrow]) + ')')

    def get_price(self, price):
        """
        Formats the price for display.

        Args:
            price (float): The price to format.

        Returns:
            str: The formatted price.
        """
        return '{:.3f}'.format(round((price / 1000 + 0.14349) * 1.21, 3))

    def get_high_low(self):
        """
        Determines the highest and lowest prices for the next day based on the price data.
        """
        h48 = self.p48.copy()
        while (self.high_afternoon == 0 or self.high_morning == 0 or self.high_tomorrow == 0 or self.low_tomorrow == 0) and len(h48) > 0:
            if self.low_tomorrow == 0 and len(h48) > 24:
                test = min(h48, key=h48.get)
                if test >= 24:
                    self.low_tomorrow = test
                h48.pop(test)

            high = max(h48, key=h48.get)
            if high <= 12 and self.high_morning == 0:
                self.high_morning = high
            if (high > 12 and high < 24) and self.high_afternoon == 0:
                self.high_afternoon = high
            if high >= 24 and high <= 36 and self.high_tomorrow == 0:
                self.high_tomorrow = high

            h48.pop(high)

    def get_config(self):
        """
        Loads configuration settings from a JSON file.
        """
        with open("config.json") as json_data_file:
            self.cfg = json.load(json_data_file)

    def get_hour_prices(self):
        """
        Fetches electricity prices for today or tomorrow based on the current time.
        """
        # Get prices for today or tomorrow if after 23:00
        if self.hour_now < 24:
            now = int(datetime.datetime.now().strftime("%Y%m%d"))
            now1 = int((datetime.datetime.now() + datetime.timedelta(days=2, hours=0)).strftime("%Y%m%d"))
        else:
            now = int((datetime.datetime.now() + datetime.timedelta(days=1, hours=0)).strftime("%Y%m%d"))
            now1 = int((datetime.datetime.now() + datetime.timedelta(days=2, hours=0)).strftime("%Y%m%d"))

        url = "https://web-api.tp.entsoe.eu/api?documentType=A44&in_Domain=10YNL----------L&out_Domain=10YNL----------L&securityToken=" + self.cfg["entsoe"]["key"] + "&periodStart=" + str(now) + "0000&periodEnd=" + str(now1) + "0000"
        xml = requests.get(url)
        soup = bs4.BeautifulSoup(xml.content, 'xml')

        # Check if we received a result
        if len(soup.find_all('Point')) == 0:
            self.notify('No result from entsoe')
            # No result, get forecast from file
            print("No result from entsoe")
            with open('entsoe.xml', 'r') as f:
                xml = f.read()
            soup = bs4.BeautifulSoup(xml, 'xml')
        else:
            # Save forecast to file
            try:
                with open("entsoe.xml", 'w+') as file:
                    file.write(str(xml.content))
            except (IOError, OSError):
                print("Error writing to file")

        # Correct index hour 1 = 0:00, 2 = 1:00 etc
        price_hour = {}
        p48 = {}
        x = 24
        if len(soup.find_all('timeseries')) > 1:
            x = 48

        # Process each TimeSeries individually
        series_offset = 0  # Keep track of where the points start (0 or 24)
        for timeseries in soup.find_all('TimeSeries'):
            for point in timeseries.find_all('Point'):
                position = int(point.find('position').text) - 1 + series_offset
                p48[position] = float(point.find('price.amount').text)
            series_offset += 24  # Increase offset for the next TimeSeries

        # Fill in any missing values
        for i in range(x):  # Since there are at most 48 points (2 * 24)
            if i not in p48:
                p48[i] = p48[i - 1] if i > 0 else 0  # Use the previous value or 0
            if i < 24:  # Only the first 24 to price_hour
                price_hour[i] = p48[i]

        # Sort the p48 dictionary by key
        p48 = dict(sorted(p48.items()))
        self.p24 = price_hour
        self.p48 = p48

    def get_forecast(self):
        """
        Fetches solar production forecasts from the forecast.solar API.
        """
        config = self.cfg["forecast.solar"]
        url = 'https://api.forecast.solar/estimate/' + str(config["lat"]) + "/" + str(config["long"]) + "/" + str(config["dec"]) + "/" + str(config["az"]) + "/" + str(config["kwp"])
        headers = {
            "content-type": "application/json"
        }
        estimate = requests.request("GET", url, headers=headers).json()

        # Check if we received a result
        if estimate['result'] is None or estimate['result'] == 'Rate limit for API calls reached.':
            self.notify('No result from forecast.solar')
            # No result, get forecast from file
            with open('forecast.json') as f:
                estimate = json.load(f)
        else:
            # Save forecast to file
            try:
                with open("forecast.json", 'w+') as file:
                    file.write(json.dumps(estimate))
            except (IOError, OSError):
                print("Error writing to file")

        now = datetime.datetime.now()
        tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1, hours=0)).replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate total forecast production for today from now until 24:00
        production_start = 0
        to_produce = 0

        if "watt_hours_period" in estimate['result']:
            for hour in estimate['result']['watt_hours_period']:
                hour_time_obj = datetime.datetime.strptime(hour, '%Y-%m-%d %H:%M:%S')
                if hour_time_obj > now and hour_time_obj < tomorrow:
                    if estimate['result']['watt_hours_period'][hour] > 1000 and production_start == 0:
                        production_start = hour_time_obj.strftime('%-H')
                    to_produce += estimate['result']['watt_hours_period'][hour] / 1000

        self.production_start = int(production_start)
        self.production_today = 0

    def get_low(self):
        """
        Determines the lowest prices for the next 24 hours and the next day.
        """
        p24 = self.p24.copy()
        ranking = []

        while len(ranking) < 3:
            low = min(p24, key=p24.get)
            p24.pop(low)
            if low < 24:
                ranking.append(low)

        self.low = sorted(ranking)
        self.ranking = ranking

        ranking = []
        p48 = self.p48.copy()

        if len(p48) > 24:
            while len(ranking) < 3:
                low = min(p48, key=p48.get)
                p48.pop(low)
                if low > 23:
                    ranking.append(low)
            self.lowTomorrow = sorted(ranking)

    def selling_first(self, p):
        """
        Enables the 'sell first' mode for the battery system.

        Args:
            p (int): The price to set for selling first.
        """
        self.notify('Sell first ON')
        set_points = [0, 100, 200, 300, 400, 500]
        loads = [p, p, p, p, p, p]
        load_points = [0, 0, 0, 0, 0, 0]
        self.write_to_batt(set_points, loads, load_points)

        # Set selling first
        self.modbus.write_multiple_holding_registers(register_addr=142, values=[0])
        exit()

    def write_to_batt(self, set_points, loads, load_points):
        """
        Writes the set points, loads, and load points to the battery.

        Args:
            set_points (list): List of set points to write.
            loads (list): List of loads to write.
            load_points (list): List of load points to write.
        """
        # Set time 1
        self.modbus.write_multiple_holding_registers(register_addr=148, values=set_points)
        # Set loads
        self.modbus.write_multiple_holding_registers(register_addr=166, values=loads)
        # Set load points
        self.modbus.write_multiple_holding_registers(register_addr=172, values=load_points)
        self.notify(str(set_points) + '\n' + str(load_points) + '\n' + str(loads))
        self.modbus.write_multiple_holding_registers(register_addr=142, values=[1])

    def calc_load_points(self):
        """
        Calculates the load points needed for today based on battery capacity and price points.
        """
        # Current capacity (kWh) of the battery
        bat_load = self.perc * self.batt_capacity / 100
        # Load needed today until 18:00
        load_today = (18 - self.hour_now) * self.batt_capacity * self.cfg["kiwatt"]["unload_perc_hour"] / 100
# Max load capacity of the battery (kWh)
        maxload = float(self.modbus.read_holding_registers(register_addr=108, quantity=1)[0]) * 50 / 1000

        # Position of setpoint in time
        count = 0
        # Calculated load before this setpoint
        calc_load = 0
        ranking = self.ranking.copy()
        prev_rank = 0

        for setpoint in self.low:
            # Check if setpoint is in the future
            if setpoint < self.hour_now:
                ranking.pop(ranking.index(setpoint))
                continue

            # Get position of setpoint in ranking (cheapest first)
            rank = ranking.index(setpoint)
            # Calculate kWh needed to load battery to max_percload
            to_load = self.batt_capacity * self.cfg["kiwatt"]["max_percload"] / 100 - (bat_load + self.production_today - load_today + calc_load)
            # Calculate hours to correct based on ranking and cheapest price
            correct = 0
            if rank == 1 and prev_rank == 2:
                correct = 1
            if correct == 0 and rank - count >= 0:
                correct = rank - count

            # Calculate load hours
            load_hours = to_load / maxload - correct
            prev_rank = rank

            if load_hours <= 0:
                load_hours = 0
            else:
                # Round up to full hour
                if load_hours > 1:
                    load_hours = 1
                # Calculate load percentage this hour max if cheapest
                if rank == 0:
                    load_perc = self.cfg["kiwatt"]["max_percload"]
                else:
                    load_perc = int(round(self.perc + (((load_hours * maxload) + calc_load) / (self.batt_capacity / 100)), 0))

                if load_perc > self.cfg["kiwatt"]["max_percload"]:
                    load_perc = self.cfg["kiwatt"]["max_percload"]

                # Add load to calculated load for next hour
                calc_load += load_hours * maxload

                # Check if setpoint is already in list
                if (setpoint * 100) in self.set_points:
                    self.set_points.remove(setpoint * 100)
                    self.load_points.pop()
                    self.loads.pop()

                # Add setpoint to list
                self.set_points.append(setpoint * 100)
                self.load_points.append(1)
                self.loads.append(load_perc)

                # Add next setpoint to list to stop charging
                self.set_points.append((setpoint + 1) * 100)
                self.load_points.append(0)
                self.loads.append(self.cfg["kiwatt"]["min_percload"])

            # Stop after 5 setpoints to be able to stop charging after setpoint 5
            if len(self.set_points) >= 5:
                break

            count += 1

        # Check if setpoint list is full
        if len(self.set_points) < 6:
            # Add self.set_points to fill list
            for x in range(6 - len(self.set_points)):
                # Check if last setpoint empty
                if len(self.set_points) == 0:
                    last = 2300
                else:
                    # Get last setpoint
                    last = (self.set_points[len(self.set_points) - 1])

                # Check if last setpoint is before 22:59
                if last <= 2259:
                    self.set_points.append(last + 100)
                else:
                    # Add setpoint at 0:00
                    self.set_points.append(0)

                self.load_points.append(0)
                self.loads.append(self.cfg["kiwatt"]["min_percload"])

        # Read current setpoints, loads, and loadpoints
        set_points_now = self.modbus.read_holding_registers(register_addr=148, quantity=6)
        loads_now = self.modbus.read_holding_registers(register_addr=166, quantity=6)
        load_points_now = self.modbus.read_holding_registers(register_addr=172, quantity=6)

        # Check if we need to update the battery settings
        if (set_points_now != self.set_points or loads_now != self.loads or load_points_now != self.load_points):
            self.write_to_batt(self.set_points, self.loads, self.load_points)

    def notify_ha(self):
        """
        Notifies Home Assistant about the current battery status and price points.
        """
        client = Client(self.cfg["homeassistant"]["url"], self.cfg["homeassistant"]["token"])
        sensor = client.get_entity(entity_id='sensor.load_now')
        myprices = []
        prices = []
        points = []

        low_today = 99
        high_today = 0
        low_tomorrow = 99
        high_tomorrow = 0

        for x in range(0, 48):
            price = round((self.p48[x] / 1000 + 0.14349) * 1.21, 3) if x in self.p48 else 0

            if x < 24:
                load = {
                    "time": datetime.datetime.now().strftime("%Y-%m-%d") + " {:02d}".format(x) + ":30:00+01:00",
                    "price": '{:.3f}'.format(price)
                }
                if price < low_today:
                    low_today = price
                if price > high_today:
                    high_today = price
                if x in self.low:
                    points.append(load)
                else:
                    myprices.append(load)
            else:
                load = {
                    "time": (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d") + " {:02d}".format(x - 24) + ":30:00+01:00",
                    "price": '{:.3f}'.format(price)
                }
                if price < low_tomorrow:
                    low_tomorrow = price
                if price > high_tomorrow:
                    high_tomorrow = price
                prices.append(load)

        # Update sensor attributes
        sensor.state.attributes["loads"] = points
        sensor.state.attributes["myprices"] = myprices
        sensor.state.attributes["prices"] = prices
        sensor.state.attributes["low_today"] = low_today
        sensor.state.attributes["high_today"] = high_today
        sensor.state.attributes["low_tomorrow"] = low_tomorrow
        sensor.state.attributes["high_tomorrow"] = high_tomorrow

        client.set_state(sensor.state)