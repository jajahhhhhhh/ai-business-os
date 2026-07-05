variable "hcloud_token" {
  description = "Hetzner Cloud API token (project-scoped, read/write). Keep out of VCS."
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "Owner SSH public key (contents of ~/.ssh/id_ed25519.pub)."
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "CIDRs allowed to reach SSH. Tighten to your IP when it is static."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "server_type" {
  description = "Hetzner server type (§16 baseline: 4 vCPU / 8 GB)."
  type        = string
  default     = "cpx31"
}

variable "location" {
  description = "Hetzner location (sgp = Singapore, closest to Thailand)."
  type        = string
  default     = "sgp"
}
