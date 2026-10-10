"""
Привилегии по объектам экосистемы: у каждого уровня свои привилегии для Resort & Spa, Baytur Ski и Baytur Kymyz.
Существующие курортные привилегии помечаются режимом resort (общие — день рождения — остаются «везде»),
для Ski и Kymyz создаются новые. Только создаёт отсутствующее: правки из админки не перезаписываются.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

TIERS = ['bronze', 'silver', 'gold', 'platinum', 'titanium', 'ambassador']
GENERAL = {'birthday'}  # группы, которые действуют во всех объектах


def L(ru, ky, en):
    return {'ru': ru, 'ky': ky, 'en': en}


# group, icon, режим, название группы, {уровень: (название, коротко, описание)}
SKI = [
    ('ski-tea', 'coffee', L('Горячий чай', 'Ысык чай', 'Hot tea'), {
        t: (L('Горячий чай на базе', 'Базада ысык чай', 'Hot tea at the base'), L('Чай', 'Чай', 'Tea'),
            L('Чайник горячего чая в кафе базы в каждый день катания.',
              'Ар бир тебүү күнү базанын кафесинде бир чайнек ысык чай.',
              'A pot of hot tea at the base café on every ski day.'))
        for t in TIERS}),
    ('ski-parking', 'parking', L('Парковка', 'Унаа токтотмо', 'Parking'), {
        t: (L('Парковка у подъёмника', 'Көтөргүчтүн жанында унаа токтотмо', 'Parking by the lift'),
            L('Парковка', 'Токтотмо', 'Parking'),
            L('Бесплатная парковка рядом с подъёмником.', 'Көтөргүчтүн жанында акысыз унаа токтотмо.',
              'Free parking next to the lift.'))
        for t in TIERS[1:]}),
    ('ski-rental', 'cashback', L('Прокат снаряжения', 'Жабдууларды ижарага алуу', 'Equipment rental'), {
        t: (L(f'Скидка на прокат −{p} %', f'Ижарага −{p} % арзандатуу', f'−{p}% on rental'),
            L(f'Прокат −{p} %', f'Ижара −{p} %', f'Rental −{p}%'),
            L(f'Скидка {p} % на прокат лыж, сноубордов и экипировки — покажите QR в пункте проката.',
              f'Лыжа, сноуборд жана жабдууларды ижарага алууга {p} % арзандатуу — ижара пунктунда QR көрсөтүңүз.',
              f'{p}% off skis, snowboards and gear — show your QR at the rental desk.'))
        for t, p in (('silver', 10), ('gold', 15), ('platinum', 20), ('titanium', 30), ('ambassador', 50))}),
    ('ski-lift', 'upgrade', L('Подъёмник без очереди', 'Көтөргүчкө кезексиз', 'Priority lift'), {
        t: (L('Подъёмник без очереди', 'Көтөргүчкө кезексиз', 'Priority lift access'),
            L('Без очереди', 'Кезексиз', 'No queue'),
            L('Отдельный проход на подъёмник без очереди.', 'Көтөргүчкө кезексиз өзүнчө өтүү.',
              'Separate lift entrance with no queue.'))
        for t in TIERS[2:]}),
    ('ski-late-checkout', 'lateCheckOut', L('Поздний выезд', 'Кеч чыгуу', 'Late check-out'), {
        t: (L(f'Поздний выезд из коттеджа до {h}:00', f'Коттедждан саат {h}:00гө чейин чыгуу',
              f'Cottage check-out until {h}:00'),
            L(f'Выезд до {h}:00', f'{h}:00гө чейин', f'Until {h}:00'),
            L(f'Коттедж можно освободить до {h}:00.', f'Коттеджди саат {h}:00гө чейин бошотсо болот.',
              f'You can leave the cottage by {h}:00.'))
        for t, h in (('gold', 13), ('platinum', 14), ('titanium', 16), ('ambassador', 18))}),
    ('ski-instructor', 'gym', L('Инструктор', 'Инструктор', 'Instructor'), {
        t: (L(f'Занятия с инструктором: {n}', f'Инструктор менен сабак: {n}', f'Lessons with an instructor: {n}'),
            L(f'Инструктор ×{n}', f'Инструктор ×{n}', f'Instructor ×{n}'),
            L(f'{n} часовых {"занятия" if n < 5 else "занятий"} с инструктором за сезон в подарок.' if n > 1 else
              'Одно часовое занятие с инструктором за сезон в подарок.',
              f'Сезонда инструктор менен {n} сааттык сабак белекке.',
              f'{n} one-hour lessons with an instructor per season.' if n > 1 else
              'One one-hour lesson with an instructor per season.'))
        for t, n in (('platinum', 1), ('titanium', 2), ('ambassador', 5))}),
    ('ski-skipass', 'gift', L('Скипасс в подарок', 'Белекке скипасс', 'Ski pass gift'), {
        'platinum': (L('Дневной скипасс в подарок', 'Белекке күндүк скипасс', 'Day ski pass as a gift'),
                     L('Скипасс', 'Скипасс', 'Ski pass'),
                     L('Один дневной скипасс за сезон.', 'Сезонда бир күндүк скипасс.', 'One day pass per season.')),
        'titanium': (L('3 дневных скипасса в подарок', 'Белекке 3 күндүк скипасс', '3 day passes as a gift'),
                     L('3 скипасса', '3 скипасс', '3 passes'),
                     L('Три дневных скипасса за сезон.', 'Сезонда үч күндүк скипасс.', 'Three day passes per season.')),
        'ambassador': (L('Сезонный скипасс', 'Сезондук скипасс', 'Season ski pass'),
                       L('Сезонный', 'Сезондук', 'Season pass'),
                       L('Скипасс на весь сезон в подарок.', 'Бүт сезонго скипасс белекке.',
                         'A ski pass for the whole season as a gift.')),
    }),
    ('ski-transfer', 'transfer', L('Трансфер', 'Трансфер', 'Transfer'), {
        t: (L('Трансфер Бишкек — Тоо-Ашуу', 'Бишкек — Тоо-Ашуу трансфери', 'Bishkek — Too-Ashuu transfer'),
            L('Трансфер', 'Трансфер', 'Transfer'),
            L('Трансфер из Бишкека на базу и обратно раз в сезон.',
              'Сезонда бир жолу Бишкектен базага жана кайра трансфер.',
              'A round-trip transfer from Bishkek once per season.'))
        for t in TIERS[4:]}),
]

KYMYZ = [
    ('kymyz-welcome', 'drink', L('Кымыз при заезде', 'Келгенде кымыз', 'Kymyz on arrival'), {
        t: (L('Пиала кымыза при заезде', 'Келгенде бир кесе кымыз', 'A bowl of kymyz on arrival'),
            L('Кымыз', 'Кымыз', 'Kymyz'),
            L('Свежий кымыз при заселении.', 'Жайгашканда жаңы кымыз.', 'Fresh kymyz when you check in.'))
        for t in TIERS}),
    ('kymyz-to-go', 'gift', L('Кымыз в дорогу', 'Жолго кымыз', 'Kymyz to go'), {
        t: (L(f'Кымыз в дорогу: {n} л', f'Жолго кымыз: {n} л', f'Kymyz to go: {n} l'),
            L(f'Кымыз {n} л', f'Кымыз {n} л', f'Kymyz {n} l'),
            L(f'{n} л кымыза с собой при выезде.', f'Чыгып жатканда {n} л кымыз.',
              f'{n} l of kymyz to take home when you leave.'))
        for t, n in (('silver', 1), ('gold', 2), ('platinum', 3), ('titanium', 3), ('ambassador', 5))}),
    ('kymyz-massage', 'spa', L('Массаж без очереди', 'Массажга кезексиз', 'Priority massage'), {
        t: (L('Приоритетная запись на массаж', 'Массажга биринчи жазылуу', 'Priority massage booking'),
            L('Массаж', 'Массаж', 'Massage'),
            L('Запись на массаж и процедуры вне очереди.', 'Массаж жана процедураларга кезексиз жазылуу.',
              'Book massage and treatments without waiting.'))
        for t in TIERS[2:]}),
    ('kymyz-banya', 'spa', L('Баня', 'Мончо', 'Banya'), {
        t: (L(f'Баня в подарок: {ru}', f'Белекке мончо: {ky}', f'Free banya: {en}'),
            L(f'Баня {ru}', f'Мончо {ky}', f'Banya {en}'),
            L(f'Баня в подарок — {ru} за заезд.', f'Ар бир келгенде белекке мончо — {ky}.',
              f'Free banya — {en} per stay.'))
        for t, ru, ky, en in (('gold', '1 час', '1 саат', '1 hour'), ('platinum', '2 часа', '2 саат', '2 hours'),
                              ('titanium', '3 часа', '3 саат', '3 hours'),
                              ('ambassador', 'каждый день', 'күн сайын', 'every day'))}),
    ('kymyz-upgrade', 'upgrade', L('Апгрейд размещения', 'Жайгашууну жакшыртуу', 'Room upgrade'), {
        t: (L(f'Апгрейд размещения: {ru}', f'Жайгашууну жакшыртуу: {ky}', f'Room upgrade: {en}'),
            L(ru, ky, en),
            L(f'При заселении — размещение выше забронированного: {ru}.',
              f'Жайгашканда — брондолгондон жогору: {ky}.', f'On check-in — a better room: {en}.'))
        for t, ru, ky, en in (('gold', '+1 категория', '+1 категория', '+1 category'),
                              ('platinum', '+1 категория', '+1 категория', '+1 category'),
                              ('titanium', '+2 категории', '+2 категория', '+2 categories'),
                              ('ambassador', 'лучший коттедж', 'эң жакшы коттедж', 'best cottage'))}),
    ('kymyz-late-checkout', 'lateCheckOut', L('Поздний выезд', 'Кеч чыгуу', 'Late check-out'), {
        t: (L(f'Поздний выезд до {h}:00', f'Саат {h}:00гө чейин чыгуу', f'Late check-out until {h}:00'),
            L(f'Выезд до {h}:00', f'{h}:00гө чейин', f'Until {h}:00'),
            L(f'Номер можно освободить до {h}:00.', f'Бөлмөнү саат {h}:00гө чейин бошотсо болот.',
              f'You can leave your room by {h}:00.'))
        for t, h in (('gold', 13), ('platinum', 14), ('titanium', 16), ('ambassador', 18))}),
    ('kymyz-horse', 'excursion', L('Конная прогулка', 'Ат менен сейил', 'Horse ride'), {
        'platinum': (L('Конная прогулка 1 час', 'Ат менен 1 саат сейил', '1-hour horse ride'),
                     L('Кони 1 ч', 'Ат 1 с', 'Horses 1 h'),
                     L('Часовая конная прогулка за заезд.', 'Ар бир келгенде бир сааттык ат сейил.',
                       'A one-hour horse ride per stay.')),
        'titanium': (L('Конная прогулка 2 часа', 'Ат менен 2 саат сейил', '2-hour horse ride'),
                     L('Кони 2 ч', 'Ат 2 с', 'Horses 2 h'),
                     L('Двухчасовая конная прогулка за заезд.', 'Ар бир келгенде эки сааттык ат сейил.',
                       'A two-hour horse ride per stay.')),
        'ambassador': (L('Конный тур на день', 'Бир күндүк ат туру', 'Full-day horse tour'),
                       L('Конный тур', 'Ат туру', 'Horse tour'),
                       L('Конный тур по Суусамырской долине на целый день.',
                         'Суусамыр өрөөнү боюнча бир күндүк ат туру.',
                         'A full-day horse tour of the Suusamyr valley.')),
    }),
    ('kymyz-transfer', 'transfer', L('Трансфер', 'Трансфер', 'Transfer'), {
        t: (L('Трансфер Бишкек — Суусамыр', 'Бишкек — Суусамыр трансфери', 'Bishkek — Suusamyr transfer'),
            L('Трансфер', 'Трансфер', 'Transfer'),
            L('Трансфер из Бишкека и обратно за заезд.', 'Ар бир келгенде Бишкектен жана кайра трансфер.',
              'A round-trip transfer from Bishkek per stay.'))
        for t in TIERS[4:]}),
]


class Command(BaseCommand):
    help = 'Привилегии по объектам: курортные помечаются resort, для Ski и Kymyz создаются свои (только отсутствующее)'

    def handle(self, *args, **opts):
        from apps.common.caching import bump_content_version
        from apps.loyalty.models import Privilege, Tier

        tiers = set(Tier.objects.filter(deleted_at__isnull=True).values_list('pk', flat=True))
        marked = created = 0
        with transaction.atomic():
            # курортные привилегии — только Resort & Spa; ещё не размеченные (modes пусто), кроме общих групп
            for p in Privilege.objects.filter(modes=[]).exclude(group__in=GENERAL):
                if p.group.startswith(('ski-', 'kymyz-')):
                    continue
                p.modes = ['resort']
                p.save(update_fields=['modes'])
                marked += 1
            for mode, rows, base in (('ski', SKI, 100), ('kymyz', KYMYZ, 200)):
                for n, (group, icon, group_title, by_tier) in enumerate(rows):
                    for tier, (title, short, description) in by_tier.items():
                        if tier not in tiers:
                            continue
                        _, new = Privilege.objects.get_or_create(pk=f'{group}-{tier}', defaults={
                            'tier_id': tier, 'modes': [mode], 'group': group, 'group_title': group_title,
                            'icon': icon, 'title': title, 'short': short, 'description': description,
                            'sort_order': base + n})
                        created += int(new)
        bump_content_version()
        self.stdout.write(self.style.SUCCESS(f'Помечено «только Resort»: {marked}; новых привилегий: {created}'))
