# Этап 1 — Matrix: Synapse + Postgres + ntfy за nginx

Приватный Matrix без федерации. Вход снаружи — существующий nginx на хосте (80/443) с сертификатом GlobalSign DV из RU-CENTER. Контейнеры слушают только `127.0.0.1`. Push на телефон без сервисов Google — собственный ntfy (UnifiedPush).

| Адрес | Что там |
|---|---|
| `https://dilimour.online` | Matrix (discovery + клиентский API), user ID `@john:dilimour.online` |
| `https://www.dilimour.online` | ntfy (push-уведомления) |

Сертификат покрывает только эти два имени, поэтому поддоменов `matrix.` / `ntfy.` нет.

```
Телефон (Element + ntfy) ─443─► MikroTik ─► nginx (хост) ─┬─► 127.0.0.1:18008 Synapse ─► Postgres (internal)
                                                          └─► 127.0.0.1:18090 ntfy ◄── пуши от Synapse
```

Сервер `matrix` — `10.10.10.245` (статическая аренда на MikroTik), белый IP `185.35.192.13`.

## 1. DNS
В RU-CENTER редактирование записей платное (DNS-master), поэтому зона вынесена на бесплатный DNS-хостинг (Selectel): в RU-CENTER → «Указать DNS-серверы самостоятельно» → NS-серверы провайдера.

| Имя | Тип | Значение |
|---|---|---|
| `@` | A | 185.35.192.13 |
| `www` | A | 185.35.192.13 |

```bash
for h in dilimour.online www.dilimour.online; do echo "$h $(dig +short $h @1.1.1.1)"; done
```

## 2. MikroTik
```
/ip firewall nat print where chain=dstnat          # проверить, нет ли уже проброса 80/443
/ip firewall nat add chain=dstnat in-interface-list=WAN protocol=tcp dst-port=80,443 action=dst-nat to-addresses=10.10.10.245 comment="lifeos nginx"
# из дома — напрямую на сервер
/ip dns static add name=dilimour.online address=10.10.10.245
/ip dns static add name=www.dilimour.online address=10.10.10.245
```

## 3. HDD 1 ТБ → ext4, `/mnt/hdd`
Диск пустой, форматируем. **Сначала убедись, что `sda` — это WD на 1 ТБ (ROTA=1), а не системный SSD.**
```bash
lsblk -o NAME,SIZE,MODEL,ROTA,FSTYPE,MOUNTPOINTS
sudo wipefs -a /dev/sda
sudo parted -s /dev/sda mklabel gpt mkpart data ext4 0% 100%
sudo partprobe /dev/sda && sudo udevadm settle   # дождаться появления /dev/sda1
sudo mkfs.ext4 -L hdd -m 1 /dev/sda1
sudo mkdir -p /mnt/hdd
echo 'LABEL=hdd /mnt/hdd ext4 defaults,noatime,nofail 0 2' | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount -a && df -h /mnt/hdd
sudo mkdir -p /mnt/hdd/backups /mnt/hdd/data
```

## 4. Сертификат
Из RU-CENTER: сертификат, промежуточный сертификат GlobalSign и **закрытый ключ** (корневой не нужен).
```bash
cd /etc/ssl/dilimour && sudo chmod 700 .
# сертификат + промежуточный — в один файл, именно в таком порядке
cat www_dilimour_online_2027_04_27.crt intermediate_pem_globalsign_ssl_dv_free_1.crt | sudo tee fullchain.pem >/dev/null
# ключ сохранить как privkey.pem
sudo chmod 600 privkey.pem
# проверки: какие имена покрыты, срок, совпадает ли ключ
openssl x509 -in /etc/ssl/dilimour/fullchain.pem -noout -subject -enddate -ext subjectAltName
diff <(openssl x509 -in /etc/ssl/dilimour/fullchain.pem -noout -pubkey) <(sudo openssl pkey -in /etc/ssl/dilimour/privkey.pem -pubout) && echo "ключ подходит"
```
В `subjectAltName` должны быть оба имени: `dilimour.online` и `www.dilimour.online`.

## 5. Код и nginx
```bash
sudo git clone git@github.com:dilimour/lifeos.git /opt/lifeos   # deploy key
sudo ln -s /opt/lifeos/infra/matrix/nginx/lifeos-http.conf  /etc/nginx/sites-enabled/
sudo ln -s /opt/lifeos/infra/matrix/nginx/lifeos-https.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
Если `nginx -t` ругается на пересечение имён с существующими сайтами — пришли вывод.

## 6. Запуск
```bash
cd /opt/lifeos/infra/matrix && sudo cp .env.example .env && sudo ./setup.sh
sudo docker compose exec synapse register_new_matrix_user -c /data/homeserver.yaml -u john -a http://localhost:8008
sudo docker compose exec ntfy ntfy user add --role=admin john
# проверка
curl -s https://dilimour.online/.well-known/matrix/client; echo
curl -s https://dilimour.online/_matrix/client/versions | head -c 120; echo
curl -s https://www.dilimour.online/v1/health; echo
```
Если включён ufw: `sudo ufw allow from 172.16.0.0/12 to any port 443 proto tcp` — чтобы Synapse из контейнера достучался до ntfy через nginx.

## 7. Бэкапы
```bash
sudo cp systemd/lifeos-matrix-backup.* /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lifeos-matrix-backup.timer
sudo systemctl start lifeos-matrix-backup.service && journalctl -u lifeos-matrix-backup -n 5
```

## 8. Телефон (Huawei без Google)
1. **ntfy** (F-Droid или APK с GitHub) → Настройки → сервер по умолчанию `https://www.dilimour.online`, пользователь `john`.
2. **Element** из F-Droid (сборка с UnifiedPush) → сервер `dilimour.online`, логин `john`.
3. Element → Настройки → Уведомления → способ доставки: ntfy.
4. Проверка: написать себе с ПК (Element Desktop) — уведомление должно прийти на телефон.

## Продление сертификата
GlobalSign DV действует до **27.04.2027**. Продлить в RU-CENTER заранее, заменить два файла в `/etc/ssl/dilimour/`, `sudo systemctl reload nginx`. Бот будет напоминать за 30 дней.
