"""Полный прайс двух объектов BAYTUR: «Тоо-Ашуу» и кымызолечение в Суусамыре.

Источник: «BAYTUR полный список услуг.docx» (10.10.2026). Цены в сомах (KGS), целые числа.
Чистый Python-модуль с данными, без импортов Django.

Пропущены позиции без цены:
  - «Шампанское Bosca —» (1.5, Бар, Алкогольные напитки)

Раздел «Акции» не перенесён (акции — следующий этап), кроме:
  - коттеджи «Тоо-Ашуу»: завтрак + скипассы входят в цену (features/description);
  - трансфер на «Тоо-Ашуу»: tag «Суперцена»;
  - дети до 6 лет включительно в Суусамыре: отдельные позиции с ценой 0.
"""


def L(ru, ky='', en=''):
    return {'ru': ru, 'ky': ky, 'en': en}


def _U(unit, max_):
    return {'type': 'unit', 'unit': unit, 'min': 1, 'max': max_}


def _F(icon, ru, ky, en):
    return {'icon': icon, 'text': L(ru, ky, en)}


# Частые примечания к цене
N_DAY = L('за сутки', 'бир суткага', 'per day')
N_PERSON = L('с человека', 'бир кишиден', 'per person')
N_HOUR = L('в час', 'саатына', 'per hour')
N_FREE = L('бесплатно', 'акысыз', 'free')
N_ONEWAY = L('в одну сторону', 'бир тарапка', 'one way')
N_ROUND = L('туда и обратно', 'барып-келүү', 'round trip')

SEASON_PACKAGE = ('2026-05-01', '2026-08-01')
SEASON_MILK = ('2026-05-01', '2026-09-01')


# ---------------------------------------------------------------------------
# VENUES
# ---------------------------------------------------------------------------

VENUES = [
    {
        'id': 'ski',
        'name': L('Baytur Ski', 'Baytur Ski', 'Baytur Ski'),
        'short': L('Горнолыжная база', 'Тоо лыжа базасы', 'Ski resort'),
        'description': L(
            'Горнолыжная база на перевале Тоо-Ашуу на высоте 3 000 м: три трассы, канатная дорога, '
            'прокат снаряжения, коттеджи и вагончики, кафе и бар.',
            'Тоо-Ашуу ашуусундагы 3 000 м бийиктиктеги тоо лыжа базасы: үч трасса, аркан жол, '
            'шаймандарды ижарага алуу, коттедждер жана вагондор, кафе жана бар.',
            'Ski resort on the Too-Ashuu pass at 3,000 m: three slopes, a ski lift, equipment rental, '
            'cottages and cabins, a cafe and a bar.',
        ),
        'address': L(
            'Перевал Тоо-Ашуу, 120 км от Бишкека по трассе Бишкек — Ош',
            'Тоо-Ашуу ашуусу, Бишкек — Ош жолу боюнча Бишкектен 120 км',
            'Too-Ashuu pass, 120 km from Bishkek on the Bishkek — Osh highway',
        ),
        'contacts': [
            {'label': L('Отдел бронирования', 'Брондоо бөлүмү', 'Booking department'),
             'phone': '+996 770 797 48', 'whatsapp': False, 'email': ''},
            {'label': L('Отдел бронирования', 'Брондоо бөлүмү', 'Booking department'),
             'phone': '+996 701 797 480', 'whatsapp': True, 'email': ''},
            {'label': L('Администратор базы', 'Базанын администратору', 'Resort administrator'),
             'phone': '+996 555 444 242', 'whatsapp': False, 'email': ''},
            {'label': L('Администратор базы', 'Базанын администратору', 'Resort administrator'),
             'phone': '+996 770 797 370', 'whatsapp': True, 'email': ''},
            {'label': L('Жалобы и предложения', 'Даттануулар жана сунуштар', 'Complaints and suggestions'),
             'phone': '', 'whatsapp': False, 'email': 'pr@baytur.kg'},
        ],
        'info': [
            {'title': L('Трассы', 'Трассалар', 'Slopes'), 'rows': [
                {'label': L('Трасса 1', 'Трасса 1', 'Slope 1'), 'value': L('2,6 км · 32°', '2,6 км · 32°', '2.6 km · 32°')},
                {'label': L('Трасса 2', 'Трасса 2', 'Slope 2'), 'value': L('2,8 км · 30°', '2,8 км · 30°', '2.8 km · 30°')},
                {'label': L('Трасса 3', 'Трасса 3', 'Slope 3'), 'value': L('3 км · 19°', '3 км · 19°', '3 km · 19°')},
            ]},
            {'title': L('Как добраться', 'Кантип жетүүгө болот', 'How to get here'), 'text': L(
                '120 км от Бишкека по трассе Бишкек — Ош, около 2,5 часа на машине. '
                'Высота: 3 000 м над уровнем моря.',
                'Бишкек — Ош жолу боюнча Бишкектен 120 км, унаа менен болжол менен 2,5 саат. '
                'Бийиктиги: деңиз деңгээлинен 3 000 м.',
                '120 km from Bishkek on the Bishkek — Osh highway, about 2.5 hours by car. '
                'Altitude: 3,000 m above sea level.',
            )},
            {'title': L('Трансфер Бишкек ↔ Тоо-Ашуу', 'Трансфер Бишкек ↔ Тоо-Ашуу', 'Transfer Bishkek ↔ Too-Ashuu'), 'rows': [
                {'label': L('Транспорт', 'Транспорт', 'Vehicle'),
                 'value': L('бус на 18 человек, водитель Владимир', '18 кишилик бус, айдоочу Владимир',
                            '18-seat minibus, driver Vladimir')},
                {'label': L('Стоимость', 'Баасы', 'Price'),
                 'value': L('1 000 с человека', 'бир кишиден 1 000', '1,000 per person')},
                {'label': L('Место сбора', 'Чогулуу жери', 'Meeting point'),
                 'value': L('ТЦ «Дордой Плаза»', '«Дордой Плаза» соода борбору', 'Dordoi Plaza mall')},
                {'label': L('Выезд из Бишкека', 'Бишкектен жөнөө', 'Departure from Bishkek'),
                 'value': L('07:00 (или по договорённости)', '07:00 (же макулдашуу боюнча)', '07:00 (or by arrangement)')},
                {'label': L('Выезд с базы', 'Базадан жөнөө', 'Departure from the resort'),
                 'value': L('16:20', '16:20', '16:20')},
                {'label': L('Бронирование', 'Брондоо', 'Booking'),
                 'value': L('+996 558 616 133', '+996 558 616 133', '+996 558 616 133')},
            ]},
        ],
        'sort_order': 10,
    },
    {
        'id': 'kymyz',
        'name': L('Baytur Kymyz', 'Baytur Kymyz', 'Baytur Kymyz'),
        'short': L('Центр кымызолечения', 'Кымыз менен дарылоо борбору', 'Kymyz cure center'),
        'description': L(
            'Центр кымызолечения в Суусамырской долине: коттеджи и юрты, трёхразовое питание '
            'и кобылье молоко, массаж и процедуры, баня, конные прогулки и отдых на природе.',
            'Суусамыр өрөөнүндөгү кымыз менен дарылоо борбору: коттедждер жана боз үйлөр, үч маал тамак '
            'жана бээ сүтү, массаж жана процедуралар, мончо, ат минип сейилдөө жана жаратылышта эс алуу.',
            'Kymyz cure center in the Suusamyr valley: cottages and yurts, three meals a day and mare milk, '
            'massage and treatments, bathhouse, horse riding and outdoor leisure.',
        ),
        'address': L('Жайылский район, Суусамыр', 'Жайыл району, Суусамыр', 'Zhaiyl district, Suusamyr'),
        'contacts': [
            {'label': L('Телефон', 'Телефон', 'Phone'), 'phone': '+996 770 797 370', 'whatsapp': True, 'email': ''},
            {'label': L('Телефон', 'Телефон', 'Phone'), 'phone': '+996 701 797 480', 'whatsapp': True, 'email': ''},
            {'label': L('Телефон', 'Телефон', 'Phone'), 'phone': '+996 770 797 480', 'whatsapp': True, 'email': ''},
        ],
        'info': [
            {'title': L('Сезон кымызолечения', 'Кымыз менен дарылоо мезгили', 'Kymyz cure season'), 'text': L(
                'Сезон длится с 01.05.2026 по 01.08.2026. В пакет входят трёхразовое питание '
                'и кобылье молоко пять раз в день.',
                'Мезгил 01.05.2026дан 01.08.2026га чейин уланат. Пакетке үч маал тамак '
                'жана күнүнө беш жолу бээ сүтү кирет.',
                'The season runs from 01.05.2026 to 01.08.2026. The package includes three meals a day '
                'and mare milk five times a day.',
            )},
            {'title': L('Как добраться', 'Кантип жетүүгө болот', 'How to get here'), 'text': L(
                'Жайылский район, Суусамыр, около 3 часов от Бишкека. Навигация через 2gis.kg.',
                'Жайыл району, Суусамыр, Бишкектен болжол менен 3 саат. Навигация 2gis.kg аркылуу.',
                'Zhaiyl district, Suusamyr, about 3 hours from Bishkek. Navigation via 2gis.kg.',
            )},
            {'title': L('Трансфер', 'Трансфер', 'Transfer'), 'text': L(
                'Трансфер выполняется на минивэне Hyundai Grand Starex (8 мест) и работает круглосуточно.',
                'Трансфер Hyundai Grand Starex минивэнинде (8 орун) аткарылат жана күнү-түнү иштейт.',
                'Transfers are made by a Hyundai Grand Starex minivan (8 seats), available 24/7.',
            )},
            {'title': L('Аренда юрты для банкета', 'Банкет үчүн боз үй ижарасы', 'Banquet yurt rental'), 'text': L(
                'Аренда стоит 1 500 в час или 7 500 за сутки и рассчитана на 4–12 человек. '
                'В стоимость входят обслуживание одним официантом, посуда и услуги посудомойщицы.',
                'Ижара саатына 1 500 же суткасына 7 500 турат жана 4–12 кишиге эсептелген. '
                'Баасына бир официанттын тейлөөсү, идиш-аяк жана идиш жуучунун кызматы кирет.',
                'Rental costs 1,500 per hour or 7,500 per day for 4–12 guests. '
                'The price includes one waiter, dishes and a dishwasher.',
            )},
            {'title': L('Номера и юрты', 'Бөлмөлөр жана боз үйлөр', 'Rooms and yurts'), 'rows': [
                {'label': L('Стандарт (коттедж)', 'Стандарт (коттедж)', 'Standard (cottage)'),
                 'value': L('3 места · санузел, горячая и холодная вода, Wi-Fi, телевизор, электрочайник',
                            '3 орун · санитардык түйүн, ысык жана муздак суу, Wi-Fi, телевизор, электр чайнек',
                            '3 guests · bathroom, hot and cold water, Wi-Fi, TV, electric kettle')},
                {'label': L('Полулюкс (коттедж)', 'Жарым люкс (коттедж)', 'Junior suite (cottage)'),
                 'value': L('2 места · санузел, горячая и холодная вода, душевая кабина, Wi-Fi, телевизор, '
                            'холодильник, электрочайник, посуда, фен',
                            '2 орун · санитардык түйүн, ысык жана муздак суу, душ кабинасы, Wi-Fi, телевизор, '
                            'муздаткыч, электр чайнек, идиш-аяк, фен',
                            '2 guests · bathroom, hot and cold water, shower cabin, Wi-Fi, TV, '
                            'fridge, electric kettle, dishes, hair dryer')},
                {'label': L('Люкс (коттедж)', 'Люкс (коттедж)', 'Suite (cottage)'),
                 'value': L('2 места · то же, что в полулюксе', '2 орун · жарым люкстагыдай эле',
                            '2 guests · same as the junior suite')},
                {'label': L('Юрта с односпальными кроватями', 'Бир кишилик керебеттүү боз үй', 'Yurt with single beds'),
                 'value': L('4 места · электрочайник, посуда, Wi-Fi', '4 орун · электр чайнек, идиш-аяк, Wi-Fi',
                            '4 guests · electric kettle, dishes, Wi-Fi')},
                {'label': L('Юрта с двуспальными кроватями', 'Эки кишилик керебеттүү боз үй', 'Yurt with double beds'),
                 'value': L('5 мест · электрочайник, посуда, Wi-Fi', '5 орун · электр чайнек, идиш-аяк, Wi-Fi',
                            '5 guests · electric kettle, dishes, Wi-Fi')},
                {'label': L('Национальная юрта для банкетов', 'Банкет үчүн улуттук боз үй', 'National banquet yurt'),
                 'value': L('4–12 мест · для банкетов и мероприятий', '4–12 орун · банкеттер жана иш-чаралар үчүн',
                            '4–12 guests · for banquets and events')},
            ]},
        ],
        'sort_order': 20,
    },
]


# ---------------------------------------------------------------------------
# OUTLETS
# ---------------------------------------------------------------------------

OUTLETS = [
    {'id': 'ski-reception', 'venue': 'ski', 'name': L('Ресепшен', 'Ресепшн', 'Reception'), 'sort_order': 10},
    {'id': 'ski-lift', 'venue': 'ski', 'name': L('Канатная дорога', 'Аркан жол', 'Ski lift'), 'sort_order': 20},
    {'id': 'ski-rental', 'venue': 'ski', 'name': L('Прокат', 'Ижара', 'Rental'), 'sort_order': 30},
    {'id': 'ski-cafe', 'venue': 'ski', 'name': L('Кафе', 'Кафе', 'Cafe'), 'sort_order': 40},
    {'id': 'ski-bar', 'venue': 'ski', 'name': L('Бар', 'Бар', 'Bar'), 'sort_order': 50},
    {'id': 'kymyz-reception', 'venue': 'kymyz', 'name': L('Ресепшен', 'Ресепшн', 'Reception'), 'sort_order': 10},
    {'id': 'kymyz-spa', 'venue': 'kymyz', 'name': L('Массаж и процедуры', 'Массаж жана процедуралар', 'Massage and treatments'), 'sort_order': 20},
    {'id': 'kymyz-leisure', 'venue': 'kymyz',
     'name': L('Досуг: баня, конные прогулки, отдых на природе',
               'Эс алуу: мончо, ат минип сейилдөө, жаратылышта эс алуу',
               'Leisure: bathhouse, horse riding, outdoor rest'), 'sort_order': 30},
    {'id': 'kymyz-kymyz', 'venue': 'kymyz', 'name': L('Кобылье молоко', 'Бээ сүтү', 'Mare milk'), 'sort_order': 40},
]


# ---------------------------------------------------------------------------
# SECTIONS
# ---------------------------------------------------------------------------

def _S(id_, venue, parent, category, title, note=None, sort_order=0):
    return {'id': id_, 'venue': venue, 'parent': parent, 'category': category,
            'title': title, 'note': note or {}, 'sort_order': sort_order}


TA, SU = 'ski', 'kymyz'

SECTIONS = [
    # --- Тоо-Ашуу ---
    _S('ski-stay', TA, None, 'rooms', L('Проживание', 'Жашоо', 'Accommodation'),
       L('Цена за сутки. В коттеджах завтрак и скипасс для каждого гостя включены.',
         'Баасы бир суткага. Коттедждерде ар бир конокко эртең мененки тамак жана скипасс кирет.',
         'Price per day. Cottages include breakfast and a ski pass for every guest.'), 10),
    _S('ski-skipass', TA, None, 'sport', L('Ski Pass, канатная дорога, инструктор', 'Ski Pass, аркан жол, инструктор',
                                          'Ski pass, lift, instructor'), None, 20),
    _S('ski-rental', TA, None, 'sport', L('Прокат снаряжения', 'Шаймандарды ижарага алуу', 'Equipment rental'), None, 30),
    _S('ski-cafe', TA, None, 'food', L('Кафе: кухня', 'Кафе: ашкана', 'Cafe: kitchen'), None, 40),
    _S('ski-cafe-breakfast', TA, 'ski-cafe', 'food', L('Завтраки', 'Эртең мененки тамактар', 'Breakfast'), None, 10),
    _S('ski-cafe-salads', TA, 'ski-cafe', 'food', L('Салаты', 'Салаттар', 'Salads'), None, 20),
    _S('ski-cafe-soups', TA, 'ski-cafe', 'food', L('Супы', 'Шорполор', 'Soups'), None, 30),
    _S('ski-cafe-mains', TA, 'ski-cafe', 'food', L('Вторые блюда', 'Экинчи тамактар', 'Main courses'), None, 40),
    _S('ski-cafe-steaks', TA, 'ski-cafe', 'food', L('Стейки', 'Стейктер', 'Steaks'), None, 50),
    _S('ski-cafe-pizza', TA, 'ski-cafe', 'food', L('Пицца', 'Пицца', 'Pizza'), None, 60),
    _S('ski-cafe-sides', TA, 'ski-cafe', 'food', L('Гарниры', 'Гарнирлер', 'Side dishes'), None, 70),
    _S('ski-cafe-snacks', TA, 'ski-cafe', 'food', L('Закуски', 'Закускалар', 'Snacks'), None, 80),
    _S('ski-cafe-sauces', TA, 'ski-cafe', 'food', L('Соусы', 'Соустар', 'Sauces'), None, 90),
    _S('ski-cafe-banquet', TA, 'ski-cafe', 'food', L('Банкетное меню', 'Банкеттик меню', 'Banquet menu'), None, 100),
    _S('ski-bar', TA, None, 'food', L('Бар', 'Бар', 'Bar'), None, 50),
    _S('ski-bar-hot', TA, 'ski-bar', 'food', L('Горячие напитки', 'Ысык суусундуктар', 'Hot drinks'), None, 10),
    _S('ski-bar-soft', TA, 'ski-bar', 'food', L('Безалкогольные напитки', 'Алкоголсуз суусундуктар', 'Soft drinks'), None, 20),
    _S('ski-bar-alcohol', TA, 'ski-bar', 'food', L('Алкогольные напитки', 'Алкоголдук суусундуктар', 'Alcoholic drinks'), None, 30),
    _S('ski-bar-snacks', TA, 'ski-bar', 'food', L('Закуски и сладости', 'Закускалар жана таттуулар', 'Snacks and sweets'), None, 40),
    _S('ski-transfer', TA, None, 'sport', L('Трансфер Бишкек ↔ Тоо-Ашуу', 'Трансфер Бишкек ↔ Тоо-Ашуу', 'Transfer Bishkek ↔ Too-Ashuu'),
       L('Бус на 18 человек. Сбор у ТЦ «Дордой Плаза», выезд в 07:00, обратно с базы в 16:20.',
         '18 кишилик бус. «Дордой Плаза» соода борборунда чогулуу, 07:00дө жөнөө, базадан 16:20да кайтуу.',
         '18-seat minibus. Meet at Dordoi Plaza mall, departure 07:00, return from the resort at 16:20.'), 60),

    # --- Суусамыр ---
    _S('kymyz-stay-full', SU, None, 'rooms',
       L('Проживание с питанием и кобыльим молоком', 'Тамак жана бээ сүтү менен жашоо', 'Stay with meals and mare milk'),
       L('Сезон с 01.05.2026 по 01.08.2026. В пакет входят трёхразовое питание и кобылье молоко пять раз в день.',
         'Мезгил 01.05.2026дан 01.08.2026га чейин. Пакетке үч маал тамак жана күнүнө беш жолу бээ сүтү кирет.',
         'Season 01.05.2026 – 01.08.2026. The package includes three meals a day and mare milk five times a day.'), 10),
    _S('kymyz-stay-room', SU, None, 'rooms',
       L('Проживание без питания', 'Тамаксыз жашоо', 'Room only'),
       L('Цены по курсу НБ КР', 'Баалар КР УБнын курсу боюнча', 'Prices at the National Bank of the KR rate'), 20),
    _S('kymyz-banquet-yurt', SU, None, 'rooms',
       L('Аренда юрты для банкета', 'Банкет үчүн боз үй ижарасы', 'Banquet yurt rental'),
       L('4–12 человек. Входят официант, посуда и услуги посудомойщицы.',
         '4–12 киши. Официант, идиш-аяк жана идиш жуучунун кызматы кирет.',
         '4–12 guests. Includes a waiter, dishes and a dishwasher.'), 30),
    _S('kymyz-massage', SU, None, 'spa', L('Массаж и процедуры', 'Массаж жана процедуралар', 'Massage and treatments'), None, 40),
    _S('kymyz-massage-massage', SU, 'kymyz-massage', 'spa', L('Массаж', 'Массаж', 'Massage'), None, 10),
    _S('kymyz-massage-honey', SU, 'kymyz-massage', 'spa', L('Медовый массаж', 'Бал массажы', 'Honey massage'), None, 20),
    _S('kymyz-massage-procedures', SU, 'kymyz-massage', 'spa', L('Процедуры', 'Процедуралар', 'Treatments'), None, 30),
    _S('kymyz-transfer', SU, None, 'sport', L('Трансфер', 'Трансфер', 'Transfer'),
       L('Минивэн Hyundai Grand Starex, 8 мест, круглосуточно. Цена за машину.',
         'Hyundai Grand Starex минивэни, 8 орун, күнү-түнү. Баасы бир унаага.',
         'Hyundai Grand Starex minivan, 8 seats, 24/7. Price per vehicle.'), 50),
    _S('kymyz-extras', SU, None, 'sport', L('Дополнительные услуги', 'Кошумча кызматтар', 'Extra services'), None, 60),
    _S('kymyz-extras-events', SU, 'kymyz-extras', 'rooms', L('Мероприятия', 'Иш-чаралар', 'Events'), None, 10),
    _S('kymyz-extras-staff', SU, 'kymyz-extras', 'food',
       L('Обслуживание мероприятий', 'Иш-чараларды тейлөө', 'Event staff'), None, 20),
    _S('kymyz-extras-nature', SU, 'kymyz-extras', 'food', L('Отдых на природе', 'Жаратылышта эс алуу', 'Outdoor rest'), None, 30),
    _S('kymyz-extras-ram', SU, 'kymyz-extras', 'food', L('Баран', 'Кой', 'Ram'), None, 40),
    _S('kymyz-extras-horses', SU, 'kymyz-extras', 'sport', L('Конные прогулки', 'Ат минип сейилдөө', 'Horse riding'), None, 50),
    _S('kymyz-extras-bath', SU, 'kymyz-extras', 'spa', L('Баня и сауна', 'Мончо жана сауна', 'Bathhouse and sauna'), None, 60),
    _S('kymyz-extras-leisure', SU, 'kymyz-extras', 'sport', L('Досуг', 'Эс алуу', 'Leisure'), None, 70),
    _S('kymyz-kymyz', SU, None, 'food', L('Кобылье молоко', 'Бээ сүтү', 'Mare milk'), None, 70),
]

_SECTION_BY_ID = {s['id']: s for s in SECTIONS}


# ---------------------------------------------------------------------------
# ITEMS
# ---------------------------------------------------------------------------

ITEMS = []
_SORT = {}


def _I(id_, section, outlet, title, price, pricing, meta=None, price_note=None, features=None,
       description=None, tag=None, season=None):
    sec = _SECTION_BY_ID[section]
    _SORT[section] = _SORT.get(section, 0) + 10
    ITEMS.append({
        'id': id_,
        'venue': sec['venue'],
        'section': section,
        'outlet': outlet,
        'category': sec['category'],
        'title': title,
        'meta': meta or {},
        'price': price,
        'pricing': pricing,
        'price_note': price_note or {},
        'features': features or [],
        'description': description or {},
        'tag': tag or {},
        'season_from': season[0] if season else None,
        'season_to': season[1] if season else None,
        'sort_order': _SORT[section],
    })


def _simple(section, outlet, pricing, rows):
    """rows: (id, title L, price, meta L|None)"""
    for id_, title, price, meta in rows:
        _I(id_, section, outlet, title, price, pricing, meta=meta)


VISIT = _U('visit', 20)

# ===== 1.1 Проживание (Тоо-Ашуу) =====
_COTTAGES = [
    (2, 8000, 'на двоих', 'эки кишиге', 'for two', '2 скипасса', '2 скипасс', '2 ski passes'),
    (3, 9500, 'на троих', 'үч кишиге', 'for three', '3 скипасса', '3 скипасс', '3 ski passes'),
    (4, 11500, 'на четверых', 'төрт кишиге', 'for four', '4 скипасса', '4 скипасс', '4 ski passes'),
    (5, 13500, 'на пятерых', 'беш кишиге', 'for five', '5 скипассов', '5 скипасс', '5 ski passes'),
]
for n, price, for_ru, for_ky, for_en, sp_ru, sp_ky, sp_en in _COTTAGES:
    _I(f'ski-cottage-{n}', 'ski-stay', 'ski-reception',
       L(f'Коттедж на {n} места' if n < 5 else f'Коттедж на {n} мест',
         f'{n} орундуу коттедж', f'Cottage for {n}'),
       price, _U('night', 30),
       meta=L(f'{n} места · завтрак + {sp_ru}' if n < 5 else f'{n} мест · завтрак + {sp_ru}',
              f'{n} орун · эртең мененки тамак + {sp_ky}', f'{n} guests · breakfast + {sp_en}'),
       price_note=N_DAY,
       features=[
           _F('people', f'до {n} гостей', f'{n} конокко чейин', f'up to {n} guests'),
           _F('breakfast', f'Завтрак {for_ru}', f'Эртең мененки тамак {for_ky}', f'Breakfast {for_en}'),
           _F('sun', f'{sp_ru} включено', f'{sp_ky} кирет', f'{sp_en} included'),
       ],
       description=L(f'Коттедж на {n} гостей. В цену входят завтрак {for_ru} и {sp_ru} — для каждого гостя.',
                     f'{n} конокко коттедж. Баасына эртең мененки тамак ({for_ky}) жана {sp_ky} кирет — ар бир конокко.',
                     f'Cottage for {n} guests. Breakfast {for_en} and {sp_en} are included — one for every guest.'))

for n, price in ((8, 8000), (10, 10000)):
    _I(f'ski-wagon-{n}', 'ski-stay', 'ski-reception',
       L(f'Вагончик на {n} мест', f'{n} орундуу вагон', f'Cabin for {n}'),
       price, _U('night', 30),
       meta=L(f'{n} мест · только проживание', f'{n} орун · жашоо гана', f'{n} guests · accommodation only'),
       price_note=N_DAY,
       features=[
           _F('people', f'до {n} гостей', f'{n} конокко чейин', f'up to {n} guests'),
           _F('bed', 'Только проживание', 'Жашоо гана', 'Accommodation only'),
       ])

# ===== 1.2 Ski Pass, канатная дорога, инструктор =====
_I('ski-skipass-adult', 'ski-skipass', 'ski-lift',
   L('Скипасс взрослый', 'Чоңдор үчүн скипасс', 'Adult ski pass'), 1500, _U('guest', 20),
   meta=L('полный день', 'толук күн', 'full day'), price_note=N_PERSON)
_I('ski-skipass-half-day', 'ski-skipass', 'ski-lift',
   L('Скипасс на полдня', 'Жарым күнгө скипасс', 'Half-day ski pass'), 950, _U('guest', 20),
   meta=L('полдня', 'жарым күн', 'half day'), price_note=N_PERSON)
_I('ski-skipass-child', 'ski-skipass', 'ski-lift',
   L('Скипасс детский', 'Балдар үчүн скипасс', 'Child ski pass'), 1000, _U('guest', 20),
   meta=L('6–12 лет', '6–12 жаш', 'ages 6–12'), price_note=N_PERSON)
_I('ski-lift-single-ride', 'ski-skipass', 'ski-lift',
   L('Разовый подъём по канатной дороге', 'Аркан жол менен бир жолу көтөрүлүү', 'Single lift ride'), 500, _U('guest', 20),
   meta=L('1 подъём', '1 көтөрүлүү', '1 ride'), price_note=N_PERSON)
_I('ski-instructor', 'ski-skipass', 'ski-lift',
   L('Услуги инструктора', 'Инструктордун кызматы', 'Ski instructor'), 2000, _U('session', 5),
   features=[_F('trainer', 'Инструктор', 'Инструктор', 'Instructor')])

# ===== 1.3 Прокат снаряжения =====
_simple('ski-rental', 'ski-rental', VISIT, [
    ('ski-rental-ski-set', L('Лыжный комплект', 'Лыжа комплекти', 'Ski set'), 1100, None),
    ('ski-rental-snowboard-set', L('Сноуборд комплект', 'Сноуборд комплекти', 'Snowboard set'), 1200, None),
    ('ski-rental-skis', L('Лыжи', 'Лыжа', 'Skis'), 900, None),
    ('ski-rental-ski-boots', L('Ботинки лыжные', 'Лыжа бут кийими', 'Ski boots'), 600, None),
    ('ski-rental-snowboard-boots', L('Ботинки для сноуборда', 'Сноуборд үчүн бут кийим', 'Snowboard boots'), 1000, None),
    ('ski-rental-poles', L('Палки', 'Таяктар', 'Ski poles'), 400, None),
    ('ski-rental-goggles', L('Лыжные очки', 'Лыжа көз айнеги', 'Ski goggles'), 500, None),
    ('ski-rental-gloves', L('Перчатки', 'Мээлейлер', 'Gloves'), 500, None),
    ('ski-rental-mat', L('Каримат', 'Каримат', 'Sleeping mat'), 200, None),
])

# ===== 1.4 Кафе: кухня =====
G300 = L('300 г', '300 г', '300 g')
KG1 = L('1 кг', '1 кг', '1 kg')

_simple('ski-cafe-breakfast', 'ski-cafe', VISIT, [
    ('ski-oatmeal-porridge', L('Каша овсяная', 'Сулу ботко', 'Oatmeal porridge'), 260, None),
    ('ski-rice-porridge', L('Каша рисовая', 'Күрүч ботко', 'Rice porridge'), 260, None),
    ('ski-fried-eggs', L('Яичница-глазунья из 2 яиц', '2 жумурткадан куурулган жумуртка', 'Fried eggs (2 eggs)'), 240,
     L('2 яйца', '2 жумуртка', '2 eggs')),
    ('ski-syrniki', L('Сырники', 'Сырники', 'Syrniki (cottage cheese pancakes)'), 260, L('2 шт.', '2 даана', '2 pcs')),
    ('ski-omelette-vegetables', L('Омлет с овощами', 'Жашылча кошулган омлет', 'Vegetable omelette'), 300, None),
    ('ski-omelette-cheese-sausage', L('Омлет с сыром и колбасой', 'Сыр жана колбаса кошулган омлет',
                                     'Omelette with cheese and sausage'), 250, None),
    ('ski-bread', L('Хлеб', 'Нан', 'Bread'), 90, None),
])
_simple('ski-cafe-salads', 'ski-cafe', VISIT, [
    ('ski-salad-caesar-chicken', L('Цезарь с курицей', 'Тоок эти менен Цезарь', 'Chicken Caesar salad'), 495, None),
    ('ski-salad-asian-spicy', L('Азиатский острый', 'Ачуу азиялык салат', 'Spicy Asian salad'), 410, None),
    ('ski-salad-greek', L('Греческий', 'Грек салаты', 'Greek salad'), 440, None),
    ('ski-salad-fresh', L('Свежий', 'Жаңы салат', 'Fresh salad'), 310, None),
    ('ski-salad-olivier', L('Оливье', 'Оливье', 'Olivier salad'), 450, None),
    ('ski-salad-shakarap', L('Шакарап', 'Шакарап', 'Shakarap salad'), 310, None),
])
_simple('ski-cafe-soups', 'ski-cafe', VISIT, [
    ('ski-soup-meatballs', L('Суп с фрикадельками', 'Фрикаделька кошулган шорпо', 'Meatball soup'), 320, None),
    ('ski-soup-pelmeni', L('Пельмени', 'Пельмени', 'Pelmeni soup'), 320, None),
    ('ski-soup-tom-yum-seafood', L('Том-Ям с морепродуктами', 'Деңиз азыктары менен Том-Ям', 'Tom Yum with seafood'), 510, None),
    ('ski-soup-borscht', L('Борщ', 'Борщ', 'Borscht'), 320, None),
    ('ski-soup-solyanka', L('Солянка', 'Солянка', 'Solyanka'), 420, None),
    ('ski-soup-lentil', L('Чечевичный суп', 'Жасмык шорпосу', 'Lentil soup'), 320, None),
    ('ski-soup-shorpo-beef', L('Шорпо из говядины', 'Уй этинен шорпо', 'Beef shorpo'), 420, None),
    ('ski-soup-ramen-egg', L('Рамен с яйцом', 'Жумуртка менен рамен', 'Ramen with egg'), 320, None),
])
_simple('ski-cafe-mains', 'ski-cafe', VISIT, [
    ('ski-kuurdak-lamb', L('Куурдак из баранины', 'Кой этинен куурдак', 'Lamb kuurdak'), 880, None),
    ('ski-kuurdak-beef', L('Куурдак из говядины', 'Уй этинен куурдак', 'Beef kuurdak'), 990, None),
    ('ski-lagman-guiru', L('Лагман «гуйру»', 'Гуйру лагман', 'Guiru lagman'), 470, None),
    ('ski-lagman-boso', L('Лагман «босо»', 'Босо лагман', 'Boso lagman'), 470, None),
    ('ski-fried-trout', L('Жареная форель', 'Куурулган форель', 'Fried trout'), 660, G300),
    ('ski-pasta-bolognese', L('Паста «Болоньезе»', 'Болоньезе пастасы', 'Pasta Bolognese'), 510, None),
    ('ski-fettuccine-chicken-mushrooms', L('Феттучини с курицей и грибами', 'Тоок эти жана козу карын менен феттучини',
                                          'Fettuccine with chicken and mushrooms'), 570, None),
    ('ski-manty-meat', L('Манты с мясом', 'Эт кошулган манты', 'Meat manty'), 430, None),
])
_simple('ski-cafe-steaks', 'ski-cafe', VISIT, [
    ('ski-steak-ribeye', L('Рибай', 'Рибай', 'Ribeye steak'), 1500, None),
])
_simple('ski-cafe-pizza', 'ski-cafe', VISIT, [
    ('ski-pizza-margherita', L('Маргарита', 'Маргарита', 'Margherita'), 540, None),
    ('ski-pizza-pepperoni', L('Пепперони', 'Пепперони', 'Pepperoni'), 670, None),
    ('ski-pizza-chicken', L('Пицца с курицей', 'Тоок эти менен пицца', 'Chicken pizza'), 670, None),
])
_simple('ski-cafe-sides', 'ski-cafe', VISIT, [
    ('ski-french-fries', L('Картофель фри', 'Фри картошкасы', 'French fries'), 220, None),
    ('ski-potato-wedges', L('Картофель по-деревенски', 'Айылча картошка', 'Country-style potatoes'), 220, None),
    ('ski-lemon', L('Лимон', 'Лимон', 'Lemon'), 90, None),
])
_simple('ski-cafe-snacks', 'ski-cafe', VISIT, [
    ('ski-onion-rings', L('Жареные луковые кольца', 'Куурулган пияз шакекчелери', 'Fried onion rings'), 275, None),
    ('ski-sausages-kinder', L('Сосиски «Киндер»', '«Киндер» сосискалары', 'Kinder sausages'), 330, None),
    ('ski-chicken-nuggets', L('Куриные наггетсы', 'Тоок наггетстери', 'Chicken nuggets'), 330, None),
])
_simple('ski-cafe-sauces', 'ski-cafe', VISIT, [
    ('ski-sauce-ketchup', L('Кетчуп', 'Кетчуп', 'Ketchup'), 50, None),
    ('ski-sauce-mayonnaise', L('Майонез', 'Майонез', 'Mayonnaise'), 70, None),
    ('ski-sauce-sour-cream', L('Сметана', 'Каймак', 'Sour cream'), 70, None),
    ('ski-sauce-cheese', L('Сырный', 'Сыр соусу', 'Cheese sauce'), 70, None),
    ('ski-sauce-jam', L('Варенье', 'Кыям', 'Jam'), 70, None),
    ('ski-sauce-jalapeno', L('Халапеньо', 'Халапеньо', 'Jalapeño'), 100, None),
])
_simple('ski-cafe-banquet', 'ski-cafe', VISIT, [
    ('ski-plov-laser', L('Плов «лазер»', '«Лазер» палоосу', 'Plov "Laser"'), 2950, KG1),
    ('ski-boorsok', L('Боорсок', 'Боорсок', 'Boorsok'), 450, KG1),
])

# ===== 1.5 Бар =====
L1 = L('1 л', '1 л', '1 L')
L05 = L('0,5 л', '0,5 л', '0.5 L')
ML50 = L('50 мл', '50 мл', '50 ml')

_simple('ski-bar-hot', 'ski-bar', VISIT, [
    ('ski-tea-black-green', L('Чай чёрный / зелёный', 'Кара / көк чай', 'Black / green tea'), 120, None),
    ('ski-tea-sea-buckthorn', L('Чай облепиховый', 'Чычырканак чайы', 'Sea buckthorn tea'), 300, None),
    ('ski-coffee-3in1', L('Кофе 3 в 1', 'Кофе 3 в 1', 'Coffee 3-in-1'), 50, None),
    ('ski-cappuccino', L('Капучино', 'Капучино', 'Cappuccino'), 210, None),
    ('ski-americano', L('Американо', 'Американо', 'Americano'), 180, None),
    ('ski-latte', L('Латте', 'Латте', 'Latte'), 210, None),
    ('ski-espresso', L('Эспрессо', 'Эспрессо', 'Espresso'), 180, None),
])
_simple('ski-bar-soft', 'ski-bar', VISIT, [
    ('ski-coca-cola-1l', L('Coca-Cola', 'Coca-Cola', 'Coca-Cola'), 150, L1),
    ('ski-juice-j7', L('Сок J7', 'J7 ширеси', 'J7 juice'), 240, None),
    ('ski-mineral-water-1l', L('Минеральная вода', 'Минералдык суу', 'Mineral water'), 80, L1),
    ('ski-mineral-water-05l', L('Минеральная вода', 'Минералдык суу', 'Mineral water'), 60, L05),
    ('ski-fuse-tea-1l', L('Холодный чай Fuse Tea', 'Fuse Tea муздак чайы', 'Fuse Tea iced tea'), 150, L1),
    ('ski-lemonade', L('Лимонад', 'Лимонад', 'Lemonade'), 140, None),
    ('ski-energy-nitro', L('Энергетик «Нитро»', '«Нитро» энергетиги', 'Nitro energy drink'), 130, None),
])
_simple('ski-bar-alcohol', 'ski-bar', VISIT, [
    ('ski-beer-urban-135l', L('Пиво «Урбан»', '«Урбан» сырасы', 'Urban beer'), 270, L('1,35 л', '1,35 л', '1.35 L')),
    ('ski-beer-zhivoe-05l', L('Пиво «Живое»', '«Живое» сырасы', 'Zhivoe beer'), 210, L05),
    ('ski-beer-arpa-05l', L('Пиво «Арпа»', '«Арпа» сырасы', 'Arpa beer'), 220, L05),
    ('ski-beer-stella-artois-05l', L('Пиво Stella Artois', 'Stella Artois сырасы', 'Stella Artois beer'), 250, L05),
    ('ski-beer-heineken-05l', L('Пиво Heineken', 'Heineken сырасы', 'Heineken beer'), 240, L05),
    ('ski-vodka-organik-05l', L('Водка «Органик»', '«Органик» арагы', 'Organik vodka'), 1200, L05),
    ('ski-vodka-organik-50ml', L('Водка «Органик»', '«Органик» арагы', 'Organik vodka'), 120, ML50),
    ('ski-vodka-nastroenie-05l', L('Водка «Настроение»', '«Настроение» арагы', 'Nastroenie vodka'), 3300, L05),
    ('ski-vodka-nastroenie-50ml', L('Водка «Настроение»', '«Настроение» арагы', 'Nastroenie vodka'), 330, ML50),
    ('ski-wine-baron', L('Вино Baron', 'Baron шарабы', 'Baron wine'), 1650, None),
    ('ski-whisky-jameson-50ml', L('Виски Jameson', 'Jameson вискиси', 'Jameson whiskey'), 170, ML50),
    ('ski-whisky-jack-daniels-50ml', L("Виски Jack Daniel's", "Jack Daniel's вискиси", "Jack Daniel's whiskey"), 1400, ML50),
    ('ski-cognac-kyrgyzstan-50ml', L('Коньяк «Кыргызстан»', '«Кыргызстан» коньягы', 'Kyrgyzstan cognac'), 140, ML50),
    ('ski-cognac-bishkek-50ml', L('Коньяк «Бишкек»', '«Бишкек» коньягы', 'Bishkek cognac'), 950, ML50),
    ('ski-champagne-sovetskoe', L('Шампанское «Советское»', '«Советское» шампан шарабы', 'Sovetskoe champagne'), 1200, None),
    # «Шампанское Bosca —» пропущено: нет цены
])
_simple('ski-bar-snacks', 'ski-bar', VISIT, [
    ('ski-peanuts', L('Арахис', 'Жер жаңгак', 'Peanuts'), 100, None),
    ('ski-wafers-yashkino-300g', L('Вафли «Яшкино»', '«Яшкино» вафлилери', 'Yashkino wafers'), 90, L('300 г', '300 г', '300 g')),
    ('ski-cheese-chechil', L('Сыр «чечил»', '«Чечил» сыры', 'Chechil cheese'), 180, None),
    ('ski-dirol', L('Dirol', 'Dirol', 'Dirol'), 70, None),
    ('ski-mentos', L('Конфеты Mentos', 'Mentos конфеттери', 'Mentos candies'), 80, None),
    ('ski-seeds-dzhin-140g', L('Семечки «Джин»', '«Джин» семичкеси', 'Dzhin sunflower seeds'), 120, L('140 г', '140 г', '140 g')),
    ('ski-seeds-dzhin-100g', L('Семечки «Джин»', '«Джин» семичкеси', 'Dzhin sunflower seeds'), 100, L('100 г', '100 г', '100 g')),
    ('ski-seeds-dzhin-70g', L('Семечки «Джин»', '«Джин» семичкеси', 'Dzhin sunflower seeds'), 80, L('70 г', '70 г', '70 g')),
    ('ski-teralin', L('Тералин', 'Тералин', 'Teralin'), 95, None),
    ('ski-pistachios', L('Фисташки', 'Мисте', 'Pistachios'), 200, None),
    ('ski-chips-lays', L("Чипсы Lay's", "Lay's чипсысы", "Lay's chips"), 140, None),
    ('ski-chips-pringles', L('Чипсы Pringles', 'Pringles чипсысы', 'Pringles chips'), 200, None),
    ('ski-chocolate-bar', L('Шоколадный батончик', 'Шоколад батончиги', 'Chocolate bar'), 120, None),
    ('ski-chocolate-tablet', L('Шоколад плиточный', 'Плитка шоколад', 'Chocolate tablet'), 180, None),
])

# ===== 1.6 Трансфер Бишкек ↔ Тоо-Ашуу =====
_I('ski-transfer-bishkek', 'ski-transfer', 'ski-reception',
   L('Трансфер Бишкек ↔ Тоо-Ашуу', 'Трансфер Бишкек ↔ Тоо-Ашуу', 'Transfer Bishkek ↔ Too-Ashuu'),
   1000, _U('guest', 18),
   meta=L('бус на 18 человек · 07:00 / 16:20', '18 кишилик бус · 07:00 / 16:20', '18-seat minibus · 07:00 / 16:20'),
   price_note=N_PERSON,
   features=[
       _F('people', 'Бус на 18 человек', '18 кишилик бус', '18-seat minibus'),
       _F('time', 'Выезд из Бишкека в 07:00, с базы в 16:20', 'Бишкектен 07:00дө, базадан 16:20да',
          'From Bishkek at 07:00, from the resort at 16:20'),
   ],
   description=L('Сбор у ТЦ «Дордой Плаза», выезд в 07:00 (или по договорённости), обратно с базы в 16:20. '
                 'Водитель Владимир. Бронирование: +996 558 616 133.',
                 '«Дордой Плаза» соода борборунда чогулуу, 07:00дө жөнөө (же макулдашуу боюнча), базадан 16:20да кайтуу. '
                 'Айдоочу Владимир. Брондоо: +996 558 616 133.',
                 'Meet at Dordoi Plaza mall, departure at 07:00 (or by arrangement), return from the resort at 16:20. '
                 'Driver Vladimir. Booking: +996 558 616 133.'),
   tag=L('Суперцена', 'Супер баа', 'Super price'))


# ===== 2.2 Проживание с питанием и кобыльим молоком =====
def _feat_full(n):
    return [
        _F('people', f'{n} гостя' if n < 5 else f'{n} гостей', f'{n} конок', f'{n} guests'),
        _F('breakfast', 'Трёхразовое питание', 'Үч маал тамак', 'Three meals a day'),
        _F('drink', 'Кобылье молоко 5 раз в день', 'Күнүнө 5 жолу бээ сүтү', 'Mare milk 5 times a day'),
    ]


_COT_STD = [_F('bath', 'Санузел', 'Санитардык түйүн', 'Bathroom'),
            _F('water', 'Горячая и холодная вода', 'Ысык жана муздак суу', 'Hot and cold water'),
            _F('wifi', 'Wi-Fi', 'Wi-Fi', 'Wi-Fi'),
            _F('tv', 'Телевизор', 'Телевизор', 'TV'),
            _F('tea', 'Электрочайник', 'Электр чайнек', 'Electric kettle')]
_COT_LUX = [_F('bath', 'Санузел и душевая кабина', 'Санитардык түйүн жана душ кабинасы', 'Bathroom and shower cabin'),
            _F('water', 'Горячая и холодная вода', 'Ысык жана муздак суу', 'Hot and cold water'),
            _F('wifi', 'Wi-Fi', 'Wi-Fi', 'Wi-Fi'),
            _F('tv', 'Телевизор', 'Телевизор', 'TV'),
            _F('cold', 'Холодильник', 'Муздаткыч', 'Fridge'),
            _F('tea', 'Электрочайник и посуда', 'Электр чайнек жана идиш-аяк', 'Electric kettle and dishes'),
            _F('warm', 'Фен', 'Фен', 'Hair dryer')]
_YURT = [_F('tea', 'Электрочайник и посуда', 'Электр чайнек жана идиш-аяк', 'Electric kettle and dishes'),
         _F('wifi', 'Wi-Fi', 'Wi-Fi', 'Wi-Fi'),
         _F('nature', 'Национальная юрта', 'Улуттук боз үй', 'Traditional yurt')]

T_STD = L('Стандарт (коттедж)', 'Стандарт (коттедж)', 'Standard (cottage)')
T_SEMI = L('Полулюкс (коттедж)', 'Жарым люкс (коттедж)', 'Junior suite (cottage)')
T_LUX = L('Люкс (коттедж)', 'Люкс (коттедж)', 'Suite (cottage)')
T_YURT1 = L('Юрта с односпальными кроватями', 'Бир кишилик керебеттүү боз үй', 'Yurt with single beds')
T_YURT2 = L('Юрта с двуспальными кроватями', 'Эки кишилик керебеттүү боз үй', 'Yurt with double beds')


def _guests(n):
    return L(f'{n} гостя' if n < 5 else f'{n} гостей', f'{n} конок', f'{n} guests')


def _meta_full(n):
    return L(f'{n} гостя · питание + кобылье молоко' if n < 5 else f'{n} гостей · питание + кобылье молоко',
             f'{n} конок · тамак + бээ сүтү', f'{n} guests · meals + mare milk')


def _note_pp(pp_ru, pp_en):
    return L(f'за сутки · {pp_ru} с человека', f'бир суткага · бир кишиден {pp_ru}', f'per day · {pp_en} per person')


_FULL = [
    ('kymyz-full-standard-3', T_STD, 3, 9450, _note_pp('3 150', '3,150'), _COT_STD),
    ('kymyz-full-standard-2', T_STD, 2, 6980, _note_pp('3 490', '3,490'), _COT_STD),
    ('kymyz-full-semi-lux-2', T_SEMI, 2, 10280, N_DAY, _COT_LUX),
    ('kymyz-full-lux-2', T_LUX, 2, 12880, N_DAY, _COT_LUX),
]
for id_, title, n, price, note, extra in _FULL:
    _I(id_, 'kymyz-stay-full', 'kymyz-reception', title, price, _U('night', 30), meta=_meta_full(n),
       price_note=note, features=_feat_full(n) + extra, season=SEASON_PACKAGE)
_I('kymyz-full-lux-extra-bed', 'kymyz-stay-full', 'kymyz-reception',
   L('Люкс: дополнительное место', 'Люкс: кошумча орун', 'Suite: extra bed'), 2480, _U('night', 30),
   meta=L('доп. место · питание + кобылье молоко', 'кошумча орун · тамак + бээ сүтү', 'extra bed · meals + mare milk'),
   price_note=N_DAY, features=[_F('bed', 'Дополнительное место', 'Кошумча орун', 'Extra bed')], season=SEASON_PACKAGE)
_I('kymyz-full-yurt-single-4', 'kymyz-stay-full', 'kymyz-reception', T_YURT1, 10000, _U('night', 30), meta=_meta_full(4),
   price_note=_note_pp('2 500', '2,500'), features=_feat_full(4) + _YURT, season=SEASON_PACKAGE)
_I('kymyz-full-yurt-double-5', 'kymyz-stay-full', 'kymyz-reception', T_YURT2, 12500, _U('night', 30), meta=_meta_full(5),
   price_note=N_DAY, features=_feat_full(5) + _YURT, season=SEASON_PACKAGE)
_I('kymyz-full-kids-under-6', 'kymyz-stay-full', 'kymyz-reception',
   L('Дети до 6 лет включительно', '6 жашка чейинки балдар (кошо алганда)', 'Children up to 6 years inclusive'),
   0, _U('guest', 20),
   meta=L('без питания и молока', 'тамаксыз жана сүтсүз', 'without meals and milk'),
   price_note=N_FREE, season=SEASON_PACKAGE)

# ===== 2.3 Проживание без питания и молока =====
_ROOM = [
    ('kymyz-room-standard-3', T_STD, 3, 5220, _COT_STD),
    ('kymyz-room-standard-2', T_STD, 2, 3680, _COT_STD),
    ('kymyz-room-semi-lux-2', T_SEMI, 2, 8700, _COT_LUX),
    ('kymyz-room-lux-2', T_LUX, 2, 10440, _COT_LUX),
]
for id_, title, n, price, extra in _ROOM:
    _I(id_, 'kymyz-stay-room', 'kymyz-reception', title, price, _U('night', 30),
       meta=L(f'{n} гостя · без питания', f'{n} конок · тамаксыз', f'{n} guests · room only'),
       price_note=N_DAY, features=[_F('people', _guests(n)['ru'], _guests(n)['ky'], _guests(n)['en'])] + extra)
_I('kymyz-room-lux-extra-bed', 'kymyz-stay-room', 'kymyz-reception',
   L('Люкс: дополнительное место', 'Люкс: кошумча орун', 'Suite: extra bed'), 5220, _U('night', 30),
   meta=L('доп. место · без питания', 'кошумча орун · тамаксыз', 'extra bed · room only'),
   price_note=N_DAY, features=[_F('bed', 'Дополнительное место', 'Кошумча орун', 'Extra bed')])
_I('kymyz-room-yurt-4', 'kymyz-stay-room', 'kymyz-reception',
   L('Юрта (4 человека)', 'Боз үй (4 киши)', 'Yurt (4 guests)'), 9918, _U('night', 30),
   meta=L('4 гостя · без питания', '4 конок · тамаксыз', '4 guests · room only'), price_note=N_DAY,
   features=[_F('people', '4 гостя', '4 конок', '4 guests')] + _YURT)
_I('kymyz-room-yurt-5', 'kymyz-stay-room', 'kymyz-reception',
   L('Юрта (5 человек)', 'Боз үй (5 киши)', 'Yurt (5 guests)'), 12441, _U('night', 30),
   meta=L('5 гостей · без питания', '5 конок · тамаксыз', '5 guests · room only'), price_note=N_DAY,
   features=[_F('people', '5 гостей', '5 конок', '5 guests')] + _YURT)
_I('kymyz-room-kids-under-6', 'kymyz-stay-room', 'kymyz-reception',
   L('Дети до 6 лет включительно', '6 жашка чейинки балдар (кошо алганда)', 'Children up to 6 years inclusive'),
   0, _U('guest', 20), price_note=N_FREE)
_I('kymyz-room-adults-kids-7plus', 'kymyz-stay-room', 'kymyz-reception',
   L('Взрослые и дети от 7 лет', 'Чоңдор жана 7 жаштан баштап балдар', 'Adults and children from 7 years'),
   1740, _U('guest', 20), price_note=N_PERSON)
_I('kymyz-arabic-breakfast', 'kymyz-stay-room', 'kymyz-reception',
   L('Арабский завтрак', 'Араб эртең мененки тамагы', 'Arabic breakfast'), 525, _U('guest', 20),
   price_note=N_PERSON, features=[_F('breakfast', 'Завтрак', 'Эртең мененки тамак', 'Breakfast')])

# ===== 2.4 Аренда юрты для банкета =====
_BANQ_FEAT = [_F('people', '4–12 человек', '4–12 киши', '4–12 guests'),
              _F('chef', 'Официант, посуда, посудомойщица', 'Официант, идиш-аяк, идиш жуучу', 'Waiter, dishes, dishwasher')]
_I('kymyz-banquet-yurt-hour', 'kymyz-banquet-yurt', 'kymyz-reception',
   L('Юрта для банкета, по часам', 'Банкет үчүн боз үй, саат менен', 'Banquet yurt, hourly'), 1500, _U('hour', 12),
   meta=L('4–12 человек', '4–12 киши', '4–12 guests'), price_note=N_HOUR, features=_BANQ_FEAT)
_I('kymyz-banquet-yurt-day', 'kymyz-banquet-yurt', 'kymyz-reception',
   L('Юрта для банкета, сутки', 'Банкет үчүн боз үй, сутка', 'Banquet yurt, full day'), 7500, _U('night', 7),
   meta=L('4–12 человек', '4–12 киши', '4–12 guests'), price_note=N_DAY, features=_BANQ_FEAT)


# ===== 2.5 Массаж и процедуры =====
def _min(m):
    if m == 60:
        return L('1 час', '1 саат', '1 hour')
    return L(f'{m} мин', f'{m} мүн', f'{m} min')


def _spa(section, rows):
    for id_, title, minutes, price, meta_over in rows:
        meta = meta_over or _min(minutes)
        _I(id_, section, 'kymyz-spa', title, price, _U('session', 5), meta=meta,
           features=[_F('time', meta['ru'], meta['ky'], meta['en'])])


_spa('kymyz-massage-massage', [
    ('kymyz-massage-general-therapeutic', L('Общий лечебный массаж', 'Жалпы дарылоочу массаж', 'General therapeutic massage'), 60, 2500, None),
    ('kymyz-massage-classic', L('Классический массаж', 'Классикалык массаж', 'Classic massage'), 60, 3000, None),
    ('kymyz-massage-back', L('Массаж спины', 'Белди массаждоо', 'Back massage'), 30, 1000, None),
    ('kymyz-massage-head-acupressure', L('Голова, точечный массаж', 'Баш, чекиттик массаж', 'Head acupressure massage'), 15, 1000, None),
    ('kymyz-massage-foot', L('Массаж стопы, обычный', 'Таман массажы, кадимки', 'Foot massage'), 20, 1000, None),
    ('kymyz-massage-neck-collar', L('Шея, воротниковая зона', 'Моюн, жака зонасы', 'Neck and collar zone'), 20, 1000, None),
    ('kymyz-massage-legs-full', L('Массаж ног полностью', 'Бутту толук массаждоо', 'Full leg massage'), 30, 1000, None),
])
_spa('kymyz-massage-honey', [
    ('kymyz-honey-massage-general', L('Медовый общий массаж', 'Жалпы бал массажы', 'Full-body honey massage'), 60, 3000, None),
    ('kymyz-honey-massage-back-glutes', L('Медовый: спина и ягодицы', 'Бал массажы: бел жана жамбаш', 'Honey massage: back and glutes'), 40, 1500, None),
])
_spa('kymyz-massage-procedures', [
    ('kymyz-zalmanov-bath', L('Ванна Залманова', 'Залманов ваннасы', 'Zalmanov bath'), 25, 1000,
     L('до 25 мин', '25 мүнөткө чейин', 'up to 25 min')),
    ('kymyz-cupping', L('Банки', 'Банкалар', 'Cupping'), 15, 1500, None),
    ('kymyz-face-sculpting-massage', L('Скульптурный массаж лица', 'Жүздүн скульптуралык массажы', 'Sculpting facial massage'), 40, 2000, None),
    ('kymyz-face-classic-massage', L('Классический массаж лица', 'Жүздүн классикалык массажы', 'Classic facial massage'), 40, 2000, None),
    ('kymyz-lymphatic-drainage-massage', L('Лимфодренажный (антицеллюлитный) массаж', 'Лимфодренаждык (антицеллюлиттик) массаж',
                                        'Lymphatic drainage (anti-cellulite) massage'), 20, 2000, None),
    ('kymyz-antler-baths', L('Пантовые ванны', 'Мүйүз (панты) ванналары', 'Antler (pantoviye) baths'), 30, 3000, None),
])

# ===== 2.6 Трансфер (Суусамыр) =====
_TR_FEAT = [_F('people', 'Hyundai Grand Starex, 8 мест', 'Hyundai Grand Starex, 8 орун', 'Hyundai Grand Starex, 8 seats'),
            _F('time', 'Круглосуточно', 'Күнү-түнү', '24/7')]
for id_, ru, ky, en, price, note in [
    ('kymyz-transfer-bishkek-oneway', 'Бишкек — Суусамыр', 'Бишкек — Суусамыр', 'Bishkek — Suusamyr', 10000, N_ONEWAY),
    ('kymyz-transfer-ak-zhol-oneway', 'Граница Ак-Жол — Суусамыр', 'Ак-Жол чек арасы — Суусамыр', 'Ak-Zhol border — Suusamyr', 8000, N_ONEWAY),
    ('kymyz-transfer-chaldovar-oneway', 'Граница Чалдовар — Суусамыр', 'Чалдовар чек арасы — Суусамыр', 'Chaldovar border — Suusamyr', 6000, N_ONEWAY),
    ('kymyz-transfer-bishkek-round', 'Бишкек — Суусамыр — Бишкек', 'Бишкек — Суусамыр — Бишкек', 'Bishkek — Suusamyr — Bishkek', 18000, N_ROUND),
    ('kymyz-transfer-ak-zhol-round', 'Граница Ак-Жол — Суусамыр — Ак-Жол', 'Ак-Жол чек арасы — Суусамыр — Ак-Жол',
     'Ak-Zhol border — Suusamyr — Ak-Zhol', 16600, N_ROUND),
    ('kymyz-transfer-chaldovar-round', 'Граница Чалдовар — Суусамыр — Чалдовар', 'Чалдовар чек арасы — Суусамыр — Чалдовар',
     'Chaldovar border — Suusamyr — Chaldovar', 12000, N_ROUND),
]:
    _I(id_, 'kymyz-transfer', 'kymyz-reception', L(ru, ky, en), price, _U('visit', 10),
       meta=L('минивэн, 8 мест', 'минивэн, 8 орун', 'minivan, 8 seats'), price_note=note, features=_TR_FEAT)

# ===== 2.7 Дополнительные услуги =====
# Мероприятия
_I('kymyz-conference-hall-full-day', 'kymyz-extras-events', 'kymyz-reception',
   L('Конференц-зал (большая юрта), целый день', 'Конференц-зал (чоң боз үй), толук күн', 'Conference hall (large yurt), full day'),
   20000, _U('visit', 5), meta=L('10:00–22:00', '10:00–22:00', '10:00–22:00'),
   features=[_F('time', '10:00–22:00', '10:00–22:00', '10:00–22:00')])
_I('kymyz-conference-hall-half-day', 'kymyz-extras-events', 'kymyz-reception',
   L('Конференц-зал (большая юрта), полдня', 'Конференц-зал (чоң боз үй), жарым күн', 'Conference hall (large yurt), half day'),
   10000, _U('visit', 5), meta=L('полдня', 'жарым күн', 'half day'))
_I('kymyz-waiter', 'kymyz-extras-staff', 'kymyz-reception',
   L('Услуги официанта', 'Официанттын кызматы', 'Waiter service'), 2000, VISIT,
   meta=L('1 официант', '1 официант', '1 waiter'))
_I('kymyz-cook', 'kymyz-extras-staff', 'kymyz-reception',
   L('Услуги повара', 'Ашпозчунун кызматы', 'Cook service'), 3000, VISIT,
   meta=L('одно горячее блюдо до 10 человек', '10 кишиге чейин бир ысык тамак', 'one hot dish for up to 10 people'),
   features=[_F('chef', 'Повар', 'Ашпозчу', 'Cook')])
# Отдых на природе
_I('kymyz-canopy-rent', 'kymyz-extras-nature', 'kymyz-leisure',
   L('Аренда навеса (до 10 человек)', 'Чатыр ижарасы (10 кишиге чейин)', 'Canopy rental (up to 10 people)'), 500, _U('hour', 12),
   meta=L('до 10 человек · с посудой', '10 кишиге чейин · идиш-аяк менен', 'up to 10 people · with dishes'), price_note=N_HOUR,
   features=[_F('people', 'до 10 человек', '10 кишиге чейин', 'up to 10 people'), _F('nature', 'С посудой', 'Идиш-аяк менен', 'With dishes')])
_I('kymyz-kazan-with-firewood', 'kymyz-extras-nature', 'kymyz-leisure',
   L('Аренда казана с дровами', 'Отун менен казан ижарасы', 'Kazan rental with firewood'), 1000, VISIT,
   meta=L('казан + 1 мешок дров', 'казан + 1 кап отун', 'kazan + 1 bag of firewood'),
   features=[_F('fire', 'Казан и мешок дров', 'Казан жана кап отун', 'Kazan and a bag of firewood')])
_I('kymyz-firewood-bag', 'kymyz-extras-nature', 'kymyz-leisure',
   L('Мешок дров', 'Кап отун', 'Bag of firewood'), 500, VISIT)
_I('kymyz-grill-rent', 'kymyz-extras-nature', 'kymyz-leisure',
   L('Аренда мангала', 'Мангал ижарасы', 'Grill rental'), 500, _U('hour', 12),
   meta=L('15 шампуров', '15 шампур', '15 skewers'), price_note=N_HOUR,
   features=[_F('fire', 'Мангал и 15 шампуров', 'Мангал жана 15 шампур', 'Grill and 15 skewers')])
# Баран
_I('kymyz-ram-purchase', 'kymyz-extras-ram', 'kymyz-leisure',
   L('Покупка барана', 'Кой сатып алуу', 'Ram purchase'), 10000, {'type': 'check', 'min': 10000, 'max': 22000},
   price_note=L('от 10 000 до 22 000', '10 000ден 22 000ге чейин', 'from 10,000 to 22,000'))
_I('kymyz-ram-butchering', 'kymyz-extras-ram', 'kymyz-leisure',
   L('Разделка барана', 'Кой союу жана бөлүү', 'Ram butchering'), 2000, _U('visit', 5))
_I('kymyz-ram-offal-cleaning', 'kymyz-extras-ram', 'kymyz-leisure',
   L('Чистка внутренностей', 'Ич эттерди тазалоо', 'Offal cleaning'), 2000, _U('visit', 5))
# Конные прогулки
_HORSE_DESC = L('По территории комплекса', 'Комплекстин аймагы боюнча', 'Within the complex grounds')
_I('kymyz-horse-ride-1h', 'kymyz-extras-horses', 'kymyz-leisure',
   L('Конная прогулка, 1 час', 'Ат минип сейилдөө, 1 саат', 'Horse ride, 1 hour'), 2000, _U('hour', 12),
   meta=L('1 час', '1 саат', '1 hour'), price_note=N_HOUR, description=_HORSE_DESC,
   features=[_F('time', '1 час', '1 саат', '1 hour')])
_I('kymyz-horse-ride-30min', 'kymyz-extras-horses', 'kymyz-leisure',
   L('Конная прогулка, 30 минут', 'Ат минип сейилдөө, 30 мүнөт', 'Horse ride, 30 minutes'), 1000, _U('session', 5),
   meta=L('30 мин', '30 мүн', '30 min'), price_note=L('за 30 минут', '30 мүнөткө', 'per 30 minutes'),
   description=_HORSE_DESC, features=[_F('time', '30 мин', '30 мүн', '30 min')])
_I('kymyz-horse-guide', 'kymyz-extras-horses', 'kymyz-leisure',
   L('Конный гид', 'Атчан гид', 'Horse riding guide'), 1000, _U('hour', 12),
   meta=L('сопровождение по территории', 'аймак боюнча коштоо', 'escort within the grounds'), price_note=N_HOUR,
   features=[_F('trainer', 'Сопровождение', 'Коштоо', 'Escort')])
# Баня и сауна
_LINEN = _F('towel', 'Халат, полотенце, простыни', 'Халат, сүлгү, шейшептер', 'Robe, towel, sheets')
_I('kymyz-bath-small', 'kymyz-extras-bath', 'kymyz-leisure',
   L('Баня маленькая', 'Кичине мончо', 'Small bathhouse'), 2000, _U('hour', 12),
   meta=L('халат, полотенце, простыни', 'халат, сүлгү, шейшептер', 'robe, towel, sheets'), price_note=N_HOUR,
   features=[_LINEN])
_I('kymyz-sauna-big', 'kymyz-extras-bath', 'kymyz-leisure',
   L('Сауна большая', 'Чоң сауна', 'Large sauna'), 10000, _U('session', 5),
   meta=L('3 часа · до 6 человек', '3 саат · 6 кишиге чейин', '3 hours · up to 6 people'),
   price_note=L('за 3 часа, до 6 человек', '3 саатка, 6 кишиге чейин', 'per 3 hours, up to 6 people'),
   features=[_F('people', 'до 6 человек', '6 кишиге чейин', 'up to 6 people'),
             _F('time', '3 часа', '3 саат', '3 hours'), _LINEN])
# Досуг
_I('kymyz-billiards', 'kymyz-extras-leisure', 'kymyz-leisure',
   L('Бильярд', 'Бильярд', 'Billiards'), 500, _U('hour', 12), price_note=N_HOUR)
_I('kymyz-shower', 'kymyz-extras-leisure', 'kymyz-leisure',
   L('Душ', 'Душ', 'Shower'), 200, _U('hour', 12), price_note=N_HOUR)

# Кобылье молоко
_I('kymyz-milk-cup', 'kymyz-kymyz', 'kymyz-kymyz',
   L('Молоко, саамал или кымыз, 1 кружка', 'Сүт, саамал же кымыз, 1 кружка', 'Mare milk, saamal or kymyz, 1 cup'),
   150, VISIT, meta=L('1 кружка', '1 кружка', '1 cup'),
   price_note=L('1 кружка (20–250 г)', '1 кружка (20–250 г)', '1 cup (20–250 g)'),
   features=[_F('drink', '20–250 г', '20–250 г', '20–250 g')])
_I('kymyz-kymyz-or-milk-1l', 'kymyz-kymyz', 'kymyz-kymyz',
   L('Кымыз или кобылье молоко, 1 литр', 'Кымыз же бээ сүтү, 1 литр', 'Kymyz or mare milk, 1 liter'),
   350, VISIT, meta=L1, price_note=L('за 1 литр', '1 литрге', 'per liter'),
   description=L('С мая по 1 сентября', 'Майдан 1-сентябрга чейин', 'From May to September 1'), season=SEASON_MILK)
_I('kymyz-saamal-1l', 'kymyz-kymyz', 'kymyz-kymyz',
   L('Саамал, 1 литр', 'Саамал, 1 литр', 'Saamal, 1 liter'),
   350, VISIT, meta=L1, price_note=L('за 1 литр', '1 литрге', 'per liter'),
   description=L('С мая по 1 сентября', 'Майдан 1-сентябрга чейин', 'From May to September 1'), season=SEASON_MILK)


ALLOWED_ICONS = {
    'view', 'bed', 'people', 'area', 'wifi', 'breakfast', 'terrace', 'pool', 'time', 'towel', 'tea', 'music',
    'fire', 'chef', 'drink', 'sun', 'water', 'gym', 'trainer', 'bath', 'nature', 'cold', 'warm', 'tv', 'flower',
}
ALLOWED_UNITS = {'night', 'session', 'guest', 'hour', 'visit'}
ALLOWED_CATEGORIES = {'rooms', 'spa', 'food', 'pools', 'sport'}


# ---------------------------------------------------------------------------
# Поля ТЗ экосистемы (режимы ski / kymyz): приложение, контакты, разделы, главная, сезоны
# ---------------------------------------------------------------------------

MODES_META = {
    'ski': {'app': 'sk', 'name': L('Baytur Ski', 'Baytur Ski', 'Baytur Ski'),
            'short': L('Горнолыжная база', 'Тоо лыжа базасы', 'Ski resort'),
            'phone': '+996701797480', 'whatsapp': '+996701797480', 'email': 'pr@baytur.kg',
            'accent': '#4A90D9', 'early_booking_enabled': False},
    'kymyz': {'app': 'sk', 'name': L('Baytur Kymyz', 'Baytur Kymyz', 'Baytur Kymyz'),
              'short': L('Центр кымызолечения', 'Кымыз менен дарылоо борбору', 'Kymyz cure center'),
              'phone': '+996770797370', 'whatsapp': '+996770797370', 'email': 'pr@baytur.kg',
              'accent': '#3FA568', 'early_booking_enabled': True},
}

# раздел → короткий id в приложении (key), тип (kind) и иконка (ShowcaseIcon)
SECTION_META = {
    'ski-stay': ('stay', 'stay', 'stay'), 'ski-skipass': ('skipass', 'pass', 'skipass'),
    'ski-rental': ('rental', 'rental', 'rental'), 'ski-cafe': ('cafe', 'menu', 'cafe'),
    'ski-bar': ('bar', 'menu', 'cafe'), 'ski-transfer': ('transfer', 'transfer', 'transfer'),
    'kymyz-stay-full': ('stay', 'stay', 'yurt'), 'kymyz-stay-room': ('rooms', 'stay', 'stay'),
    'kymyz-banquet-yurt': ('banquet', 'extra', 'yurt'), 'kymyz-massage': ('massage', 'procedure', 'massage'),
    'kymyz-transfer': ('transfer', 'transfer', 'transfer'), 'kymyz-extras': ('extras', 'extra', 'horses'),
    'kymyz-kymyz': ('kymyz', 'menu', 'kymyz'),
}

# справка: раздел «info» режима строится из VENUES[...]['info']; трассам — угол для шкалы сложности
INFO_SECTIONS = {
    'ski': {'id': 'ski-info', 'key': 'trails', 'icon': 'trails', 'title': L('Трассы и как добраться',
                                                                          'Трассалар жана жол', 'Slopes and directions')},
    'kymyz': {'id': 'kymyz-info', 'key': 'info', 'icon': 'kymyz', 'title': L('Справка', 'Маалымат', 'Info')},
}
SLOPES = {'Трасса 1': 32, 'Трасса 2': 30, 'Трасса 3': 19}

SHOWCASES = {
    'ski': {'facts': [L('3 000 м', '3 000 м', '3,000 m'), L('3 трассы', '3 трасса', '3 slopes'),
                      L('120 км от Бишкека', 'Бишкектен 120 км', '120 km from Bishkek')],
            'cta': L('Купить скипасс', 'Скипасс сатып алуу', 'Buy a ski pass'), 'cta_section': 'skipass',
            'tiles': [('skipass', 'skipass', L('Скипасс', 'Скипасс', 'Ski pass')),
                      ('rental', 'rental', L('Прокат', 'Ижара', 'Rental')),
                      ('stay', 'stay', L('Проживание', 'Жашоо', 'Stay')),
                      ('cafe', 'cafe', L('Кафе', 'Кафе', 'Cafe')),
                      ('transfer', 'transfer', L('Трансфер', 'Трансфер', 'Transfer')),
                      ('trails', 'trails', L('Трассы', 'Трассалар', 'Slopes'))]},
    'kymyz': {'facts': [L('Сезон: май — июль', 'Мезгил: май — июль', 'Season: May — July'),
                        L('Кымыз 5 раз в день', 'Кымыз күнүнө 5 жолу', 'Kymyz 5 times a day'),
                        L('3 часа от Бишкека', 'Бишкектен 3 саат', '3 hours from Bishkek')],
              'cta': L('Забронировать', 'Брондоо', 'Book now'), 'cta_section': 'stay',
              'tiles': [('stay', 'yurt', L('Проживание', 'Жашоо', 'Stay')),
                        ('massage', 'massage', L('Массаж', 'Массаж', 'Massage')),
                        ('kymyz', 'kymyz', L('Кымыз', 'Кымыз', 'Kymyz')),
                        ('extras', 'horses', L('Досуг', 'Эс алуу', 'Leisure')),
                        ('transfer', 'transfer', L('Трансфер', 'Трансфер', 'Transfer')),
                        ('info', 'kymyz', L('Справка', 'Маалымат', 'Info'))]},
}

# сезоны S&K (ТЗ §6.1): даты правятся в админке
SEASONS = [
    {'venue': 'kymyz', 'year': 2026, 'starts_at': '2026-05-01', 'ends_at': '2026-08-01'},
    {'venue': 'ski', 'year': 2026, 'starts_at': '2026-12-20', 'ends_at': '2027-03-31'},
    {'venue': 'kymyz', 'year': 2027, 'starts_at': '2027-05-01', 'ends_at': '2027-08-01',
     'early_booking_from': '2026-12-01'},
]


# Акции, которые уже есть в прайсах (цены в ITEMS их уже учитывают — акции показывают их в приложении).
# key — для повторной загрузки (load_venues не создаёт акцию с тем же названием повторно).
PROMOTIONS = [
    {'title': L('Завтрак и скипасс для каждого гостя бесплатно', 'Ар бир конокко эртең мененки тамак жана скипасс акысыз',
                'Free breakfast and ski pass for every guest'),
     'description': L('При проживании в коттедже «Тоо-Ашуу» завтрак и скипасс для каждого гостя уже входят в цену.',
                      '«Тоо-Ашуу» коттеджинде жашаганда ар бир конокко эртең мененки тамак жана скипасс баага кирет.',
                      'Breakfast and a ski pass for every guest are included when staying in a Too-Ashuu cottage.'),
     'tag': L('Скипасс в подарок', 'Скипасс белекке', 'Free ski pass'),
     'kind': 'gift', 'value': 0, 'scope': 'items',
     'items': ['ski-cottage-2', 'ski-cottage-3', 'ski-cottage-4', 'ski-cottage-5'], 'gift_item': 'ski-skipass-adult'},
    {'title': L('Дети до 6 лет включительно живут бесплатно', '6 жашка чейинки балдар акысыз жашашат',
                'Children up to 6 stay free'),
     'description': L('Для детей до 6 лет включительно проживание бесплатно (без питания и кобыльего молока).',
                      '6 жашка чейинки балдар үчүн жашоо акысыз (тамаксыз жана бээ сүтүсүз).',
                      'Accommodation is free for children up to 6 (without meals and mare milk).'),
     'tag': L('Бесплатно', 'Акысыз', 'Free'),
     'kind': 'specialPrice', 'value': 0, 'scope': 'items', 'audience': 'children',
     'items': ['kymyz-full-kids-under-6', 'kymyz-room-kids-under-6']},
    {'title': L('Трансфер по суперцене', 'Супер баадагы трансфер', 'Transfer at a super price'),
     'description': L('Трансфер Бишкек ↔ «Тоо-Ашуу» — 1 000 сом с человека.', 'Бишкек ↔ «Тоо-Ашуу» трансфери — кишиге 1 000 сом.',
                      'Bishkek ↔ Too-Ashuu transfer — 1,000 KGS per person.'),
     'tag': L('Суперцена', 'Супер баа', 'Super price'),
     'kind': 'specialPrice', 'value': 1000, 'scope': 'items', 'items': ['ski-transfer-bishkek']},
]


if __name__ == '__main__':
    import re
    from collections import Counter

    errors = []
    id_re = re.compile(r'^[a-z0-9-]{1,60}$')
    venue_ids = {v['id'] for v in VENUES}
    outlet_by_id = {o['id']: o for o in OUTLETS}

    # Уникальность внутри каждой коллекции и между ITEMS и SECTIONS/OUTLETS.
    # (Outlet и section могут делить id — ta-rental/ta-cafe/ta-bar заданы так намеренно.)
    for name, coll in (('VENUES', VENUES), ('OUTLETS', OUTLETS), ('SECTIONS', SECTIONS), ('ITEMS', ITEMS)):
        dup = [k for k, c in Counter(x['id'] for x in coll).items() if c > 1]
        if dup:
            errors.append(f'{name}: duplicate ids {dup}')
    clash = {i['id'] for i in ITEMS} & ({s['id'] for s in SECTIONS} | set(outlet_by_id))
    if clash:
        errors.append(f'item ids clash with sections/outlets: {sorted(clash)}')

    for coll in (OUTLETS, SECTIONS, ITEMS):
        for x in coll:
            if not id_re.match(x['id']):
                errors.append(f'bad id {x["id"]!r}')
            if x['venue'] not in venue_ids:
                errors.append(f'{x["id"]}: unknown venue {x["venue"]}')
            if not x['id'].startswith({'ski': 'ski-', 'kymyz': 'kymyz-'}.get(x['venue'], '?')):
                errors.append(f'{x["id"]}: wrong prefix for venue {x["venue"]}')

    parents = {s['parent'] for s in SECTIONS if s['parent']}
    for s in SECTIONS:
        if s['category'] not in ALLOWED_CATEGORIES:
            errors.append(f'section {s["id"]}: bad category {s["category"]}')
        if s['parent'] and (s['parent'] not in _SECTION_BY_ID or _SECTION_BY_ID[s['parent']]['venue'] != s['venue']):
            errors.append(f'section {s["id"]}: bad parent {s["parent"]}')

    for it in ITEMS:
        sec = _SECTION_BY_ID.get(it['section'])
        if not sec:
            errors.append(f'{it["id"]}: unknown section {it["section"]}')
            continue
        if it['section'] in parents:
            errors.append(f'{it["id"]}: section {it["section"]} is not a leaf')
        if it['category'] != sec['category']:
            errors.append(f'{it["id"]}: category {it["category"]} != section {sec["category"]}')
        if sec['venue'] != it['venue']:
            errors.append(f'{it["id"]}: venue mismatch with section')
        o = outlet_by_id.get(it['outlet'])
        if not o or o['venue'] != it['venue']:
            errors.append(f'{it["id"]}: bad outlet {it["outlet"]}')
        if type(it['price']) is not int or it['price'] < 0:
            errors.append(f'{it["id"]}: bad price {it["price"]!r}')
        p = it['pricing']
        if p.get('type') == 'unit':
            if p.get('unit') not in ALLOWED_UNITS:
                errors.append(f'{it["id"]}: bad unit {p.get("unit")}')
            if not (isinstance(p.get('min'), int) and isinstance(p.get('max'), int) and 1 <= p['min'] <= p['max']):
                errors.append(f'{it["id"]}: bad unit min/max')
        elif p.get('type') == 'check':
            if not (isinstance(p.get('min'), int) and isinstance(p.get('max'), int) and p['min'] <= p['max']):
                errors.append(f'{it["id"]}: bad check range')
            elif it['price'] != p['min']:
                errors.append(f'{it["id"]}: check price must equal min')
        else:
            errors.append(f'{it["id"]}: bad pricing type {p.get("type")}')
        for f in it['features']:
            if f.get('icon') not in ALLOWED_ICONS:
                errors.append(f'{it["id"]}: bad icon {f.get("icon")}')
        for key in ('title',):
            if not it[key].get('ru') or not it[key].get('en') or not it[key].get('ky'):
                errors.append(f'{it["id"]}: incomplete {key}')
        for key in ('season_from', 'season_to'):
            v = it[key]
            if v is not None and not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
                errors.append(f'{it["id"]}: bad {key} {v}')

    print('venues:', len(VENUES), ' outlets:', len(OUTLETS), ' sections:', len(SECTIONS), ' items:', len(ITEMS))
    for v in VENUES:
        print(f'  {v["id"]}: outlets={sum(o["venue"] == v["id"] for o in OUTLETS)} '
              f'sections={sum(s["venue"] == v["id"] for s in SECTIONS)} '
              f'items={sum(i["venue"] == v["id"] for i in ITEMS)}')
    per_section = Counter(i['section'] for i in ITEMS)
    for s in SECTIONS:
        if s['id'] in per_section:
            print(f'    {s["id"]:<24} {s["category"]:<6} {per_section[s["id"]]}')

    if errors:
        print('\nFAILED:')
        for e in errors:
            print('  -', e)
        raise SystemExit(1)
    print('\nOK')
