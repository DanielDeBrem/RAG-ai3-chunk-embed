#!/usr/bin/env bash
#
# GPU Temperature-Based Fan Control voor Supermicro
#
# WAARSCHUWING: Dit script past fan speeds aan via IPMI.
# Gebruik met voorzichtigheid! Test eerst handmatig.
#
# Temperature zones:
# - <60°C: Quiet mode (30% fans)
# - 60-75°C: Normal mode (50% fans)
# - 75-85°C: Active cooling (70% fans)
# - 85-90°C: High cooling (90% fans)
# - >90°C: MAX cooling (100% fans)
#

set -euo pipefail

# Configuratie
CHECK_INTERVAL=10  # Seconden tussen checks
LOG_FILE="/home/daniel/Projects/RAG-ai3-chunk-embed/logs/fan_control.log"
DRY_RUN="${DRY_RUN:-true}"  # Set to 'false' om daadwerkelijk fans aan te passen

# IPMI settings (pas aan voor jouw systeem)
IPMI_HOST="${IPMI_HOST:-localhost}"
IPMI_USER="${IPMI_USER:-ADMIN}"
IPMI_PASS="${IPMI_PASS:-}"  # Set via environment variable

# Fan zones (Supermicro heeft meestal meerdere zones)
FAN_ZONE_CPU=0x00
FAN_ZONE_PERIPHERAL=0x01

# Kleuren
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_color() {
    echo -e "${2}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

# Check of ipmitool beschikbaar is
if ! command -v ipmitool &> /dev/null; then
    log_color "ERROR: ipmitool not found. Install with: sudo apt install ipmitool" "$RED"
    exit 1
fi

# Haal max GPU temperatuur op
get_max_gpu_temp() {
    nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | sort -rn | head -1
}

# Haal gemiddelde GPU temperatuur op
get_avg_gpu_temp() {
    nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | \
        awk '{sum+=$1; count++} END {print int(sum/count)}'
}

# Set fan mode via IPMI
set_fan_mode() {
    local mode=$1  # 0 = Standard, 1 = Full, 2 = Optimal, 4 = Heavy IO
    
    if [ "$DRY_RUN" = "true" ]; then
        log_color "DRY_RUN: Would set fan mode to $mode" "$YELLOW"
        return 0
    fi
    
    if [ -z "$IPMI_PASS" ]; then
        # Local IPMI (geen password nodig)
        sudo ipmitool raw 0x30 0x45 0x01 "$mode" 2>/dev/null || {
            log_color "Failed to set fan mode (try with sudo)" "$RED"
            return 1
        }
    else
        # Remote IPMI
        ipmitool -H "$IPMI_HOST" -U "$IPMI_USER" -P "$IPMI_PASS" \
            raw 0x30 0x45 0x01 "$mode" 2>/dev/null || {
            log_color "Failed to set fan mode via remote IPMI" "$RED"
            return 1
        }
    fi
    
    log_color "Fan mode set to $mode" "$GREEN"
}

# Set fan speed percentage (alleen in manual mode)
set_fan_speed() {
    local zone=$1
    local speed=$2  # 0-100 percentage
    
    # Convert percentage to hex value (0-64 = 0-100%)
    local hex_speed=$(printf "0x%02x" $((speed * 64 / 100)))
    
    if [ "$DRY_RUN" = "true" ]; then
        log_color "DRY_RUN: Would set zone $zone to $speed% ($hex_speed)" "$YELLOW"
        return 0
    fi
    
    if [ -z "$IPMI_PASS" ]; then
        sudo ipmitool raw 0x30 0x70 0x66 0x01 "$zone" "$hex_speed" 2>/dev/null || {
            log_color "Failed to set fan speed" "$RED"
            return 1
        }
    else
        ipmitool -H "$IPMI_HOST" -U "$IPMI_USER" -P "$IPMI_PASS" \
            raw 0x30 0x70 0x66 0x01 "$zone" "$hex_speed" 2>/dev/null || {
            log_color "Failed to set fan speed via remote IPMI" "$RED"
            return 1
        }
    fi
}

# Main fan control loop
fan_control_loop() {
    log_color "Starting GPU temperature-based fan control" "$BLUE"
    log_color "DRY_RUN=$DRY_RUN (set to 'false' to actually control fans)" "$YELLOW"
    log_color "Check interval: ${CHECK_INTERVAL}s" "$BLUE"
    echo ""
    
    local current_mode="unknown"
    local current_speed=0
    
    while true; do
        # Get GPU temperatures
        local max_temp=$(get_max_gpu_temp)
        local avg_temp=$(get_avg_gpu_temp)
        
        # Determine required fan speed based on max temperature
        local target_speed=30
        local target_mode="optimal"
        
        if [ "$max_temp" -lt 60 ]; then
            target_speed=30
            target_mode="quiet"
        elif [ "$max_temp" -lt 75 ]; then
            target_speed=50
            target_mode="normal"
        elif [ "$max_temp" -lt 85 ]; then
            target_speed=70
            target_mode="active"
        elif [ "$max_temp" -lt 90 ]; then
            target_speed=90
            target_mode="high"
        else
            target_speed=100
            target_mode="MAX"
        fi
        
        # Log current status
        log "GPU Temps: Max=${max_temp}°C, Avg=${avg_temp}°C | Target: ${target_mode} (${target_speed}%)"
        
        # Adjust fans if needed (with hysteresis: only change if >5% difference)
        local speed_diff=$((target_speed - current_speed))
        if [ "${speed_diff#-}" -gt 5 ] || [ "$max_temp" -gt 90 ]; then
            log_color "Adjusting fans: ${current_speed}% → ${target_speed}% (mode: ${target_mode})" "$YELLOW"
            
            # Set to full manual control first
            set_fan_mode 0x01  # Full speed mode (we'll manually control from there)
            sleep 1
            
            # Set both zones to target speed
            set_fan_speed "$FAN_ZONE_CPU" "$target_speed"
            set_fan_speed "$FAN_ZONE_PERIPHERAL" "$target_speed"
            
            current_speed=$target_speed
            current_mode=$target_mode
        fi
        
        sleep "$CHECK_INTERVAL"
    done
}

# Cleanup function
cleanup() {
    log_color "Received interrupt signal, restoring automatic fan control..." "$YELLOW"
    
    if [ "$DRY_RUN" = "false" ]; then
        # Restore to automatic fan control
        set_fan_mode 0x00  # Standard/Auto mode
        log_color "Fans restored to automatic control" "$GREEN"
    fi
    
    exit 0
}

# Trap signals for cleanup
trap cleanup SIGINT SIGTERM

# Show warning
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          GPU Temperature-Based Fan Control                     ║"
echo "║                    SUPERMICRO IPMI                             ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "⚠️  WARNING: This script will control system fans via IPMI"
echo ""
echo "Current mode: DRY_RUN=$DRY_RUN"
if [ "$DRY_RUN" = "true" ]; then
    echo "  → No actual changes will be made (testing only)"
    echo "  → To enable: DRY_RUN=false $0"
else
    echo "  → LIVE MODE: Fans WILL be controlled!"
    echo "  → Press Ctrl+C to stop and restore automatic control"
    echo ""
    echo "Waiting 5 seconds... (Ctrl+C to abort)"
    sleep 5
fi
echo ""

# Create log directory
mkdir -p "$(dirname "$LOG_FILE")"

# Start fan control
fan_control_loop
