"""Мелкие утилиты."""
import html


def esc(value) -> str:
    """Экранирует пользовательский текст перед вставкой в HTML-сообщение."""
    return html.escape("" if value is None else str(value), quote=False)


async def safe_edit(message, text: str, reply_markup=None) -> bool:
    """edit_text, который не падает на «message is not modified».

    Именно эта ошибка вешала кнопки: Telegram отвечает 400, если новый текст
    совпадает с текущим, а исключение не давало дойти до call.answer().
    """
    from aiogram.exceptions import TelegramBadRequest

    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return False
        raise
