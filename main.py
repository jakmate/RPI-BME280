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
from fastapi import FastAPI, Request
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
        self.time = 0

    def get_temp(self):
        """Getter for temp"""
        return self.temp

    def set_temp(self, temperature):
        """Setter for temp"""
        self.temp = temperature

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


async def read_temperature():
    """Reads temperature using bme280 lib,
    updates state and goes to sleep for TTL seconds"""
    while True:
        try:
            if not state.bus:
                state.connect()
                await asyncio.sleep(0.1)
            state.set_temp(round(state.bme280.get_temperature(), 1))
            state.set_time(int(datetime.utcnow().timestamp()))

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
    """Runs get_temperature until cancelled"""
    task = asyncio.create_task(read_temperature())
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
@app.get("/api/metrics")
async def get_json_metrics():
    """Returns json formatted state"""
    return {"temp": state.get_temp(), "time": state.get_time()}


# Prometheus endpoint
@app.get("/metrics")
async def get_prometheus_metrics():
    """Returns prometheus formatted state"""
    lines = []
    lines.append("# HELP rpi_temperature_celsius Temperature from BME280")
    lines.append("# TYPE rpi_temperature_celsius gauge")
    if state.get_temp() is not None:
        lines.append(f"rpi_temperature_celsius {state.get_temp()}")
    lines.append("# HELP rpi_timestamp_seconds Unix timestamp when metric was sampled")
    lines.append("# TYPE rpi_timestamp_seconds gauge")
    lines.append(f"rpi_timestamp_seconds {state.get_time()}")
    lines.append("")
    return "\n".join(lines)


@cli.command()
def main(
    port: Annotated[int, typer.Option(help="Port Number to be used (1-65535)")] = 8080,
    host: Annotated[str, typer.Option(help="Bind Address")] = "0.0.0.0",
    cache: Annotated[int, typer.Option(help="Cache TTL in seconds")] = 2,
):
    """Run fastapi app"""
    state.set_ttl(cache)
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    cli()
