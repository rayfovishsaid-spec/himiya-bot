"""Точка входа для хостингов (bothost и др.), которым нужен main.py.

Логика целиком в bot.py — здесь только запуск, чтобы платформа,
ищущая `main.py`, сразу нашла вход.
"""
import asyncio

from bot import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
