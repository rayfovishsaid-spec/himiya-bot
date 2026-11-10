#!/bin/bash
# Супервизор: держит ровно один экземпляр бота живым.
# Если процесс завис/упал — поднимает заново. Код 2 (занят bot.lock) — выходим.
cd "$(dirname "$0")"
while true; do
    python3 -u bot.py
    code=$?
    if [ "$code" -eq 2 ]; then
        echo "[supervisor] другой экземпляр уже работает — выхожу"
        break
    fi
    echo "[supervisor] бот завершился с кодом $code, перезапуск через 3 с"
    sleep 3
done
