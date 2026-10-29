#!/usr/bin/env bash
set -euo pipefail
umask 077

# Amazon Linux 2023: servidor sem banco local ou servicos adicionais.
dnf install -y docker
systemctl enable --now docker

compose_version=v5.6.1
download_dir=$(mktemp -d)
compose_url="https://github.com/docker/compose/releases/download/${compose_version}"
curl --fail --silent --show-error --location --proto '=https' \
    "${compose_url}/docker-compose-linux-x86_64" -o "${download_dir}/docker-compose-linux-x86_64"
curl --fail --silent --show-error --location --proto '=https' \
    "${compose_url}/docker-compose-linux-x86_64.sha256" -o "${download_dir}/compose.sha256"
(cd "$download_dir" && sha256sum --check compose.sha256)
install -d -m 0755 /usr/local/lib/docker/cli-plugins
install -m 0755 "${download_dir}/docker-compose-linux-x86_64" /usr/local/lib/docker/cli-plugins/docker-compose

install -d -o ec2-user -g ec2-user -m 0755 /opt/xfit
install -d -o root -g root -m 0700 /opt/xfit-secrets

# A micro tem 1 GiB; swap no volume criptografado protege picos do build/app.
if [ ! -f /swapfile ]; then
    fallocate -l 512M /swapfile
    chmod 0600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    printf '/swapfile swap swap defaults 0 0\n' >> /etc/fstab
fi
docker compose version
