#!/usr/bin/env bash
ips=(

)

for ip in "${ips[@]}"; do
  scp -i id_rsa deployer-package.tar.gz root@$ip:~/
  ssh -t -t -i id_rsa -o StrictHostKeyChecking=no root@$ip /bin/bash <<EOF
hostname
tar xvfz deployer-package.tar.gz
rm -r ~/cloud-benchmarking
rm -r ~/cloud-benchmarking-deployer
mv ~/pkg/cloud-benchmarking ~/
mv ~/pkg/cloud-benchmarking-deployer ~/


echo 'done'
exit 0
EOF

done