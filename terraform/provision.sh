#!/bin/bash

function wait_lock() {
  echo "[*] lsof lock-frontend"
  while lsof /var/lib/dpkg/lock-frontend; do
    echo 'waiting on lsof lock-frontend'
    sleep 5
  done
}

echo "[*] starting provisioning"
touch ~/.hushlogin
hostnamectl set-hostname $1

wait_lock

wait_lock

# https://github.com/ansible/ansible/issues/25414#issuecomment-401212950
# Ensure to disable u-u to prevent breaking later
systemctl mask unattended-upgrades.service
systemctl stop unattended-upgrades.service

# Ensure process is in fact off:
echo "Ensuring unattended-upgrades are in fact disabled"
#while pgrep unattended; echo 'waiting on unattended-upgrades'; do sleep 1; done
sudo systemctl disable --now apt-daily{{,-upgrade}.service,{,-upgrade}.timer}
sudo systemctl disable --now unattended-upgrades

## try another method as well - https://github.com/chef/bento/issues/609#issuecomment-226043057
#systemctl disable apt-daily.service # disable run when system boot
#systemctl disable apt-daily.timer   # disable timer run
#systemctl stop apt-daily.service
#systemctl stop apt-daily.timer

# https://github.com/ansible/ansible/issues/25414#issuecomment-486060125
echo "[*] systemd-run for apt-daily"
systemd-run --property="After=apt-daily.service apt-daily-upgrade.service" --wait /bin/true
echo "[*] apt-daily has stopped"

apt-get update -y

wait_lock

echo "[*] installing build tools"
apt-get install -y unzip dos2unix python3-pip python3-venv net-tools

wait_lock

echo "[*] installing terraform"
wget https://releases.hashicorp.com/terraform/0.14.7/terraform_0.14.7_linux_amd64.zip -O terraform.zip
unzip terraform.zip
mv terraform /usr/local/bin/
terraform --version
tar xvfz deployer-package.tar.gz

echo "[*] installing pip3 requirements"
ls -al
mv ~/pkg/cloud-benchmarking ~/
mv ~/pkg/cloud-benchmarking-deployer ~/
pip3 install -r ~/pyterra-requirements.txt