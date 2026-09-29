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
4. Проверьте карту, вход, реальный эфир и мобильный экран по HTTPS. Сделайте `pg_dump --schema=livemap` через Session pooler с ролью владельца и проверьте восстановление в отдельной PostGIS-базе. Не полагайтесь на автоматические backups Free-тарифа.

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

На собственном сервере запускайте `bash scripts/backup.sh` по расписанию, копируйте архивы за пределы сервера и ограничьте доступ к ним. Проверяйте восстановление через `bash scripts/verify-backup.sh backups/ИМЯ.dump`: скрипт создаёт отдельную временную БД, восстанавливает архив и удаляет её. Проверка не заменяет регулярную проверку данных приложения после восстановления.

Перед обновлением сделайте backup. Для отката приложения вернитесь к предыдущему коммиту и пересоберите контейнеры. Если новая миграция меняла данные, сначала остановите API/worker, сохраните текущую БД и восстановите проверенный архив в отдельной среде; не выполняйте `alembic downgrade` на рабочей базе без оценки потерь данных. После восстановления снова проверьте `health/ready`, карту, поиск, вход администратора и публикацию камеры.

## Приёмка публичного адреса

Откройте HTTPS-адрес с другого устройства и проверьте карту, поиск, карточку, работающий эфир, недоступный эфир и мобильную ширину. В админке создайте место и источник, подтвердите права, опубликуйте камеру, затем снимите её с публикации и убедитесь, что она исчезла из публичной выдачи. Повторите в Chromium, Firefox и Safari. Проверьте ограничения MapTiler по домену, тариф и бюджет в Analytics перед постоянной публикацией. Результаты проверки и дату внесите в Kanban-доску.
