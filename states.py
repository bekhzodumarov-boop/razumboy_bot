from aiogram.fsm.state import State, StatesGroup


class RegistrationState(StatesGroup):
    team_name = State()
    team_size = State()
    captain_name = State()
    phone = State()
    comment = State()
    choose_event = State()
    confirm = State()


class AdminCreateEventState(StatesGroup):
    title = State()
    description = State()
    event_date = State()
    event_time = State()
    location = State()
    location_url = State()
    price_text = State()
    photo = State()
    confirm = State()


class AdminEditEventState(StatesGroup):
    choose_field = State()
    enter_value = State()


class AdminBroadcastState(StatesGroup):
    choose_type = State()
    choose_event = State()
    custom_text = State()
    custom_photo = State()


class ConfirmPlayersState(StatesGroup):
    waiting_reply = State()


class AskQuestionState(StatesGroup):
    waiting_question = State()


class BlitzQuizState(StatesGroup):
    question = State()
    photo = State()
    answer = State()
    duration = State()
    mode = State()  # 'first' или 'all'


class SubscribeState(StatesGroup):
    first_name = State()
    last_name = State()
    gender = State()
    age = State()
    phone = State()
