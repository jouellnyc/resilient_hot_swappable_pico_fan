# base_mq.py
# Base class for MQ gas sensors
# Ported from https://github.com/amperka/TroykaMQ

from machine import Pin, ADC
from micropython import const
import utime
from math import exp, log

class BaseMQ(object):
    ## Measuring attempts in cycle
    MQ_SAMPLE_TIMES = const(5)

    ## Delay after each measurement, in ms
    MQ_SAMPLE_INTERVAL = const(5000)

    ## Heating period, in ms
    MQ_HEATING_PERIOD = const(60000)

    ## Cooling period, in ms
    MQ_COOLING_PERIOD = const(90000)

    ## This strategy measure values immediately, so it might be inaccurate
    STRATEGY_FAST = const(1)

    ## This strategy measure values separately
    STRATEGY_ACCURATE = const(2)    

    def __init__(self, pinData, pinHeater=-1, boardResistance=10, baseVoltage=5.0, measuringStrategy=2):
        self._heater = False
        self._cooler = False
        self._ro = -1       
        self._useSeparateHeater = False
        self._baseVoltage = baseVoltage
        self._lastMeasurement = utime.ticks_ms()
        self._rsCache = None
        self.dataIsReliable = False
        self.pinData = ADC(pinData)
        self.measuringStrategy = measuringStrategy
        self._boardResistance = boardResistance
        
        if pinHeater != -1:
            self._useSeparateHeater = True
            self.pinHeater = Pin(pinHeater, Pin.OUTPUT)

    def getRoInCleanAir(self):
        raise NotImplementedError("Please Implement this method")

    def calibrate(self, ro=-1):
        if ro == -1:
            ro = 0
            print("Calibrating MQ sensor:")
            for i in range(0, self.MQ_SAMPLE_TIMES + 1):        
                print("Step {0}".format(i))
                ro += self.__calculateResistance__(self.pinData.read_u16())
                utime.sleep_ms(self.MQ_SAMPLE_INTERVAL)
            ro = ro / (self.getRoInCleanAir() * self.MQ_SAMPLE_TIMES)
        self._ro = ro
        print("Calibration complete. RO = {0}".format(ro))

    def heaterPwrHigh(self):
        if self._useSeparateHeater:
            self.pinHeater.on()
        self._heater = True
        self._prMillis = utime.ticks_ms()

    def heaterPwrLow(self):
        self._heater = True
        self._cooler = True
        self._prMillis = utime.ticks_ms()

    def heaterPwrOff(self):
        if self._useSeparateHeater:
            self.pinHeater.off()
        self._heater = False

    def __calculateResistance__(self, rawAdc):
        # Convert from Pico's 0-65535 to voltage
        vrl = rawAdc * (self._baseVoltage / 65535)
        rsAir = (self._baseVoltage - vrl) / vrl * self._boardResistance
        return rsAir

    def __readRs__(self):
        if self.measuringStrategy == self.STRATEGY_ACCURATE:            
            rs = 0
            for i in range(0, self.MQ_SAMPLE_TIMES + 1): 
                rs += self.__calculateResistance__(self.pinData.read_u16())
                utime.sleep_ms(self.MQ_SAMPLE_INTERVAL)
            rs = rs / self.MQ_SAMPLE_TIMES
            self._rsCache = rs
            self.dataIsReliable = True
            self._lastMeasurement = utime.ticks_ms()
        else:
            rs = self.__calculateResistance__(self.pinData.read_u16())
            self.dataIsReliable = False
        return rs

    def readScaled(self, a, b):        
        return exp((log(self.readRatio()) - b) / a)

    def readRatio(self):
        if self._ro == -1:
            print("Sensor not calibrated!")
            return 0
        return self.__readRs__() / self._ro

    def heatingCompleted(self):
        if (self._heater) and (not self._cooler) and (utime.ticks_diff(utime.ticks_ms(), self._prMillis) > self.MQ_HEATING_PERIOD):
            return True
        else:
            return False

    def coolanceCompleted(self):
        if (self._heater) and (self._cooler) and (utime.ticks_diff(utime.ticks_ms(), self._prMillis) > self.MQ_COOLING_PERIOD):
            return True
        else:
            return False

    def cycleHeat(self):
        self._heater = False
        self._cooler = False
        self.heaterPwrHigh()
        print("Heating sensor")

    def atHeatCycleEnd(self):
        if self.heatingCompleted():
            self.heaterPwrLow()
            print("Cooling sensor")
            return False
        elif self.coolanceCompleted():
            self.heaterPwrOff()
            return True
        else:
            return False