import json
import os
import random
import sys
from enum import Enum
from pprint import pprint
import queue
from time import sleep
import threading
from typing import NamedTuple

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


LJUST_PADDING = 12
ALL_KEY = 'all'
WORKING_KEY = 'working'
FINISHED_KEY = 'finished'
WORKING_COUNT_MAX = (30 * 10)
ALL_REGIONS = json.load(open(os.path.join('..', 'cloud-benchmarking', 'artifacts', 'all_regions.json')))
SHUFFLED_REGIONS = json.load(open(os.path.join('..', 'cloud-benchmarking', 'artifacts', 'all-region-combos-shuffled.json')))
REGION_COORDS = {}
stuff = json.load(open(os.path.join('..', 'cloud-benchmarking', 'artifacts', 'all_regions.full.json')))
for provider, regions in stuff.items():
    for region, coord in regions.items():
        REGION_COORDS[region] = coord


def get_redis_client():
    if True:
        return redis.Redis(host=os.environ.get('REDIS_HOST'),
                           username='default', password=os.environ.get('REDIS_PASSWORD'),
                           port=os.environ.get('REDIS_PORT', 6379), ssl=False, db=0)


REDIS_CLIENT = get_redis_client()


class CloudProvider(Enum):
    AZURE = 'azure'
    LINODE = 'linode'
    DIGITALOCEAN = 'digitalocean'
    VULTR = 'vultr'
    OVH = 'ovh'
    GCP = 'gcp'
    AWS = 'aws'


    @staticmethod
    def ssh_user(provider: str):
        if provider == CloudProvider.AZURE.value:
            return 'azureroot'
        elif provider == CloudProvider.AWS.value:
            return 'ubuntu'

        return 'root'


    def __str__(self):
        return self.value


class BenchmarkHost(NamedTuple):
    provider: CloudProvider
    region: str
    zone: str = None


    def zoneless(self) -> str:
        return str(BenchmarkHost(self.provider, self.region, None))


    def __str__(self) -> str:
        base_str = f'{self.provider}+{self.region}'
        if self.zone is not None and len(self.zone) > 0 and (self.zone != self.region):
            return f'{base_str}[{self.zone}]'
        return base_str


def get_region_provider(region):
    for provider, regions in ALL_REGIONS.items():
        if region in regions:
            return provider
    return None


def get_provider_limits(provider) -> int:
    return {
        'linode': 175,
        'digitalocean': 300,
        'vultr': 300,
        'azure': 100,
        'gcp': 100,
        'aws': 100
    }[provider]


def get_region_limits(provider, region) -> int:
    if provider == 'gcp':
        return min(4, 8) # public ip addr vs. regional dedicated vCPU count
    if provider == 'azure':
        if region in ['centralindia', 'norwayeast']:
            return 10
        return min(20, 100) # public ip addr vs. regional dedicated vCPU count

    return 20


def get_combo_color(provider1, provider2) -> str:
    colors = {
        'vultr': '#007bfc',
        'digitalocean': '#0069ff',
        'linode': '#02b159',
        'gcp': '#1a73e8',
        'aws': '#d13212',
        'azure': '#ffb900',
        'all': '#ff00b4'
    }
    if provider1 == provider2:
        return colors[provider1]
    return colors['all']


def get_provider_current_usage(provider) -> int:
    resp = REDIS_CLIENT.get(provider)
    if resp is None:
        resp = 0
    return int(resp)


def get_region_current_usage(provider, region):
    resp = REDIS_CLIENT.get(f'{provider}:{region}')
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
        if (current_region_count + increase_request) > get_region_limits(provider, region):
            can_execute = False

    return can_execute


def should_keep_running():
    for provider in list(ALL_REGIONS.keys()):
        if get_provider_current_usage(provider) > 0:
            return True
    return is_working_queue_empty()


def put_into_finished_queue(combo):
    REDIS_CLIENT.lpush(FINISHED_KEY, json.dumps(combo))


def put_into_working_queue(combo):
    REDIS_CLIENT.lpush(WORKING_KEY, json.dumps(combo))


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
    return (REDIS_CLIENT.llen(WORKING_KEY) == 0)


def get_working_queue_size() -> int:
    resp = REDIS_CLIENT.llen(WORKING_KEY)
    if resp is None:
        resp = 0
    return int(resp)


SCHEDULER_URL = 'http://127.0.0.1:5000'


def clear_redis():
    REDIS_CLIENT.flushall()


def insert_data():
    values = [json.dumps(combo) for combo in SHUFFLED_REGIONS]
    for provider in sorted(ALL_REGIONS.keys()):
        REDIS_CLIENT.set(provider, 0)

    REDIS_CLIENT.lpush(ALL_KEY, *values)


def report_finished_benchmark(finished):
    REDIS_CLIENT.lrem(WORKING_KEY, 1, json.dumps(finished))
    configs = []
    for region in finished:
        provider = get_region_provider(region)
        REDIS_CLIENT.decr(provider, 1)
        REDIS_CLIENT.decr(f'{provider}:{region}', 1)
        configs.append(BenchmarkHost(provider=provider, region=region))
    put_into_finished_queue(finished)
    return 'ok'


def get_next_benchmark():
    resp = requests.get(f'{SCHEDULER_URL}/next-benchmark')
    return resp.json()


def update_pbars():
    pass


def do_run_orig(id):
    run = True
    while run:
        candidate = get_from_backlog_queue()
        if candidate is None:
            run = should_keep_running()
            continue
        if can_execute_combo(candidate):
            for region in candidate:
                provider = get_region_provider(region)
                REDIS_CLIENT.incr(provider, 1)
                REDIS_CLIENT.incr(f'{provider}:{region}', 1)
            put_into_working_queue(candidate)
            REDIS_CLIENT.set(f'worker:{os.getpid()}', json.dumps(candidate))
            sleep(random.uniform(0, 1))
            report_finished_benchmark(candidate)
            REDIS_CLIENT.set(f'worker:{os.getpid()}', json.dumps(None))
        else:
            print(f'[{id}] {candidate}')
            put_into_backlog_queue(candidate)
        run = should_keep_running()


if __name__ == "__main__":
    do_run_orig(sys.argv[1])
