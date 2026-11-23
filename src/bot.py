from pathlib import Path

import telebot
from config import BOT_TOKEN

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# Файл хранится рядом с bot.py, поэтому запуск из другой папки не мешает.
GROUPS_FILE = Path(__file__).resolve().parent / "groups.txt"

# Общее состояние, доступное обработчикам и игровому модулю.
game_state = {"started": False}


def get_groups():
    """Возвращает список зарегистрированных ID групп."""
    try:
        with GROUPS_FILE.open("r", encoding="utf-8") as file:
            groups = []

            for line in file:
                line = line.strip()

                if not line:
                    continue

                try:
                    chat_id = int(line)
                    if chat_id not in groups:
                        groups.append(chat_id)
                except ValueError:
                    print(f"[WARNING] Некорректная строка в groups.txt: {line}")

            return groups

    except FileNotFoundError:
        return []
    except OSError as error:
        print(f"[ERROR] Не удалось прочитать groups.txt: {error}")
        return []


def save_groups(groups):
    """Безопасно перезаписывает список групп."""
    temporary_file = GROUPS_FILE.with_suffix(".tmp")

    try:
        with temporary_file.open("w", encoding="utf-8") as file:
            for chat_id in groups:
                file.write(f"{chat_id}\n")

        temporary_file.replace(GROUPS_FILE)

    except OSError as error:
        print(f"[ERROR] Не удалось сохранить список групп: {error}")


def add_group(chat_id):
    groups = get_groups()

    if chat_id not in groups:
        groups.append(chat_id)
        save_groups(groups)
        print(f"[INFO] Добавлена группа: {chat_id}")


def remove_group(chat_id):
    groups = get_groups()

    if chat_id in groups:
        groups.remove(chat_id)
        save_groups(groups)
        print(f"[INFO] Удалена группа: {chat_id}")


@bot.my_chat_member_handler()
def handle_chat_member(update):
    """Регистрирует группу при добавлении бота и удаляет при исключении."""
    chat_id = update.chat.id
    status = update.new_chat_member.status

    if status in ("member", "administrator"):
        add_group(chat_id)
    elif status in ("left", "kicked"):
        remove_group(chat_id)
