terraform {
  required_providers {
    digitalocean = {
      source = "digitalocean/digitalocean"
    }
    local = {
      source = "hashicorp/local"
    }
    tls = {
      source = "hashicorp/tls"
    }
    linode = {
      source = "linode/linode"
    }
  }
  required_version = ">= 0.13"
}
