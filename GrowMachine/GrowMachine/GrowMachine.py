#!/usr/bin/env python
# -*- coding: utf-8 -*-

#############################
# see: https://apscheduler.readthedocs.org/en/latest/userguide.html#adding-jobs
# for scheduler (package already installed)
#############################

import logging
import logging.config
logging.config.fileConfig('logging.config')

from apscheduler.schedulers.background import BackgroundScheduler
from ConfigParser import *
import RPi.GPIO as GPIO                            #provides pin support
import os.path

import ATT_IOT as IOT                              #provide cloud support
from time import sleep                             #pause the app
from datetime import datetime                      # get the current hour to set the lights when the device is turned on.
import Network

#set up the ATT internet of things platform

IOT.DeviceId = ""
IOT.ClientId = ""
IOT.ClientKey = ""

TempSensorName = "Temperature"                                #name of the button
TempSensorPin = 1

WaterLevelSensorName = "Water level"                                #name of the button
WaterLevelSensorPin = 2

LightsRelaisName = "Lights"
LightsRelaisPin = 18
LightRelaisState = False

WaterRelaisName = "Irrigation"
WaterRelaisPin = 16
WaterRelaisState = False                                        # keep track of the current state of the water relais.  We try to set it off every 10 seconds, if it's on (flood/pomp dry prevention)

ConfigSeasonName = "Season"
ConfigSeasonId = 9
ConfigFile = 'growmachine.config'

IsConnected = False                                                 # so we know if we already connected to cloud succesfully or not.

#setup GPIO using Board numbering
#alternative:  GPIO.setmode(GPIO.BCM)
GPIO.setmode(GPIO.BOARD)

#set up the pins
#GPIO.setup(SensorPin, GPIO.IN, pull_up_down=GPIO.PUD_UP)  #, pull_up_down=GPIO.PUD_DOWN
GPIO.setup(LightsRelaisPin, GPIO.OUT)
GPIO.setup(WaterRelaisPin, GPIO.OUT)
GPIO.output(WaterRelaisPin, True)                   # make certain wather is turned off at startup, pin takes reversed value. Do before everything else: so that the water doesn't keep on running if something else went wrong.		

def setConfigSeason(value):
    try:
        global scheduler
        IOT.send(value, ConfigSeasonId)                 #first return value, in case something went wrong, the config is first stored, so upon restart, the correct config is retrieved.
        configs = ConfigParser()                        # save the configuration
        configs.set('general', 'season', value)
        with open(ConfigFile, 'w') as f:
            configs.write(f)
        if scheduler:
            scheduler.shutdown(wait=False)                      # stop any pending jobs so we can recreate them with the new config later on.
            scheduler = None
        SetClock(value.lower())
        StartScheduler()
    except:
        logging.exception('failed to store new season config')


#callback: handles values sent from the cloudapp to the device
def on_message(id, value):
    global WaterRelaisState
    if id.endswith(str(LightsRelaisPin)) == True:
        value = value.lower()                        #make certain that the value is in lower case, for 'True' vs 'true'
        if value == "true": SwitchLightsOn()
        elif value == "false": SwitchLightsOff()
        else: logging.error("unknown value: " + value)
    elif id.endswith(str(WaterRelaisPin)) == True:
        value = value.lower()                        #make certain that the value is in lower case, for 'True' vs 'true'
        if value == "true": TurnWaterOn()
        elif value == "false": TurnWaterOff()
        else: logging.error("unknown value: " + value)
    elif id.endswith(str(ConfigSeasonId)) == True:
        setConfigSeason(value.lower())
    else:
        logging.error("unknown actuator: " + id)
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

def LoadConfig(season = None):
    '''
    load the previously stored configurations and set accordingly
    first tries from the cloud,if that is not available, from previously stored config file.
    :param season: the season to use. When not specified, will be loaded from config file
    '''
    try:
        if not season and os.path.isfile(ConfigFile):
            configs = ConfigParser()
            if configs.read(ConfigFile):
                season = configs.get('general', 'season')
        if season:
            logging.info("found season: " + str(season))
            if season[unicode('state')]:
                logging.info("setting to season: " + str(season))
                SetClock(str(season[unicode('state')][unicode('value')]))
        currentHour = datetime.now().hour
        logging.info("current hour: " + str(currentHour))
        if currentHour >= CycleStart and currentHour <= CycleEnd:
            SwitchLightsOn()
        else:
            SwitchLightsOff()
    except:
        logging.exception('failed to load config')
    

def SwitchLightsOn():
    '''Switch the lights on'''
    global LightRelaisState
    try:
        LightRelaisState = True
        GPIO.output(LightsRelaisPin, False)     # pin takes reversed value
        if IsConnected:                         # no need to try and send the state if not yet connected, will be updated when connection is successfull
            IOT.send('true', LightsRelaisPin)
    except:
        logging.exception('failed to switch lights on')

def SwitchLightsOff():
    '''Switch the lights off'''
    global LightRelaisState
    try:
        LightRelaisState = False
        GPIO.output(LightsRelaisPin, True)      #pin is reversed value
        if IsConnected:                         # no need to try and send the state if not yet connected, will be updated when connection is successfull
            IOT.send('false', LightsRelaisPin)
    except:
        logging.exception('failed to switch lights off')

def TurnWaterOn():
    global WaterRelaisState
    '''Turn the water on'''
    try:
        GPIO.output(WaterRelaisPin, False)      # pin takes reversed value.
        WaterRelaisState = True
        if IsConnected:                         # no need to try and send the state if not yet connected, will be updated when connection is successfull
            IOT.send("true", WaterRelaisPin)
    except:
        logging.exception('failed to turn water on')
	

def TurnWaterOff():
    '''Turn the water off'''
    global WaterRelaisState
    try:
        if WaterRelaisState == True:
            GPIO.output(WaterRelaisPin, True)       # pin takes reversed value
            WaterRelaisState = False
            if IsConnected:                         # no need to try and send the state if not yet connected, will be updated when connection is successfull
                IOT.send("false", WaterRelaisPin)
    except:
        logging.exception('failed to turn water off')


scheduler = None                                                        # init the scheduler so other functions can also reach it.
def StartScheduler():
    '''start the scheduler to turn on/off the lights and the watersystem'''
    global scheduler 
    logging.info('starting scheduler (' + CycleStr + ')...')
    if not scheduler: 
        scheduler = BackgroundScheduler()
    scheduler.add_job(SwitchLightsOn, 'cron', hour=CycleStart)            # at 9 (on) and at 21 hours (off)
    scheduler.add_job(SwitchLightsOff, 'cron', hour=CycleEnd)            # at 9 (on) and at 21 hours (off)
    scheduler.add_job(TurnWaterOn, 'cron', hour=CycleStr)             # every hour between 9 and 21
    scheduler.add_job(TurnWaterOff, 'cron', second='*/15')              # check every 10 seconds: should the water be turned off (day and night is savest)
    try:
        scheduler.start()
        logging.info('schedule set')
    except (KeyboardInterrupt, SystemExit):                         # so we can get out of a start when tryin to stop the app
        pass


def tryConnect():
    global IsConnected
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
            try:
                season = IOT.getAssetState(ConfigSeasonId)
            except:
                logging.exception('failed to get asset state')
            LoadConfig(season)                                     # load the cloud settings into the appbefore closing the http connection. otherwise this call fails.
            IOT.subscribe()              							#starts the bi-directional communication
            sleep(2)                                                    # wait 2 seconds until the subscription has succeeded (bit of a hack, better would be to use the callback)
            IsConnected = True
            IOT.send(str(LightRelaisState).lower(), LightsRelaisPin)       # provide feedback to the platform of the current state of the light (after startup), this failed while loading config, cause mqtt is not yet set up.
            IOT.send(str(WaterRelaisState).lower(), WaterRelaisPin)
    except:
        logging.exception("failed to set up the connection with the cloud")
        IsConnected = False

try:
    tryConnect()
    if IsConnected == False:
        LoadConfig()                                    # try to load a previously stored config
    StartScheduler()
# main loop: run as long as the device is turned on
    while True:
        if IsConnected == False:
            tryConnect()
        sleep(10)
except (KeyboardInterrupt, SystemExit):
    if scheduler:
        scheduler.shutdown(wait=False)                  # make certain that other threads are stopped. 
    exit(0)
