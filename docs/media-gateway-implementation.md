# RTSP → HLS: реализация и проверка

03.10.2026 добавлены launcher, контейнер, отдельный Compose и локальная проверка.
MediaMTX **1.21.1**, Linux amd64 архив проверяется по SHA256 при сборке.
Публичная RTSP-камера пока не подключена: стандартный RTSP-адрес существующей
камеры Telecoma вернул `403 Denied`. Учётные данные не подбирались.

| Компонент | Файл / назначение |
| --- | --- |
| Launcher | `deploy/media/gateway.py`: фиксированный путь `camera1`, приватный upstream из окружения. |
| Container | `deploy/media/Dockerfile`: непривилегированный процесс без зависимостей приложения и БД. |
| HTTPS | `deploy/media/compose.yaml`, `Caddyfile`: сертификат для домена шлюза, только `/camera1/*`. |
| Catalog | `MEDIA_GATEWAY_PUBLIC_BASE`: допускает ровно `<base>/camera1/index.m3u8` с `secret_ref=LIVEMAP_RTSP_UPSTREAM`. |
| Protocol check | `scripts/check_media_gateway.py`: FFmpeg генерирует тестовую таблицу и публикует по локальному RTSP. Это не настоящая камера каталога. |

## Границы доступа

- RTSP URL/пароль остаются в окружении отдельного шлюза. `Source.stream_url`
  содержит только HTTPS HLS; `Source.secret_ref` — имя настройки, не её значение.
  Публичный API не возвращает ссылку на секрет.
- Требуется точный `LIVEMAP_RTSP_ALLOWED_HOST`. Все DNS-ответы проверяются на
  публичность, один IP закрепляется. `--local-test` допускает loopback upstream,
  но тогда HLS слушает только loopback. Начальный upstream — RTSP/TCP без TLS;
  RTSPS ещё не реализован.
- API, метрики, pprof, запись, RTSP listener, RTMP, WebRTC, SRT и MoQ выключены.
  Разрешено только чтение `camera1`; нет публикации, wildcard paths и произвольных URL.
- On-demand запуск/остановка; ограничены сегменты и очередь; один CORS origin.
  Launcher маскирует URL и доступы в логах. Конфигурация временная, на Linux — 0600.
  Входящие `MTX_*` overrides удаляются, чтобы ими нельзя было открыть интерфейсы.
- Compose задаёт 1 CPU, 512 MiB, read-only filesystem, отдельную сеть без БД,
  `cap_drop: ALL`, `no-new-privileges`. Docker на текущем устройстве не позволил
  проверить исполнение этих ограничений; протокол проверен native binary.
- DNS pinning **не заменяет firewall**. На целевом сервере нужно разрешить исходящие
  соединения только к IP/RTSP-порту оператора: это ограничивает также redirects/SDP.
  Настройка firewall остаётся незавершённым критерием C09.

## Запуск после получения рабочего источника

Создать приватный `.env.media` вне Git:

```dotenv
LIVEMAP_RTSP_UPSTREAM=rtsp://USER:PASSWORD@camera.operator.example/live
LIVEMAP_RTSP_ALLOWED_HOST=camera.operator.example
PUBLIC_ORIGIN=https://livemap-demo.onrender.com
MEDIA_DOMAIN=media.your-domain.example
```

```sh
docker compose --env-file .env.media -f deploy/media/compose.yaml up --build -d
```

Это домены-заглушки. Нужны реальный домен, сервер с 80/443, egress firewall,
рабочий upstream и условия публичного показа. На API задать
`MEDIA_GATEWAY_PUBLIC_BASE=https://media.your-domain.example`; через админку сохранить
публичный HLS URL с указанным `secret_ref`. Проверить права, worker и настоящие кадры,
после чего опубликовать камеру типа HLS. Прямой `rtsp://` остаётся запрещённым.

При отзыве разрешения снять камеру с публикации **и остановить шлюз**:
снятие маркера само по себе не закрывает публичный HLS endpoint.
При смене IP оператора повторить проверку, обновить firewall и перезапустить процесс.
Для H265/несовместимого аудио понадобится отдельный транскодер; автоматического
перекодирования здесь нет. Render Free не предоставляет постоянный медиасервис.

## Локальная приёмка

```sh
python scripts/check_media_gateway.py --mediamtx /path/to/mediamtx \
  --ffmpeg /path/to/ffmpeg --report backups/media-acceptance.json
```

Проверены RTSP/TCP → H264/fMP4 HLS, master/media playlist, сегмент, точный CORS,
отсутствие CORS для чужого origin, 20 параллельных запросов сегмента,
восстановление после остановки/перезапуска upstream и его остановка после ухода читателей.
Chromium/Firefox воспроизвели тестовую таблицу 640×360 через `CameraPlayer`: время выросло
более чем на 8 секунд. HTTPS URL/API временно подменены только в тестовом браузере;
это не проверка публичного TLS шлюза.

Тесты проверяют привязку секрета к настроенному HTTPS пути: другой host/path/query,
произвольный ключ и iframe блокируются. Ненастроенный gateway не публикует источник.
Остаются настоящая RTSP-камера, облачный endpoint/firewall, длительная проверка
20 видеоплеерами и задержка/ресурсы на целевом сервере. Safari/macOS исключены владельцем.

Основания: [конфигурация MediaMTX](https://mediamtx.org/docs/references/configuration-file),
[браузерное воспроизведение](https://mediamtx.org/docs/read/web-browsers),
[RTSP playback Flussonic](https://flussonic.com/doc/fms/play/).
