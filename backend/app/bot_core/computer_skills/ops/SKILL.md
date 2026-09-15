---
name: ops
description: Состояние VPS: диск, память, docker, nginx, systemd, хвост логов. Команды через ssh_exec.
---

Хост, логин и пароль или ключ – из чата. Сначала `list_connectors`, если доступ уже был.

Снимай картину узкими командами, не «расскажи про сервер»:
1. `uname -a; uptime; df -h; free -m`
2. Сервис из задачи: `systemctl is-active …; systemctl status … --no-pager -l | tail`
3. Контейнеры: `docker ps -a` только если пользователь про docker/compose.
4. Логи: `journalctl -u … -n 80 --no-pager` или `tail -n 80` конкретного файла. Не `tail -f`, не весь syslog.
5. Nginx/ошибки: конфиг не переписывай без явной просьбы. Сначала `nginx -t`.

Нельзя без отдельной фразы подтверждения: rm -rf, mkfs, drop, reboot, docker system prune, stop прод-базы.

Ключи и пароли в ответ не пиши. Упало – короткий stderr и следующий безопасный шаг, не лекция.
