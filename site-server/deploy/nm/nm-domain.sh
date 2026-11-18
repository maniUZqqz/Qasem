#!/usr/bin/env bash
# nm-domain.sh - NMarketing را روی دامنهٔ خودتان با HTTPS بنشان.  راهنما: nm-domain.sh --help  ·  docs/deploy/domain-fa.md
# نصب: ln -sf /var/www/NM/upmarket/deploy/nm/nm-domain.sh /root/nm-domain.sh
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec "${NM_BOOT_PYTHON:-python3}" "$HERE/nm_domain.py" "$@"
