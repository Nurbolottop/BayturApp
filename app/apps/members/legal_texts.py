"""
Черновики документов мобильного приложения (07.10.2026) — составлены по фактической работе бэкенда.
Перед публикацией в сторах текст должен проверить юрист курорта; правится в панели (Настройки → Документы).
Разметка: «## Заголовок», «- пункт», пустая строка — новый абзац. Подстановки: {phone}, {whatsapp}, {purge_days}.
"""

PRIVACY = {
    'ru': """Политика конфиденциальности мобильного приложения BAYTUR

Эта политика описывает, какие данные собирает мобильное приложение программы лояльности курорта BAYTUR («приложение», «мы»), зачем и как долго мы их храним. Политика сайта курорта к приложению не относится.

## Какие данные мы собираем
- Номер телефона — для входа по SMS-коду или PIN-коду и как идентификатор участника.
- Имя, фамилия, дата рождения, email (необязательно), фото профиля (необязательно) — для анкеты участника; дата рождения нужна для повышенного кешбека в день рождения.
- История баллов и заявок: услуги, суммы, начисления, списания, уровень программы — чтобы вести ваш счёт в программе лояльности.
- Обращения в поддержку и приложенные к ним фото.
- Технические данные: push-токен Firebase Cloud Messaging, идентификатор установки приложения, версия приложения и платформа (iOS / Android), события использования экранов (аналитика) — чтобы отправлять уведомления, защищать аккаунт и улучшать приложение.

## Вход через Google и Apple
Если вы входите через Google или Apple, мы получаем идентификатор вашего аккаунта у этого сервиса, а также имя и email, если вы разрешили их передать. Пароль от Google или Apple к нам не попадает. Привязку можно отключить в профиле.

## Оплата
Онлайн-оплата проходит на стороне платёжного сервиса Freedom Pay. Данные банковской карты вводятся на его странице и к нам не попадают; мы получаем только результат оплаты и сумму.

## Кому мы передаём данные
- Freedom Pay — для проведения онлайн-оплаты.
- smspro.nikita.kg — для отправки SMS-кодов (передаётся только номер телефона и текст кода).
- Google Firebase — для доставки push-уведомлений.
- Google и Apple — только если вы сами выбрали вход через них.
Мы не продаём данные и не передаём их для рекламы третьих лиц.

## Уведомления и реклама
Уведомления о начислениях, заявках и уровне приходят в приложении и push-сообщениями. Рекламные рассылки — только с вашего согласия; отключить их можно в настройках приложения.

## Сколько мы храним данные
Данные хранятся, пока у вас есть аккаунт. Аналитические события хранятся не дольше 13 месяцев, лента уведомлений — 30 дней.

## Удаление аккаунта
Удалить аккаунт можно в приложении (Профиль → Удалить аккаунт) или на странице https://app.baytur.kg/account/delete. В течение {purge_days} дней аккаунт можно восстановить, войдя по тому же номеру; затем данные удаляются безвозвратно, остаток баллов сгорает. Финансовые записи о заявках и оплатах хранятся обезличенно, как требует закон.

## Ваши права
Вы можете посмотреть и изменить свои данные в профиле, отозвать согласие на рекламу, отвязать вход через Google и Apple, удалить аккаунт или запросить информацию о ваших данных.

## Контакты
По вопросам о данных: телефон {phone}, WhatsApp +{whatsapp}, раздел «Поддержка» в приложении.

При изменении политики мы публикуем новую версию, и приложение попросит принять её заново.""",

    'en': """BAYTUR mobile app privacy policy

This policy explains what data the BAYTUR resort loyalty programme mobile app ("the app", "we") collects, why, and how long we keep it. The resort website's policy does not apply to the app.

## Data we collect
- Phone number — to sign in with an SMS code or PIN and to identify you as a member.
- First name, last name, date of birth, email (optional), profile photo (optional) — for your member profile; the date of birth is used for increased birthday cashback.
- Points and request history: services, amounts, credits, payments, programme tier — to keep your loyalty account.
- Support requests and photos attached to them.
- Technical data: Firebase Cloud Messaging push token, app installation ID, app version and platform (iOS / Android), screen usage events (analytics) — to send notifications, protect your account and improve the app.

## Sign in with Google and Apple
If you sign in with Google or Apple, we receive your account identifier with that service and, if you allow it, your name and email. Your Google or Apple password never reaches us. You can unlink these services in your profile.

## Payments
Online payments are processed by Freedom Pay. Card details are entered on its page and never reach us; we only receive the payment result and amount.

## Who we share data with
- Freedom Pay — to process online payments.
- smspro.nikita.kg — to send SMS codes (only the phone number and the code text).
- Google Firebase — to deliver push notifications.
- Google and Apple — only if you choose to sign in with them.
We do not sell data or share it for third-party advertising.

## Notifications and marketing
Notifications about points, requests and your tier arrive in the app and as push messages. Marketing messages are sent only with your consent; you can turn them off in the app settings.

## How long we keep data
We keep data while your account exists. Analytics events are kept for no longer than 13 months, the notification feed for 30 days.

## Deleting your account
You can delete your account in the app (Profile → Delete account) or at https://app.baytur.kg/account/delete. For {purge_days} days you can restore it by signing in with the same number; after that the data is deleted permanently and remaining points expire. Financial records of requests and payments are kept in anonymised form as required by law.

## Your rights
You can view and edit your data in your profile, withdraw marketing consent, unlink Google and Apple sign-in, delete your account or request information about your data.

## Contacts
Questions about your data: phone {phone}, WhatsApp +{whatsapp}, or the Support section in the app.

When this policy changes we publish a new version and the app will ask you to accept it again.""",

    'ky': """BAYTUR мобилдик тиркемесинин купуялуулук саясаты

Бул саясат BAYTUR курортунун лоялдуулук программасынын мобилдик тиркемеси («тиркеме», «биз») кайсы маалыматтарды чогултаарын, эмне үчүн жана канча убакыт сактаарын түшүндүрөт. Курорттун сайтынын саясаты тиркемеге тиешелүү эмес.

## Кайсы маалыматтарды чогултабыз
- Телефон номери — SMS-код же PIN-код менен кирүү жана катышуучуну аныктоо үчүн.
- Аты, фамилиясы, туулган күнү, email (милдеттүү эмес), профилдин сүрөтү (милдеттүү эмес) — катышуучунун анкетасы үчүн; туулган күнү туулган күндөгү жогорулатылган кешбек үчүн керек.
- Упайлардын жана өтүнмөлөрдүн тарыхы: кызматтар, суммалар, чегерүүлөр, төлөмдөр, программанын деңгээли — лоялдуулук эсебиңизди жүргүзүү үчүн.
- Колдоо кызматына кайрылуулар жана аларга тиркелген сүрөттөр.
- Техникалык маалыматтар: Firebase Cloud Messaging push-токени, тиркемени орнотуунун идентификатору, тиркеменин версиясы жана платформасы (iOS / Android), экрандарды колдонуу окуялары (аналитика) — билдирүүлөрдү жөнөтүү, аккаунтту коргоо жана тиркемени жакшыртуу үчүн.

## Google жана Apple аркылуу кирүү
Google же Apple аркылуу кирсеңиз, ошол кызматтагы аккаунтуңуздун идентификаторун, ошондой эле уруксат берсеңиз атыңызды жана email'иңизди алабыз. Google же Apple сырсөзүңүз бизге келбейт. Байланышты профилден өчүрө аласыз.

## Төлөм
Онлайн төлөм Freedom Pay төлөм кызматында жүргүзүлөт. Банк картасынын маалыматтары анын баракчасында киргизилет жана бизге келбейт; биз төлөмдүн жыйынтыгын жана суммасын гана алабыз.

## Маалыматтарды кимге беребиз
- Freedom Pay — онлайн төлөмдү жүргүзүү үчүн.
- smspro.nikita.kg — SMS-коддорду жөнөтүү үчүн (телефон номери жана коддун тексти гана).
- Google Firebase — push-билдирүүлөрдү жеткирүү үчүн.
- Google жана Apple — алар аркылуу кирүүнү өзүңүз тандасаңыз гана.
Биз маалыматтарды сатпайбыз жана үчүнчү жактардын жарнамасы үчүн бербейбиз.

## Билдирүүлөр жана жарнама
Упайлар, өтүнмөлөр жана деңгээл тууралуу билдирүүлөр тиркемеде жана push-билдирүү катары келет. Жарнамалык билдирүүлөр сиздин макулдугуңуз менен гана жөнөтүлөт; аларды тиркеменин жөндөөлөрүнөн өчүрө аласыз.

## Маалыматтарды канча убакыт сактайбыз
Маалыматтар аккаунтуңуз бар болгон убакытта сакталат. Аналитикалык окуялар 13 айдан ашык сакталбайт, билдирүүлөр тасмасы — 30 күн.

## Аккаунтту өчүрүү
Аккаунтту тиркемеден (Профиль → Аккаунтту өчүрүү) же https://app.baytur.kg/account/delete баракчасынан өчүрө аласыз. {purge_days} күндүн ичинде ошол эле номер менен кирип аккаунтту калыбына келтирсе болот; андан кийин маалыматтар биротоло өчүрүлөт, калган упайлар күйүп кетет. Өтүнмөлөр жана төлөмдөр боюнча каржылык жазуулар мыйзам талап кылгандай жеке маалыматсыз сакталат.

## Сиздин укуктарыңыз
Профилде маалыматтарыңызды көрүп жана өзгөртө аласыз, жарнамага макулдугуңузду кайтарып ала аласыз, Google жана Apple аркылуу кирүүнү ажыратып, аккаунтту өчүрө аласыз же маалыматтарыңыз тууралуу маалымат сурай аласыз.

## Байланыш
Маалыматтар боюнча суроолор: телефон {phone}, WhatsApp +{whatsapp}, тиркемедеги «Колдоо» бөлүмү.

Саясат өзгөргөндө жаңы версиясын жарыялайбыз, тиркеме аны кайра кабыл алууну сурайт.""",
}

TERMS = {
    'ru': """Условия программы лояльности BAYTUR

Эти условия описывают правила программы лояльности курорта BAYTUR в мобильном приложении. Регистрируясь, вы принимаете эти условия.

## Участие
- Участником может стать физическое лицо от 16 лет с номером телефона.
- Один номер телефона — один аккаунт. Передавать аккаунт другим лицам нельзя.

## Баллы
- Курс: 1 балл = 1 сом.
- Баллы начисляются за услуги курорта (кешбек) только с части, оплаченной деньгами: базовая ставка — 5 % от суммы, на более высоких уровнях к ней добавляется надбавка. Ставка вашего уровня показывается в приложении до отправки заявки.
- В день рождения и в дни акций кешбек может быть выше — условия показываются в приложении.
- Баллы начисляются после того, как сотрудник курорта подтвердит заявку.
- Баллы не сгорают и не обмениваются на деньги.

## Оплата баллами
- Баллами можно оплатить услугу, если на счёте хватает баллов на всю её стоимость, — частичная оплата баллами не предусмотрена.
- Баллы резервируются при отправке заявки и списываются при подтверждении; при отказе или отмене резерв возвращается.

## Уровни
- Уровни: Бронза, Серебро, Золото, Платина, Титан, Амбассадор. Привилегии каждого уровня показаны в приложении (раздел «Уровни»).
- Уровень зависит от «Нынешних» баллов — баллов, заработанных за текущий календарный год на текущем уровне. Пороги перехода показаны в приложении.
- При переходе на новый уровень «Нынешние» начинаются с нуля. 1 января каждого года «Нынешние» обнуляются.
- Для Титана и Амбассадора, помимо баллов, могут потребоваться задания — они показаны в приложении.

## Подтверждение уровня и постоянный статус
- Уровень нужно подтверждать каждый год: собрать за год не меньше лимита, указанного в приложении. Лимит = собранное на уровне за предыдущий год + 10 000 баллов и со временем только растёт.
- Если уровень не подтверждён, 1 января он понижается на одну ступень. В год получения уровня подтверждать его не нужно.
- Постоянный статус: если у вас достаточно баллов за всё время и лет в программе (условия для каждого уровня — в приложении), уровень присваивается навсегда и больше не понижается.
- Траты баллов на уровень не влияют.

## Изменение и отмена
- Курорт может отменить начисление по ошибочной или отменённой заявке.
- Курорт вправе менять правила, пороги и привилегии программы. Изменения действуют с момента публикации; при изменении этих условий приложение попросит принять новую версию.

## Удаление аккаунта
При удалении аккаунта и по истечении {purge_days} дней на восстановление баллы и уровень аннулируются.

## Контакты
Телефон {phone}, WhatsApp +{whatsapp}, раздел «Поддержка» в приложении.""",

    'en': """BAYTUR loyalty programme terms

These terms set out the rules of the BAYTUR resort loyalty programme in the mobile app. By registering you accept these terms.

## Membership
- Any individual aged 16 or over with a phone number can join.
- One phone number — one account. Accounts may not be transferred to others.

## Points
- Rate: 1 point = 1 KGS.
- Points (cashback) are earned for resort services only on the part paid with money: the base rate is 5% of the amount, and higher tiers add a bonus on top. Your tier's rate is shown in the app before you send a request.
- On your birthday and during promotions cashback may be higher — the conditions are shown in the app.
- Points are credited after a resort employee confirms the request.
- Points do not expire and cannot be exchanged for money.

## Paying with points
- You can pay for a service with points if your balance covers its full price — partial payment with points is not available.
- Points are reserved when you send a request and charged on confirmation; if the request is rejected or cancelled, the reserve is released.

## Tiers
- Tiers: Bronze, Silver, Gold, Platinum, Titanium, Ambassador. Each tier's privileges are shown in the app (Tiers section).
- Your tier depends on your "current" points — points earned in the current calendar year on your current tier. Thresholds are shown in the app.
- When you move up a tier, current points start again from zero. Current points are also reset on 1 January every year.
- Titanium and Ambassador may require achievements in addition to points — they are shown in the app.

## Keeping your tier and permanent status
- A tier must be confirmed every year by collecting at least the limit shown in the app. The limit = points collected on the tier in the previous year + 10,000 points, and it only grows.
- If a tier is not confirmed, it drops by one step on 1 January. No confirmation is needed in the year you reach a tier.
- Permanent status: if you have enough lifetime points and years in the programme (the conditions for each tier are shown in the app), the tier is yours forever and never drops.
- Spending points does not affect your tier.

## Changes and cancellations
- The resort may reverse points credited for an erroneous or cancelled request.
- The resort may change the programme rules, thresholds and privileges. Changes take effect when published; when these terms change, the app will ask you to accept the new version.

## Deleting your account
When you delete your account and the {purge_days}-day restore period ends, your points and tier are cancelled.

## Contacts
Phone {phone}, WhatsApp +{whatsapp}, or the Support section in the app.""",

    'ky': """BAYTUR лоялдуулук программасынын шарттары

Бул шарттар мобилдик тиркемедеги BAYTUR курортунун лоялдуулук программасынын эрежелерин баяндайт. Катталуу менен сиз ушул шарттарды кабыл аласыз.

## Катышуу
- 16 жаштан өткөн, телефон номери бар жеке адам катышуучу боло алат.
- Бир телефон номери — бир аккаунт. Аккаунтту башка адамдарга өткөрүүгө болбойт.

## Упайлар
- Курс: 1 упай = 1 сом.
- Упайлар (кешбек) курорттун кызматтары үчүн акча менен төлөнгөн бөлүгүнөн гана чегерилет: негизги чен — сумманын 5 %, жогорку деңгээлдерде ага кошумча кошулат. Деңгээлиңиздин чени өтүнмө жөнөтүлгөнгө чейин тиркемеде көрсөтүлөт.
- Туулган күнүңүздө жана акция күндөрүндө кешбек жогору болушу мүмкүн — шарттары тиркемеде көрсөтүлөт.
- Упайлар курорттун кызматкери өтүнмөнү ырастагандан кийин чегерилет.
- Упайлар күйбөйт жана акчага алмаштырылбайт.

## Упай менен төлөө
- Эсебиңиздеги упайлар кызматтын толук баасына жетсе, аны упай менен төлөй аласыз — упай менен жарым-жартылай төлөө каралган эмес.
- Өтүнмө жөнөтүлгөндө упайлар резервге коюлат жана ырасталганда чегерилет; баш тартылса же жокко чыгарылса, резерв кайтарылат.

## Деңгээлдер
- Деңгээлдер: Коло, Күмүш, Алтын, Платина, Титан, Амбассадор. Ар бир деңгээлдин артыкчылыктары тиркемеде («Деңгээлдер» бөлүмү) көрсөтүлгөн.
- Деңгээл «Учурдагы» упайларга — учурдагы календардык жылда учурдагы деңгээлде топтолгон упайларга жараша болот. Өтүү босоголору тиркемеде көрсөтүлгөн.
- Жаңы деңгээлге өткөндө «Учурдагы» упайлар нөлдөн башталат. Ар жылы 1-январда «Учурдагы» упайлар нөлгө түшөт.
- Титан жана Амбассадор үчүн упайлардан тышкары тапшырмалар талап кылынышы мүмкүн — алар тиркемеде көрсөтүлгөн.

## Деңгээлди ырастоо жана туруктуу статус
- Деңгээлди ар жылы ырастоо керек: жыл ичинде тиркемеде көрсөтүлгөн лимиттен кем эмес топтоо. Лимит = мурунку жылы деңгээлде топтолгону + 10 000 упай, убакыт өткөн сайын өсөт гана.
- Деңгээл ырасталбаса, 1-январда бир тепкичке төмөндөйт. Деңгээлге жеткен жылы аны ырастоонун кереги жок.
- Туруктуу статус: бардык убакыттагы упайларыңыз жана программадагы жылдарыңыз жетиштүү болсо (ар бир деңгээлдин шарттары тиркемеде), деңгээл түбөлүккө ыйгарылат жана төмөндөбөйт.
- Упайларды коротуу деңгээлге таасир этпейт.

## Өзгөртүү жана жокко чыгаруу
- Курорт ката же жокко чыгарылган өтүнмө боюнча чегерилген упайларды жокко чыгара алат.
- Курорт программанын эрежелерин, босоголорун жана артыкчылыктарын өзгөртүүгө укуктуу. Өзгөртүүлөр жарыяланган учурдан тартып күчүнө кирет; бул шарттар өзгөргөндө тиркеме жаңы версиясын кабыл алууну сурайт.

## Аккаунтту өчүрүү
Аккаунт өчүрүлүп, калыбына келтирүү үчүн берилген {purge_days} күн өткөндөн кийин упайлар жана деңгээл жокко чыгарылат.

## Байланыш
Телефон {phone}, WhatsApp +{whatsapp}, тиркемедеги «Колдоо» бөлүмү.""",
}
