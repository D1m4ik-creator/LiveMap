# Выпуск и эксплуатация LiveMap

## Бесплатный демонстрационный стенд: Render + Supabase

Адрес: **https://livemap-demo.onrender.com/**. Render service: `srv-dau2l6nlk1mc73dende0`, Frankfurt, Free. Репозиторий подключён через публичный URL без GitHub OAuth: [автоматические deploy в этом режиме не поддерживаются](https://render.com/docs/deploys). После нового push используйте Render MCP `trigger_deploy` или Manual Deploy в Dashboard. Blueprint описывает readiness path, но Direct Creation MCP не передаёт healthCheckPath: текущий Render healthcheck проверяет корень сайта. Отдельно проверяйте `/api/v1/health/ready`; этот путь можно назначить в Settings сервиса.

Используется один [Render Free Web Service](https://render.com/docs/free) из `render.yaml` и [Supabase Postgres с PostGIS](https://supabase.com/docs/guides/database/extensions/postgis). Python-сервис собирает React через `scripts/render-build.sh`, применяет миграции и запускает API через `scripts/render-start.sh`. `Dockerfile.render` остаётся альтернативой контейнерного запуска. На Render Free сервис засыпает после 15 минут без запросов: встроенный worker работает только пока процесс активен. Supabase Free также может приостанавливать неактивные проекты. Стенд предназначен для приёмки; круглосуточная работа не гарантируется.

Подключение базы:

1. Создайте проект Supabase Free. Возьмите hostname из **Connect → Direct → Session pooler**, порт **5432**, базу `postgres`. Session pooler нужен для IPv4-сети Render; transaction pooler 6543 не используется с prepared statements asyncpg.
2. Администратор устанавливает PostGIS в `extensions`. Создайте роли `livemap_owner` и `livemap_app` с разными случайными паролями, без SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS. Предоставьте роль `livemap_owner` пользователю `postgres` и создайте схему `livemap AUTHORIZATION livemap_owner`. Выдайте `livemap_app` только USAGE схемы и DML таблиц через `ALTER DEFAULT PRIVILEGES FOR ROLE livemap_owner IN SCHEMA livemap`. Обеим ролям нужен USAGE `extensions`. Исключите `livemap` из exposed schemas Data API.
3. Задайте `DATABASE_SCHEMA=livemap`, `POSTGRES_USER=livemap_app.<ref>`, `POSTGRES_PASSWORD`, `POSTGRES_MIGRATION_USER=livemap_owner.<ref>`, `POSTGRES_MIGRATION_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_DB=postgres`, `POSTGRES_PORT=5432`, `POSTGRES_SSL=true`. Пароли хранятся в Render Environment и игнорируемом Git файле `.env.supabase`.
4. Для TLS задайте `POSTGRES_SSL_CA_FILE=deploy/certs/supabase-prod-ca-2021.crt`, `POSTGRES_SSL_LEGACY_CA=true`. Публичный сертификат скачан по ссылке из Database Settings Supabase. CA 2021 не содержит keyUsage; режим совместимости снимает только VERIFY_X509_STRICT Python 3.13. Проверки цепочки, срока и hostname остаются включёнными. SHA256 файла: `700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`.
5. Примените `alembic upgrade head` с ролью владельца. Затем выполните `deploy/supabase-access.sql` как администратор: закрываются права anon/authenticated, включается RLS с доступом только роли backend. Runtime не может менять таблицы или версию миграций. Start script удаляет пароли миграций из окружения процесса API.

Сборка и проверка:

1. Создайте Render Python Web Service Free из ветки `codex/livemap-foundation`: build `sh scripts/render-build.sh`, start `sh scripts/render-start.sh`. Версии Python/Node/uv и остальные настройки находятся в `render.yaml`; создание поддерживается Render MCP. `VITE_MAPTILER_KEY` задаётся до сборки при наличии.
2. Дождитесь успешной сборки, миграций и `/api/v1/health/ready`. `PUBLIC_ORIGIN` берётся из `RENDER_EXTERNAL_URL`. Проверьте MapTiler-ограничения по итоговому адресу.
3. Для административных команд загрузите `.env.supabase` в окружение терминала и задайте `PUBLIC_ORIGIN` равным адресу Render. Выполните `livemap-admin create-user ИМЯ --role admin`, `livemap-seed-candidates`, затем `livemap-seed-verified`. Публикация требует свежей браузерной проверки и live probe.
4. Проверьте карту, вход, реальный эфир и мобильный экран по HTTPS. Создайте зашифрованную копию каталога и проверьте восстановление в отдельной PostGIS-базе, как описано ниже. Не полагайтесь на автоматические backups Free-тарифа.

Текущий проект Supabase: `jpjynmxezjnzcdnrumxr`, Frankfurt, организация D1m4ik-creator's Org. Session pooler: `aws-1-eu-central-1.pooler.supabase.com`. API сохраняет собственную авторизацию LiveMap; ключи Supabase и доступ к базе во фронтенд не передаются. Для постоянного сервиса нужны процесс без сна, внешние оповещения и регулярные проверяемые резервные копии.

## Развёртывание Compose на собственном сервере

Если появится сервер, установите Docker Engine и Compose, откройте TCP 80/443 в firewall, клонируйте репозиторий. Укажите в `.env` длинный пароль БД, `SITE_ADDRESS=домен`, `PUBLIC_ORIGIN=https://домен`, `HTTP_PORT=80`, `HTTPS_PORT=443`. Порт БД в Compose привязан к `127.0.0.1`; не открывайте 5432 в firewall. `VITE_MAPTILER_KEY` встраивается в браузерную сборку и должен быть ограничен доменом.

Выпуск на собственном сервере:

```bash
cp .env.example .env
# Отредактировать .env; задать SITE_ADDRESS, PUBLIC_ORIGIN, HTTP_PORT, HTTPS_PORT.
docker compose up -d db
docker compose --profile app build
docker compose run --rm api alembic upgrade head
docker compose --profile app up -d
docker compose --profile app ps
curl -fsS https://домен/api/v1/health/ready
```

Первого администратора создайте из терминала сервера: `docker compose run --rm api livemap-admin create-user USERNAME --role admin`. Пароль задаётся интерактивно. Если потоки уже одобрены, запустите `docker compose run --rm api livemap-seed-verified` и проверьте фактические эфиры с публичного адреса до открытия каталога.

## Наблюдение

`/api/v1/health/live` проверяет процесс, `/api/v1/health/ready` проверяет БД. Контейнер API использует readiness healthcheck; worker перезапускается при падении. API пишет JSON-события с кодом ответа и временем выполнения без query string и токенов. Worker пишет отдельные события `camera_check` с кодом ошибки, длительностью и ID камеры. Внутренний `/internal/metrics` содержит счётчик и гистограмму HTTP-запросов в формате Prometheus; Caddy не публикует этот путь. Административный `/api/v1/admin/operations` показывает количество опубликованных, недоступных и давно не проверявшихся камер, обращения пользователей и возраст последней проверки. Для внешнего алерта настройте проверку `/api/v1/health/ready` и оповещение о недоступности, скачке 5xx и `worker_stale=true`.

## Резервные копии и откат

### Supabase: зашифрованный экспорт

Для облачной базы используйте PostgreSQL 17+ и `age`. Создайте recovery identity
через `age-keygen -o PRIVATE_KEY_FILE` вне репозитория и сохраните её отдельно
от архивов с доступом только владельца. В Git и в настройки CI передаётся
только публичный recipient; пароль базы и private identity нельзя помещать
в команды, логи или артефакты workflow.

```bash
uv run python scripts/cloud_backup.py backup --env-file .env.supabase \
  --pg-bin /usr/bin --recipient PUBLIC_AGE_RECIPIENT --output backups
# .env.restore содержит только доступ к локальному тестовому PostGIS
uv run python scripts/cloud_backup.py verify --env-file .env.restore \
  --pg-bin /usr/bin --identity PRIVATE_KEY_FILE --archive backups/ИМЯ.dump.age
```

`pg_dump` через текущий Session pooler обрывается на `SET extra_float_digits`.
Для этого стенда используется `scripts/catalog_backup.py`: обычное SQL-соединение,
транзакция REPEATABLE READ READ ONLY, все девять таблиц приложения и точная
ревизия Alembic. Геометрия сохраняется как EWKB. Записи сразу передаются в age,
без незашифрованного экспортного файла. Контрольная сумма и число строк проверяются
при восстановлении. Неожиданные таблицы блокируют экспорт, чтобы новые данные
не потерялись незаметно. 03.10.2026 настоящая копия Supabase восстановлена в
одноразовой локальной PostGIS-базе: все строки, геометрия и последовательности
проверены. Устаревшие сессии при реальном аварийном восстановлении нужно отозвать.

```bash
uv run python scripts/catalog_backup.py backup --env-file .env.backup \
  --recipient PUBLIC_AGE_RECIPIENT --output backups
uv run python scripts/catalog_backup.py verify --env-file LOCAL_RESTORE_ENV \
  --identity PRIVATE_KEY_FILE --archive backups/ИМЯ.catalog.age
```

Это копия данных приложения. Supabase Auth, Storage, настройки проекта, роли
Postgres и определения расширений в неё не входят. Для восстановления нужны
исходники соответствующего выпуска с Alembic и PostGIS. Права runtime восстанавливаются
отдельно через `deploy/supabase-access.sql`; роль чтения backup описана в
`deploy/supabase-backup.sql`. Она не может изменять данные, создавать объекты
или обходить RLS. Новые RLS-таблицы требуют отдельной политики чтения.

Workflow `.github/workflows/backup.yml` создаёт копию ежедневно в 05:43 по Москве.
Архивы age хранятся в GitHub Actions Artifacts 30 дней, отдельно от Render и
Supabase. GitHub Secret `LIVEMAP_BACKUP_DB_PASSWORD` содержит только пароль
роли чтения, variable `LIVEMAP_BACKUP_RECIPIENT` — публичный ключ шифрования.
Приватный ключ не передаётся в CI. На этом устройстве он сохранён в
`backups/recovery-key.txt`, каталог исключён из Git. Сохраните независимую копию
ключа: потеря ключа делает архивы невосстановимыми. Данные администратора
в публичных артефактах присутствуют только в зашифрованном архиве.
Расписание начинает работать после размещения workflow в default branch;
checkout внутри workflow использует ветку выпущенного приложения.

### Внешняя проверка стенда

Запустите `python scripts/check_public_service.py --output backups/monitor-result.json`.
Проверяются readiness, публичная карта и агрегат `/api/v1/health/cameras`.
Workflow `.github/workflows/monitor.yml` проверяет стенд раз в шесть часов
(03:17, 09:17, 15:17, 21:17 по Москве), учитывая пробуждение Render Free.
Артефакты за 14 дней содержат число online/published/stale камер и время ответа
readiness, сводки камер и карты. При сбое создаётся GitHub Issue, повторный сбой
не создаёт дубликаты; успешная проверка закрывает инцидент с ссылкой на запуск.
Сбой создания или загрузки backup вызывает отдельный Issue. Это канал оповещений
в репозитории; личные email/push зависят от ваших GitHub notification settings.
Расписание GitHub исполняется только из default branch. В рабочей ветке
проверка также запускается при изменении эксплуатационных файлов.
Это наблюдение за демостендом, не гарантия круглосуточной доступности.

На собственном сервере запускайте `bash scripts/backup.sh` по расписанию, копируйте архивы за пределы сервера и ограничьте доступ к ним. Проверяйте восстановление через `bash scripts/verify-backup.sh backups/ИМЯ.dump`: скрипт создаёт отдельную временную БД, восстанавливает архив и удаляет её. Проверка не заменяет регулярную проверку данных приложения после восстановления.

Перед обновлением сделайте backup. Для отката приложения вернитесь к предыдущему коммиту и пересоберите контейнеры. Если новая миграция меняла данные, сначала остановите API/worker, сохраните текущую БД и восстановите проверенный архив в отдельной среде; не выполняйте `alembic downgrade` на рабочей базе без оценки потерь данных. После восстановления снова проверьте `health/ready`, карту, поиск, вход администратора и публикацию камеры.

## Приёмка публичного адреса

Откройте HTTPS-адрес с другого устройства и проверьте карту, поиск, карточку, работающий эфир, недоступный эфир и мобильную ширину. В админке создайте место и источник, подтвердите права, опубликуйте камеру, затем снимите её с публикации и убедитесь, что она исчезла из публичной выдачи. Повторите в Chromium, Firefox и Safari. Проверьте ограничения MapTiler по домену, тариф и бюджет в Analytics перед постоянной публикацией. Результаты проверки и дату внесите в Kanban-доску.
