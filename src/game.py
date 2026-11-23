import html
import random
import time

from telebot.apihelper import ApiTelegramException

from bot import bot, game_state, remove_group, add_group


ALPHABET = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"

POLLS_TIMEOUT = 15
MSG_TIMEOUT = 2

# poll_id -> объект Group. Нужен для учёта проголосовавших пользователей.
poll_groups = {}


def is_group_unavailable(error):
    """Определяет ошибки, означающие потерю доступа к группе."""
    error_code = getattr(error, "error_code", None)
    description = str(error).lower()

    if error_code == 403:
        return True

    unavailable_messages = (
        "chat not found",
        "bot was kicked",
        "bot is not a member",
        "bot is not a participant",
    )

    return any(message in description for message in unavailable_messages)


def safe_delete_message(chat_id, message_id):
    """Удаляет сообщение, не завершая игру из-за уже удалённого сообщения."""
    if message_id is None:
        return

    try:
        bot.delete_message(chat_id, message_id)
    except ApiTelegramException as error:
        if is_group_unavailable(error):
            raise
        print(f"[WARNING] Не удалось удалить сообщение {message_id}: {error}")


class Word:
    def __init__(self, word, clue):
        self.__word = word.upper().strip()
        self.__clue = clue.strip()
        self.__opened_letters = set()
        self.__available_letters = ALPHABET

    def open_letter(self, letter):
        if letter not in self.__available_letters:
            return False

        self.__opened_letters.add(letter)
        self.__available_letters = self.__available_letters.replace(letter, "")
        return letter in self.__word

    def is_guessed(self):
        return all(
            letter in self.__opened_letters
            for letter in self.__word
            if letter in ALPHABET
        )

    def get_board(self):
        result = []

        for letter in self.__word:
            if letter in self.__opened_letters or letter not in ALPHABET:
                result.append(letter)
            else:
                result.append("_")

        return " ".join(result)

    @property
    def clue(self):
        return self.__clue

    @property
    def available_letters(self):
        return self.__available_letters


class Group:
    def __init__(self, chat_id):
        self.__chat_id = chat_id
        self.__score = 0
        self.__poll_message_id = None
        self.__poll_unique_id = None
        self.__info_message_id = None
        self.__result_message_id = None
        self.__users = {}

    def add_user(self, user):
        if user is not None:
            self.__users[user.id] = user

    @property
    def users(self):
        return list(self.__users.values())

    @property
    def score(self):
        return self.__score

    @property
    def chat_id(self):
        return self.__chat_id

    def start_game(self):
        bot.send_message(
            self.__chat_id,
            "Игра началась!\nЖелаю удачи!"
        )

    def start_poll(self, word):
        # Убираем сообщения прошлого раунда. Их отсутствие не должно ломать игру.
        safe_delete_message(self.__chat_id, self.__info_message_id)
        safe_delete_message(self.__chat_id, self.__poll_message_id)
        safe_delete_message(self.__chat_id, self.__result_message_id)

        self.__info_message_id = None
        self.__poll_message_id = None
        self.__result_message_id = None

        info = bot.send_message(
            self.__chat_id,
            f"Отгадайте слово!\n"
            f"{word.get_board()}\n"
            f"Подсказка:\n{word.clue}\n"
            f"Количество очков:\n{self.__score}"
        )
        self.__info_message_id = info.message_id

        available = list(word.available_letters)

        if len(available) < 2:
            raise RuntimeError("Недостаточно доступных букв для создания опроса")

        # Telegram Poll поддерживает от 2 до 10 вариантов.
        options = available[:3]

        poll_message = bot.send_poll(
            chat_id=self.__chat_id,
            question=(
                f"Выберите букву или добавьте свой вариант. "
                f"Время голосования — {POLLS_TIMEOUT} секунд."
            ),
            options=options,
            is_anonymous=False,
            allows_multiple_answers=False,
            allow_adding_options=True,
        )

        if poll_message.poll is None:
            raise RuntimeError("Telegram не вернул данные созданного опроса")

        self.__poll_message_id = poll_message.message_id
        self.__poll_unique_id = poll_message.poll.id
        poll_groups[self.__poll_unique_id] = self

        print(
            f"[INFO] Опрос создан: группа={self.__chat_id}, "
            f"poll_id={self.__poll_unique_id}"
        )

    def end_poll(self, word):
        """Закрывает опрос и применяет выбранную букву."""
        if self.__poll_message_id is None:
            return

        poll = None

        try:
            poll = bot.stop_poll(
                self.__chat_id,
                self.__poll_message_id
            )
        except ApiTelegramException as error:
            if is_group_unavailable(error):
                raise

            # Например, опрос уже автоматически закрылся.
            # В этом случае используем случайную доступную букву.
            print(
                f"[WARNING] Не удалось получить результат опроса "
                f"в группе {self.__chat_id}: {error}"
            )
        finally:
            if self.__poll_unique_id is not None:
                poll_groups.pop(self.__poll_unique_id, None)

        letter = None

        if poll is not None:
            max_votes = 0
            leaders = []

            for option in poll.options:
                candidate = option.text.strip().upper()

                if (
                    len(candidate) == 1
                    and candidate in word.available_letters
                ):
                    if option.voter_count > max_votes:
                        max_votes = option.voter_count
                        leaders = [candidate]
                    elif option.voter_count == max_votes and max_votes > 0:
                        leaders.append(candidate)

            if leaders:
                letter = random.choice(leaders)

        if letter is None:
            if not word.available_letters:
                self.__clear_poll_state()
                return
            letter = random.choice(word.available_letters)

        safe_delete_message(self.__chat_id, self.__poll_message_id)
        self.__poll_message_id = None
        self.__poll_unique_id = None

        if word.open_letter(letter):
            self.__score += 5
            text = (
                f"{word.get_board()}\n\n"
                f"Буква {letter} есть в слове!\n"
                f"+5 очков"
            )
        else:
            text = (
                f"{word.get_board()}\n\n"
                f"Буквы {letter} нет в слове."
            )

        result = bot.send_message(self.__chat_id, text)
        self.__result_message_id = result.message_id

    def __clear_poll_state(self):
        if self.__poll_unique_id is not None:
            poll_groups.pop(self.__poll_unique_id, None)

        self.__poll_message_id = None
        self.__poll_unique_id = None


class Game:
    def __init__(self, word, clue):
        self.__word = Word(word, clue)
        self.__groups = []

    def append_group(self, group):
        if all(existing.chat_id != group.chat_id for existing in self.__groups):
            self.__groups.append(group)

    def remove_group(self, group):
        if group in self.__groups:
            self.__groups.remove(group)

    def __handle_group_error(self, group, error):
        print(f"[ERROR] Группа {group.chat_id}: {error}")

        if is_group_unavailable(error):
            print(f"[INFO] Группа {group.chat_id} исключена из игры")
            remove_group(group.chat_id)
            self.remove_group(group)

    def __send_results(self):
        sorted_groups = sorted(
            self.__groups,
            key=lambda group: group.score,
            reverse=True
        )

        lines = ["Игра окончена!", "", "Результаты:"]

        for index, group in enumerate(sorted_groups, start=1):
            lines.append(
                f"\n{index}. Группа {group.chat_id} — {group.score} очков"
            )
            lines.append("Участники:")

            if group.users:
                for user in group.users:
                    name = html.escape(user.first_name or "Пользователь")
                    link = f'<a href="tg://user?id={user.id}">{name}</a>'
                    lines.append(f"• {link}")
            else:
                lines.append("• Пока никто не голосовал")

        results = "\n".join(lines)

        # Telegram ограничивает длину одного сообщения 4096 символами.
        # Делим длинный рейтинг на части, не разрезая HTML-ссылки.
        chunks = []
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > 3500 and current:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line

        if current:
            chunks.append(current)

        for group in self.__groups[:]:
            try:
                for chunk in chunks:
                    bot.send_message(
                        group.chat_id,
                        chunk,
                        parse_mode="HTML"
                    )
            except Exception as error:
                self.__handle_group_error(group, error)

    def start_game(self):
        if game_state["started"]:
            raise RuntimeError("Другая игра уже запущена")

        if not self.__groups:
            print("[WARNING] Нет групп для игры")
            return

        game_state["started"] = True

        try:
            # Приветствуем каждую группу отдельно.
            for group in self.__groups[:]:
                try:
                    group.start_game()
                except Exception as error:
                    self.__handle_group_error(group, error)

            while not self.__word.is_guessed():
                if not self.__groups:
                    print("[INFO] Не осталось доступных групп. Игра остановлена.")
                    break

                active_groups = []

                # Создаём опросы. Ошибка одной группы не мешает остальным.
                for group in self.__groups[:]:
                    try:
                        group.start_poll(self.__word)
                        active_groups.append(group)
                    except Exception as error:
                        self.__handle_group_error(group, error)

                if not active_groups:
                    if self.__groups:
                        print("[WARNING] Ни в одной группе не удалось создать опрос.")
                        time.sleep(MSG_TIMEOUT)
                        continue
                    break

                time.sleep(POLLS_TIMEOUT + 1)

                # Закрываем только те опросы, которые удалось создать.
                for group in active_groups:
                    if group not in self.__groups:
                        continue

                    try:
                        group.end_poll(self.__word)
                    except Exception as error:
                        self.__handle_group_error(group, error)

                time.sleep(MSG_TIMEOUT)

            if self.__groups:
                self.__send_results()

        finally:
            # Удаляем оставшиеся соответствия опросов и сбрасываем состояние.
            for poll_id, group in list(poll_groups.items()):
                if group in self.__groups:
                    poll_groups.pop(poll_id, None)

            game_state["started"] = False


@bot.message_handler(commands=["start"])
def send_welcome(message):
    chat_id = message.chat.id

    if message.chat.type == "private":
        bot.send_message(
            chat_id,
            "Создайте группу, добавьте туда друзей и пригласите "
            "бота, чтобы сыграть в командное «Поле чудес»."
        )
        return

    if message.chat.type in ("group", "supergroup"):
        add_group(chat_id)

        if game_state["started"]:
        # остальной код
            bot.send_message(
                chat_id,
                "Игра уже началась. Дождитесь следующей."
            )
            return

        bot.send_message(chat_id, "Ожидайте начала игры!")
        send_rules(message)


@bot.message_handler(commands=["rules"])
def send_rules(message):
    bot.send_message(
        message.chat.id,
        "Правила:\n"
        "• Нужно отгадать слово по подсказке.\n"
        f"• На голосование за букву даётся {POLLS_TIMEOUT} секунд.\n"
        "• За угаданную букву команда получает 5 очков."
    )


@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    group = poll_groups.get(poll_answer.poll_id)

    if group is not None:
        group.add_user(poll_answer.user)
