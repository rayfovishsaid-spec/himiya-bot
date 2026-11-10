"""FSM-состояния."""
from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    name = State()
    age = State()
    city = State()
    gender = State()
    seek = State()
    photo = State()
    voice = State()
    interests = State()


class QuestionFlow(StatesGroup):
    answering = State()   # отвечает на 5 вопросов анкеты (индекс в data["q_index"])


class Chat(StatesGroup):
    talking = State()     # активный чат, data["match_id"]


class Report(StatesGroup):
    reason = State()
