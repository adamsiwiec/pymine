from datetime import datetime

from discord_webhook import DiscordWebhook, DiscordEmbed
from enum import Enum
import asyncio

import json
from tenacity import *
import requests

import sys
from loguru import logger

logger.add("pymine.log")

DEFAULT_URL = "http://localhost:4000/api"
DISCORD_WEBHOOK = sys.argv[1]
COMPUTER_NAME = sys.argv[2]  # use param later

# LOGIC:
# 1. Establish connection to main server
# 2. Get list of excavators
# 3. Keep track of last known status
# 4. Log to console
# 5. Send to server
# 6. Get new status
# 7. If status is down, notify server


class Alert:
    def __init__(self, webhook):
        self.wh = DiscordWebhook(url=webhook)

    def gpu_status_alert(self, device):
        if device.status == Status.DOWN:
            return "GPU {} is down\n".format(device.name)
        elif device.status == Status.SLOW:
            return "GPU {} is slow\n".format(device.name)
        else:
            return "GPU {} is up\n".format(device.name)

    def gpu_speed_alert(self, device):
        if device.speed == 0:
            return "GPU {} is not hashing\n".format(device.name)
        else:
            return "GPU {} is hashing at {} H/s\n".format(
                device.name, device.speed)

    def last_seen_alert(self, device):
        return "Last seen {}\n".format(device.last_seen)

    def alert(self, device):
        alert_string = ""
        alert_string += self.gpu_status_alert(device)
        alert_string += self.gpu_speed_alert(device)
        alert_string += self.last_seen_alert(device)
        embedded = DiscordEmbed(title="GPU {} Status".format(device.name),
                                description=alert_string)
        self.wh.add_embed(embedded)
        self.wh.execute()


class Status(Enum):
    UP = 1
    DOWN = 2
    SLOW = 3
    UNKNOWN = 4


class Device:
    def __init__(self, id, uuid, name, details):
        self.id = id
        self.uuid = uuid
        self.name = name
        self.details = details
        self.status = Status.UNKNOWN
        self.speed = 0
        self.speed_history = {}
        self.last_seen = None
        self.hw_errors = 0
        self.temp = 0
        self.memtemp = 0
        self.fans = 0

    @retry(wait=wait_fixed(3) + wait_random(0, 2), stop=stop_after_attempt(5))
    def getData(self):
        try:
            self.getGPUMetaData()
        except Exception as e:
            logger.error(e)
            raise e

    def getGPUMetaData(self):
        logger.info("Getting metadata for device: " + self.name)
        defaultParams = {
            "command":
            json.dumps({
                "id": 1,
                "method": "device.get",
                "params": [str(self.id)]
            })
        }
        res = requests.get(DEFAULT_URL, params=defaultParams)
        self.data = res.json()


@retry(wait=wait_fixed(3) + wait_random(0, 2))
def setupExcavator(devices, url):
    logger.info("Getting data for devices")
    defaultParams = {
        "command": json.dumps({
            "id": 1,
            "method": "device.list",
            "params": []
        })
    }
    res = requests.get(url, params=defaultParams)
    logger.info(res.status_code)
    for device in res.json()["devices"]:
        logger.info(device)
        new_dev = Device(device["device_id"], device["uuid"], device["name"],
                         device["details"])
        devices.append(new_dev)


@retry(wait=wait_fixed(3) + wait_random(0, 2), stop=stop_after_attempt(5))
def getGPUSpeed(devices):
    logger.info("Getting speed for all devices")
    defaultParams = {
        "command": json.dumps({
            "id": 1,
            "method": "worker.list",
            "params": []
        })
    }
    res = requests.get(DEFAULT_URL, params=defaultParams)
    data = res.json()

    for device in devices:
        for worker in data["workers"]:
            if device.uuid == worker["device_uuid"]:
                device.speed = worker["algorithms"][0]["speed"]
                for avgspeed in worker["algorithms"][0]["avgspeed"]:
                    device.speed_history[
                        avgspeed["window"]] = avgspeed["speed"]


def checkDeviceStatus(alert, device):
    if device.speed > 0:
        device.last_seen = datetime.now()
        device.status = Status.UP
        logger.info(
            "Device {} passed inspection with status {} and speed {}".format(
                device.name, device.status, device.speed))
    elif device.speed < 0.75 * device.speed_history[5]:
        device.status = Status.SLOW
        alert.alert(device)
    elif device.speed_history[5] == 0:
        device.status = Status.DOWN
        alert.alert(device)
    else:
        logger.info(
            "Device {} passed inspection with status {} and speed {}".format(
                device.name, device.status, device.speed))


def main():
    devices = []
    alert = Alert(DISCORD_WEBHOOK)
    setupExcavator(devices, DEFAULT_URL)

    while True:
        sleep(12)
        for device in devices:
            try:
                device.getData()
            except Exception as e:
                device.status = Status.DOWN
                alert.alert(device)
        getGPUSpeed(devices)
        for device in devices:
            checkDeviceStatus(alert, device)


main()