import json
import os

import subprocess
import sys
import time

import humanize
import redis
from colorama import Fore, Style
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)


def get_redis_client():
    return redis.Redis(host=os.environ.get('REDIS_HOST'),
                       username='default', password=os.environ.get('REDIS_PASSWORD'),
                       port=os.environ.get('REDIS_PORT'), ssl=True, db=0)


REDIS_CLIENT = get_redis_client()


def run_ssh_cmd(ip_str, cmd_str):
    cmd = [
        'ssh',
        '-i', 'id_rsa',
        '-o', 'StrictHostKeyChecking=no',
        f'root@{ip_str}'
    ]
    cmd.extend(cmd_str.split())
    p = subprocess.run(cmd, capture_output=True)
    return str(p.stdout.decode('ascii'))


def start_bucketeer(ip):
    return run_ssh_cmd(ip, "nohup python3 bucketeer.py 2>&1 < /dev/null &")


def get_bucket_count(ip):
    resp = run_ssh_cmd(ip, 'wc -l joblog.collector-*.log').split(' ')[0]
    if len(resp.strip()) == 0:
        resp = 0
    return int(resp)


def get_torrent_count(ip):
    return int(run_ssh_cmd(ip, 'ls archive | wc -l'))


def get_workdir_size(ip):
    resp = run_ssh_cmd(ip, 'du -h data | tail -n 1').split()
    if len(resp) == 0:
        return 0
    return resp[0]


def get_data_dir_size(ip):
    resp = run_ssh_cmd(ip, 'du data | tail -n 1').split()
    if len(resp) == 0:
        return 0
    return int(resp[0].strip())
    # return run_ssh_cmd(ip, 'du -h data | tail -n 1')


def get_total_lines(ip):
    resp = run_ssh_cmd(ip, "wc -l ~/pub_issue_ids.txt").split(' ')[0]

    if len(resp) == 0:
        resp = '0'
    return int(resp)


last_count = {}

if __name__ == '__main__':
    EXPECTED_PROCESSES = 30
    PROCESS_COUNT_EXTRA_COUNT = 2
    # for server in servers:
    #     subprocess.run(['ssh-keygen', '-R', server[1]])
    ljust_len = len("255.255.255.255")
    rjust_len = len("1,000")
    rjust_delta_len = len("10,000")
    while True:
        servers = []
        outputs = json.load(open('terraform.tfstate'))['outputs']
        status_servers = outputs['status_servers']['value']
        for status_server in status_servers:
            name, ip = eval(status_server)[0]
            servers.append((name, ip))

        total = 0
        total_running_count = 0
        for server in servers:
            ip = server[1]
            file = f"{int(server[0].split('-')[1])}.txt"
            resp = run_ssh_cmd(ip, "ps aux | grep pyterra.py | wc -l").strip()
            if len(resp) == 0:
                process_count = 0
            else:
                process_count = int(resp)

            running_count = process_count - PROCESS_COUNT_EXTRA_COUNT
            running_count_matches_expected = (process_count == (PROCESS_COUNT_EXTRA_COUNT + EXPECTED_PROCESSES))
            if running_count_matches_expected:
                prefix = Fore.GREEN + f'[{running_count}/{EXPECTED_PROCESSES}] ' + Style.RESET_ALL
            else:
                prefix = Fore.RED + f'[{running_count}/{EXPECTED_PROCESSES}] ' + Style.RESET_ALL

            data_dir_size = get_data_dir_size(ip) * 1024
            print(
                # prefix + f'{ip.ljust(ljust_len)}\t{server[0]}:\t{humanize.intcomma(get_working_line_number(ip)).rjust(rjust_len)} / {humanize.intcomma(get_bucket_count(ip)).rjust(rjust_len)} buckets')
                prefix + f'{ip.ljust(ljust_len)}\t{server[0]}:\t{str(running_count).rjust(rjust_len)}')

            total_running_count += running_count
            sys.stdout.flush()
        print(f'[{total_running_count}/{EXPECTED_PROCESSES * len(servers)}] {humanize.intword(total_running_count)}')
        sys.stdout.flush()
        time.sleep(60)
