#!/usr/bin/env bash
# Simple maar vrij complete inventory van de machine

set -euo pipefail

HOST=$(hostname)
NOW=$(date -Iseconds || date)

echo "=================================================="
echo " SYSTEM INVENTORY - $HOST  ($NOW)"
echo "=================================================="
echo

# ---------- OS / Kernel ----------
echo "### OS / Kernel"
if command -v lsb_release >/dev/null 2>&1; then
  lsb_release -a 2>/dev/null || true
else
  echo "lsb_release niet gevonden, /etc/os-release:"
  cat /etc/os-release 2>/dev/null || true
fi
echo
uname -a
echo

# ---------- CPU ----------
echo "### CPU"
if command -v lscpu >/dev/null 2>&1; then
  lscpu | egrep 'Model name|Socket|CPU\(s\)|Thread|Core|NUMA node' || lscpu
else
  echo "lscpu niet gevonden, val terug op /proc/cpuinfo (samenvatting):"
  grep -m 1 'model name' /proc/cpuinfo || true
  echo "Totaal vCPU's: $(grep -c '^processor' /proc/cpuinfo || echo '?')"
fi
echo

# ---------- RAM ----------
echo "### RAM"
free -h || true
echo

# ---------- GPU (NVIDIA) ----------
echo "### GPU (NVIDIA)"
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "- Basis info:"
  nvidia-smi --query-gpu=index,name,memory.total,memory.free,utilization.gpu,utilization.memory \
             --format=csv,noheader 2>/dev/null || nvidia-smi || true
  echo
  echo "- Topologie (GPU onderling / CPU):"
  nvidia-smi topo -m 2>/dev/null || echo "nvidia-smi topo -m niet beschikbaar"
else
  echo "nvidia-smi niet gevonden -> NVIDIA drivers / CUDA lijken niet actief."
fi
echo

# ---------- Storage ----------
echo "### Disk / Filesystems"
echo "- Blokken (schijven + partities):"
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE | sed 's/^/  /'
echo
echo "- Filesystem gebruik:"
df -hT | sed 's/^/  /'
echo

# ---------- Network ----------
echo "### Network"
echo "- Interfaces + IP's:"
ip -br a | sed 's/^/  /'
echo
echo "- Default route:"
ip route show default 2>/dev/null | sed 's/^/  /' || echo "  geen default route info"
echo

# ---------- Belangrijke tools ----------
echo "### Belangrijke tools"
for bin in python3 pip3 conda docker nvidia-smi ollama git curl; do
  if command -v "$bin" >/dev/null 2>&1; then
    VER=$("$bin" --version 2>&1 | head -n 1)
    printf "  %-10s %s\n" "$bin" "$VER"
  else
    printf "  %-10s NIET gevonden\n" "$bin"
  fi
done
echo

# ---------- Docker details (als aanwezig) ----------
if command -v docker >/dev/null 2>&1; then
  echo "### Docker"
  echo "- Docker info (samenvatting):"
  docker info 2>/dev/null | egrep 'Server Version|Storage Driver|Cgroup Driver|Runtimes' || echo "  geen docker info"
  echo
  echo "- Draaiende containers:"
  docker ps --format '  {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' || echo "  geen containers"
  echo
fi

# ---------- Python omgeving ----------
if command -v python3 >/dev/null 2>&1; then
  echo "### Python pakketten (top 20 op naam, optioneel uit te breiden)"
  python3 - << 'PY' 2>/dev/null || echo "  kon geen pip list draaien"
import pkg_resources
pkgs = sorted(pkg_resources.working_set, key=lambda p: p.project_name.lower())
for p in pkgs[:20]:
    print(f"  {p.project_name}=={p.version}")
PY
  echo
fi

echo "=================================================="
echo " KLAAR: $HOST"
echo "=================================================="
