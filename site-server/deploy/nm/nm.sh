#!/usr/bin/env bash
# مدیریتِ سریعِ NMarketing:  nm.sh status | restart | stop | start | logs [web|celery|beat|website|3d] | update
U="nm-web nm-celery nm-celery-beat nm-website nm-up3d-orchestrator nm-up3d-worker"
case "${1:-status}" in
  status)  for u in $U; do printf '%-22s %s\n' "$u" "$(systemctl is-active $u)"; done;
           curl -s -o /dev/null -w "healthz %{http_code}\n" http://127.0.0.1:8040/healthz ;;
  restart) systemctl restart $U; "$0" status ;;
  stop)    systemctl stop $U ;;
  start)   systemctl start $U; "$0" status ;;
  logs)    case "${2:-web}" in
             web) tail -n 80 /var/www/NM/upmarket/logs/web-error.log ;;
             celery) tail -n 80 /var/www/NM/upmarket/logs/celery.log ;;
             beat) tail -n 40 /var/www/NM/upmarket/logs/beat.log ;;
             website) journalctl -u nm-website -n 60 --no-pager ;;
             3d) journalctl -u nm-up3d-orchestrator -u nm-up3d-worker -n 60 --no-pager ;;
           esac ;;
  update)  bash /var/www/NM/upmarket/deploy/nm/install.sh ;;
  *) echo "nm.sh status|restart|stop|start|logs [web|celery|beat|website|3d]|update" ;;
esac
