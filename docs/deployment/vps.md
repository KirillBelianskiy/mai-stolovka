# Альтернативное развёртывание MAI Stolovka на Linux VPS

[Mini App в Telegram](https://t.me/mai_stolovka_bot/maistolovka) уже привязано к `https://maistolovka.me`. Эта схема переносит интерфейс и API на Linux VPS. Для схемы с Cloudflare Pages и локальным API на Mac см. [Cloudflare Tunnel](cloudflare-tunnel.md). Caddy принимает HTTPS на том же домене и передаёт запросы к интерфейсу и API в Docker Compose. Ссылка в Telegram остаётся прежней.

Понадобятся SSH-доступ к VPS, доступ к DNS домена в Cloudflare и токен именно `@mai_stolovka_bot` из BotFather. На сервере установите Git, Python 3.12, OpenSSL, Docker Engine с Compose v2 и [Caddy](https://caddyserver.com/docs/install). Откройте входящие TCP 80 и 443 для HTTPS и сохраните доступ по SSH. Команды ниже рассчитаны на новый сервер или отдельный каталог с новым набором томов. Для переноса уже существующей рабочей базы нужен отдельный бэкап и план миграции.

## 1. Запустить сборку на VPS

```sh
git clone --branch codex/ui-completeness https://github.com/KirillBelianskiy/mai-stolovka.git mai-stolovka
cd mai-stolovka
git checkout --detach 585f6147dc2c6fca6301d6e6339afd10f4991944
python3 infra/create-local-env.py
python3 infra/create-auth-env.py
nano .env
```

В `.env` укажите настоящий `TELEGRAM_BOT_TOKEN` и установите `ORDER_DEMO_PAYMENTS_ENABLED=true` для демонстрационного кошелька. Сохраните созданные сервером пароли и JWT-ключи в защищённой резервной копии. Токен вводите на сервере в редакторе. Для повторных запусков используйте тот же `.env`. Локальный `infra/local-demo.py up` рассчитан на синтетический токен и здесь не применяется.

В корне клона создайте `compose.override.yml`. Docker Compose подхватит этот файл автоматически.

```yaml
services:
  user-service:
    environment:
      APP_SESSION_COOKIE_ALLOWED_ORIGINS: https://maistolovka.me
```

Запустите сервисы и выполните миграции. При ошибке на любом шаге разберите её перед продолжением.

```sh
docker compose config --quiet &&
docker compose up -d --build --wait --wait-timeout 300 &&
docker compose up -d --no-deps --force-recreate --wait proxy
```

```sh
for service in user-service menu-service order-service notification-service; do
  docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic \
    "$service" upgrade head || break
done
```

После четырёх успешных миграций создайте тему Kafka и запустите обработчики событий пилотной сборки.

```sh
python3 infra/kafka-topic.py --create-dev &&
docker compose --profile inbox --profile outbox up -d --build notification-inbox outbox-worker &&
curl -fsS http://127.0.0.1:8080/api/v1/menu/items
```

На пустой базе последний запрос должен вернуть JSON с пустым меню. Штатные порты приложения, PostgreSQL и Kafka привязаны к `127.0.0.1`. Текущая сборка сохраняет события уведомлений. Отправка уведомлений в Telegram остаётся отдельной задачей.

## 2. Подготовить меню, слоты и аккаунт

Создайте администратора. Пароль вводится интерактивно.

```sh
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/python user-service \
  -m user_service.cli provision-staff --username cafeteria.admin --full-name "Администратор столовой" --role ADMIN
```

Для заполнения демонстрационного меню запустите на VPS этот блок. Он создаёт шесть блюд с HTTPS-адресами фотографий и использует существующий загрузчик каталога из сборки. Запросы к API идут через локальный порт.

```sh
PYTHONPATH=infra python3 - <<'PY'
from getpass import getpass
import json
from urllib.request import Request, urlopen
from local_demo_menu import seed_menu

def request(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = Request("http://127.0.0.1:8080" + path, data=data, headers=headers, method=method)
    with urlopen(req, timeout=30) as response:
        return json.load(response)

admin = request("POST", "/api/v1/users/auth/staff", {
    "username": "cafeteria.admin",
    "password": getpass("Пароль администратора: "),
})
items = seed_menu(request, "https://maistolovka.me", admin["access_token"])
print(f"Блюд в демокаталоге: {len(items)}")
PY
```

Со своего компьютера откройте SSH-туннель для интерфейса сотрудников. Подставьте своего SSH-пользователя и адрес VPS.

```sh
ssh -N -L 127.0.0.1:18081:127.0.0.1:8081 USER@SERVER
```

Откройте [рабочее место сотрудников](http://127.0.0.1:18081/), войдите как `cafeteria.admin` и создайте будущие слоты в разделе «Меню и слоты». Это время выдачи, показываемое клиенту по Москве.

## 3. Подключить домен

В конфигурацию Caddy, обычно `/etc/caddy/Caddyfile`, добавьте блок для домена. Если Caddy уже обслуживает другие сайты, сохраните их блоки.

```caddyfile
maistolovka.me {
    @staff path /api/v1/users/auth/staff /api/v1/ws/kitchen
    respond @staff 404

    reverse_proxy 127.0.0.1:8080
}
```

```sh
sudo caddy validate --config /etc/caddy/Caddyfile
```

Сохраните текущую DNS-запись корневого домена, включая тип, адрес и режим проксирования. В Cloudflare DNS замените запись `@`, ведущую на старый Pages-сайт, на A-запись с публичным IPv4 VPS в режиме **DNS only**. Если есть AAAA, обновите её до IPv6 этого VPS либо удалите устаревшую AAAA. Если Cloudflare не позволяет заменить управляемую Pages запись, сначала отсоедините домен в настройках Pages. При этом сохраните возможность вернуть его в Pages для отката.

```sh
sudo systemctl reload caddy
curl -fsS https://maistolovka.me/api/v1/menu/items
curl -fsS -o /dev/null https://maistolovka.me/design/dishes/syrniki.jpg
```

Caddy выпустит сертификат, когда DNS укажет на VPS и порты 80/443 будут доступны. Если после переключения нужно откатить публикацию, восстановите исходную DNS-запись и, если домен отсоединяли, привязку к Pages. [Документация Caddy по HTTPS](https://caddyserver.com/docs/automatic-https)

## 4. Проверить из Telegram

1. Откройте [Mini App](https://t.me/mai_stolovka_bot/maistolovka). Проверьте вход и шесть фотографий. При HTTP 401 на входе проверьте, что сервер использует токен этого бота. При HTTP 403 проверьте точный HTTPS Origin в `compose.override.yml` и пересоздайте User Service и proxy.
2. Для проверки заказа пополните кошелёк тестового клиента от имени ADMIN. Эндпоинт `POST /api/v1/orders/wallet/credits` принимает `Authorization: Bearer <ADMIN JWT>`, `Idempotency-Key: <UUID>` и JSON `{"user_id":"<UUID клиента>","amount":200000}`. UUID клиента возвращается в `GET /api/v1/users/me` после его входа. Сумма в копейках, пример начисляет 2 000 ₽. При повторе того же начисления используйте прежний ключ и тело.
3. Выберите слот, оформите тестовый заказ и проверьте его появление в рабочем месте сотрудников. Проверьте вход после закрытия и повторного открытия Mini App.

Для диагностики на VPS используйте `docker compose ps -a` и `docker compose logs --tail 100 user-service menu-service order-service proxy`. При обновлении пересоберите сервисы, выполните миграции и пересоздайте proxy. Для сохранения данных используйте тот же каталог, Compose-проект и тома. Команда `down --volumes` удаляет данные.
