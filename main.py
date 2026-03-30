#!/usr/bin/env python

"""BME280 sensor data exported using FastAPI

Routes:
    /metrics       Prometheus text-format
    /api/metrics   JSON state
    /temperaure    JSON temperaute
    /humidity      JSON humidity
    /pressure      JSON pressure

Default config:
    Host: 0.0.0.0
    Port: 9090
    Cache TTL: 2s

CLI Arguments:
    --host <ip>   Bind Address
    --port <n>     Port
    --cache <n>    Cache TTL
    --help

Usage Examples:
    uv run main.py --host 0.0.0.0 --port 9000 --cache 5

"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from bme280 import BME280
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from smbus2 import SMBus
import typer
import uvicorn

cli = typer.Typer()


class State:
    """Tracks state of sensor"""

    def __init__(self):
        self.bus = None
        self.bme280 = None
        self.ttl = None
        self.temp = None
        self.humidity = None
        self.pressure = None
        self.time = 0

    def get_temp(self):
        """Getter for temp"""
        return self.temp

    def set_temp(self, temperature):
        """Setter for temp"""
        self.temp = temperature

    def get_humidity(self):
        """Getter for humidity"""
        return self.humidity

    def set_humidity(self, humidity):
        """Setter for humidity"""
        self.humidity = humidity

    def get_pressure(self):
        """Getter for pressure"""
        return self.pressure

    def set_pressure(self, pressure):
        """Setter for pressure"""
        self.pressure = pressure

    def get_time(self):
        """Getter for time"""
        return self.time

    def set_time(self, time):
        """Setter for time"""
        self.time = time

    def get_ttl(self):
        """Getter for ttl"""
        return self.ttl

    def set_ttl(self, ttl):
        """Setter for ttl"""
        self.ttl = ttl

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


async def read_metrics():
    """Reads metrics using bme280 lib,
    updates state and goes to sleep for TTL seconds"""
    while True:
        try:
            if not state.bus:
                state.connect()
                await asyncio.sleep(1)
            state.set_temp(round(state.bme280.get_temperature(), 1))
            state.set_humidity(round(state.bme280.get_humidity(), 1))
            state.set_pressure(round(state.bme280.get_pressure(), 1))
            state.set_time(int(datetime.utcnow().timestamp()))
            # print(
            #    f"Temp: {state.get_temp()} Time: {state.get_time()}
            #    Pressure: {state.get_pressure()}
            #    Humidity: {state.get_humidity()}"
            # )

        except OSError as e:
            print(f"An OS error occured: {e}")
            state.disconnect()
            state.set_temp(None)
        except ZeroDivisionError as e:
            print(f"Division by zero occured: {e}")
            state.set_temp(None)
        except Exception as e:
            print(f"New Exception {e}")
            state.set_temp(None)
            state.disconnect()

        await asyncio.sleep(state.get_ttl())


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Runs get_metrics until cancelled"""
    task = asyncio.create_task(read_metrics())
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


# JSON endpoints
@app.get("/api/metrics")
async def get_json_metrics():
    """Returns json formatted state"""
    return {
        "temp": state.get_temp(),
        "humidity": state.get_humidity(),
        "pressure": state.get_pressure(),
        "time": state.get_time(),
    }


@app.get("/api/temperature")
async def get_json_temperature():
    """Returns json formatted temperature"""
    return {
        "temp": state.get_temp(),
        "time": state.get_time(),
    }


@app.get("/api/humidity")
async def get_json_humidity():
    """Returns json formatted humidity"""
    return {
        "humidity": state.get_humidity(),
        "time": state.get_time(),
    }


@app.get("/api/pressure")
async def get_json_pressure():
    """Returns json formatted pressure"""
    return {
        "pressure": state.get_pressure(),
        "time": state.get_time(),
    }


# Prometheus endpoint
@app.get("/metrics")
async def get_prometheus_metrics():
    """Returns prometheus formatted state"""
    lines = []
    lines.append(
        "# HELP cc_metrics_ambient_temperature_celsius Temperature from BME280"
    )
    lines.append("# TYPE cc_metrics_ambient_temperature_celsius gauge")
    if state.get_temp() is not None:
        lines.append(f"cc_metrics_ambient_temperature_celsius {state.get_temp()}")

    lines.append("# HELP cc_metrics_ambient_humidity_per Humidity from BME280")
    lines.append("# TYPE cc_metrics_ambient_humidity_per gauge")
    if state.get_humidity() is not None:
        lines.append(f"cc_metrics_ambient_humidity {state.get_humidity()}")

    lines.append("# HELP cc_metrics_ambient_pressure_hPa Pressure from BME280")
    lines.append("# TYPE cc_metrics_ambient_pressure_hPa gauge")
    if state.get_pressure() is not None:
        lines.append(f"cc_metrics_ambient_pressure_hPa {state.get_pressure()}")

    lines.append(
        "# HELP cc_metrics_ambient_timestamp_seconds Unix timestamp when sampled"
    )
    lines.append("# TYPE cc_metrics_ambient_timestamp_seconds gauge")
    lines.append(f"cc_metrics_ambient_timestamp_seconds {state.get_time()}\n")

    content = "\n".join(lines)

    return Response(content=content, media_type="text/plain; charset=utf-8")


@cli.command()
def main(
    port: Annotated[int, typer.Option(help="Port Number to be used (1-65535)")] = 9090,
    host: Annotated[str, typer.Option(help="Bind Address")] = "0.0.0.0",
    cache: Annotated[int, typer.Option(help="Cache TTL in seconds")] = 2,
):
    """Run fastapi app"""
    state.set_ttl(cache)
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    cli()
