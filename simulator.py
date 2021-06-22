import dataclasses
import json
import os
import random
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pprint import pprint
import queue
from time import sleep
import threading
from typing import NamedTuple
from jinja2 import FileSystemLoader, Environment

import humanize
import redis
from tqdm import tqdm
from flask import Flask, render_template, jsonify
from flask_cors import CORS, cross_origin
from pony.orm import *
import concurrent.futures
from multiprocessing.dummy import freeze_support
import time
import requests


SHOW_PBARS = True
LJUST_PADDING = 12
ALL_KEY = "all"
WORKING_KEY = "working"
FINISHED_KEY = "finished"
WORKING_COUNT_MAX = 30 * 10
ALL_REGIONS = json.load(
    open(os.path.join("..", "cloud-benchmarking", "artifacts", "all_regions.json"))
)
SHUFFLED_REGIONS = json.load(
    open(
        os.path.join(
            "..", "cloud-benchmarking", "artifacts", "all-region-combos-shuffled.json"
        )
    )
)
REGION_COORDS = {}
stuff = json.load(
    open(os.path.join("..", "cloud-benchmarking", "artifacts", "all_regions.full.json"))
)
for provider, regions in stuff.items():
    for region, coord in regions.items():
        REGION_COORDS[region] = coord

PBARS = {}


def get_redis_client():
    if True:
        return redis.Redis(
            host=os.environ.get("REDIS_HOST"),
            username="default",
            password=os.environ.get("REDIS_PASSWORD"),
            port=os.environ.get("REDIS_PORT"),
            ssl=False,
            db=0,
        )


REDIS_CLIENT = get_redis_client()


class CloudProvider(Enum):
    AZURE = "azure"
    LINODE = "linode"
    DIGITALOCEAN = "digitalocean"
    VULTR = "vultr"
    OVH = "ovh"
    GCP = "gcp"
    AWS = "aws"

    @staticmethod
    def ssh_user(provider: str):
        if provider == CloudProvider.AZURE.value:
            return "azureroot"
        elif provider == CloudProvider.AWS.value:
            return "ubuntu"

        return "root"

    def __str__(self):
        return self.value


class BenchmarkHost(NamedTuple):
    provider: CloudProvider
    region: str
    zone: str = None

    def zoneless(self) -> str:
        return str(BenchmarkHost(self.provider, self.region, None))

    def __str__(self) -> str:
        base_str = f"{self.provider}+{self.region}"
        if self.zone is not None and len(self.zone) > 0 and (self.zone != self.region):
            return f"{base_str}[{self.zone}]"
        return base_str


def get_region_provider(region):
    for provider, regions in ALL_REGIONS.items():
        if region in regions:
            return provider
    return None


def get_all_provider_limits() -> dict:
    return {
        "linode": 175,
        "digitalocean": 300,
        "vultr": 300,
        "azure": 100,
        "gcp": 100,
        "aws": 100,
    }


def get_provider_limits(provider) -> int:
    return get_all_provider_limits()[provider]


def get_region_limits(provider, region) -> int:
    if provider == "aws":
        return 32

    if provider == "gcp":
        # return min(4, 8)  # public ip addr vs. regional dedicated vCPU count
        return min(8, 24)  # public ip addr vs. regional dedicated vCPU count

    if provider == "azure":
        if region in ["centralindia", "norwayeast"]:
            return 10
        return min(20, 100)  # public ip addr vs. regional dedicated vCPU count

    return 20


def get_combo_color(provider1, provider2) -> str:
    colors = {
        "vultr": "#007bfc",
        "digitalocean": "#0069ff",
        "linode": "#02b159",
        "gcp": "#1a73e8",
        "aws": "#d13212",
        "azure": "#ffb900",
        "all": "#ff00b4",
    }
    if provider1 == provider2:
        return colors[provider1]
    return colors["all"]


app = Flask(__name__)
cors = CORS(app)
app.config["CORS_HEADERS"] = "Content-Type"
app.APP_CACHED_DATA = {}


@app.route("/data2")
@cross_origin()
def json_data():
    data = {
        "ALL_KEY": ALL_KEY,
        "providers": list(ALL_REGIONS.keys()),
        "provider_regions": ALL_REGIONS,
        "provider_usage_limits": {},
        "total_list_items": sum(
            [get_queue_length(key) for key in [ALL_KEY, WORKING_KEY, FINISHED_KEY]]
        ),
    }

    for provider in ALL_REGIONS.keys():
        data["provider_usage_limits"][provider] = {
            "current": get_provider_current_usage(provider),
            "limit": get_provider_limits(provider),
        }

    for key in REDIS_CLIENT.keys():
        key = key.decode()
        try:
            data[key] = REDIS_CLIENT.get(key).decode()
        except:
            data[key] = [
                json.loads(item.decode()) for item in REDIS_CLIENT.lrange(key, 0, -1)
            ]

    data[ALL_KEY] = data.get(ALL_KEY, [])
    data[WORKING_KEY] = data.get(WORKING_KEY, [])
    data[FINISHED_KEY] = data.get(FINISHED_KEY, [])

    app.APP_CACHED_DATA = data

    return jsonify(data)


@app.route("/")
@cross_origin()
def html_data():
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("dashboard.html.jinja2")
    rendered_html = template.render(providers=list(ALL_REGIONS.keys()))
    return rendered_html


@app.route("/map-old")
@cross_origin()
def hello():
    coords = []
    inprogress_regions = [
        json.loads(item.decode()) for item in REDIS_CLIENT.lrange(WORKING_KEY, 0, -1)
    ]
    for inprogress_dicts in inprogress_regions:
        region_pairs = inprogress_dicts.get("combo", [])
        coords.append(
            [
                REGION_COORDS[region_pairs[0]],
                REGION_COORDS[region_pairs[1]],
                get_combo_color(
                    get_region_provider(region_pairs[0]),
                    get_region_provider(region_pairs[1]),
                ),
            ]
        )
    stats = {
        WORKING_KEY: coords,
        ALL_KEY: REDIS_CLIENT.llen(ALL_KEY),
        FINISHED_KEY: REDIS_CLIENT.llen(FINISHED_KEY),
    }
    for pbar_key in list(PBARS.keys())[3:]:
        stats[pbar_key] = get_provider_current_usage(pbar_key)
    return jsonify(stats)


def get_provider_current_usage(provider) -> int:
    resp = REDIS_CLIENT.get(provider)
    if resp is None:
        resp = 0
    return int(resp)


@app.route("/map")
@cross_origin()
def new_map():
    coords = []
    inprogress_regions = app.APP_CACHED_DATA.get(WORKING_KEY, [])
    for inprogress_dicts in inprogress_regions:
        region_pairs = inprogress_dicts.get("combo", [])
        coords.append(
            [
                REGION_COORDS[region_pairs[0]],
                REGION_COORDS[region_pairs[1]],
                get_combo_color(
                    get_region_provider(region_pairs[0]),
                    get_region_provider(region_pairs[1]),
                ),
            ]
        )
    stats = {
        WORKING_KEY: coords,
    return jsonify(stats)


def get_provider_current_usage(provider) -> int:
    resp = REDIS_CLIENT.get(provider)
    if resp is None:
        resp = 0
    return int(resp)


def get_region_current_usage(provider, region):
    resp = REDIS_CLIENT.get(f"{provider}:{region}")
    if resp is None:
        resp = 0
    return int(resp)


def can_execute_combo(regions) -> bool:
    can_execute = get_working_queue_size() < WORKING_COUNT_MAX

    provider_reqs = {}
    region_reqs = {}

    for region in regions:
        provider = get_region_provider(region)
        if provider not in provider_reqs:
            provider_reqs[provider] = 0
        if region not in region_reqs:
            region_reqs[region] = 0

    provider_reqs[provider] = 1 + provider_reqs[provider]
    region_reqs[region] = 1 + region_reqs[region]

    for provider, increase_request in provider_reqs.items():
        current_count = get_provider_current_usage(provider)
        if (current_count + increase_request) > get_provider_limits(provider):
            can_execute = False

    for region, increase_request in region_reqs.items():
        provider = get_region_provider(region)
        current_region_count = get_region_current_usage(provider, region)
        if (current_region_count + increase_request) > get_region_limits(
            provider, region
        ):
            can_execute = False

    return can_execute


def should_keep_running():
    for pbar_key in list(PBARS.keys())[3:]:
        if get_provider_current_usage(pbar_key) > 0:
            return True
    return False


def put_into_finished_queue(combo: dict):
    combo["end_dtm"] = str(datetime.now(timezone.utc))
    REDIS_CLIENT.lpush(FINISHED_KEY, json.dumps(combo))


def put_into_working_queue(combo: str):
    REDIS_CLIENT.lpush(
        WORKING_KEY,
        json.dumps({"combo": combo, "start_dtm": str(datetime.now(timezone.utc))}),
    )


def put_into_backlog_queue(combo):
    REDIS_CLIENT.lpush(ALL_KEY, json.dumps(combo))


def get_from_backlog_queue():
    resp = REDIS_CLIENT.rpop(ALL_KEY)
    if resp is None:
        return None
    return json.loads(resp)


def get_from_working_queue():
    resp = REDIS_CLIENT.rpop(WORKING_KEY)
    if resp is None:
        return None
    return json.loads(resp)


def is_working_queue_empty():
    return REDIS_CLIENT.llen(WORKING_KEY) == 0


def get_working_queue_size() -> int:
    resp = REDIS_CLIENT.llen(WORKING_KEY)
    if resp is None:
        resp = 0
    return int(resp)


SCHEDULER_URL = "http://127.0.0.1:5000"


def clear_redis():
    REDIS_CLIENT.flushall()


def insert_data(data_to_insert=SHUFFLED_REGIONS):
    values = [json.dumps(combo) for combo in data_to_insert]
    for provider in sorted(ALL_REGIONS.keys()):
        PBARS[provider] = tqdm(
            total=get_provider_limits(provider),
            desc=provider.ljust(LJUST_PADDING, " "),
            position=len(PBARS),
        )
        REDIS_CLIENT.set(provider, 0)

    PBARS[ALL_KEY].total = len(data_to_insert)
    PBARS[FINISHED_KEY].total = len(data_to_insert)
    PBARS[WORKING_KEY].total = WORKING_COUNT_MAX

    REDIS_CLIENT.lpush(ALL_KEY, *values)
    PBARS[ALL_KEY].update(len(values))


def report_finished_benchmark(finished):
    if SHOW_PBARS:
        PBARS[WORKING_KEY].update(-1)
        PBARS[WORKING_KEY].refresh()
    configs = []
    for region in finished["combo"]:
        provider = get_region_provider(region)
        REDIS_CLIENT.decr(provider, 1)
        REDIS_CLIENT.decr(f"{provider}:{region}", 1)
        if SHOW_PBARS:
            PBARS[provider].update(-1)
            PBARS[provider].refresh()
        configs.append(BenchmarkHost(provider=provider, region=region))
    put_into_finished_queue(finished)
    if SHOW_PBARS:
        PBARS[FINISHED_KEY].update(1)
    return "ok"


def get_next_benchmark():
    resp = requests.get(f"{SCHEDULER_URL}/next-benchmark")
    return resp.json()


def do_run():
    run = True
    open("simulator.log", "w").close()
    while run:
        if random.choice([1, 2, 3, 4]) != 1 and not is_working_queue_empty():
            finished = get_from_working_queue()
            report_finished_benchmark(finished)

        candidate = get_next_benchmark()
        if candidate is not None:
            pass

        run = should_keep_running()
        PBARS[ALL_KEY].refresh()

    for pbar in PBARS.values():
        pbar.close()


def get_queue_length(list_key):
    return int(REDIS_CLIENT.llen(list_key))


def update_pbars():
    if not SHOW_PBARS:
        return

    for list_key in [ALL_KEY, WORKING_KEY, FINISHED_KEY]:
        PBARS[list_key].n = get_queue_length(list_key)
        PBARS[list_key].refresh()

    for provider in sorted(ALL_REGIONS.keys()):
        PBARS[provider].n = get_provider_current_usage(provider)
        PBARS[provider].refresh()


def do_run_orig():
    run = True
    open("simulator.log", "w").close()
    while run:
        if random.choice([1, 2, 3, 4]) != 1 and not is_working_queue_empty():
            finished = get_from_working_queue()
            report_finished_benchmark(finished)

        candidate = get_from_backlog_queue()
        if candidate is None:
            run = should_keep_running()
            continue
        if can_execute_combo(candidate):
            for region in candidate:
                provider = get_region_provider(region)

                if SHOW_PBARS:
                    PBARS[provider].update(1)
                REDIS_CLIENT.incr(provider, 1)
                REDIS_CLIENT.incr(f"{provider}:{region}", 1)

            if SHOW_PBARS:
                PBARS[ALL_KEY].update(-1)
            put_into_working_queue(candidate)

            if SHOW_PBARS:
                PBARS[WORKING_KEY].update(1)
        else:
            put_into_backlog_queue(candidate)
        run = should_keep_running()

        update_pbars()

    for pbar in PBARS.values():
        pbar.close()


def call_runner(id):
    subprocess.run(
        [
            os.path.abspath(os.path.join("venv", "Scripts", "python.exe")),
            "runner.py",
            str(id),
        ]
    )


import logging, sys


if __name__ == "__main__":
    PBARS = {
        ALL_KEY: tqdm(
            total=len(SHUFFLED_REGIONS),
            desc="BACKLOG".ljust(LJUST_PADDING, " "),
            position=0,
        ),
        FINISHED_KEY: tqdm(
            total=len(SHUFFLED_REGIONS),
            desc="FINISHED".ljust(LJUST_PADDING, " "),
            position=1,
        ),
        WORKING_KEY: tqdm(
            total=WORKING_COUNT_MAX,
            desc="WORKING".ljust(LJUST_PADDING, " "),
            position=2,
        ),
    }
    logging = logging.getLogger()
    clear_redis()

    if True:
        insert_data()
        threading.Thread(target=app.run).start()
        do_run_orig()
    else:
        threading.Thread(target=app.run).start()

    # app.run()
    # app.run()
    # do_run()
    # exit(1)
    # exit(0)
    # freeze_support()
    # workers = 100
    # if sys.platform == 'win32':
    #     workers = min(61, workers)
    # print(f"Starting processing with workers")
    # start = time.perf_counter()
    # with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
    #     r = list(tqdm(executor.map(call_runner, list(range(0, workers))), total=workers))
    #     # executor.submit(call_runner).result()
    # end = time.perf_counter()
    # print(f"Total time: {end - start:0.4f} seconds")
    # print(f"Total time: {humanize.naturaltime(end - start)}")
