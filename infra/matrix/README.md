# Этап 1 — Matrix: Synapse + Postgres + ntfy за nginx

Приватный Matrix без федерации. Вход снаружи — существующий nginx на хосте (80/443), сертификат Let's Encrypt через certbot. Контейнеры слушают только `127.0.0.1`. Push на телефон без сервисов Google — собственный ntfy (UnifiedPush).

```
Телефон (Element + ntfy) ─443─► MikroTik ─► nginx (хост) ─┬─► 127.0.0.1:8008 Synapse ─► Postgres (internal)
                                                          └─► 127.0.0.1:8090 ntfy ◄── пуши от Synapse
```

Данные:
- сервер `matrix` — `10.10.10.245` (enp5s0), белый IP `185.35.192.13` (статический);
- системный SSD — `sdb` (LVM, `/`), HDD 1 ТБ — `sda1` (NTFS, не смонтирован).

## 1. DNS (RU-CENTER)
| Имя | Тип | Значение |
|---|---|---|
| `@` | A | 185.35.192.13 |
| `matrix` | A | 185.35.192.13 |
| `ntfy` | A | 185.35.192.13 |

```bash
for h in dilimour.online matrix.dilimour.online ntfy.dilimour.online; do echo "$h $(dig +short $h @1.1.1.1)"; done
```

## 2. MikroTik
```
# закрепить адрес сервера (сейчас он выдан DHCP динамически)
/ip dhcp-server lease make-static [find address=10.10.10.245]
# проверить, нет ли уже проброса 80/443
/ip firewall nat print where chain=dstnat
# проброс (если ещё нет)
/ip firewall nat add chain=dstnat in-interface-list=WAN protocol=tcp dst-port=80,443 action=dst-nat to-addresses=10.10.10.245 comment="lifeos nginx"
# из дома — напрямую на сервер, без выхода наружу
/ip dns static add name=dilimour.online address=10.10.10.245
/ip dns static add name=matrix.dilimour.online address=10.10.10.245
/ip dns static add name=ntfy.dilimour.online address=10.10.10.245
```

## 3. Код на сервер
```bash
sudo git clone git@github.com:dilimour/lifeos.git /opt/lifeos   # deploy key
cd /opt/lifeos/infra/matrix
cp .env.example .env
```

## 4. Сертификат и nginx
```bash
sudo apt install -y certbot
sudo mkdir -p /var/www/certbot
sudo ln -s /opt/lifeos/infra/matrix/nginx/lifeos-http.conf /etc/nginx/sites-enabled/lifeos-http.conf
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot \
  -d dilimour.online -d matrix.dilimour.online -d ntfy.dilimour.online \
  --deploy-hook "systemctl reload nginx"
sudo ln -s /opt/lifeos/infra/matrix/nginx/lifeos-https.conf /etc/nginx/sites-enabled/lifeos-https.conf
sudo nginx -t && sudo systemctl reload nginx
```
Если `nginx -t` ругается на `default_server` или пересечение имён — пришли вывод, поправим. Существующие сайты nginx не трогаем.

## 5. Запуск
```bash
cd /opt/lifeos/infra/matrix && sudo ./setup.sh
sudo docker compose exec synapse register_new_matrix_user -c /data/homeserver.yaml -u john -a http://localhost:8008
sudo docker compose exec ntfy ntfy user add --role=admin john
# проверка снаружи (с телефона без Wi-Fi или curl с внешнего хоста)
curl -s https://dilimour.online/.well-known/matrix/client
curl -s https://matrix.dilimour.online/_matrix/client/versions | head -c 120; echo
curl -s https://ntfy.dilimour.online/v1/health
```
Если включён ufw: `sudo ufw allow from 172.16.0.0/12 to any port 443 proto tcp` — чтобы Synapse из контейнера достучался до ntfy через nginx.

## 6. Бэкапы
HDD `sda1` сейчас NTFS и не смонтирован — сначала решаем, форматировать в ext4 или монтировать как есть (см. основной чат). Потом:
```bash
sudo cp systemd/lifeos-matrix-backup.* /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lifeos-matrix-backup.timer
sudo systemctl start lifeos-matrix-backup.service && journalctl -u lifeos-matrix-backup -n 5
```

## 7. Телефон (Huawei без Google)
1. **ntfy** (F-Droid или APK с GitHub) → Настройки → сервер по умолчанию `https://ntfy.dilimour.online`, пользователь `john`.
2. **Element** из F-Droid (сборка с UnifiedPush) → сервер `dilimour.online`, логин `john`.
3. Element → Настройки → Уведомления → способ доставки: ntfy.
4. Проверка: написать себе с ПК (Element Desktop) — уведомление должно прийти на телефон.

## 8. Дальше
Этап 2: бот-оркестратор создаёт Space «Моя жизнь» с комнатами Сводки · Финансы · Здоровье · Спорт · Работа · Обучение · Досуг.
