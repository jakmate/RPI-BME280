#!/usr/bin/env python

"""BME280 sensor data exported using FastAPI.

Routes:
    /metrics           Prometheus text-format
    /api/metrics       JSON state
    /api/temperature   JSON temperature
    /api/humidity      JSON humidity
    /api/pressure      JSON pressure

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
import logging
import typing
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

import typer
import uvicorn
from bme280 import BME280  # type: ignore[import-untyped]
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from smbus2 import SMBus

cli = typer.Typer()
logger = logging.getLogger(__name__)


class State:
    """Tracks state of sensor."""

    def __init__(self) -> None:
        """Initialise empty state."""
        self.bus: SMBus | None = None
        self.bme280: BME280 | None = None
        self.ttl: int = 2
        self.temp: float | None = None
        self.humidity: float | None = None
        self.pressure: float | None = None
        self.time: int = 0

    def reset_metrics(self) -> None:
        """Reset metrics to default values."""
        self.temp = None
        self.humidity = None
        self.pressure = None

    def connect(self) -> None:
        """Initialise BME280."""
        self.bus = SMBus(1)
        self.bme280 = BME280(i2c_dev=self.bus)

    def disconnect(self) -> None:
        """Reset the BME280 to default."""
        if self.bus:
            self.bus.close()
        self.bus = None
        self.bme280 = None


state = State()


async def read_metrics() -> None:
    """Reads metrics via bme280 lib, updates state and goes to sleep for TTL seconds."""
    while True:
        try:
            if not state.bus:
                state.connect()
                await asyncio.sleep(1)

            if state.bme280:
                state.temp = round(state.bme280.get_temperature(), 1)
                state.humidity = round(state.bme280.get_humidity(), 1)
                state.pressure = round(state.bme280.get_pressure(), 1)
            state.time = int(datetime.now(UTC).timestamp())

        except OSError:
            logger.exception("OS error occurred")
            state.disconnect()
            state.reset_metrics()
        except Exception:
            logger.exception("Unexpected error")
            state.disconnect()
            state.reset_metrics()

        await asyncio.sleep(state.ttl)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Runs get_metrics until cancelled."""
    task = asyncio.create_task(read_metrics())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
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
async def add_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Adds security headers."""
    response = await call_next(request)

    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# JSON endpoints
@app.get("/api/metrics")
async def get_json_metrics() -> dict[str, typing.Any]:
    """Returns JSON formatted state."""
    return {
        "temp": state.temp,
        "humidity": state.humidity,
        "pressure": state.pressure,
        "time": state.time,
    }


@app.get("/api/temperature")
async def get_json_temperature() -> dict[str, typing.Any]:
    """Returns JSON formatted temperature."""
    return {
        "temp": state.temp,
        "time": state.time,
    }


@app.get("/api/humidity")
async def get_json_humidity() -> dict[str, typing.Any]:
    """Returns JSON formatted humidity."""
    return {
        "humidity": state.humidity,
        "time": state.time,
    }


@app.get("/api/pressure")
async def get_json_pressure() -> dict[str, typing.Any]:
    """Returns JSON formatted pressure."""
    return {
        "pressure": state.pressure,
        "time": state.time,
    }


# Prometheus endpoint
@app.get("/metrics")
async def get_prometheus_metrics() -> Response:
    """Returns prometheus formatted state."""
    lines = []
    lines.append(
        "# HELP cc_metrics_ambient_temperature_celsius Temperature from BME280",
    )
    lines.append("# TYPE cc_metrics_ambient_temperature_celsius gauge")
    if state.temp is not None:
        lines.append(f"cc_metrics_ambient_temperature_celsius {state.temp}")

    lines.append("# HELP cc_metrics_ambient_humidity_percent Humidity from BME280")
    lines.append("# TYPE cc_metrics_ambient_humidity_percent gauge")
    if state.humidity is not None:
        lines.append(f"cc_metrics_ambient_humidity_percent {state.humidity}")

    lines.append("# HELP cc_metrics_ambient_pressure_hpa Pressure from BME280")
    lines.append("# TYPE cc_metrics_ambient_pressure_hpa gauge")
    if state.pressure is not None:
        lines.append(f"cc_metrics_ambient_pressure_hpa {state.pressure}")

    lines.append(
        "# HELP cc_metrics_ambient_timestamp_seconds Unix timestamp when sampled",
    )
    lines.append("# TYPE cc_metrics_ambient_timestamp_seconds gauge")
    lines.append(f"cc_metrics_ambient_timestamp_seconds {state.time}\n")

    content = "\n".join(lines)

    return Response(content=content, media_type="text/plain; charset=utf-8")


@cli.command()
def main(
    port: typing.Annotated[
        int,
        typer.Option(help="Port Number to be used (1-65535)"),
    ] = 9090,
    host: typing.Annotated[str, typer.Option(help="Bind Address")] = "0.0.0.0",  # noqa: S104
    cache: typing.Annotated[int, typer.Option(help="Cache TTL in seconds")] = 2,
) -> None:
    """Run fastapi app."""
    state.ttl = cache
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
