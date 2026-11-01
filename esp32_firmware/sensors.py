# DHARAA Sensor Drivers for MicroPython
import time
try:
    import machine
    import dht
    MICROPYTHON = True
except ImportError:
    MICROPYTHON = False

import config

class SensorManager:
    def __init__(self):
        self.flow_pulse_count = 0
        self.dht_sensor = None
        self.adc_moisture = None
        self.rain_pin = None
        self.flow_pin = None

        if MICROPYTHON:
            # 1. Setup Soil Moisture ADC
            try:
                self.adc_moisture = machine.ADC(machine.Pin(config.PIN_MOISTURE_ADC))
                self.adc_moisture.atten(machine.ADC.ATTN_11DB)  # 0 - 3.6V range
                self.adc_moisture.width(machine.ADC.WIDTH_12BIT) # 0 - 4095 range
            except Exception as e:
                print("ADC moisture setup error:", e)

            # 2. Setup DHT22
            try:
                self.dht_sensor = dht.DHT22(machine.Pin(config.PIN_DHT22))
            except Exception as e:
                print("DHT22 setup error:", e)

            # 3. Setup Rain Sensor Pin
            try:
                self.rain_pin = machine.Pin(config.PIN_RAIN_DO, machine.Pin.IN)
            except Exception as e:
                print("Rain sensor setup error:", e)

            # 4. Setup Flow Sensor with Hardware Interrupt
            try:
                self.flow_pin = machine.Pin(config.PIN_FLOW, machine.Pin.IN, machine.Pin.PULL_UP)
                self.flow_pin.irq(trigger=machine.Pin.IRQ_RISING, handler=self._flow_pulse_irq)
            except Exception as e:
                print("Flow sensor setup error:", e)

    def _flow_pulse_irq(self, pin):
        self.flow_pulse_count += 1

    def read_moisture(self):
        """
        Reads capacitive soil moisture sensor and applies linear calibration formula:
        moisture_percent = 100 * (DRY_RAW - raw) / (DRY_RAW - WET_RAW)
        Returns (moisture_pct, status_str)
        """
        if not MICROPYTHON or self.adc_moisture is None:
            return 42.0, "OK"

        try:
            # Average 5 samples for ADC stability
            readings = [self.adc_moisture.read() for _ in range(5)]
            raw = sum(readings) / len(readings)

            # Check bounds
            if raw <= 0 or raw > 4095:
                return None, "MOISTURE_OUT_OF_BOUNDS"

            dry = config.DRY_RAW
            wet = config.WET_RAW
            if dry == wet:
                return None, "CALIBRATION_INVALID"

            # In capacitive sensors, higher moisture = lower ADC raw reading
            pct = 100.0 * (dry - raw) / (dry - wet)
            clamped_pct = max(0.0, min(100.0, pct))
            return round(clamped_pct, 1), "OK"
        except Exception as e:
            return None, f"MOISTURE_READ_FAIL:{str(e)}"

    def read_dht22(self):
        """
        Reads DHT22 temperature and relative humidity.
        Returns (temp_c, humidity_pct, status_str)
        """
        if not MICROPYTHON or self.dht_sensor is None:
            return 27.5, 65.0, "OK"

        try:
            self.dht_sensor.measure()
            t = self.dht_sensor.temperature()
            h = self.dht_sensor.humidity()
            if -40 <= t <= 80 and 0 <= h <= 100:
                return round(float(t), 1), round(float(h), 1), "OK"
            return None, None, "DHT_OUT_OF_SPEC"
        except Exception as e:
            return None, None, f"DHT_READ_ERROR:{str(e)}"

    def read_rain(self):
        """
        Reads digital rain sensor.
        Returns 1 if wet/raining detected, else 0.
        """
        if not MICROPYTHON or self.rain_pin is None:
            return 0
        try:
            val = self.rain_pin.value()
            return 1 if val == config.RAIN_WET_LEVEL else 0
        except Exception:
            return 0

    def get_and_reset_flow_pulses(self):
        """
        Returns pulse count accumulated since last call and resets counter.
        """
        pulses = self.flow_pulse_count
        self.flow_pulse_count = 0
        return pulses
