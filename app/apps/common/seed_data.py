"""
Сид из текущих хардкод-данных мобилки (ТЗ §3, §6).

Точно по ТЗ: правила кешбека 5 разделов, 5 уровней с порогами, id 15 привилегий, их уровни и иконки,
цифры демо-профиля (BT-048219, 845 000, три операции) и пример «кедровая бочка × 2, promoRate 0.14».
Остальное (названия и цены 15 услуг, тексты статей/акций/сторис, переводы ky/en) — заготовка:
файлы LocalCatalogRepository / LocalContentRepository / LocalLoyaltyRepository в бек не переданы,
их нужно перенести из мобилки (админка или правка этого файла).
Фото — пути в хранилище seed/…; файлы нужно загрузить из assets/images/ мобилки.
"""
from apps.common.i18n import l10n as L

OUTLETS = [
    ('reception', L('Ресепшен', 'Ресепшн', 'Reception'), 1),
    ('davinci', L('Da Vinci', 'Da Vinci', 'Da Vinci'), 2),
    ('coco-loco', L('Coco Loco', 'Coco Loco', 'Coco Loco'), 3),
    ('pier-bar', L('Бар на пирсе', 'Пирстеги бар', 'Pier bar'), 4),
    ('spa', L('SPA', 'SPA', 'SPA'), 5),
    ('sport', L('Спорт', 'Спорт', 'Sport'), 6),
]

ALL_METHODS = ['cash', 'finik', 'freedomPay', 'elqr']
LIMITED_METHODS = ['cash', 'finik', 'elqr']

# id, title, sort, rate, maxPointsShare, methods — значения из ТЗ §3.1
CATEGORIES = [
    ('rooms', L('Номера', 'Бөлмөлөр', 'Rooms'), 1, '0.07', '0.30', ALL_METHODS),
    ('spa', L('SPA', 'SPA', 'SPA'), 2, '0.07', '1.00', ALL_METHODS),
    ('food', L('Рестораны', 'Ресторандар', 'Restaurants'), 3, '0.05', '0.50', ALL_METHODS),
    ('pools', L('Бассейны', 'Бассейндер', 'Pools'), 4, '0.10', '1.00', LIMITED_METHODS),
    ('sport', L('Спорт', 'Спорт', 'Sport'), 5, '0.10', '1.00', LIMITED_METHODS),
]


def feat(icon, ru, ky='', en=''):
    return {'icon': icon, 'text': L(ru, ky, en)}


# id, category, outlet, title, meta, price, pricing, promo(rate, tag) | None, tag, description, features
ITEMS = [
    ('room-standard', 'rooms', 'reception', L('Стандарт, вид на горы', 'Стандарт, тоого көрүнүш', 'Standard, mountain view'),
     L('2 гостя · queen-size · 28 м²', '2 конок · queen-size · 28 м²', '2 guests · queen-size · 28 m²'), 14000,
     {'type': 'unit', 'unit': 'night', 'min': 1, 'max': 14}, None, None,
     L('Уютный номер с видом на горы.', '', 'Cozy room with a mountain view.'),
     [feat('view', 'Вид на горы', '', 'Mountain view'), feat('bed', 'Queen-size', '', 'Queen-size'),
      feat('wifi', 'Wi-Fi', '', 'Wi-Fi'), feat('breakfast', 'Завтрак включён', '', 'Breakfast included')]),
    ('room-deluxe', 'rooms', 'reception', L('Делюкс, вид на озеро', 'Делюкс, көлгө көрүнүш', 'Deluxe, lake view'),
     L('2 гостя · king-size · 38 м²', '2 конок · king-size · 38 м²', '2 guests · king-size · 38 m²'), 23000,
     {'type': 'unit', 'unit': 'night', 'min': 1, 'max': 14}, None, None,
     L('Просторный номер с террасой и видом на Иссык-Куль.', '', 'Spacious room with a terrace and a view of Issyk-Kul.'),
     [feat('view', 'Вид на озеро', '', 'Lake view'), feat('bed', 'King-size', '', 'King-size'),
      feat('people', '2 гостя', '', '2 guests'), feat('area', '38 м²', '', '38 m²'),
      feat('terrace', 'Терраса', '', 'Terrace'), feat('breakfast', 'Завтрак включён', '', 'Breakfast included')]),
    ('room-villa', 'rooms', 'reception', L('Вилла у воды', 'Суу жээгиндеги вилла', 'Waterfront villa'),
     L('4 гостя · 2 спальни · 90 м²', '4 конок · 2 уктоочу бөлмө · 90 м²', '4 guests · 2 bedrooms · 90 m²'), 52000,
     {'type': 'unit', 'unit': 'night', 'min': 1, 'max': 14}, None, None,
     L('Отдельная вилла с бассейном у самой воды.', '', 'Private villa with a pool by the water.'),
     [feat('pool', 'Свой бассейн', '', 'Private pool'), feat('people', '4 гостя', '', '4 guests'),
      feat('area', '90 м²', '', '90 m²'), feat('terrace', 'Терраса', '', 'Terrace')]),
    ('spa-bochka', 'spa', 'spa', L('Кедровая бочка', 'Кедр челеги', 'Cedar barrel'),
     L('40 минут · 1 гость', '40 мүнөт · 1 конок', '40 minutes · 1 guest'), 2500,
     {'type': 'unit', 'unit': 'session', 'min': 1, 'max': 10}, ('0.14', L('×2 баллы', '×2 упай', '×2 points')), None,
     L('Фитобочка из кедра: прогрев и травяной пар.', '', 'Cedar phyto-barrel with herbal steam.'),
     [feat('time', '40 минут', '', '40 minutes'), feat('tea', 'Травяной чай', '', 'Herbal tea'),
      feat('towel', 'Полотенца', '', 'Towels')]),
    ('spa-stone', 'spa', 'spa', L('Стоун-массаж', 'Таш массаж', 'Stone massage'),
     L('60 минут · горячие камни', '60 мүнөт · ысык таштар', '60 minutes · hot stones'), 3500,
     {'type': 'unit', 'unit': 'session', 'min': 1, 'max': 10}, None, None,
     L('Массаж горячими базальтовыми камнями.', '', 'Massage with hot basalt stones.'),
     [feat('time', '60 минут', '', '60 minutes'), feat('warm', 'Горячие камни', '', 'Hot stones'),
      feat('music', 'Музыка', '', 'Music')]),
    ('spa-hammam', 'spa', 'spa', L('Хаммам', 'Хаммам', 'Hammam'),
     L('90 минут · пилинг', '90 мүнөт · пилинг', '90 minutes · peeling'), 4500,
     {'type': 'unit', 'unit': 'session', 'min': 1, 'max': 10}, None, None,
     L('Турецкая баня с пенным массажем.', '', 'Turkish bath with foam massage.'),
     [feat('time', '90 минут', '', '90 minutes'), feat('bath', 'Пенный массаж', '', 'Foam massage')]),
    ('food-davinci', 'food', 'davinci', L('Ресторан Da Vinci', 'Da Vinci ресторану', 'Da Vinci restaurant'),
     L('Итальянская кухня · средний чек 3 500 сом', 'Италия ашканасы', 'Italian cuisine · avg. check 3,500 KGS'), 3500,
     {'type': 'check', 'min': 300, 'max': 300000}, None, None,
     L('Паста, пицца из печи и вина.', '', 'Pasta, wood-fired pizza and wine.'),
     [feat('chef', 'Шеф-повар', '', 'Chef'), feat('drink', 'Винная карта', '', 'Wine list'),
      feat('view', 'Вид на озеро', '', 'Lake view')]),
    ('food-cocoloco', 'food', 'coco-loco', L('Coco Loco', 'Coco Loco', 'Coco Loco'),
     L('Пляжное кафе · средний чек 2 000 сом', 'Пляж кафеси', 'Beach café · avg. check 2,000 KGS'), 2000,
     {'type': 'check', 'min': 300, 'max': 300000}, None, L('больше баллов', 'көбүрөөк упай', 'more points'),
     L('Боулы, гриль и лимонады у воды.', '', 'Bowls, grill and lemonades by the water.'),
     [feat('sun', 'У пляжа', '', 'On the beach'), feat('drink', 'Лимонады', '', 'Lemonades')]),
    ('food-pier', 'food', 'pier-bar', L('Бар на пирсе', 'Пирстеги бар', 'Pier bar'),
     L('Коктейли · закат', 'Коктейлдер · күн батыш', 'Cocktails · sunset'), 1500,
     {'type': 'check', 'min': 300, 'max': 300000}, None, None,
     L('Коктейли и закуски на закате.', '', 'Cocktails and snacks at sunset.'),
     [feat('drink', 'Коктейли', '', 'Cocktails'), feat('music', 'Диджей', '', 'DJ')]),
    ('pools-thermal', 'pools', 'reception', L('Термальный бассейн', 'Термалдык бассейн', 'Thermal pool'),
     L('+36 °C · весь день', '+36 °C · күн бою', '+36 °C · all day'), 1500,
     {'type': 'unit', 'unit': 'guest', 'min': 1, 'max': 10}, None, None,
     L('Тёплая минеральная вода круглый год.', '', 'Warm mineral water all year round.'),
     [feat('warm', '+36 °C', '', '+36 °C'), feat('towel', 'Полотенца', '', 'Towels')]),
    ('pools-outdoor', 'pools', 'reception', L('Открытый бассейн', 'Ачык бассейн', 'Outdoor pool'),
     L('Шезлонги · бар', 'Шезлонгдор · бар', 'Loungers · bar'), 1000,
     {'type': 'unit', 'unit': 'guest', 'min': 1, 'max': 10}, None, None,
     L('Бассейн с видом на горы.', '', 'Pool with a mountain view.'),
     [feat('sun', 'Шезлонги', '', 'Loungers'), feat('water', 'Подогрев', '', 'Heated')]),
    ('pools-kids', 'pools', 'reception', L('Детский бассейн', 'Балдар бассейни', 'Kids pool'),
     L('Глубина 0,6 м', 'Тереңдиги 0,6 м', 'Depth 0.6 m'), 700,
     {'type': 'unit', 'unit': 'guest', 'min': 1, 'max': 10}, None, None,
     L('Мелкий подогреваемый бассейн.', '', 'Shallow heated pool.'),
     [feat('water', 'Подогрев', '', 'Heated'), feat('people', 'Для детей', '', 'For kids')]),
    ('sport-gym', 'sport', 'sport', L('Тренажёрный зал', 'Спорт залы', 'Gym'),
     L('07:00–23:00', '07:00–23:00', '07:00–23:00'), 800,
     {'type': 'unit', 'unit': 'visit', 'min': 1, 'max': 10}, None, None,
     L('Кардио и силовые тренажёры.', '', 'Cardio and strength equipment.'),
     [feat('gym', 'Тренажёры', '', 'Equipment'), feat('towel', 'Полотенца', '', 'Towels')]),
    ('sport-tennis', 'sport', 'sport', L('Теннисный корт', 'Теннис корту', 'Tennis court'),
     L('Хард · ракетки', 'Хард · ракеткалар', 'Hard court · rackets'), 2000,
     {'type': 'unit', 'unit': 'hour', 'min': 1, 'max': 4}, None, None,
     L('Корт с покрытием хард.', '', 'Hard court.'),
     [feat('time', '1 час', '', '1 hour'), feat('trainer', 'Тренер по запросу', '', 'Coach on request')]),
    ('sport-sup', 'sport', 'sport', L('SUP-прогулка', 'SUP сейили', 'SUP ride'),
     L('Доска · жилет · инструктор', 'Такта · жилет · инструктор', 'Board · vest · instructor'), 1500,
     {'type': 'unit', 'unit': 'hour', 'min': 1, 'max': 4}, None, None,
     L('Прогулка на сапборде по озеру.', '', 'Paddleboarding on the lake.'),
     [feat('water', 'Озеро', '', 'Lake'), feat('trainer', 'Инструктор', '', 'Instructor')]),
]

# Пороги — из ТЗ §3.2
# id, название, порог («Нынешних» за год на предыдущем уровне), может стать вечным, подтверждение.
# Пороги — примерные из ТЗ лояльности (§7.2): точные цифры задаёт курорт в админке.
TIERS = [
    ('bronze', L('Бронза', 'Коло', 'Bronze'), 0, True, 'none'),
    ('silver', L('Серебро', 'Күмүш', 'Silver'), 200_000, True, 'points'),
    ('gold', L('Золото', 'Алтын', 'Gold'), 300_000, True, 'points'),
    ('platinum', L('Платина', 'Платина', 'Platinum'), 900_000, True, 'points'),
    ('titanium', L('Титан', 'Титан', 'Titanium'), 2_000_000, False, 'points_and_achievements'),
    ('ambassador', L('Амбассадор', 'Амбассадор', 'Ambassador'), 3_000_000, False, 'points_and_achievements'),
]

# id, tier, icon, title, short, description — id/уровни из ТЗ §3.2, тексты — заготовка
PRIVILEGES = [
    ('cashback', 'bronze', 'cashback', L('Кешбек баллами', 'Упай кешбеги', 'Points cashback'), L('Кешбек', 'Кешбек', 'Cashback'),
     L('Баллы за каждую оплату деньгами: 100 баллов = 1 сом.', '', 'Points for every money payment: 100 points = 1 KGS.')),
    ('birthday', 'bronze', 'birthday', L('Кешбек ×2 в день рождения', 'Туулган күнү ×2 кешбек', '×2 cashback on birthday'), L('ДР ×2', 'ТК ×2', 'B-day ×2'),
     L('Неделя дня рождения — двойной кешбек.', '', 'Double cashback during your birthday week.')),
    ('welcome', 'bronze', 'drink', L('Приветственный напиток', 'Тосуу суусундугу', 'Welcome drink'), L('Напиток', 'Суусундук', 'Drink'),
     L('Напиток при заезде.', '', 'A drink on check-in.')),
    ('early', 'silver', 'earlyCheckIn', L('Ранний заезд', 'Эрте кирүү', 'Early check-in'), L('Ранний заезд', 'Эрте кирүү', 'Early in'),
     L('Заезд с 10:00 при наличии номеров.', '', 'Check-in from 10:00 subject to availability.')),
    ('lounger', 'silver', 'beach', L('Шезлонг на пляже', 'Пляждагы шезлонг', 'Beach lounger'), L('Шезлонг', 'Шезлонг', 'Lounger'),
     L('Закреплённый шезлонг на пляже.', '', 'A reserved beach lounger.')),
    ('parking', 'silver', 'parking', L('Бесплатная парковка', 'Акысыз унаа токтотуучу жай', 'Free parking'), L('Парковка', 'Паркинг', 'Parking'),
     L('Парковка на территории курорта.', '', 'Parking on the resort grounds.')),
    ('late', 'gold', 'lateCheckOut', L('Поздний выезд', 'Кеч чыгуу', 'Late check-out'), L('Поздний выезд', 'Кеч чыгуу', 'Late out'),
     L('Выезд до 16:00.', '', 'Check-out until 16:00.')),
    ('upgrade', 'gold', 'upgrade', L('Повышение категории номера', 'Бөлмөнүн категориясын жогорулатуу', 'Room upgrade'), L('Апгрейд', 'Апгрейд', 'Upgrade'),
     L('При наличии свободных номеров.', '', 'Subject to availability.')),
    ('spa-priority', 'gold', 'spa', L('Приоритетная запись в SPA', 'SPAга артыкчылыктуу жазылуу', 'SPA priority booking'), L('SPA', 'SPA', 'SPA'),
     L('Запись в SPA без очереди.', '', 'Priority SPA booking.')),
    ('transfer', 'platinum', 'transfer', L('Трансфер', 'Трансфер', 'Transfer'), L('Трансфер', 'Трансфер', 'Transfer'),
     L('Трансфер из аэропорта.', '', 'Airport transfer.')),
    ('concierge', 'platinum', 'concierge', L('Личный консьерж', 'Жеке консьерж', 'Personal concierge'), L('Консьерж', 'Консьерж', 'Concierge'),
     L('Консьерж 24/7 в WhatsApp.', '', '24/7 concierge on WhatsApp.')),
    ('chef', 'platinum', 'chef', L('Ужин от шефа', 'Шефтен кечки тамак', 'Chef’s dinner'), L('Шеф', 'Шеф', 'Chef'),
     L('Авторский ужин раз в сезон.', '', 'A signature dinner once a season.')),
    ('villa', 'titanium', 'villa', L('Вилла по цене делюкса', 'Делюкс баасындагы вилла', 'Villa at deluxe price'), L('Вилла', 'Вилла', 'Villa'),
     L('Проживание на вилле по цене делюкса.', '', 'Stay in a villa at the deluxe rate.')),
    ('events', 'titanium', 'events', L('Закрытые события', 'Жабык иш-чаралар', 'Private events'), L('События', 'Иш-чаралар', 'Events'),
     L('Приглашения на закрытые вечера.', '', 'Invitations to private evenings.')),
    ('spa-day', 'titanium', 'gift', L('SPA-день в подарок', 'Белекке SPA күнү', 'Complimentary SPA day'), L('SPA-день', 'SPA күнү', 'SPA day'),
     L('Один SPA-день в год бесплатно.', '', 'One free SPA day a year.')),
]


def article(aid, category, tag, title, lead, body, quote=None, days_ago=0, minutes=3):
    return {'id': aid, 'category': category, 'tag': tag, 'title': title, 'lead': lead, 'body': body,
            'quote': quote, 'days_ago': days_ago, 'minutes': minutes, 'image': f'seed/articles/{aid}.jpg'}


ARTICLES = [
    article('spa-bochka-promo', 'spa', L('Акция', 'Акция', 'Promo'), L('Кедровая бочка — ×2 баллы', 'Кедр челеги — ×2 упай', 'Cedar barrel — ×2 points'),
            L('До 30 сентября — удвоенный кешбек.', '', 'Double cashback until 30 September.'),
            {'ru': ['Сеанс в кедровой бочке приносит вдвое больше баллов.'], 'en': ['A cedar barrel session earns twice the points.']}),
    article('davinci-dinner', 'food', L('Рестораны', 'Ресторандар', 'Restaurants'), L('Ужин в Da Vinci', 'Da Vinci кечки тамак', 'Dinner at Da Vinci'),
            L('Новое меню от шефа.', '', 'New menu from the chef.'), {'ru': ['Паста ручной работы и пицца из печи.']}, days_ago=2),
    article('villa-weekend', 'rooms', L('Номера', 'Бөлмөлөр', 'Rooms'), L('Выходные на вилле', 'Виллада дем алыш', 'Weekend at the villa'),
            L('Вилла у воды для всей семьи.', '', 'Waterfront villa for the whole family.'), {'ru': ['Отдельная вилла с бассейном.']}, days_ago=4),
    article('thermal-pool', 'pools', L('Бассейны', 'Бассейндер', 'Pools'), L('Термальный бассейн', 'Термалдык бассейн', 'Thermal pool'),
            L('+36 °C круглый год.', '', '+36 °C all year round.'), {'ru': ['Минеральная вода из собственной скважины.']}, days_ago=6),
    article('sup-sunset', 'sport', L('Спорт', 'Спорт', 'Sport'), L('SUP на закате', 'Күн батышта SUP', 'SUP at sunset'),
            L('Прогулки с инструктором.', '', 'Rides with an instructor.'), {'ru': ['Сапборды и жилеты выдаём на пирсе.']}, days_ago=8),
    article('jazz-evening', None, L('События', 'Иш-чаралар', 'Events'), L('Джазовый вечер', 'Джаз кечеси', 'Jazz evening'),
            L('Живая музыка на пирсе.', '', 'Live music on the pier.'), {'ru': ['Каждую субботу на закате.']}, days_ago=1),
    article('yoga-morning', 'sport', L('События', 'Иш-чаралар', 'Events'), L('Утренняя йога', 'Эртең мененки йога', 'Morning yoga'),
            L('На пляже с тренером.', '', 'On the beach with a coach.'), {'ru': ['Ежедневно в 08:00.']}, days_ago=1),
    article('wine-tasting', 'food', L('События', 'Иш-чаралар', 'Events'), L('Дегустация вин', 'Шарап даамын татуу', 'Wine tasting'),
            L('Вечер с сомелье.', '', 'An evening with a sommelier.'), {'ru': ['В ресторане Da Vinci.']}, days_ago=3),
    article('kids-club', None, L('События', 'Иш-чаралар', 'Events'), L('Детский клуб', 'Балдар клубу', 'Kids club'),
            L('Аниматоры и мастер-классы.', '', 'Animators and workshops.'), {'ru': ['С 10:00 до 18:00.']}, days_ago=3),
    article('bonfire', None, L('События', 'Иш-чаралар', 'Events'), L('Вечер у костра', 'От жанындагы кече', 'Bonfire night'),
            L('Музыка и чай у огня.', '', 'Music and tea by the fire.'), {'ru': ['Пятница, 21:00.']}, days_ago=5),
]

PROMOS = [  # article_id, subtitle, cta
    ('spa-bochka-promo', L('×2 баллы за кедровую бочку', '', '×2 points for the cedar barrel'), L('Подробнее', 'Кененирээк', 'Details')),
    ('davinci-dinner', L('Новое меню Da Vinci', '', 'New Da Vinci menu'), L('Смотреть', 'Көрүү', 'View')),
    ('villa-weekend', L('Выходные на вилле', '', 'Villa weekend'), L('Забронировать', 'Брондоо', 'Book')),
    ('thermal-pool', L('Термальный бассейн', '', 'Thermal pool'), L('Подробнее', 'Кененирээк', 'Details')),
    ('sup-sunset', L('SUP на закате', '', 'SUP at sunset'), L('Подробнее', 'Кененирээк', 'Details')),
]

EVENTS = [  # article_id, when, place
    ('jazz-evening', L('Сб · 19:00', 'Ишм · 19:00', 'Sat · 19:00'), L('Пирс', 'Пирс', 'Pier')),
    ('yoga-morning', L('Ежедневно · 08:00', 'Күн сайын · 08:00', 'Daily · 08:00'), L('Пляж', 'Пляж', 'Beach')),
    ('wine-tasting', L('Чт · 20:00', 'Бш · 20:00', 'Thu · 20:00'), L('Da Vinci', 'Da Vinci', 'Da Vinci')),
    ('kids-club', L('Ежедневно · 10:00', 'Күн сайын · 10:00', 'Daily · 10:00'), L('Детский клуб', 'Балдар клубу', 'Kids club')),
    ('bonfire', L('Пт · 21:00', 'Жм · 21:00', 'Fri · 21:00'), L('Пляж', 'Пляж', 'Beach')),
]

STORIES = {  # category → (title, [(title, text, itemId)])
    'rooms': (L('Номера', 'Бөлмөлөр', 'Rooms'), [
        (L('Делюкс у озера', '', 'Lakeside deluxe'), L('Терраса и вид на Иссык-Куль', '', 'Terrace and Issyk-Kul view'), 'room-deluxe'),
        (L('Вилла у воды', '', 'Waterfront villa'), L('Для всей семьи', '', 'For the whole family'), 'room-villa')]),
    'spa': (L('SPA', 'SPA', 'SPA'), [
        (L('Кедровая бочка', '', 'Cedar barrel'), L('×2 баллы до конца сентября', '', '×2 points until end of September'), 'spa-bochka'),
        (L('Стоун-массаж', '', 'Stone massage'), L('Горячие камни', '', 'Hot stones'), 'spa-stone')]),
    'food': (L('Рестораны', 'Ресторандар', 'Restaurants'), [
        (L('Da Vinci', '', 'Da Vinci'), L('Итальянская кухня', '', 'Italian cuisine'), 'food-davinci'),
        (L('Бар на пирсе', '', 'Pier bar'), L('Коктейли на закате', '', 'Sunset cocktails'), 'food-pier')]),
    'pools': (L('Бассейны', 'Бассейндер', 'Pools'), [
        (L('Термальный', '', 'Thermal'), L('+36 °C', '', '+36 °C'), 'pools-thermal')]),
    'sport': (L('Спорт', 'Спорт', 'Sport'), [
        (L('SUP', '', 'SUP'), L('Прогулка по озеру', '', 'Lake ride'), 'sport-sup'),
        (L('Теннис', '', 'Tennis'), L('Корт хард', '', 'Hard court'), 'sport-tennis')]),
}

COMPLAINT_CATEGORIES = [  # из ТЗ §9.2
    ('service', L('Обслуживание', 'Тейлөө', 'Service')),
    ('room', L('Номер', 'Бөлмө', 'Room')),
    ('food', L('Рестораны', 'Ресторандар', 'Restaurants')),
    ('spa', L('SPA', 'SPA', 'SPA')),
    ('pools_sport', L('Бассейны и спорт', 'Бассейн жана спорт', 'Pools & sport')),
    ('points', L('Баллы и заявки', 'Упайлар жана өтүнмөлөр', 'Points & requests')),
    ('app', L('Приложение', 'Колдонмо', 'App')),
    ('other', L('Другое', 'Башка', 'Other')),
]
