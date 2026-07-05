# AI Business OS — single-VPS provisioning (ARCHITECTURE.md §16, ADR-0001).
# Provider: Hetzner Cloud. Cost reference: CPX31 ≈ €13-15/mo.

terraform {
  required_version = ">= 1.7"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

resource "hcloud_ssh_key" "owner" {
  name       = "aibos-owner"
  public_key = var.ssh_public_key
}

resource "hcloud_firewall" "aibos" {
  name = "aibos-fw"

  rule {
    description = "SSH (key-only; fail2ban on host)"
    direction   = "in"
    protocol    = "tcp"
    port        = "22"
    source_ips  = var.ssh_allowed_cidrs
  }
  rule {
    description = "HTTP (Caddy ACME + redirect)"
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
  rule {
    description = "HTTPS"
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "aibos" {
  name         = "aibos-prod"
  image        = "ubuntu-24.04"
  server_type  = var.server_type
  location     = var.location
  ssh_keys     = [hcloud_ssh_key.owner.id]
  firewall_ids = [hcloud_firewall.aibos.id]

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_public_key = var.ssh_public_key
  })

  backups = true # Hetzner-level image backups (+20% cost) on top of our B2 data backups

  lifecycle {
    prevent_destroy = true # the database lives here; destroy only deliberately
  }
}
