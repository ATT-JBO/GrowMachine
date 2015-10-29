#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################
# see: https://apscheduler.readthedocs.org/en/latest/userguide.html#adding-jobs
# for scheduler (package already installed)
#############################

import logging
logging.basicConfig()

from apscheduler.schedulers.blocking import BlockingScheduler

import RPi.GPIO as GPIO                            #provides pin support
import ATT_IOT as IOT                              #provide cloud support
from time import sleep                             #pause the app
from datetime import datetime                      # get the current hour to set the lights when the device is turned on.
import Network

#set up the ATT internet of things platform

IOT.DeviceId = "3QpxZucPWJjrugpsIPys6aC"
IOT.ClientId = "KardCard"
IOT.ClientKey = "42pprmkiubr"

TempSensorName = "Temperature"                                #name of the button
TempSensorPin = 1

WaterLevelSensorName = "Water level"                                #name of the button
WaterLevelSensorPin = 2

LightsRelaisName = "Lights"
LightsRelaisPin = 18

WaterRelaisName = "Irrigation"
WaterRelaisPin = 16
WaterRelaisState = False                                        # keep track of the current state of the water relais.  We try to set it off every 10 seconds, if it's on (flood/pomp dry prevention)

ConfigSeasonName = "Season"
ConfigSeasonId = 9

#setup GPIO using Board numbering
#alternative:  GPIO.setmode(GPIO.BCM)
GPIO.setmode(GPIO.BOARD)

#set up the pins
#GPIO.setup(SensorPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)  #, pull_up_down=GPIO.PUD_DOWN
GPIO.setup(LightsRelaisPin, GPIO.OUT)
GPIO.setup(WaterRelaisPin, GPIO.OUT)
GPIO.output(WaterRelaisPin, True)                   # make certain wather is turned off at startup, pin takes reversed value. Do before everything else: so that the water doesn't keep on running if something else went wrong.		

#callback: handles values sent from the cloudapp to the device
def on_message(id, value):
    global WaterRelaisState, scheduler
    if id.endswith(str(LightsRelaisPin)) == True:
        value = value.lower()                        #make certain that the value is in lower case, for 'True' vs 'true'
        if value == "true":
            GPIO.output(LightsRelaisPin, False)              # pins are reversed
            IOT.send("true", LightsRelaisPin)                #provide feedback to the cloud that the operation was succesful
        elif value == "false":
            GPIO.output(LightsRelaisPin, True)
            IOT.send("false", LightsRelaisPin)                #provide feedback to the cloud that the operation was succesful
        else:
            print("unknown value: " + value)
    elif id.endswith(str(WaterRelaisPin)) == True:
        value = value.lower()                        #make certain that the value is in lower case, for 'True' vs 'true'
        if value == "true":
            WaterRelaisState = True
            GPIO.output(WaterRelaisPin, False)              # pins are reversed
            IOT.send("true", WaterRelaisPin)                #provide feedback to the cloud that the operation was succesful
        elif value == "false":
            WaterRelaisState = False
            GPIO.output(WaterRelaisPin, True)
            IOT.send("false", WaterRelaisPin)                #provide feedback to the cloud that the operation was succesful
        else:
            print("unknown value: " + value)
    elif id.endswith(str(ConfigSeasonId)) == True:
        IOT.send(value.lower(), ConfigSeasonId)                 #first return value, in case something went wrong, the config is first stored, so upon restart, the correct config is retrieved.
        if scheduler:
            scheduler.shutdown(wait=False)                      # stop any pending jobs so we can recreate them with the new config later on.
            scheduler = None
        SetClock(value.lower())
        StartScheduler()
    else:
        print("unknown actuator: " + id)
IOT.on_message = on_message

CycleStart = 9
CycleEnd = 21
CycleStr = '9-21'

def SetClock(season):
    global CycleStart, CycleEnd, CycleStr
    if season == 'grow':
        'set to 18 hour cycle'
        CycleStart = 5
        CycleEnd = 23
        CycleStr = '5-23'
    elif season == 'flower':
        'set to 12 hour cycle'
        CycleStart = 9
        CycleEnd = 21
        CycleStr = '9-21'

def LoadConfig():
    '''
    load the previously stored configurations and set accordingly
    '''
    season = IOT.getAssetState(ConfigSeasonId)
    if season:
        print "found season: " + str(season)
        if season[unicode('state')]: 
            print "setting to season: " + str(season)
            SetClock(str(season[unicode('state')][unicode('value')]))
    #todo: calculate the current light setting and set it
    currentHour = datetime.now().hour
    print "current hour: " + str(currentHour)
    if currentHour >= CycleStart and currentHour <= CycleEnd:
        GPIO.output(LightsRelaisPin, False)                         # inversed value for pin
        return True
    else:
        GPIO.output(LightsRelaisPin, True)
        return False
    

def SwitchLightsOn():
    '''Switch the lights on'''
    GPIO.output(LightsRelaisPin, False)     # pin takes reversed value
    IOT.send('true', LightsRelaisPin) 

def SwitchLightsOff():
    '''Switch the lights off'''
    GPIO.output(LightsRelaisPin, True)      #pin is reversed value
    IOT.send('false', LightsRelaisPin) 

def TurnWaterOn():
    global WaterRelaisState
    '''Turn the water on'''
    WaterRelaisState = True
    GPIO.output(WaterRelaisPin, False)      # pin takes reversed value.
    IOT.send("true", WaterRelaisPin) 

def TurnWaterOff():
    '''Turn the water off'''
    global WaterRelaisState
    if WaterRelaisState == True:
        WaterRelaisState = False
        GPIO.output(WaterRelaisPin, True)       # pin takes reversed value
        IOT.send("false", WaterRelaisPin) 


scheduler = None                                                        # init the scheduler so other functions can also reach it.
def StartScheduler():
    '''start the scheduler to turn on/off the lights and the watersystem'''
    global scheduler 
    print 'starting scheduler (' + CycleStr + ')...'
    if not scheduler: 
        scheduler = BlockingScheduler()
    scheduler.add_job(SwitchLightsOn, 'cron', hour=CycleStart)            # at 9 (on) and at 21 hours (off)
    scheduler.add_job(SwitchLightsOff, 'cron', hour=CycleEnd)            # at 9 (on) and at 21 hours (off)
    scheduler.add_job(TurnWaterOn, 'cron', hour=CycleStr)             # every hour between 9 and 21
    scheduler.add_job(TurnWaterOff, 'cron', second='*/15')              # check every 10 seconds: should the water be turned off (day and night is savest)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


try:
    networkCheckCount = 0
    while Network.isConnected() == False and networkCheckCount < 5:             # we check a number of times to give the network more time to start up.
        networkCheckCount = networkCheckCount + 1
        sleep(2)
    if Network.isConnected() == False:
        logging.error("failed to set up network connection")
    else:
        #make certain that the device & it's features are defined in the cloudapp
        IOT.connect()
        #IOT.addAsset(TempSensorPin, TempSensorName, "temperature", False, "number", "Secondary")
        #IOT.addAsset(WaterLevelSensorPin, WaterLevelSensorName, "Water level", False, "number", "Secondary")
        IOT.addAsset(LightsRelaisPin, LightsRelaisName, "Turn the lights on/off", True, "boolean", "Primary")
        IOT.addAsset(WaterRelaisPin, WaterRelaisName, "Turn the water flow on/off", True, "boolean", "Primary")
        IOT.addAsset(ConfigSeasonId, ConfigSeasonName, "Configure the season", True, "{'type': 'string','enum': ['grow', 'flower']}", 'Config')
        lightsOn = LoadConfig()                                            # load the previously stored settings before closing the http connection. otherwise this call fails.
        IOT.subscribe()              							#starts the bi-directional communication
        sleep(2)                                                    # wait 2 seconds until the subscription has succeeded (bit of a hack, better would be to use the callback)
        IOT.send(str(lightsOn).lower(), LightsRelaisPin)             # provide feedback to the platform of the current state of the light (after startup)
        IOT.send("false", WaterRelaisPin) 
except:
    logging.exception("failed to set up the connection with the cloud")
StartScheduler()

try:
# main loop: run as long as the device is turned on
    while True:
#    if GPIO.input(SensorPin) == 0:                        #for PUD_DOWN, == 1
#        if SensorPrev == False:
#            print(SensorName + " activated")
#            IOT.send("true", SensorPin)
#            SensorPrev = True
#    elif SensorPrev == True:
#        print(SensorName + " deactivated")
#        IOT.send("false", SensorPin)
#        SensorPrev = False
        sleep(10)
except (KeyboardInterrupt, SystemExit):
    if scheduler:
        scheduler.shutdown(wait=False)                  # make certain that other threads are stopped. 
    exit(0)
