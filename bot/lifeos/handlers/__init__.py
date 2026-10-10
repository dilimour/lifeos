from . import finance, health, learning, leisure, sport, work

HANDLERS = {m.KEY: m for m in (finance, health, sport, work, learning, leisure)}
