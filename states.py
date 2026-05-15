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
    phone = State()


class AdminBroadcastTemplateState(StatesGroup):
    new_title = State()   # название нового шаблона
    new_text = State()    # текст нового шаблона
    edit_text = State()   # редактирование текста шаблона


class AdminPhotoAlbumState(StatesGroup):
    date_text = State()   # «29 марта»
    game_type = State()   # Razumboy / Razumbooo
    url = State()         # ссылка на фото


class AdminGiveawayState(StatesGroup):
    announce_text = State()   # текст объявления
    congrats_text = State()   # текст поздравления
    announce_time = State()   # время рассылки HH:MM
    draw_time = State()       # время жеребьёвки HH:MM
    image = State()           # картинка


class WinnerConfirmState(StatesGroup):
    team_name = State()       # ожидаем название команды от победителя


class AdminWinnersBroadcastState(StatesGroup):
    message_text = State()    # текст рассылки победителям Рандомбой


class AdminReferralCheckState(StatesGroup):
    waiting_code = State()    # ввод кода скидки для верификации
