import json
import os
import random
from enum import Enum
from pprint import pprint
import queue
from time import sleep
import threading
from typing import NamedTuple

import humanize
import redis
from tqdm import tqdm
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS, cross_origin
from pony.orm import *
import concurrent.futures
from multiprocessing.dummy import freeze_support
import time


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

PBARS = {
    ALL_KEY: tqdm(total=len(SHUFFLED_REGIONS), desc='BACKLOG'.ljust(LJUST_PADDING, ' '), position=0),
    FINISHED_KEY: tqdm(total=len(SHUFFLED_REGIONS), desc='FINISHED'.ljust(LJUST_PADDING, ' '), position=1),
    WORKING_KEY: tqdm(total=WORKING_COUNT_MAX, desc='WORKING'.ljust(LJUST_PADDING, ' '), position=2)
}


def get_redis_client():
    if True:
        return redis.Redis(host=os.environ.get('REDIS_HOST'),
                           username='default', password=os.environ.get('REDIS_PASSWORD'),
                           port=os.environ.get('REDIS_PORT'), ssl=False, db=0)



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


def get_combo_color(provider1, provider2) -> str:
    colors = {
        'vultr': '#007bfc',
        'digitalocean': '#0069ff',
        'linode': '#02b159',
        'google': '#1a73e8',
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


def can_execute_combo(regions) -> bool:
    can_execute = PBARS[WORKING_KEY].n < WORKING_COUNT_MAX
    for region in regions:
        provider = get_region_provider(region)
        # current_count = PBARS[provider].n
        current_count = get_provider_current_usage(provider)
        if (current_count + 1) > get_provider_limits(provider):
            can_execute = False
    return can_execute


app = Flask(__name__)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'


@app.route("/")
@cross_origin()
def hello():
    # first_combo = random.choice(SHUFFLED_REGIONS)
    # print(first_combo)
    coords = []
    inprogress_regions = [json.loads(item.decode()) for item in REDIS_CLIENT.lrange(WORKING_KEY, 0, -1)]
    for region_pairs in inprogress_regions:
        coords.append([
            REGION_COORDS[region_pairs[0]],
            REGION_COORDS[region_pairs[1]],
            get_combo_color(get_region_provider(region_pairs[0]), get_region_provider(region_pairs[1]))
        ])
    stats = {
        WORKING_KEY: coords,
        ALL_KEY: REDIS_CLIENT.llen(ALL_KEY),
        FINISHED_KEY: REDIS_CLIENT.llen(FINISHED_KEY),
    }
    for pbar_key in list(PBARS.keys())[3:]:
        stats[pbar_key] = get_provider_current_usage(pbar_key)
    return jsonify(stats)


@app.route('/keep-running', methods=['GET'])
def keep_running():
    return jsonify(should_keep_running())


def should_keep_running():
    for pbar_key in list(PBARS.keys())[3:]:
        if get_provider_current_usage(pbar_key) > 0:
            return True
    return False


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
    # working_queue.empty()
    return (REDIS_CLIENT.llen(WORKING_KEY) == 0)


@app.route("/reset", methods=['POST'])
def clear_redis():
    app.logger.info(f"reset ALL_KEY, WORKING_KEY, FINISHED_KEY")
    REDIS_CLIENT.flushall()
    return 'ok'


@app.route("/insert-combos", methods=['POST'])
def reset_redis():
    req_data = request.get_json(force=True)
    app.logger.info(f"found {len(req_data['providers'])} providers")
    app.logger.info(f"found {len(req_data['combos'])} combos")
    for provider in sorted(req_data['providers']):
        PBARS[provider] = tqdm(total=get_provider_limits(provider), desc=provider.ljust(LJUST_PADDING, ' '), position=len(PBARS))
        REDIS_CLIENT.set(provider, 0)

    REDIS_CLIENT.lpush(ALL_KEY, *req_data['combos'])
    PBARS[ALL_KEY].update(len(req_data['combos']))
    return 'ok'


@app.route('/report-finished', methods=['POST'])
def report_finished_benchmark():
    finished = request.get_json(force=True)['finished']
    PBARS[WORKING_KEY].update(-1)
    PBARS[WORKING_KEY].refresh()
    configs = []
    for region in finished:
        provider = get_region_provider(region)
        REDIS_CLIENT.decr(provider, 1)
        PBARS[provider].update(-1)
        PBARS[provider].refresh()
        configs.append(BenchmarkHost(provider=provider, region=region))
    put_into_finished_queue(finished)
    PBARS[FINISHED_KEY].update(1)
    return 'ok'


@app.route('/next-benchmark', methods=['GET'])
def get_next_benchmark():
    run = True
    while run:
        candidate = get_from_backlog_queue()
        if candidate is None:
            run = should_keep_running()
            continue
        if can_execute_combo(candidate):
            for region in candidate:
                provider = get_region_provider(region)
                PBARS[provider].update(1)
                REDIS_CLIENT.incr(provider, 1)
            PBARS[ALL_KEY].update(-1)
            PBARS[WORKING_KEY].update(1)
            put_into_working_queue(candidate)
            return jsonify(candidate)
        else:
            put_into_backlog_queue(candidate)
    return jsonify(None)


def do_run():
    run = True
    open('simulator.log', 'w').close()
    while run:
        if random.choice([1, 2, 3, 4]) != 1 and not is_working_queue_empty():
            report_finished_benchmark()

        candidate = get_from_backlog_queue()
        if candidate is None:
            run = should_keep_running()
            continue
        if can_execute_combo(candidate):
            for region in candidate:
                provider = get_region_provider(region)
                PBARS[provider].update(1)
                REDIS_CLIENT.incr(provider, 1)
            PBARS[ALL_KEY].update(-1)
            put_into_working_queue(candidate)
            PBARS[WORKING_KEY].update(1)
        else:
            put_into_backlog_queue(candidate)
        run = should_keep_running()
        PBARS[ALL_KEY].refresh()

    for pbar in PBARS.values():
        pbar.close()


if __name__ == "__main__":
    app.run(debug=True)
