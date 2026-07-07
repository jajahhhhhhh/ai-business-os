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
  # cpx32 = 4 vCPU / 8 GB / 160 GB (§16 baseline). The older cpx31 was retired
  # by Hetzner for new orders; cpx32 is the current-generation equivalent.
  description = "Hetzner server type (4 vCPU / 8 GB baseline)."
  type        = string
  default     = "cpx32"
}

variable "location" {
  # nbg1 = Nuremberg, DE. Cheapest CPX tier (~€15/mo vs ~€38 in Singapore);
  # latency to Thailand (~200ms) is irrelevant for a dashboard + cron jobs.
  # Valid: fsn1, nbg1, hel1 (EU), ash, hil (US), sin (Singapore).
  description = "Hetzner location code."
  type        = string
  default     = "nbg1"
}
