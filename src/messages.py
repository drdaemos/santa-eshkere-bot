"""Russian message templates for Santa Eshkere bot"""


class Messages:
    """All user-facing messages in Russian"""

    # Group messages
    WELCOME = """🎅 Сани заправлены, олени готовы! (готовы же?)
Чтобы участвовать в раздаче подарков, напишите /join
Бот отправит вам личное сообщение для регистрации."""

    ASSIGNMENTS_SENT = "🎅 Сани поехали! Проверьте личку"

    JOIN_CHECK_DM = "Загляните в личку - вам написал бот! 👆"

    # User registration flow
    ASK_NAME = """🎅 Давно тебя не было в уличных гонках! (то есть в нашем секретном обмене подарками)

Давай напишем имя, которое увидит твой Санта из группы **{group_name}**."""

    ASK_WISHLIST = """Отлично! Теперь самое важное — вишлист (ответы "я не знаю" не принимаются).

Не стесняйся, говори прямо:
• Идеи подарков (мечтать не вредно)
• Интересы/хобби
• Размеры одежды (ну а вдруг?)
• Что ты НЕ хочешь

Можно будет потом поменять через команду /wishlist"""

    REGISTRATION_COMPLETE = """✓ Огонь, ты в деле!

**Имя:** {name}
**Вишлист:** {wishlist}

Ожидаем команды на старт от админа группы. Жди сообщений в личке! 🎁🎅

**Команды:**
/wishlist - Изменить вишлист
/status - Посмотреть статус регистрации"""

    # Wishlist management
    SHOW_CURRENT_WISHLIST = "Твой вишлист:\n\n>{wishlist}\n\nЧто-то поменять?"

    WISHLIST_UPDATED = "✓ Вишлист обновлён!"

    # Status messages
    STATUS_BEFORE_ASSIGNMENT = """✓ Ты в группе **{group_name}**!

**Имя:** {name}
**Вишлист:** 
>{wishlist}

Ожидаем распределения от администратора."""

    STATUS_AFTER_ASSIGNMENT = """🎁 Готовь подарки для группы **{group_name}**!

**Кому дарить:** {receiver_name}
**Вишлист:**
>{receiver_wishlist}

Удачи! 🎅"""

    STATUS_MULTIPLE_GROUPS = """Ты в нескольких группах (реально, столько друзей?)!:

{groups_status}"""

    STATUS_GROUP_ENTRY = """{index}. **{group_name}**
   Статус: {status}"""

    # Assignment notification
    ASSIGNMENT_NOTIFICATION = """🎁 Час Ч, день Д - пора за подарками!

Дарим подарок в группе **{group_name}**!
Получает: **{receiver_name}**
**Вишлист:**
>{receiver_wishlist}

Счастливого дарения! 🎅"""

    # Admin commands
    LIST_GROUPS = """Активные группы:

{groups_list}

Нажми на кнопку ниже для выбора группы:"""

    GROUP_LIST_ENTRY = """{index}. **{group_name}** (ID: {chat_id})
   • Активирована: {activated_at}
   • Участников: {participants}
   • Распределение: {assignment_status}"""

    GROUP_SELECTED = "✓ Выбрана группа: **{group_name}**"

    DISBAND_CONFIRM = "Это отметит группу **{group_name}** как расформированную. Пользователи не смогут присоединиться. Продолжить? (да/нет)"

    GROUP_DISBANDED = "✓ Группа расформирована. Используйте /start в той группе для повторной активации."

    ADDRULE_SELECT_FIRST = "Выберите первого человека"

    ADDRULE_SELECT_SECOND = "Выбран **{first_name}**. Выберите второго человека"

    ADDRULE_COMPLETE = "✓ Правило исключения добавлено для **{group_name}**: {name1} ↔ {name2}"

    LIST_RULES = """Правила исключения для **{group_name}**:

{rules_list}

Всего: {count} правила"""

    RULE_ENTRY = "• {name1} ↔ {name2}"

    RULE_REMOVED = "✓ Правило удалено"

    REMOVE_RULE_SELECT = "Выберите правило для удаления:"

    LIST_JOINED = """Зарегистрированные участники в **{group_name}** ({count}):

{users_list}"""

    USER_ENTRY = "• {name} (@{username})"
    USER_ENTRY_NO_USERNAME = "• {name}"

    ADMIN_HELP = """**Команды администратора:**

**Управление группами:**
/listgroups - Список всех активных групп
/selectgroup <номер> - Выбрать группу для работы
/disband - Расформировать выбранную группу

**Правила исключения:**
/addrule - Добавить правило исключения
/listrules - Показать все правила
/removerule - Удалить правило

**Участники и распределение:**
/listjoined - Список участников
/dryrunassignments - Симуляция распределения (без сохранения)
/reset - Сбросить распределения (⚠️ осторожно)

**В группе:**
/start - Активировать бота (только в группе)
/kickitoff - Отправить распределение (только в группе)"""

    RESET_CONFIRM = "⚠️ Это удалит все распределения для этой группы. Продолжить? (да/нет)"

    RESET_COMPLETE = "✓ Распределения сброшены"

    # Error messages
    ERROR_ALREADY_REGISTERED = "❌ Вы уже зарегистрированы в этой группе! Используйте /wishlist для изменения."

    ERROR_GROUP_INACTIVE = "❌ Эта группа неактивна. Попросите администратора активировать её командой /start."

    ERROR_NOT_REGISTERED = "❌ Сначала нужно зарегистрироваться. Напишите /join в группе."

    ERROR_DM_ONLY = "❌ Эта команда доступна только в личных сообщениях."

    ERROR_GROUP_ONLY = "❌ Эта команда доступна только в группе."

    ERROR_ADMIN_ONLY = "❌ Только администратор может использовать эту команду."

    ERROR_NO_GROUP_SELECTED = "❌ Пожалуйста, сначала выберите группу командой /selectgroup."

    ERROR_NOT_ENOUGH_PARTICIPANTS = "❌ Недостаточно участников в этой группе (минимум 3)."

    ERROR_ASSIGNMENT_IMPOSSIBLE = "❌ Невозможно создать корректное распределение с текущими правилами исключения."

    ERROR_GROUP_NOT_FOUND = "❌ Группа не найдена или уже расформирована."

    ERROR_SYSTEM = "⚠️ Что-то пошло не так. Попробуйте ещё раз или обратитесь к администратору."

    ERROR_INVALID_INPUT = "❌ Неправильный формат. Пожалуйста, попробуйте ещё раз."

    ERROR_DUPLICATE_RULE = "❌ Это правило уже существует."

    ERROR_SAME_USER = "❌ Нельзя создать правило для одного и того же пользователя."

    # Confirmation prompts
    CONFIRM_YES = "да"
    CONFIRM_NO = "нет"

    # Status texts
    STATUS_ASSIGNED = "Распределено — {receiver_name} получит подарок"
    STATUS_PENDING = "Ожидание распределения"
    ASSIGNMENT_STATUS_SENT = "Отправлено"
    ASSIGNMENT_STATUS_NOT_SENT = "Не отправлено"

    # No rules/users
    NO_RULES = "Нет правил исключения."
    NO_PARTICIPANTS = "Нет зарегистрированных участников."
    NO_GROUPS = "Нет активных групп."
