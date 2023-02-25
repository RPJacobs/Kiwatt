# Kiwatt
# Auto loading KIWATT inverter 10,0kW with ANWB Energie Dynamic Contract | lowest prices ENTSO-e (API)

I've installed a Kiwatt inverter and two 10kWh batteries:

<img height="300" alt="Screenshot 2023-02-23 at 09 18 32" src="https://user-images.githubusercontent.com/14312145/220854538-416808c0-96b3-41f8-97b2-c44dee61343a.png">

ANWB Dynamic Energy Contract, hourly prices.

<img src="https://user-images.githubusercontent.com/14312145/220854731-5550bcd1-854c-43cb-a98e-d735a17f873a.PNG" height="300">

Goal is to set this load table in the inverter

<img height="300" alt="Screenshot 2023-02-23 at 09 18 44" src="https://user-images.githubusercontent.com/14312145/220854820-4989714c-4a38-49a9-a28e-bf756e7a9e68.png">

Let's start with a dongle connected to the inverter

<img height="300" alt="Screenshot 2023-02-23 at 09 22 43" src="https://user-images.githubusercontent.com/14312145/220855304-c6b4198d-ca3e-4d40-bea0-fc1c33505ef4.png">

It's a 'stick logger', my best friend google told me it is a SOFAR, SOLARMAN LS4G-3. Here is a manual (in dutch) found the default user and password (admin/admin)

https://www.woud-energieadvies.nl/wp-content/uploads/2020/03/Wi-Fi-installatie-Sofar-Solar.pdf

After connecting the logger to my local network it aumatically connected to a remote server. It connects to https://pro.solarmanpv.com/ you can create an account and based on the serial nummer of the logger (security issue!!) you can read al kinds of data. Inverter Type：Three phase LV Hybrid! This learned me that my inverter is also sold as Deye and Sunsynk. Interesting; goal number 2, block external connection. Google a bit more and I found the config page. http://x.x.x.x/config_hide.html here you can remove or change the remote server settings.

After a quick portscan: 8899. A modbus interface, found a library: https://github.com/jmccrohan/pysolarmanv5 with great documentation!

Now we need to find the modbus documentation of our inverter. Scanning the registry with pysolarmanv5 showed me the registers 0-900 and 10000-20000 are used. Also discoverd the SOC (battery percentage) as register 588. Eventually i used https://github.com/StephanJoubert/home_assistant_solarman to read all values to a home assistent setup. Reading is fine but i needed to write the registers! Used the config file form StephanJoubert: deye_sg04lp3.yaml and a lot of googling later a found a word doc in a forum with the documentation.

[Modbus amit posun.docx](https://github.com/RPJacobs/Kiwatt/files/10811793/Modbus.amit.posun.docx)

<img width="669" alt="Screenshot 2023-02-23 at 09 53 16" src="https://user-images.githubusercontent.com/14312145/220860907-b6f4aa94-ab9b-4062-a07b-d40fe0824008.png">

With the registers I needed:

<img width="1052" alt="Screenshot 2023-02-23 at 09 54 34" src="https://user-images.githubusercontent.com/14312145/220861173-68662120-c226-4191-9f8a-2651a7836437.png">

pysolarmanv5 test code:

```python
""" Scan Modbus registers to find valid registers"""
from pysolarmanv5 import PySolarmanV5
import requests

def main():
    modbus = PySolarmanV5(
        "x.x.x.x", 2713xxxxxx, port=8899, mb_slave_id=1, verbose=0
    )
    """Times"""
    print(modbus.read_holding_registers(register_addr=148, quantity=6))
    """Percentage"""
    print(modbus.read_holding_registers(register_addr=166, quantity=6))
    """Enable grid charge"""
    print(modbus.read_holding_registers(register_addr=172, quantity=6))
    
    """set time 1"""
    modbus.write_multiple_holding_registers(register_addr=148, values=[100, 300, 900, 1300, 1800, 2100])

    """Times"""
    print(modbus.read_holding_registers(register_addr=148, quantity=6))
    
if __name__ == "__main__":
    main()
```

Now all I needed was an API with the price forcast.

https://doe-duurzaam.nl/2023/01/02/dynamische-energieprijzen-inlezen-met-home-assistant-zo-doe-je-dat/ Helped me to find ENTSO-e.

And ofcourse there is a library: https://github.com/EnergieID/entsoe-py

My script can now:
  1. Download an XML with day_ahead_prices.
  2. find the lowest prices (3 hours to load all 20kWh)
  3. programm the inverter to load from grid.
  
# Installation

pip install pysolarmanv5

pip install entsoe-py

pip install beautifulsoup4


[My File](../master/entso.py)

Used a cronjob to load the script @23:00 and telegram to send me an update...

TO DO: optimise load window.
