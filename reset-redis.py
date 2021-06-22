import os, json
from simulator import clear_redis, insert_data


if __name__ == '__main__':
    clear_redis()
    with open(os.path.join('..', 'cloud-benchmarking', 'sets-for-redis.json'), 'r') as fp:
        region_combos = json.load(fp)
    insert_data(data_to_insert=region_combos)
