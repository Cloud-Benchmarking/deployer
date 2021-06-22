import json
import os
import shutil
import subprocess
from pprint import pprint

from python_terraform import *


COHORT = 'all-providers-real'
PROJECT_NAME = 'cloud-benchmarking'
PROJECT_DEPLOYER_NAME = 'cloud-benchmarking-deployer'
DATA_DIR = 'artifacts'

# replacement strings
WINDOWS_LINE_ENDING = b'\r\n'
UNIX_LINE_ENDING = b'\n'


def fix_line_endings(file_path):
    with open(file_path, 'rb') as open_file:
        content = open_file.read()

    content = content.replace(WINDOWS_LINE_ENDING, UNIX_LINE_ENDING)

    with open(file_path, 'wb') as open_file:
        open_file.write(content)


if __name__ == '__main__':
    tf = Terraform(working_dir='terraform')
    tf.init()

    rsync_dest_dr = os.path.join(PROJECT_NAME, 'rsync', COHORT)
    if not os.path.exists(rsync_dest_dr):
        os.makedirs(rsync_dest_dr)

    status_servers = tf.tfstate.outputs['status_servers']['value']
    pprint(status_servers)

    shutil.copyfile(os.path.join('terraform', 'id_rsa'), os.path.join(f'{PROJECT_NAME}', 'id_rsa'))
    shutil.copyfile(os.path.join('terraform', 'id_rsa.pub'), os.path.join(f'{PROJECT_NAME}', 'id_rsa.pub'))

    rsync_script_path = os.path.join(f'{PROJECT_NAME}', f'rsync-{COHORT}.sh')
    rsync_joblog_path = os.path.join(f'{PROJECT_NAME}', f'rsync-{COHORT}.joblog.sh')

    rsync_file = open(rsync_script_path, 'w')
    rsync_joblog = open(rsync_joblog_path, 'w')

    rsync_file.write(f'cd {PROJECT_NAME}/' + '\n')
    rsync_joblog.write(f'cd {PROJECT_NAME}/' + '\n')

    for status_server in status_servers:
        name, ip = eval(status_server)[0]
        # subprocess.run([
        #     'ssh-keygen',
        #     '-R', ip
        # ])
        # print(f'{eval(status_server)[0]},')
        print(f'ssh-keygen -R {ip}')
        rsync_file.write(
            f"rsync -r -e 'ssh -i id_rsa -o StrictHostKeyChecking=no' root@{ip}:/root/{PROJECT_NAME}/{DATA_DIR}/{COHORT}/ {PROJECT_NAME}/rsync/{COHORT}/{name}/ &" + '\n')
        rsync_joblog.write(
            f"rsync -r -e 'ssh -i id_rsa -o StrictHostKeyChecking=no' root@{ip}:/root/{PROJECT_DEPLOYER_NAME}/nohup.out {PROJECT_NAME}/rsync/{COHORT}/_joblogs/{name}.nohup.out &" + '\n')
    rsync_file.close()
    rsync_joblog.close()

    fix_line_endings(rsync_script_path)
    fix_line_endings(rsync_joblog_path)
