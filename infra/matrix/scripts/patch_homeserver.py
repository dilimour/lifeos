"""Приводит сгенерированный homeserver.yaml к нашей схеме. Запускается внутри контейнера synapse."""
import os
import yaml

p = "/data/homeserver.yaml"
c = yaml.safe_load(open(p))

c["database"] = {
    "name": "psycopg2",
    "args": {
        "user": "synapse",
        "password": os.environ["POSTGRES_PASSWORD"],
        "dbname": "synapse",
        "host": "postgres",
        "cp_min": 5,
        "cp_max": 10,
    },
}
c["listeners"] = [{
    "port": 8008, "tls": False, "type": "http", "x_forwarded": True,
    "bind_addresses": ["0.0.0.0"],
    "resources": [{"names": ["client"], "compress": False}],
}]
c["public_baseurl"] = f"https://{os.environ['MATRIX_HOST']}/"
# приватный сервер: без федерации и без открытой регистрации
c["federation_domain_whitelist"] = []
c["trusted_key_servers"] = []
c["suppress_key_server_warning"] = True
c["allow_public_rooms_over_federation"] = False
c["enable_registration"] = False
c["report_stats"] = False
c["url_preview_enabled"] = False
c["presence"] = {"enabled": False}
c["max_upload_size"] = "50M"
# разрешаем пуши на ntfy через шлюз докера (host-gateway, 172.17.0.1)
c["ip_range_whitelist"] = ["172.16.0.0/12"]

yaml.safe_dump(c, open(p, "w"), allow_unicode=True, sort_keys=False)
os.chown(p, 991, 991)
print("homeserver.yaml обновлён")
