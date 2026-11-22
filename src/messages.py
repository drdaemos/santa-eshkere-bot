"""Russian message templates (Telegram HTML).

Fill placeholders only via formatting.render(), which escapes values.
Static text must be valid HTML: write < > & as &lt; &gt; &amp;.
"""


class Messages:
    # --- group ------------------------------------------------------------------
    # The join post: one group message, edited as people join and leave
    JOIN_POST = """🎅 Сани заправлены, олени готовы! (готовы же?)

Тайный Санта в группе <b>{group_name}</b>. Жми кнопку — регистрация в личке с ботом, займёт минуту.{deadline}

<b>Участвуют ({count}):</b> {names}"""
    JOIN_POST_DRAWN = """🎅 Тайный Санта в группе <b>{group_name}</b> — распределение уже прошло, задания у всех в личке.

Ещё не с нами? Жми кнопку — впишу тебя в цепочку.{deadline}

<b>Участвуют ({count}):</b> {names}"""
    JOIN_POST_CLOSED = """🎅 Этот сезон Тайного Санты в группе <b>{group_name}</b> закрыт.

<b>Участвовали ({count}):</b> {names}"""
    JOIN_POST_DEADLINE = "\n⏰ Регистрация открыта до <b>{deadline}</b>."
    JOIN_POST_REGISTRATION_OVER = """🎅 Тайный Санта в группе <b>{group_name}</b> — регистрация закрыта.

<b>Участвуют ({count}):</b> {names}"""
    JOIN_POST_MOVED = "🎅 Актуальная кнопка для участия — в сообщении ниже 👇"
    JOIN_POST_NOBODY = "пока никого — будь первым!"
    JOIN_POST_MORE = " и ещё {count}"
    JOIN_BUTTON = "🎁 Участвовать"

    ASSIGNMENTS_SENT = "🎅 Сани поехали! Проверьте личку"

    # /kickitoff asks first: the draw can't be taken back once people read it
    DRAW_CONFIRM = """Запустить распределение для <b>{count}</b> участников? Все сразу получат задания в личку.{unfinished}"""
    DRAW_UNFINISHED = """

⏳ Начали регистрацию, но не закончили: {names}. Можно подождать их — или запустить сейчас: они смогут присоединиться и после распределения."""
    DRAW_START_BUTTON = "🎅 Запустить"
    DRAW_STALE = "Распределение уже прошло."

    # Joining deadline (/deadline in the group)
    DEADLINE_SET = "⏰ Регистрация открыта до <b>{deadline}</b>. После этого новые участники не смогут присоединиться."
    DEADLINE_REMOVED = "✓ Дедлайн убран: регистрация открыта до конца сезона."
    DEADLINE_CURRENT = "⏰ Регистрация открыта до <b>{deadline}</b>.\n\n{usage}"
    DEADLINE_NONE = "Дедлайна нет: регистрация открыта до конца сезона.\n\n{usage}"
    DEADLINE_PASSED_ADMIN = """⏰ Регистрация в <b>{group_name}</b> закрыта. Участников: {count}.{unfinished}

Запускай распределение: /kickitoff в группе."""
    DEADLINE_PASSED_GROUP = "⏰ Регистрация закрыта, участников: {count}. Админ, запускай распределение: /kickitoff"
    DEADLINE_PASSED_UNFINISHED = "\nНе закончили регистрацию (ещё могут успеть): {names}."
    DRAW_DEADLINE_NOTE = "\n\n⏰ Регистрация открыта до {deadline}: кто присоединится позже, получит задание сразу."
    JOIN_CLOSED_DEADLINE = "⏰ Регистрация в группе <b>{group_name}</b> закрыта ({deadline}). Если очень хочется — попроси админа продлить её."

    # The bot was added to a group
    BOT_ADDED = """Привет! Я помогу провести Тайного Санту 🎅
Админ группы, отправь /start — появится пост с кнопкой «Участвовать». Дальше всё в личке, группу спамить не буду."""
    BOT_ADDED_BY_ADMIN = """Привет! Я помогу провести Тайного Санту 🎅
Жмите кнопку в посте ниже — регистрация в личке, займёт минуту. Группу спамить не буду."""

    DELIVERY_FAILED = """⚠️ Не смог написать: {names}.
Откройте личку с ботом и наберите /status — задание уже ждёт вас там."""

    JOIN_DM_FAILED = """{name}, не могу написать тебе в личку :(
Нажми кнопку ниже и затем «Start» — регистрация продолжится там."""
    JOIN_DM_BUTTON = "💬 Открыть бота"

    DRAW_ALREADY_DONE = """❌ Распределение в этом сезоне уже сделано — повторно перемешивать не буду.
Если правда нужно заново: /reset в личке с ботом, потом /kickitoff."""


    NO_SEASON = "❌ Сейчас нет активного сезона. Админ может открыть его командой /start."

    NEW_SEASON_CONFIRM = """Закрыть текущий сезон и открыть новый?
Участникам нужно будет снова нажать «Участвовать» (прошлые имя и вишлист можно оставить в один клик). Правила исключения сохранятся."""

    NEW_SEASON_OPENED = "🎄 Новый сезон открыт — кнопка для участия в группе."

    # --- registration -----------------------------------------------------------
    ASK_NAME = """🎅 Давно тебя не было в уличных гонках! (то есть в нашем секретном обмене подарками)

Давай напишем имя, которое увидит твой Санта из группы <b>{group_name}</b>."""

    LATE_JOIN_NOTE = """

<i>Распределение уже прошло — после регистрации я впишу тебя в цепочку, и задание придёт сразу.</i>"""

    ASK_NAME_BUTTONS_HINT = "\n\nНапиши имя или выбери кнопкой 👇"
    REUSE_NAME_BUTTON = "🔁 {name}"
    TELEGRAM_NAME_BUTTON = "👤 {name}"

    ASK_WISHLIST = """Отлично! Теперь самое важное — вишлист (ответы "я не знаю" не принимаются).

Не стесняйся, говори прямо:
• Идеи подарков (мечтать не вредно)
• Интересы/хобби
• Размеры одежды (ну а вдруг?)
• Что ты НЕ хочешь

Можно будет потом поменять через команду /wishlist"""

    ASK_WISHLIST_REUSE_HINT = """

В прошлый раз ты писал(а):
<blockquote>{wishlist}</blockquote>
Можно оставить его кнопкой ниже."""
    REUSE_WISHLIST_BUTTON = "🔁 Как в прошлый раз"

    REGISTRATION_COMPLETE = """✓ Огонь, ты в деле!

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>

Когда админ запустит распределение, задание придёт сюда 🎁🎅
Вишлист можно поменять в любой момент — просто пришли новый текст."""

    REGISTRATION_COMPLETE_LATE = """✓ Огонь, ты в деле!

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>

Распределение уже прошло, так что задание — следующим сообщением 🎁"""

    ALREADY_IN = """✓ Ты уже участвуешь в группе <b>{group_name}</b>.

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>"""
    JOIN_NOT_A_MEMBER = """Эта кнопка — для участников группы <b>{group_name}</b>.
Попроси добавить тебя в группу и нажми её ещё раз."""

    EDIT_WISHLIST_BUTTON = "✏️ Вишлист"
    LEAVE_BUTTON = "🚪 Выйти"

    LATE_JOIN_IMPOSSIBLE = """❌ Распределение уже прошло, и из-за правил исключения не получается вписать тебя в цепочку.
Напиши админу группы: он может сбросить распределение (/reset) и запустить заново."""

    RESUME_FLOW = "Продолжим регистрацию 👇"

    NEED_TEXT = "Я понимаю только текст 🙈 Напиши, пожалуйста, словами."

    INVALID_INPUT = "❌ {reason}"

    # --- user commands ----------------------------------------------------------
    DM_GREETING = "Супер, бот на связи! Теперь нажми «Участвовать» в группе (или напиши там /join)."

    USER_HELP = """Я бот Санта Эщкере 🎅

/status — статус и твоё задание
/wishlist — изменить вишлист
/leave — выйти из игры
/cancel — отменить текущее действие

Чтобы участвовать, нажми «Участвовать» в группе (или напиши там /join)."""

    REGISTERED_HELP = """🎅 Я на связи! Посмотреть задание — /status (там же после распределения можно написать Санте или получателю).
Чтобы дополнить вишлист, просто пришли текст."""

    CONFIRM_FREE_WISHLIST = """Что сделать с этим текстом?
<blockquote>{wishlist}</blockquote>"""
    CONFIRM_FREE_WISHLIST_CHAT_HINT = "\n\nЭто сообщение Санте или получателю? Тогда «Отмена» и кнопка «✉️ Санте» или «✉️ Получателю» в /status."
    CONFIRM_FREE_WISHLIST_ADD = "➕ Добавить"
    CONFIRM_FREE_WISHLIST_REPLACE = "🔁 Заменить"

    SHOW_CURRENT_WISHLIST = """Твой вишлист:
<blockquote>{wishlist}</blockquote>
Пришли, что добавить, — допишу в конец. Переписать всё — кнопка ниже. (/cancel — отмена)"""
    REPLACE_WISHLIST_BUTTON = "🔁 Заменить всё"
    REPLACE_WISHLIST_PROMPT = "Пришли новый вишлист целиком — старый заменю. Передумал(а) — /cancel."

    WISHLIST_UPDATED = """✓ Вишлист обновлён:
<blockquote>{wishlist}</blockquote>"""
    WISHLIST_UNCHANGED = "Вишлист и так такой 🙂"
    UNDO_BUTTON = "↩️ Вернуть"
    WISHLIST_RESTORED = """↩️ Вернул как было:
<blockquote>{wishlist}</blockquote>"""
    UNDO_STALE = "Возвращать нечего: вишлист с тех пор уже менялся."

    RECEIVER_WISHLIST_CHANGED = """✏️ {receiver_name} обновил(а) вишлист (группа <b>{group_name}</b>):
<blockquote>{receiver_wishlist}</blockquote>"""
    RECEIVER_WISHLIST_ADDED = """✏️ {receiver_name} дополнил(а) вишлист (группа <b>{group_name}</b>):
➕ <blockquote>{added}</blockquote>
Весь вишлист:
<blockquote>{receiver_wishlist}</blockquote>"""

    CANCELLED = "Отменено."
    NOTHING_TO_CANCEL = "Нечего отменять 🙂"

    STATUS_BEFORE_ASSIGNMENT = """✓ Ты участвуешь в группе <b>{group_name}</b>!

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>

Ждём, когда админ запустит распределение."""

    STATUS_AFTER_ASSIGNMENT = """🎁 Готовь подарки для группы <b>{group_name}</b>!

<b>Кому дарить:</b> {receiver_name}
<b>Вишлист:</b>
<blockquote>{receiver_wishlist}</blockquote>

Удачи! 🎅"""

    STATUS_MULTIPLE_GROUPS = """Ты в нескольких группах (реально, столько друзей?)!

{groups_status}"""

    STATUS_GROUP_ENTRY = """{index}. <b>{group_name}</b>
   Статус: {status}"""

    STATUS_ASSIGNED = "Распределено — {receiver_name} получит подарок"
    STATUS_PENDING = "Ожидание распределения"

    ASSIGNMENT_NOTIFICATION = """🎁 Час Ч, день Д - пора за подарками!

Дарим подарок в группе <b>{group_name}</b>!
Получает: <b>{receiver_name}</b>
<b>Вишлист:</b>
<blockquote>{receiver_wishlist}</blockquote>

Счастливого дарения! 🎅{chat_hint}"""

    REASSIGNMENT_NOTIFICATION = """🔄 Небольшая перестановка в группе <b>{group_name}</b>: состав участников изменился, и у тебя новое задание.
Прошлое больше не действует.

Получает: <b>{receiver_name}</b>
<b>Вишлист:</b>
<blockquote>{receiver_wishlist}</blockquote>{chat_hint}"""

    EMPTY_WISHLIST = "Не указан"

    # Anonymous messages: Santa <-> receiver, one message per tap, text only
    CHAT_HINT = "\n\n✉️ Кнопками ниже можно анонимно написать получателю (спросить размер, цвет…) или своему Тайному Санте."
    CHAT_TO_RECEIVER_BUTTON = "✉️ Получателю"
    CHAT_TO_SANTA_BUTTON = "✉️ Санте"
    CHAT_TO_RECEIVER_IN_GROUP_BUTTON = "✉️ Получателю · {group_name}"
    CHAT_TO_SANTA_IN_GROUP_BUTTON = "✉️ Санте · {group_name}"
    CHAT_REPLY_BUTTON = "↩️ Ответить"
    CHAT_COMPOSE_TO_RECEIVER = """✉️ Напиши сообщение для <b>{name}</b> (группа <b>{group_name}</b>). Я передам его от Тайного Санты — кто ты, не узнают.

Одно сообщение, только текст."""
    CHAT_COMPOSE_TO_SANTA = """✉️ Напиши сообщение своему Тайному Санте (группа <b>{group_name}</b>). Санта знает, кому дарит, а ты его — нет 😉

Одно сообщение, только текст."""
    CHAT_FROM_SANTA = """🎅 <b>Тебе пишет твой Тайный Санта</b> (группа <b>{group_name}</b>):

<blockquote>{text}</blockquote>"""
    CHAT_FROM_RECEIVER = """💌 <b>Пишет {name}</b> — тот, кому ты даришь (группа <b>{group_name}</b>):

<blockquote>{text}</blockquote>"""
    CHAT_SENT = "✓ Отправлено. Ответ придёт сюда же."
    CHAT_NOT_DELIVERED = "Не получилось доставить: похоже, человек закрыл личку с ботом. Попробуй позже."
    CHAT_STALE = "Этот диалог больше не действует: распределение поменялось или сезон закончился."

    # --- leaving ----------------------------------------------------------------
    LEAVE_PICK_GROUP = "Из какой группы выйти?"
    LEAVE_CONFIRM = "Выйти из игры в группе <b>{group_name}</b>?{drawn_note}"
    DRAWN_REPAIR_NOTE = """

Распределение уже сделано: я перестрою цепочку так, что новое задание получат один-два участника, остальных это не коснётся."""
    LEFT_SEASON = "✓ Ты больше не участвуешь в группе <b>{group_name}</b>. Передумаешь — нажми «Участвовать» в группе."
    REPAIR_TOO_FEW = "❌ Останется меньше 3 участников — так распределение не работает. Админ может сбросить его (/reset) или открыть новый сезон (/newseason)."
    REPAIR_IMPOSSIBLE = "❌ Из-за правил исключения не получается перестроить распределение, затронув только пару человек. Админ может сбросить его (/reset) и запустить заново (/kickitoff)."

    # --- admin ------------------------------------------------------------------
    LIST_GROUPS = """Активные группы:

{groups_list}

Нажми на кнопку ниже для выбора группы:"""

    GROUP_LIST_ENTRY = """{index}. <b>{group_name}</b> (ID: {chat_id})
   • Активирована: {activated_at}
   • Участников: {participants}
   • Распределение: {assignment_status}"""

    ASSIGNMENT_STATUS_SENT = "Отправлено"
    ASSIGNMENT_STATUS_NOT_SENT = "Не отправлено"

    GROUP_SELECTED = """✓ Выбрана группа: <b>{group_name}</b>

Используйте команды для управления этой группой:
/listjoined - Список участников
/removeparticipant - Убрать участника
/addrule - Добавить правило исключения
/listrules - Показать правила
/dryrunassignments - Симуляция распределения
/reset - Сбросить распределение
/disband - Расформировать группу"""

    CONFIRM_YES_BUTTON = "Да"
    CONFIRM_NO_BUTTON = "Нет"
    CANCEL_BUTTON = "Отмена"
    PREV_PAGE_BUTTON = "←"
    NEXT_PAGE_BUTTON = "→"

    DISBAND_CONFIRM = "Это отметит группу <b>{group_name}</b> как расформированную. Пользователи не смогут присоединиться. Продолжить?"
    GROUP_DISBANDED = "✓ Группа расформирована. Используйте /start в той группе для повторной активации."

    RESET_CONFIRM = "⚠️ Это удалит распределение текущего сезона в группе <b>{group_name}</b>; участники и правила останутся. Продолжить?"
    RESET_COMPLETE = "✓ Распределения сброшены"
    RESET_NOTHING = "Распределения ещё не было — сбрасывать нечего."

    ADDRULE_SELECT_FIRST = "Выбери первого человека:"
    ADDRULE_SELECT_SECOND = "Выбран: <b>{first_name}</b>\n\nТеперь выбери второго человека:"
    ADDRULE_COMPLETE = "✓ Правило исключения добавлено для <b>{group_name}</b>: {name1} ↔ {name2}"
    ADDRULE_NOT_ENOUGH = "❌ В группе недостаточно участников для создания правил исключения (минимум 2)."

    LIST_RULES = """Правила исключения для <b>{group_name}</b>:

{rules_list}

Всего: {count}"""
    RULE_ENTRY = "• {name1} ↔ {name2}"
    RULE_NOT_IN_SEASON = " (не участвует в этом сезоне)"
    RULE_REMOVED = "✓ Правило удалено"
    REMOVE_RULE_SELECT = "Выбери правило для удаления:"

    LIST_JOINED = """Зарегистрированные участники в <b>{group_name}</b> ({count}):

{users_list}{unfinished}{undelivered}"""
    LIST_JOINED_UNFINISHED = """

⏳ Начали регистрацию, но не закончили: {names}"""
    LIST_JOINED_UNDELIVERED = """

⚠️ Не получили задание (бот не может им написать): {names}. Пусть откроют личку с ботом и наберут /status."""
    REMOVE_PARTICIPANT_SELECT = "Кого убрать из сезона?"
    REMOVE_PARTICIPANT_CONFIRM = "Убрать <b>{name}</b> из сезона в группе <b>{group_name}</b>?{drawn_note}"
    REMOVE_PARTICIPANT_DONE = "✓ {name} больше не участвует."
    REMOVE_PARTICIPANT_REASSIGNED = "\nНовое задание получили участников: {count}."
    REMOVED_BY_ADMIN = "Админ убрал тебя из участников в группе <b>{group_name}</b>. Если это ошибка — нажми «Участвовать» в группе ещё раз."

    USER_ENTRY = "• {name} (@{username})"
    USER_ENTRY_NO_USERNAME = "• {name}"

    DRY_RUN = """✅ Распределение в <b>{group_name}</b> возможно.

Участников: {participants}
Правил исключения: {rules}

<i>Пары не показываю, чтобы не портить сюрприз. Настоящее распределение — /kickitoff в группе.</i>"""

    ADMIN_HELP = """<b>Команды администратора:</b>

<b>Управление группами:</b>
/listgroups - Список всех активных групп
/selectgroup &lt;номер&gt; - Выбрать группу для работы (если группа одна, она выбрана сама)
/disband - Расформировать выбранную группу

<b>Правила исключения:</b>
/addrule - Добавить правило исключения
/listrules - Показать все правила
/removerule - Удалить правило

<b>Участники и распределение:</b>
/listjoined - Список участников
/removeparticipant - Убрать участника (распределение поправится само)
/dryrunassignments - Проверить, что распределение возможно
/reset - Сбросить распределение (⚠️ осторожно)

<b>В группе:</b>
/start - Активировать бота
/kickitoff - Запустить распределение (с подтверждением)
/deadline 30.11 18:00 - Дедлайн регистрации (/deadline off — убрать)
/newseason - Закрыть сезон и открыть новый"""

    STALE_BUTTON = "Эта кнопка устарела."

    # --- errors -----------------------------------------------------------------
    ERROR_GROUP_INACTIVE = "❌ Бот в этой группе выключен. Попроси админа включить его командой /start."
    ERROR_NOT_REGISTERED = "❌ Сначала нужно зарегистрироваться: нажми «Участвовать» в группе (или напиши там /join)."
    ERROR_DM_ONLY = "❌ Эта команда доступна только в личных сообщениях."
    ERROR_GROUP_ONLY = "❌ Эта команда доступна только в группе."
    ERROR_ADMIN_ONLY = "❌ Только администратор может использовать эту команду."
    ERROR_NO_GROUP_SELECTED = "❌ Сначала выбери группу: /listgroups."
    ERROR_NOT_ENOUGH_PARTICIPANTS = "❌ Недостаточно участников в этой группе (минимум 3)."
    ERROR_ASSIGNMENT_IMPOSSIBLE = "❌ Невозможно создать корректное распределение с текущими правилами исключения."
    ERROR_GROUP_NOT_FOUND = "❌ Группа не найдена или уже расформирована."
    ERROR_SYSTEM = "⚠️ Что-то пошло не так. Попробуй ещё раз чуть позже или напиши админу группы."
    ERROR_DUPLICATE_RULE = "❌ Это правило уже существует."
    NO_RULES = "Нет правил исключения."
    NO_PARTICIPANTS = "Нет зарегистрированных участников."
    NO_GROUPS = "Нет активных групп."
