"""Russian message templates (Telegram HTML).

Fill placeholders only via formatting.render(), which escapes values.
Static text must be valid HTML: write < > & as &lt; &gt; &amp;.
"""


class Messages:
    # --- group ------------------------------------------------------------------
    WELCOME = """🎅 Сани заправлены, олени готовы! (готовы же?)
Чтобы участвовать в раздаче подарков, напишите /join
Бот отправит вам личное сообщение для регистрации."""

    ASSIGNMENTS_SENT = "🎅 Сани поехали! Проверьте личку"

    DELIVERY_FAILED = """⚠️ Не смог написать: {names}.
Откройте личку с ботом и наберите /status — задание уже ждёт вас там."""

    JOIN_DM_FAILED = """Не могу написать тебе в личку :(
Нажми кнопку ниже и затем «Start» — регистрация продолжится там."""
    JOIN_DM_BUTTON = "Открыть личку с ботом"

    DRAW_ALREADY_DONE = """❌ Распределение в этом сезоне уже сделано — повторно перемешивать не буду.
Если правда нужно заново: /reset в личке с ботом, потом /kickitoff."""

    JOIN_AFTER_DRAW = "❌ Распределение в этом сезоне уже прошло, присоединиться нельзя. Напишите админу группы."

    NO_SEASON = "❌ Сейчас нет активного сезона. Админ может открыть его командой /start."

    NEW_SEASON_CONFIRM = """Закрыть текущий сезон и открыть новый?
Участникам нужно будет снова написать /join (прошлые имя и вишлист можно оставить в один клик). Правила исключения сохранятся."""

    NEW_SEASON_OPENED = """🎄 Новый сезон открыт!
Чтобы участвовать, напишите /join"""

    # --- registration -----------------------------------------------------------
    ASK_NAME = """🎅 Давно тебя не было в уличных гонках! (то есть в нашем секретном обмене подарками)

Давай напишем имя, которое увидит твой Санта из группы <b>{group_name}</b>."""

    ASK_NAME_REUSE_HINT = "\n\nИли нажми кнопку, чтобы оставить как в прошлый раз."
    REUSE_NAME_BUTTON = "Как в прошлый раз: {name}"

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
    REUSE_WISHLIST_BUTTON = "Оставить прошлый вишлист"

    REGISTRATION_COMPLETE = """✓ Огонь, ты в деле!

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>

Ожидаем команды на старт от админа группы. Жди сообщений в личке! 🎁🎅

<b>Команды:</b>
/wishlist - Изменить вишлист
/status - Посмотреть статус регистрации"""

    RESUME_FLOW = "Продолжим регистрацию 👇"

    NEED_TEXT = "Я понимаю только текст 🙈 Напиши, пожалуйста, словами."

    INVALID_INPUT = "❌ {reason}"

    # --- user commands ----------------------------------------------------------
    DM_GREETING = "Супер, бот на связи. Напиши теперь сообщение /join в группе"

    USER_HELP = """Я бот Санта Эщкере 🎅

/status — статус и твоё задание
/wishlist — изменить вишлист
/cancel — отменить текущее действие

Чтобы участвовать, напиши /join в групповом чате."""

    SHOW_CURRENT_WISHLIST = """Твой вишлист:
<blockquote>{wishlist}</blockquote>
Напиши новый одним сообщением (или /cancel)."""

    WISHLIST_UPDATED = "✓ Вишлист обновлён!"

    RECEIVER_WISHLIST_CHANGED = """✏️ {receiver_name} обновил(а) вишлист (группа <b>{group_name}</b>):
<blockquote>{receiver_wishlist}</blockquote>"""

    CANCELLED = "Отменено."
    NOTHING_TO_CANCEL = "Нечего отменять 🙂"

    STATUS_BEFORE_ASSIGNMENT = """✓ Ты в группе <b>{group_name}</b>!

<b>Имя:</b> {name}
<b>Вишлист:</b>
<blockquote>{wishlist}</blockquote>

Ожидаем распределения от администратора."""

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

Счастливого дарения! 🎅"""

    EMPTY_WISHLIST = "Не указан"

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
/addrule - Добавить правило исключения
/listrules - Показать правила
/dryrunassignments - Симуляция распределения
/reset - Сбросить распределение
/disband - Расформировать группу"""

    CONFIRM_YES_BUTTON = "Да"
    CONFIRM_NO_BUTTON = "Нет"

    DISBAND_CONFIRM = "Это отметит группу <b>{group_name}</b> как расформированную. Пользователи не смогут присоединиться. Продолжить?"
    GROUP_DISBANDED = "✓ Группа расформирована. Используйте /start в той группе для повторной активации."

    RESET_CONFIRM = "⚠️ Это удалит распределение текущего сезона в группе <b>{group_name}</b>; участники и правила останутся. Продолжить?"
    RESET_COMPLETE = "✓ Распределения сброшены"
    RESET_NOTHING = "Распределения ещё не было — сбрасывать нечего."

    ADDRULE_SELECT_FIRST = "Выберите первого человека:"
    ADDRULE_SELECT_SECOND = "Выбран: <b>{first_name}</b>\n\nТеперь выберите второго человека:"
    ADDRULE_COMPLETE = "✓ Правило исключения добавлено для <b>{group_name}</b>: {name1} ↔ {name2}"
    ADDRULE_NOT_ENOUGH = "❌ В группе недостаточно участников для создания правил исключения (минимум 2)."

    LIST_RULES = """Правила исключения для <b>{group_name}</b>:

{rules_list}

Всего: {count}"""
    RULE_ENTRY = "• {name1} ↔ {name2}"
    RULE_NOT_IN_SEASON = " (не участвует в этом сезоне)"
    RULE_REMOVED = "✓ Правило удалено"
    REMOVE_RULE_SELECT = "Выберите правило для удаления:"

    LIST_JOINED = """Зарегистрированные участники в <b>{group_name}</b> ({count}):

{users_list}"""
    USER_ENTRY = "• {name} (@{username})"
    USER_ENTRY_NO_USERNAME = "• {name}"

    DRY_RUN = """<b>Симуляция распределения для группы: {group_name}</b>

Участников: {participants}
Правил исключения: {rules}

<b>Пары (даритель → получатель):</b>
{pairs}

<i>Это только симуляция. Данные не сохранены в базу.</i>"""
    DRY_RUN_PAIR = "• {giver} → {receiver}"

    ADMIN_HELP = """<b>Команды администратора:</b>

<b>Управление группами:</b>
/listgroups - Список всех активных групп
/selectgroup &lt;номер&gt; - Выбрать группу для работы
/disband - Расформировать выбранную группу

<b>Правила исключения:</b>
/addrule - Добавить правило исключения
/listrules - Показать все правила
/removerule - Удалить правило

<b>Участники и распределение:</b>
/listjoined - Список участников
/dryrunassignments - Симуляция распределения (без сохранения)
/reset - Сбросить распределение (⚠️ осторожно)

<b>В группе:</b>
/start - Активировать бота
/kickitoff - Отправить распределение
/newseason - Закрыть сезон и открыть новый"""

    STALE_BUTTON = "Эта кнопка устарела."

    # --- errors -----------------------------------------------------------------
    ERROR_ALREADY_REGISTERED = "❌ Вы уже зарегистрированы в этой группе! Используйте /wishlist для изменения."
    ERROR_GROUP_INACTIVE = "❌ Эта группа неактивна. Попросите администратора активировать её командой /start."
    ERROR_NOT_REGISTERED = "❌ Сначала нужно зарегистрироваться. Напишите /join в группе."
    ERROR_DM_ONLY = "❌ Эта команда доступна только в личных сообщениях."
    ERROR_GROUP_ONLY = "❌ Эта команда доступна только в группе."
    ERROR_ADMIN_ONLY = "❌ Только администратор может использовать эту команду."
    ERROR_NO_GROUP_SELECTED = "❌ Пожалуйста, сначала выберите группу командой /listgroups."
    ERROR_NOT_ENOUGH_PARTICIPANTS = "❌ Недостаточно участников в этой группе (минимум 3)."
    ERROR_ASSIGNMENT_IMPOSSIBLE = "❌ Невозможно создать корректное распределение с текущими правилами исключения."
    ERROR_GROUP_NOT_FOUND = "❌ Группа не найдена или уже расформирована."
    ERROR_SYSTEM = "⚠️ Что-то пошло не так. Попробуйте ещё раз или обратитесь к администратору."
    ERROR_DUPLICATE_RULE = "❌ Это правило уже существует."
    NO_RULES = "Нет правил исключения."
    NO_PARTICIPANTS = "Нет зарегистрированных участников."
    NO_GROUPS = "Нет активных групп."
