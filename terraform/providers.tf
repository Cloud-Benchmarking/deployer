provider "digitalocean" {
    token = var.do_api_token
    spaces_access_id  = var.do_space_key
    spaces_secret_key = var.do_space_secret
}

provider "linode" {
    token = var.linode_api_token
}