# Yandex Music для Home Assistant

HACS-интеграция, которая добавляет Яндекс Музыку в Home Assistant как источник медиа с управлением очередью треков.

## Возможности

- Браузер медиа: плейлисты, станции по настроению, любимые треки
- Режимы воспроизведения: Спокойное, Без слов (инструментал), Энергичное, Моя волна
- Управление очередью: автоматическая загрузка следующих треков со станции
- Делегирование воспроизведения на любой медиаплеер в HA (Chromecast, Sonos, Яндекс Станция и др.)
- Интеграция с автоматизациями HA и голосовыми командами Алисы

---

## Установка через HACS

1. Откройте HACS → **Интеграции** → меню (три точки) → **Пользовательские репозитории**
2. Добавьте репозиторий: `https://github.com/osipovartem/ha-yandex-music`
3. Тип: **Интеграция**
4. Найдите **Yandex Music** в HACS и установите
5. Перезапустите Home Assistant

## Установка вручную

Скопируйте папку `custom_components/yandex_music/` в директорию `/config/custom_components/` вашего Home Assistant, затем перезапустите.

---

## Получение токена

Токен — это строка авторизации, которая позволяет компоненту получать доступ к вашей библиотеке Яндекс Музыки.

### Способ 1: через браузер (рекомендуется)

1. Откройте браузер и войдите в [passport.yandex.ru](https://passport.yandex.ru)
2. Перейдите по ссылке:
   ```
   https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
   ```
3. Нажмите **Разрешить**
4. Скопируйте токен из адресной строки (параметр `access_token=...`)

### Способ 2: через Python

```python
from yandex_music import Client
# Если у вас есть токен напрямую от Яндекс.Паспорта, используйте его
client = Client("ВАШ_ТОКЕН").init()
print(client.account_status().account.login)
```

---

## Настройка

1. Перейдите: **Настройки → Устройства и службы → Добавить интеграцию → Yandex Music**
2. Введите токен
3. После добавления перейдите в **Настройки** интеграции и укажите:
   - **Медиаплеер для воспроизведения** — устройство, на которое будет отправляться музыка
   - **Станция по умолчанию** — музыка, которая будет играть при команде «включи музыку»

---

## Использование

### Медиа браузер

В карточке медиаплеера нажмите **Обзор медиа**. Вы увидите:

```
Yandex Music
├── Станции и настроение
│   ├── Моя волна
│   ├── Спокойное
│   ├── Без слов
│   └── Энергичное
├── Мои плейлисты
│   └── ...
└── Мне нравится
```

### Сервис play_media в автоматизациях

```yaml
service: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: station
  media_content_id: "station:calm"        # Спокойное
  # media_content_id: "station:wordless"  # Без слов
  # media_content_id: "station:energetic" # Энергичное
  # media_content_id: "station:onyourwave" # Моя волна
```

### Плейлист по ID

```yaml
media_content_id: "playlist:123456:3"    # uid:kind
```

### Любимые треки

```yaml
media_content_id: "liked:tracks"
```

---

## Автоматизация с Алисой

Для запуска музыки голосовой командой через Алису:

```yaml
automation:
  - alias: "Алиса: Включи спокойную музыку"
    trigger:
      - platform: state
        entity_id: input_text.alice_command   # или другой триггер от Алисы
        to: "включи спокойную музыку"
    action:
      - service: media_player.play_media
        target:
          entity_id: media_player.yandex_music
        data:
          media_content_type: station
          media_content_id: "station:calm"
```

> Подробнее о настройке интеграции с Алисой через [YandexSmartHome](https://github.com/dmitry-k/yandex_smart_home) или Webhook.

---

## Лицензия

MIT License. Это неофициальный компонент, не связанный с Яндексом.
