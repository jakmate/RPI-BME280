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

    def reset_metrics(self):
        """Reset metrics to default values"""
        self.temp = None
        self.humidity = None
        self.pressure = None

    def connect(self):
        """Initialise BME280"""
        self.bus = SMBus(1)
        self.bme280 = BME280(i2c_dev=self.bus)

    def disconnect(self):
        """Reset the BME280 to default"""
        if self.bus:
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

            state.temp = round(state.bme280.get_temperature(), 1)
            state.humidity = round(state.bme280.get_humidity(), 1)
            state.pressure = round(state.bme280.get_pressure(), 1)
            state.time = int(datetime.utcnow().timestamp())

        except OSError as e:
            print(f"An OS error occured: {e}")
            state.disconnect()
            state.reset_metrics()
        except ZeroDivisionError as e:
            print(f"Division by zero occured: {e}")
            state.disconnect()
            state.reset_metrics()
        except Exception as e:
            print(f"New Exception {e}")
            state.disconnect()
            state.reset_metrics()

        await asyncio.sleep(state.ttl)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Runs get_metrics until cancelled"""
    task = asyncio.create_task(read_metrics())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    state.disconnect()


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
        "temp": state.temp,
        "humidity": state.humidity,
        "pressure": state.pressure,
        "time": state.time,
    }


@app.get("/api/temperature")
async def get_json_temperature():
    """Returns json formatted temperature"""
    return {
        "temp": state.temp,
        "time": state.time,
    }


@app.get("/api/humidity")
async def get_json_humidity():
    """Returns json formatted humidity"""
    return {
        "humidity": state.humidity,
        "time": state.time,
    }


@app.get("/api/pressure")
async def get_json_pressure():
    """Returns json formatted pressure"""
    return {
        "pressure": state.pressure,
        "time": state.time,
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
    if state.temp is not None:
        lines.append(f"cc_metrics_ambient_temperature_celsius {state.temp}")

    lines.append("# HELP cc_metrics_ambient_humidity_per Humidity from BME280")
    lines.append("# TYPE cc_metrics_ambient_humidity_per gauge")
    if state.humidity is not None:
        lines.append(f"cc_metrics_ambient_humidity {state.humidity}")

    lines.append("# HELP cc_metrics_ambient_pressure_hPa Pressure from BME280")
    lines.append("# TYPE cc_metrics_ambient_pressure_hPa gauge")
    if state.pressure is not None:
        lines.append(f"cc_metrics_ambient_pressure_hPa {state.pressure}")

    lines.append(
        "# HELP cc_metrics_ambient_timestamp_seconds Unix timestamp when sampled"
    )
    lines.append("# TYPE cc_metrics_ambient_timestamp_seconds gauge")
    lines.append(f"cc_metrics_ambient_timestamp_seconds {state.time}\n")

    content = "\n".join(lines)

    return Response(content=content, media_type="text/plain; charset=utf-8")


@cli.command()
def main(
    port: Annotated[int, typer.Option(help="Port Number to be used (1-65535)")] = 9090,
    host: Annotated[str, typer.Option(help="Bind Address")] = "0.0.0.0",
    cache: Annotated[int, typer.Option(help="Cache TTL in seconds")] = 2,
):
    """Run fastapi app"""
    state.ttl = cache
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    cli()
