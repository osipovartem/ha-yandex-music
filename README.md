<p align="center">
  <img src="https://raw.githubusercontent.com/osipovartem/ha-yandex-music/main/custom_components/yandex_music/brand/icon@2x.png" width="160" alt="Yandex Music for Home Assistant icon">
</p>

<a id="english"></a>

# Yandex Music for Home Assistant

**English** | [Русский](#russian)

An unofficial HACS integration that plays Yandex Music on a selected Home Assistant media player and manages the track queue.

> This project is not affiliated with or endorsed by Yandex.

## Features

- Media browser with presets, personalized Yandex stations, personal playlists, and liked tracks
- Delegated playback on any Home Assistant player that accepts HTTP music URLs
- Automatic station queue refill
- Continuous looping for personal playlists and liked tracks
- Play, pause, stop, seek, shuffle, next, and previous controls
- Default source (station, liked tracks, or personal playlist) for simple play/turn-on commands
- Alice voice control through the [Yandex Smart Home](https://github.com/dext0r/yandex_smart_home) integration
- Immediate proxy shutdown when playback is stopped or the target player is turned off

## Requirements

- Home Assistant 2023.1 or newer
- A Yandex Music account and OAuth token
- A target `media_player` reachable from Home Assistant
- Home Assistant 2026.3 or newer to display the bundled local integration icon

## Installation with HACS

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Add `https://github.com/osipovartem/ha-yandex-music` as an **Integration** repository.
4. Find **Yandex Music**, install it, and restart Home Assistant.

### Manual installation

Copy `custom_components/yandex_music/` to `/config/custom_components/yandex_music/` and restart Home Assistant.

## Getting a token

The token gives the integration access to your Yandex Music library. Treat it like a password: do not commit it or paste it into an issue.

1. Sign in at [passport.yandex.ru](https://passport.yandex.ru).
2. Open this OAuth authorization URL:

   ```text
   https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
   ```

3. Approve access.
4. Copy the value of `access_token` from the redirected URL.

## Configuration

No YAML is required for basic playback. Configure the integration in the Home Assistant UI:

1. Open **Settings → Devices & services → Add integration → Yandex Music**.
2. Enter the token.
3. Open **Configure** for the installed integration and set:
   - **Target media player** — the speaker or receiver that will play the stream.
   - **Default source** — a preset or personalized station, liked tracks, or personal playlist started by Play, Turn on, or Alice's “turn on music” command.

The integration creates a virtual entity such as `media_player.yandex_music`. Send commands to this virtual entity; it delegates audio to the configured target player.

The source list is loaded from the connected Yandex Music account. Changing the default source saves the new choice but does not start it immediately; it is used by the next Play or Turn on command.

To keep the main settings screen compact, select **Choose personal playlist →** and press **Next**. A second screen opens a dropdown containing only your playlists. Personal playlists and liked tracks loop from the beginning after their last track; with shuffle enabled, they are reshuffled before each new pass.

## Usage

### Media browser

Open **Browse media** on the Yandex Music entity. Available sources include:

- My Wave (`station:onyourwave`)
- Calm (`station:calm`)
- Instrumental (`station:wordless`)
- Energetic (`station:energetic`)
- Personalized stations recommended for the connected account
- Personal playlists
- Liked tracks

### Play a station

```yaml
action: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: station
  media_content_id: "station:calm"
```

Other supported IDs:

```yaml
# Personal playlist (uid:kind)
media_content_id: "playlist:123456:3"

# Liked tracks
media_content_id: "liked:tracks"

# A raw Yandex Music station ID
media_content_id: "station_id:user:onyourwave"
```

### Playback controls

```yaml
# Stop playback and close the active proxy stream
action: media_player.media_stop
target:
  entity_id: media_player.yandex_music

# Next track
action: media_player.media_next_track
target:
  entity_id: media_player.yandex_music

# Previous track
action: media_player.media_previous_track
target:
  entity_id: media_player.yandex_music
```

Turning off the virtual player also stops playback, but does not power down the physical target speaker.

## Alice voice control

Expose the virtual Yandex Music entity through Yandex Smart Home. Its next/previous and on/off features are advertised by the entity itself. If you configure features explicitly, use:

```yaml
yandex_smart_home:
  entity_config:
    media_player.yandex_music:
      name: Яндекс музыка
      features:
        - turn_on_off
        - play_pause
        - next_previous_track
        - play_media
      support_set_channel: false
```

After changing the configuration, restart Home Assistant and update the device list in the Yandex smart-home app. Example phrases (the exact wording can depend on the room and entity name):

- “Алиса, включи Яндекс музыку”
- “Алиса, выключи Яндекс музыку”
- “Алиса, следующий трек на Яндекс музыке”
- “Алиса, предыдущий трек на Яндекс музыке”

## Troubleshooting

- The target player must accept `media_player.play_media` with an HTTP URL. For some receivers, a DLNA DMR entity works better than a vendor-specific entity.
- The target device must be able to reach Home Assistant's internal URL and port.
- If an external stop is reported as `idle` before the expected end of the track, the integration treats it as a stop and closes the proxy. Near the natural end of a track, `idle` advances the queue.
- Stream URLs use short-lived random session tokens. Stopping or changing tracks immediately invalidates the previous URL.

## Issues and security

Bug reports and feature requests are welcome in [GitHub Issues](https://github.com/osipovartem/ha-yandex-music/issues). Remove tokens, private URLs, and personal data from logs before posting. For a security problem, follow [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)

---

<a id="russian"></a>

# Yandex Music для Home Assistant

[English](#english) | **Русский**

Неофициальная HACS-интеграция для воспроизведения Яндекс Музыки на выбранном медиаплеере Home Assistant с управлением очередью треков.

> Проект не связан с Яндексом и не поддерживается им официально.

## Возможности

- Браузер медиа: пресеты, персональные станции Яндекса, личные плейлисты и понравившиеся треки
- Воспроизведение на любом медиаплеере Home Assistant, принимающем HTTP-ссылки
- Автоматическое пополнение очереди станции
- Непрерывное зацикливание личных плейлистов и понравившихся треков
- Play, pause, stop, seek, shuffle, следующий и предыдущий трек
- Источник по умолчанию: станция, понравившиеся треки или личный плейлист
- Голосовое управление через Алису и [Yandex Smart Home](https://github.com/dext0r/yandex_smart_home)
- Немедленная остановка прокси-потока при остановке музыки или выключении целевого плеера

## Требования

- Home Assistant 2023.1 или новее
- Аккаунт Яндекс Музыки и OAuth-токен
- Целевой `media_player`, доступный из Home Assistant
- Home Assistant 2026.3 или новее для отображения встроенной локальной иконки

## Установка через HACS

1. Откройте **HACS → Интеграции**.
2. В меню с тремя точками выберите **Пользовательские репозитории**.
3. Добавьте `https://github.com/osipovartem/ha-yandex-music` с типом **Интеграция**.
4. Найдите **Yandex Music**, установите и перезапустите Home Assistant.

### Ручная установка

Скопируйте `custom_components/yandex_music/` в `/config/custom_components/yandex_music/` и перезапустите Home Assistant.

## Получение токена

Токен предоставляет интеграции доступ к вашей медиатеке. Обращайтесь с ним как с паролем: не коммитьте его и не публикуйте в issue.

1. Войдите в аккаунт на [passport.yandex.ru](https://passport.yandex.ru).
2. Откройте ссылку авторизации:

   ```text
   https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d
   ```

3. Разрешите доступ.
4. Скопируйте значение `access_token` из адресной строки после перенаправления.

## Настройка

Для базового воспроизведения YAML не нужен. Настройте интеграцию через интерфейс Home Assistant:

1. Откройте **Настройки → Устройства и службы → Добавить интеграцию → Yandex Music**.
2. Введите токен.
3. Откройте **Настройки** установленной интеграции и задайте:
   - **Медиаплеер для воспроизведения** — колонку или ресивер, куда будет отправлен поток.
   - **Источник по умолчанию** — пресет или персональная станция, понравившиеся треки либо личный плейлист для кнопки Play, команды включения или фразы Алисы «включи музыку».

Интеграция создаёт виртуальную сущность, например `media_player.yandex_music`. Все команды нужно отправлять ей — музыку она передаст выбранному целевому плееру.

Список источников загружается из подключённого аккаунта Яндекс Музыки. Изменение источника сохраняет новый выбор, но не запускает его сразу: он включится следующей командой Play или Turn on.

Чтобы основной экран настроек оставался компактным, выберите **Выбрать личный плейлист →** и нажмите **Далее**. На втором экране откроется выпадающий список только с плейлистами. После последнего трека личный плейлист или список «Мне нравится» начинается сначала; при включённом shuffle очередь перемешивается перед каждым новым кругом.

## Использование

### Браузер медиа

Нажмите **Обзор медиа** у сущности Yandex Music. Доступны:

- Моя волна (`station:onyourwave`)
- Спокойное (`station:calm`)
- Без слов (`station:wordless`)
- Энергичное (`station:energetic`)
- Персональные станции, рекомендованные для подключённого аккаунта
- Личные плейлисты
- Понравившиеся треки

### Запуск станции

```yaml
action: media_player.play_media
target:
  entity_id: media_player.yandex_music
data:
  media_content_type: station
  media_content_id: "station:calm"
```

Другие поддерживаемые идентификаторы:

```yaml
# Личный плейлист (uid:kind)
media_content_id: "playlist:123456:3"

# Любимые треки
media_content_id: "liked:tracks"

# Прямой ID станции Яндекс Музыки
media_content_id: "station_id:user:onyourwave"
```

### Управление воспроизведением

```yaml
# Остановить музыку и закрыть активный прокси-поток
action: media_player.media_stop
target:
  entity_id: media_player.yandex_music

# Следующий трек
action: media_player.media_next_track
target:
  entity_id: media_player.yandex_music

# Предыдущий трек
action: media_player.media_previous_track
target:
  entity_id: media_player.yandex_music
```

Выключение виртуального плеера также останавливает музыку, но не отключает питание физической колонки.

## Голосовое управление через Алису

Передайте виртуальную сущность Yandex Music в Yandex Smart Home. Она сама объявляет поддержку следующего/предыдущего трека и включения/выключения. Если список функций задан явно, используйте:

```yaml
yandex_smart_home:
  entity_config:
    media_player.yandex_music:
      name: Яндекс музыка
      features:
        - turn_on_off
        - play_pause
        - next_previous_track
        - play_media
      support_set_channel: false
```

После изменения конфигурации перезапустите Home Assistant и обновите список устройств в приложении Умного дома Яндекса. Примеры фраз (точная форма зависит от комнаты и имени сущности):

- «Алиса, включи Яндекс музыку»
- «Алиса, выключи Яндекс музыку»
- «Алиса, следующий трек на Яндекс музыке»
- «Алиса, предыдущий трек на Яндекс музыке»

## Если что-то не работает

- Целевой плеер должен принимать `media_player.play_media` с HTTP-ссылкой. Для некоторых ресиверов сущность DLNA DMR работает лучше фирменной интеграции.
- Устройство должно открывать внутренний адрес и порт Home Assistant.
- Если целевой плеер сообщает `idle` заметно раньше конца трека, интеграция считает это ручной остановкой и закрывает поток. Возле естественного конца трека `idle` переключает очередь дальше.
- В ссылках потока используются короткоживущие случайные сессионные токены. Остановка или смена трека сразу делает старую ссылку недействительной.

## Issues и безопасность

Ошибки и предложения можно публиковать в [GitHub Issues](https://github.com/osipovartem/ha-yandex-music/issues). Перед публикацией удалите из логов токены, приватные адреса и личные данные. Для уязвимостей следуйте [SECURITY.md](SECURITY.md).

## Лицензия

[MIT](LICENSE)
