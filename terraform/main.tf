resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits = 4096
}
resource "local_file" "ssh_private_key" {
  content = tls_private_key.ssh.private_key_pem
  filename = "${path.module}/id_rsa"
  file_permission = "600"
}
resource "local_file" "ssh_public_key" {
  content = tls_private_key.ssh.public_key_openssh
  filename = "${path.module}/id_rsa.pub"
  file_permission = "600"
}
/*
resource "digitalocean_database_cluster" "grabber-cluster" {
  name       = "grabber-cluster"
  engine     = "redis"
  version    = "6"
  size       = "db-s-2vcpu-4gb"
  region     = "sfo2"
  node_count = 1
  eviction_policy = "noeviction"
}

output "do_redis_password" {
  value = digitalocean_database_cluster.grabber-cluster.password
}
output "do_redis_hostname" {
  value = digitalocean_database_cluster.grabber-cluster.host
}
output "do_redis_port" {
  value = digitalocean_database_cluster.grabber-cluster.port
}
//*/
///*

/*
resource "linode_sshkey" "ssh_key" {
  label = "deployer-key"
  ssh_key = chomp(tls_private_key.ssh.public_key_openssh)
}

resource "linode_instance" "deployer" {
  count = 1
  image = "linode/ubuntu20.10"
  label = format("deployer-%s", count.index)
  region = "us-west"
    type   = "g6-dedicated-48"
//  type = "g6-standard-1"

  authorized_keys = [
    linode_sshkey.ssh_key.ssh_key]

  tags = [
    "deployer"]

  connection {
    type = "ssh"
    user = "root"
    private_key = tls_private_key.ssh.private_key_pem
    host = self.ip_address
  }

  provisioner "file" {
    source = "pyterra-requirements.txt"
    destination = "~/pyterra-requirements.txt"
  }

  provisioner "file" {
    source = "deployer-package.tar.gz"
    destination = "~/deployer-package.tar.gz"
  }

  provisioner "file" {
    source = "provision.sh"
    destination = "/tmp/provision.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/provision.sh",
      "/tmp/provision.sh deployer-${count.index}"
    ]
  }
//  provisioner "remote-exec" {
//    inline = [
//      "cd ~/cloud-benchmarking-deployer",
//      "nohup python3 launcher.py 1>&2 | tee deployer-${count.index}.log &"
//    ]
//  }
}

output "ips" {
  value = linode_instance.deployer[*].ip_address
}
output "status_servers" {
  # Result is a map from availability zone to instance ids, such as:
  value = [
  for instance in linode_instance.deployer:
  "('${instance.label}', '${instance.ip_address}'),"
  ]
}
//*/
///*
resource "digitalocean_ssh_key" "ssh_key" {
  name = "deployer-key"
  public_key = tls_private_key.ssh.public_key_openssh
}
resource "digitalocean_droplet" "deployer" {
  count = 1
  image = "ubuntu-20-10-x64"
  name = format("deployer-%s", count.index + 1)
  region = "sfo3"
  size = "c-32"
  monitoring = true

  ssh_keys = [
    digitalocean_ssh_key.ssh_key.id]
  tags = [
    "deployer"
  ]

  connection {
    type = "ssh"
    user = "root"
    private_key = tls_private_key.ssh.private_key_pem
    host = self.ipv4_address
  }

  provisioner "file" {
    source = "pyterra-requirements.txt"
    destination = "~/pyterra-requirements.txt"
  }

  provisioner "file" {
    source = "deployer-package.tar.gz"
    destination = "~/deployer-package.tar.gz"
  }

  provisioner "file" {
    source = "provision.sh"
    destination = "/tmp/provision.sh"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod +x /tmp/provision.sh",
      "/tmp/provision.sh deployer-${count.index + 1}"
    ]
  }
  //  provisioner "remote-exec" {
  //    inline = [
  //      "cd ~/cloud-benchmarking-deployer",
  //      "nohup python3 launcher.py 1>&2 &"
  //    ]
  //  }
}

output "ips" {
  value = digitalocean_droplet.deployer[*].ipv4_address
}
output "status_servers" {
  # Result is a map from availability zone to instance ids, such as:
  value = [
  for instance in digitalocean_droplet.deployer:
  "('${instance.name}', '${instance.ipv4_address}'),"
  ]
}
//*/