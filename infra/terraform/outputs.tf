output "server_ip" {
  description = "Point your domain's A record here."
  value       = hcloud_server.aibos.ipv4_address
}

output "server_ipv6" {
  value = hcloud_server.aibos.ipv6_address
}

output "ssh" {
  value = "ssh deploy@${hcloud_server.aibos.ipv4_address}"
}
