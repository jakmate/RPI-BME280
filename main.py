#!/usr/bin/env python

"""BME280 sensor data exported using FastAPI

Routes:
    /metrics       Prometheus text-format
    /api/metrics   JSON format

Default config:
    Host: 0.0.0.0
    Port: 8080
    Cache TTL: 2s

CLI Arguments:
    -l <ip>, --host <ip>   Bind Address
    -p <n>, --port <n>     Port
    -c <n>, --cache <n>    Cache TTL
    -h, --help

Usage Examples:
    uv run main.py -l 0.0.0.0 -p 9000 -c 5

"""

import argparse
import asyncio
from contextlib import asynccontextmanager

from bme280 import BME280
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from smbus2 import SMBus
import uvicorn

# Parse args
parser = argparse.ArgumentParser(prog="main")
parser.add_argument(
    "-p", "--port", type=int, default=8080, help="Port number to be used (1-65535)"
)
parser.add_argument("-l", "--host", default="0.0.0.0", help="Bind Address")
parser.add_argument("-c", "--cache", type=int, default=2, help="Cache TTL in seconds")
args = parser.parse_args()

# Initialise vars
PORT = args.port
HOST = args.host
TTL = args.cache


class State:
    """Tracks state of sensor"""

    def __init__(self):
        self.bus = None
        self.bme280 = None
        self.temp = None
        self.time = 0

    def get_json_state(self):
        """Return state as json"""
        return {"temp": state.temp, "time": state.time}

    def get_prometheus_state(self):
        """Returns prometheus formatted state"""
        return f"""# HELP rpi_temperature_celsius Temperature from BME280
                # TYPE rpi_temperature_celsius gauge
                rpi_temperature_celsius {state.temp}
                # HELP rpi_timestamp_seconds Unix timestamp when metric was sampled"
                # TYPE rpi_timestamp_seconds gauge
                rpi_timestamp_seconds {state.time}
                """

    def connect(self):
        """Initialise BME280"""
        self.bus = SMBus(1)
        self.bme280 = BME280(i2c_dev=self.bus)

    def disconnect(self):
        """Reset the BME280 to default"""
        self.bus.close()
        self.bus = None
        self.bme280 = None


state = State()


async def get_temperature():
    """Gets temperature using bme280 lib,
    updates state and goes to sleep for TTL seconds"""
    while True:
        try:
            if not state.bus:
                state.connect()
            temperature = round(state.bme280.get_temperature(), 1)
            print(f"{temperature}°C {int(asyncio.get_event_loop().time())}")

            state.temp = temperature
            state.time = int(asyncio.get_event_loop().time())

        except OSError as e:
            print(f"An I/O error occured {e}")
            state.disconnect()

        await asyncio.sleep(TTL)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Runs get_temperature until cancelled"""
    task = asyncio.create_task(get_temperature())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_headers(request: Request, call_next):
    """Adds security headers"""
    response = await call_next(request)

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# JSON endpoint
@app.get("api/metrics")
async def get_json_metrics():
    """Returns json formatted state"""
    return state.get_json_state()


# Prometheus endpoint
@app.get("/metrics")
async def get_prometheus_metrics():
    """Returns prometheus formatted state"""
    return state.get_prometheus_state()


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, reload=False)
