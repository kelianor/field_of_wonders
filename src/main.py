import threading
import time

from telebot.apihelper import ApiTelegramException

from bot import bot, get_groups
from game import ALPHABET, Game, Group


def start_bot():
    """Запускает polling и повторяет запуск после непредвиденной ошибки."""
    while True:
        try:
            print("[INFO] Telegram-бот запущен")
            bot.infinity_polling(
                skip_pending=True,
                timeout=20,
                long_polling_timeout=20
            )
        except KeyboardInterrupt:
            print("[INFO] Остановка Telegram-бота")
            break
        except Exception as error:
            print(f"[ERROR] Ошибка polling: {error}")
            print("[INFO] Повторная попытка через 5 секунд")
            time.sleep(5)


def read_word():
    while True:
        word = input("Введите загаданное слово: ").strip().upper()

        if not word:
            print("Слово не может быть пустым.")
            continue

        if not any(letter in ALPHABET for letter in word):
            print("В слове должна быть хотя бы одна русская буква.")
            continue

        return word


def read_clue():
    while True:
        clue = input("Введите подсказку: ").strip()

        if clue:
            return clue

        print("Подсказка не может быть пустой.")


def main():
    bot_thread = threading.Thread(
        target=start_bot,
        name="telegram-polling",
        daemon=True
    )
    bot_thread.start()

    print("Бот работает. Для остановки нажмите Ctrl+C.")

    try:
        while True:
            word = read_word()
            clue = read_clue()

            input("Нажмите Enter, чтобы начать игру...")

            groups = get_groups()

            if not groups:
                print(
                    "Нет зарегистрированных групп. "
                    "Добавьте бота в группу и выполните там /start."
                )
                continue

            game = Game(word, clue)

            for chat_id in groups:
                game.append_group(Group(chat_id))

            print(f"Игра запускается. Количество групп: {len(groups)}")

            try:
                game.start_game()
            except Exception as error:
                print(f"[ERROR] Критическая ошибка игры: {error}")

            print("Игра завершена.")

    except KeyboardInterrupt:
        print("\n[INFO] Программа остановлена пользователем.")


if __name__ == "__main__":
    main()
